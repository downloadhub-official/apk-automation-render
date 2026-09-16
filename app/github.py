from __future__ import annotations

import mimetypes
import logging
from pathlib import Path
from urllib.parse import quote

import requests

import config
from .utils import human_bytes

logger = logging.getLogger(__name__)

API = "https://api.github.com"
API_VERSION = "2026-03-10"


class GitHubError(RuntimeError):
    pass


class GitHubReleaseManager:
    """Upload all APK assets into one fixed, reusable GitHub Release.

    The Render test bot does not create a new tag for every APK. It reuses
    GITHUB_RELEASE_TAG (default: render-test-v1). If the release already
    exists, a new APK is added to that release. If an asset with the same
    filename already exists, it is deleted first and then replaced.

    IMPORTANT: the target release must be mutable. GitHub immutable published
    releases cannot accept new/changed assets. Keep immutable releases disabled
    for this test release.
    """

    def __init__(self):
        token = str(config.GITHUB_TOKEN or "").strip()
        if not token or "PASTE_" in token:
            raise GitHubError("GITHUB_TOKEN is not configured.")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "APK-Automation-Bot-Render-Test/1.1",
            }
        )

    @property
    def repo_url(self) -> str:
        return (
            f"{API}/repos/{quote(config.GITHUB_OWNER)}/"
            f"{quote(config.GITHUB_REPO)}"
        )

    def _request(self, method: str, url: str, **kwargs):
        try:
            response = self.session.request(
                method,
                url,
                timeout=(config.HTTP_CONNECT_TIMEOUT, config.HTTP_READ_TIMEOUT),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise GitHubError(f"GitHub network error: {exc}") from exc

        if not response.ok:
            raise GitHubError(
                f"GitHub API {response.status_code}: {response.text[:1200]}"
            )
        return response

    def get_release_by_tag(self) -> dict | None:
        tag = config.GITHUB_RELEASE_TAG
        url = f"{self.repo_url}/releases/tags/{quote(tag, safe='')}"
        try:
            response = self.session.get(
                url,
                timeout=(config.HTTP_CONNECT_TIMEOUT, config.HTTP_READ_TIMEOUT),
            )
        except requests.RequestException as exc:
            raise GitHubError(f"GitHub network error: {exc}") from exc

        if response.status_code == 404:
            return None
        if not response.ok:
            raise GitHubError(
                f"GitHub API {response.status_code}: {response.text[:1200]}"
            )
        return response.json()

    def create_draft_release(self) -> dict:
        tag = config.GITHUB_RELEASE_TAG
        payload = {
            "tag_name": tag,
            "target_commitish": config.GITHUB_TARGET_BRANCH,
            "name": config.GITHUB_RELEASE_TITLE[:125],
            "body": (
                "APK Automation Bot — Render Cloud Test.\n\n"
                "All test APK assets are stored in this single Release.\n"
            ),
            "draft": True,
            "prerelease": False,
            "generate_release_notes": False,
        }
        response = self._request("POST", f"{self.repo_url}/releases", json=payload)
        release = response.json()
        logger.info(
            "Created fixed-tag GitHub draft release id=%s tag=%s",
            release.get("id"),
            release.get("tag_name"),
        )
        return release

    def get_or_create_release(self) -> dict:
        release = self.get_release_by_tag()
        if release:
            return release
        return self.create_draft_release()

    def list_assets(self, release: dict) -> list[dict]:
        url = release.get("assets_url")
        if not url:
            raise GitHubError("GitHub release has no assets_url.")
        return self._request("GET", url).json()

    def delete_asset(self, asset: dict) -> None:
        url = asset.get("url")
        if not url:
            raise GitHubError("GitHub asset has no API URL.")
        self._request("DELETE", url)
        logger.info("Deleted existing GitHub asset id=%s name=%s", asset.get("id"), asset.get("name"))

    def remove_existing_asset(self, release: dict, filename: str) -> None:
        assets = self.list_assets(release)
        for asset in assets:
            if str(asset.get("name", "")).casefold() == filename.casefold():
                self.delete_asset(asset)

    def upload_asset(self, release: dict, local_path: Path) -> dict:
        upload_url = str(release.get("upload_url") or "")
        if not upload_url:
            raise GitHubError("GitHub release has no upload_url.")

        upload_url = upload_url.split("{", 1)[0]
        name = local_path.name
        content_type = (
            mimetypes.guess_type(name)[0]
            or "application/vnd.android.package-archive"
        )

        try:
            with local_path.open("rb") as fh:
                response = self.session.post(
                    upload_url,
                    params={"name": name},
                    headers={
                        "Content-Type": content_type,
                        "Content-Length": str(local_path.stat().st_size),
                    },
                    data=fh,
                    timeout=(
                        config.HTTP_CONNECT_TIMEOUT,
                        config.HTTP_READ_TIMEOUT,
                    ),
                )
        except (OSError, requests.RequestException) as exc:
            raise GitHubError(f"GitHub APK upload failed: {exc}") from exc

        if response.status_code != 201:
            raise GitHubError(
                f"GitHub asset upload failed ({response.status_code}): "
                f"{response.text[:1200]}"
            )
        return response.json()

    def verify_asset(self, release: dict, local_path: Path) -> dict:
        assets = self.list_assets(release)
        matches = [
            asset for asset in assets
            if str(asset.get("name", "")).casefold() == local_path.name.casefold()
        ]
        if len(matches) != 1:
            raise GitHubError(
                f"Expected exactly one uploaded asset named {local_path.name!r}; "
                f"found {len(matches)}."
            )

        asset = matches[0]
        if asset.get("state") != "uploaded":
            raise GitHubError(
                f"GitHub asset state is {asset.get('state')!r}, not 'uploaded'."
            )

        local_size = local_path.stat().st_size
        remote_size = int(asset.get("size") or -1)
        if local_size != remote_size:
            raise GitHubError(
                f"GitHub asset size mismatch: local={local_size}, remote={remote_size}."
            )

        url = asset.get("browser_download_url")
        if not url:
            raise GitHubError("Uploaded asset has no browser_download_url.")
        return asset

    def publish_if_draft(self, release: dict) -> dict:
        if not release.get("draft"):
            return release

        url = release.get("url")
        if not url:
            raise GitHubError("GitHub release has no API URL.")

        response = self._request(
            "PATCH",
            url,
            json={
                "draft": False,
                "prerelease": False,
                "make_latest": "true" if config.GITHUB_MAKE_LATEST else "false",
            },
        )
        published = response.json()
        if published.get("draft"):
            raise GitHubError("GitHub release is still a draft after publish request.")
        return published

    def create_release_with_asset(
        self,
        app: str,
        local_apk: Path,
        size: int,
        sha256: str,
    ) -> tuple[dict, dict]:
        """Add/replace one APK asset inside the single fixed Release."""
        release = self.get_or_create_release()

        # A published immutable release cannot be changed. Fail clearly
        # instead of creating another tag, which is exactly what this test
        # project is designed not to do.
        if release.get("immutable") is True:
            raise GitHubError(
                f"GitHub release tag {config.GITHUB_RELEASE_TAG!r} is immutable. "
                "Disable immutable releases for this test release, then retry."
            )

        self.remove_existing_asset(release, local_apk.name)
        uploaded = self.upload_asset(release, local_apk)
        verified = self.verify_asset(release, local_apk)
        published = self.publish_if_draft(release)

        # Keep the returned release object current after a draft is published.
        published["tag_name"] = config.GITHUB_RELEASE_TAG
        logger.info(
            "APK stored in fixed GitHub Release tag=%s app=%s file=%s size=%s sha256=%s",
            config.GITHUB_RELEASE_TAG,
            app,
            local_apk.name,
            human_bytes(size),
            sha256,
        )
        return published, verified
