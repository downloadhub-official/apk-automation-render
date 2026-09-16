from __future__ import annotations

import logging
import threading
from pathlib import Path

import config
from .blogger import BloggerError, BloggerManager
from .github import GitHubError, GitHubReleaseManager
from .shortener import ShortenerError, create_short_links
from .utils import human_bytes, identify_app, safe_filename, sha256_file

logger = logging.getLogger(__name__)
LOCK = threading.Lock()


class WorkflowError(RuntimeError):
    pass


def run_workflow(filename: str, local_apk: Path, report_sync) -> str:
    if config.ONE_JOB_AT_A_TIME and not LOCK.acquire(blocking=False):
        raise WorkflowError(
            "❌ ERROR\n\nAnother APK job is already running.\n"
            "This test bot processes one APK at a time."
        )

    try:
        return _run_workflow(filename, local_apk, report_sync)
    finally:
        if config.ONE_JOB_AT_A_TIME:
            LOCK.release()


def _run_workflow(filename: str, local_apk: Path, report) -> str:
    filename = safe_filename(filename)

    try:
        app = identify_app(filename, config.APP_ALIASES)
    except ValueError as exc:
        raise WorkflowError(
            f"❌ APP IDENTIFICATION ERROR\n\n{exc}\n\n"
            "No GitHub/Blogger change was made."
        ) from exc

    if not app:
        raise WorkflowError(
            f"❌ APP IDENTIFICATION ERROR\n\nFilename: {filename}\n"
            "No configured app name was found in the filename.\n"
            "No GitHub/Blogger change was made."
        )

    page_id = config.APP_TO_BLOGGER_PAGE.get(app)
    if not page_id:
        raise WorkflowError(
            f"❌ CONFIG ERROR\n\nApp {app!r} was identified, but no Blogger "
            "Page ID is configured."
        )

    if not local_apk.exists():
        raise WorkflowError("❌ Local APK file is missing after Telegram download.")

    size = local_apk.stat().st_size
    if size <= 0:
        raise WorkflowError("❌ APK file is empty.")

    sha = sha256_file(local_apk)

    report(
        "🔎 STEP 2/7 — APK ready\n"
        f"App: {app}\n"
        f"Blogger Page ID: {page_id}\n"
        f"Filename: {filename}\n"
        f"Size: {human_bytes(size)}\n"
        f"SHA-256: {sha}"
    )

    report("🐙 STEP 3/7 — Creating new GitHub Release + uploading APK...")
    github = GitHubReleaseManager()

    try:
        release, verified_asset = github.create_release_with_asset(
            app=app,
            local_apk=local_apk,
            size=size,
            sha256=sha,
        )
    except GitHubError as exc:
        raise WorkflowError(
            f"❌ GITHUB ERROR\n\n{exc}\n\nBlogger was NOT changed."
        ) from exc

    github_url = verified_asset["browser_download_url"]
    report(
        "✅ STEP 3/7 — GitHub Release published + verified\n"
        f"Release: {release.get('name')}\n"
        f"Tag: {release.get('tag_name')}\n"
        f"Asset: {verified_asset.get('name')}\n"
        f"Remote size: {human_bytes(int(verified_asset.get('size', 0)))}\n"
        f"URL: {github_url}"
    )

    report("🔗 STEP 4/7 — Generating short links...")
    try:
        short_links = create_short_links(github_url)
    except ShortenerError as exc:
        raise WorkflowError(
            f"❌ SHORTENER ERROR\n\n{exc}\n\n"
            "GitHub Release was published and verified, but Blogger was NOT changed.\n"
            f"GitHub URL: {github_url}"
        ) from exc

    new_links = dict(short_links)
    new_links["direct_github"] = github_url

    report(
        "✅ STEP 4/7 — Short links ready\n"
        + "\n".join(f"{k.upper()}: {v}" for k, v in new_links.items())
    )

    report("🧪 STEP 5/7 — Blogger preflight + backup...")
    blogger = BloggerManager()
    backup_dir = Path(config.BACKUP_DIR) / "blogger"

    try:
        page = blogger.get_page(page_id)
        old_found = blogger.find_provider_links(page.get("content", ""))

        relevant = {
            provider: urls
            for provider, urls in old_found.items()
            if provider in new_links and urls
        }
        if not relevant:
            raise BloggerError(
                "No configured shortener/direct-GitHub URL was found on the target "
                "Blogger page. Blogger was NOT changed."
            )

        backup_path = blogger.backup_html(
            app=app,
            page_id=page_id,
            page=page,
            backup_dir=backup_dir,
        )
    except BloggerError as exc:
        raise WorkflowError(
            f"❌ BLOGGER PREFLIGHT ERROR\n\n{exc}\n\n"
            "GitHub Release remains available; Blogger was NOT changed."
        ) from exc

    report(
        "✅ STEP 5/7 — Blogger preflight passed\n"
        f"Matched: {', '.join(relevant.keys())}\n"
        f"Backup: {backup_path}"
    )

    report("✏️ STEP 6/7 — Updating Blogger links + verification...")
    try:
        result = blogger.update_links_safely(
            app=app,
            page_id=page_id,
            new_links=new_links,
            backup_dir=backup_dir,
        )
    except BloggerError as exc:
        raise WorkflowError(
            f"❌ BLOGGER UPDATE ERROR\n\n{exc}\n\n"
            "A Blogger backup was created before update.\n"
            f"Backup directory: {backup_dir}\n"
            f"GitHub URL: {github_url}"
        ) from exc

    report(
        "✅ STEP 6/7 — Blogger update + post-verification successful\n"
        f"Replaced: {result['replaced_counts']}\n"
        f"Page: {result.get('page_url')}\n"
        f"Backup: {result['backup_path']}"
    )

    if not config.KEEP_SUCCESSFUL_DOWNLOAD:
        local_apk.unlink(missing_ok=True)

    report("🔍 STEP 7/7 — Final verification complete")

    return (
        "🎉 SUCCESS — RENDER CLOUD APK AUTOMATION COMPLETE\n\n"
        f"App: {app}\n"
        f"APK: {filename}\n"
        f"Size: {human_bytes(size)}\n"
        f"SHA-256: {sha}\n\n"
        f"GitHub Release: {release.get('html_url')}\n"
        f"GitHub Asset: {verified_asset.get('name')}\n"
        f"GitHub URL: {github_url}\n\n"
        + "\n".join(f"{k.upper()}: {v}" for k, v in new_links.items())
        + "\n\n"
        f"Blogger Page ID: {page_id}\n"
        f"Replacements: {result['replaced_counts']}\n"
        f"Backup: {result['backup_path']}\n\n"
        "✅ Telegram Local Bot API\n"
        "✅ GitHub Release upload + verification\n"
        "✅ Short links generated\n"
        "✅ Blogger updated + post-verified"
    )
