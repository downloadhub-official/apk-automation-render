from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/blogger"]


class BloggerError(RuntimeError):
    pass


def _load_credentials() -> Credentials:
    """Load an authorized Google user token from Render Environment Variables.

    Render is headless, so an interactive InstalledAppFlow is deliberately not
    attempted. GOOGLE_TOKEN_JSON must be the authorized-user token JSON created
    during the one-time OAuth authorization step.
    """
    token_json = str(getattr(config, "GOOGLE_TOKEN_JSON", "") or "").strip()
    if not token_json:
        raise BloggerError(
            "GOOGLE_TOKEN_JSON is not configured. Render cannot perform an "
            "interactive Google OAuth login. Generate an authorized Blogger "
            "user token once on a local machine, then paste its JSON into "
            "Render as GOOGLE_TOKEN_JSON."
        )

    try:
        info = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    except Exception as exc:
        raise BloggerError(f"Could not read GOOGLE_TOKEN_JSON: {exc}") from exc

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise BloggerError(f"Google token refresh failed: {exc}") from exc

    if not creds.valid:
        raise BloggerError(
            "GOOGLE_TOKEN_JSON is not a valid authorized-user token. "
            "Re-authorize Blogger access and replace the Render value."
        )

    return creds


class BloggerManager:
    def __init__(self):
        self.service = build(
            "blogger",
            "v3",
            credentials=_load_credentials(),
            cache_discovery=False,
        )

    def get_page(self, page_id: str) -> dict:
        try:
            return (
                self.service.pages()
                .get(blogId=config.BLOG_ID, pageId=page_id)
                .execute()
            )
        except Exception as exc:
            raise BloggerError(f"Could not fetch Blogger page {page_id}: {exc}") from exc

    @staticmethod
    def _provider_matches(url: str, markers: tuple[str, ...]) -> bool:
        lowered = (url or "").casefold()
        return any(marker.casefold() in lowered for marker in markers)

    @staticmethod
    def _direct_github_markers() -> tuple[str, ...]:
        configured = getattr(config, "DIRECT_GITHUB_URL_MARKERS", ())
        return tuple(configured or ())


    def find_provider_links(self, html: str) -> dict[str, list[str]]:
        soup = BeautifulSoup(html or "", "html.parser")
        markers_by_provider = dict(config.PROVIDER_URL_MARKERS)
        direct_markers = self._direct_github_markers()
        if direct_markers:
            markers_by_provider["direct_github"] = direct_markers

        found = {provider: [] for provider in markers_by_provider}

        for tag in soup.find_all(href=True):
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            for provider, markers in markers_by_provider.items():
                if self._provider_matches(href, markers):
                    found[provider].append(href)

        return found

    def preflight(
        self,
        page: dict,
        new_links: dict[str, str],
    ) -> tuple[str, dict[str, list[str]]]:
        html = page.get("content")
        if html is None:
            raise BloggerError("Target Blogger page has no HTML content.")

        found = self.find_provider_links(html)

        missing = [provider for provider in new_links if not found.get(provider)]
        if missing:
            raise BloggerError(
                "Blogger preflight failed: the target page is missing expected "
                "link(s): " + ", ".join(missing) + ". Blogger was NOT changed."
            )

        return html, found

    def backup_html(self, app: str, page_id: str, page: dict, backup_dir: Path) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = backup_dir / f"{app}_{page_id}_{stamp}.html"

        payload = {
            "blog_id": config.BLOG_ID,
            "page_id": page_id,
            "title": page.get("title"),
            "url": page.get("url"),
            "updated": page.get("updated"),
            "content": page.get("content"),
            "saved_at_utc": stamp,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def replace_links(
        self,
        html: str,
        new_links: dict[str, str],
    ) -> tuple[str, dict[str, int]]:
        soup = BeautifulSoup(html, "html.parser")
        counts = {provider: 0 for provider in new_links}

        for tag in soup.find_all(href=True):
            href = tag.get("href")
            if not isinstance(href, str):
                continue

            for provider, replacement in new_links.items():
                if provider == "direct_github":
                    markers = self._direct_github_markers()
                else:
                    markers = config.PROVIDER_URL_MARKERS.get(provider, ())
                if self._provider_matches(href, markers):
                    tag["href"] = replacement
                    counts[provider] += 1
                    break

        return str(soup), counts

    def update_page(self, page: dict, new_html: str) -> dict:
        # Send only writable page fields. Output-only fields such as url, id,
        # blog and updated are deliberately omitted.
        body = {
            "title": page.get("title", ""),
            "content": new_html,
        }

        try:
            return (
                self.service.pages()
                .update(
                    blogId=config.BLOG_ID,
                    pageId=page["id"],
                    body=body,
                )
                .execute()
            )
        except Exception as exc:
            raise BloggerError(f"Blogger update failed: {exc}") from exc

    def post_verify(
        self,
        page_id: str,
        new_links: dict[str, str],
        expected_counts: dict[str, int],
    ) -> dict[str, list[str]]:
        fresh = self.get_page(page_id)
        html = fresh.get("content", "")

        # New URLs must exist.
        for provider, new_url in new_links.items():
            if expected_counts.get(provider, 0) <= 0:
                continue
            if html.count(new_url) < expected_counts[provider]:
                raise BloggerError(
                    f"Post-verification failed: expected {expected_counts[provider]} "
                    f"occurrence(s) of new {provider} URL."
                )

        # Old provider URLs are checked by provider presence, not by knowing
        # their exact previous URL. The exact old hrefs were captured before
        # update and must be absent after update.
        return self.find_provider_links(html)

    def update_links_safely(
        self,
        app: str,
        page_id: str,
        new_links: dict[str, str],
        backup_dir: Path,
    ) -> dict:
        page = self.get_page(page_id)

        old_html, old_found = self.preflight(page, new_links)
        backup_path = self.backup_html(app, page_id, page, backup_dir)

        new_html, counts = self.replace_links(old_html, new_links)

        if sum(counts.values()) <= 0:
            raise BloggerError(
                "No links were replaced after preflight. Blogger was NOT changed."
            )

        # Exact replacement verification in memory:
        # Every old matching href selected by provider should be gone from the
        # corresponding provider set after replacement.
        old_urls = {
            provider: list(urls)
            for provider, urls in old_found.items()
            if provider in new_links
        }

        for provider, urls in old_urls.items():
            for old_url in urls:
                if old_url in new_html and old_url not in new_links.values():
                    raise BloggerError(
                        f"Pre-update URL still exists in generated HTML for {provider}: "
                        f"{old_url}"
                    )

        updated = self.update_page(page, new_html)

        # Re-fetch and verify.
        fresh = self.get_page(page_id)
        fresh_html = fresh.get("content", "")

        for provider, urls in old_urls.items():
            for old_url in urls:
                if old_url in fresh_html and old_url not in new_links.values():
                    raise BloggerError(
                        f"Post-verification failed: old {provider} URL still exists: "
                        f"{old_url}"
                    )

        for provider, count in counts.items():
            if count <= 0:
                continue
            new_url = new_links[provider]
            if fresh_html.count(new_url) < count:
                raise BloggerError(
                    f"Post-verification failed: new {provider} URL is missing."
                )

        return {
            "backup_path": str(backup_path),
            "replaced_counts": counts,
            "page_url": updated.get("url") or page.get("url"),
        }
