from __future__ import annotations

import json
import os


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ============================================================
# RENDER CLOUD TEST CONFIGURATION
# No Production credentials are stored in this file.
# All secrets belong in Render Environment Variables.
# ============================================================

# ---------------- Telegram ----------------
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_ID = env("TELEGRAM_API_ID")
TELEGRAM_API_HASH = env("TELEGRAM_API_HASH")

# Local Bot API runs inside this same Render container.
LOCAL_BOT_API_BASE = env("LOCAL_BOT_API_BASE", "http://127.0.0.1:8081")
LOCAL_BOT_API_CONTAINER_DIR = env(
    "LOCAL_BOT_API_CONTAINER_DIR", "/var/lib/telegram-bot-api"
)
LOCAL_BOT_API_FILE_TIMEOUT_SECONDS = int(
    env("LOCAL_BOT_API_FILE_TIMEOUT_SECONDS", "1800")
)

allowed_chat = env("ALLOWED_CHAT_ID")
ALLOWED_CHAT_ID = int(allowed_chat) if allowed_chat else None

RENDER_EXTERNAL_URL = env("RENDER_EXTERNAL_URL")
WEBHOOK_PATH = env("WEBHOOK_PATH", "/telegram")
WEBHOOK_SECRET = env("WEBHOOK_SECRET")
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = "/" + WEBHOOK_PATH

# ---------------- GitHub TEST repository ----------------
GITHUB_OWNER = env("GITHUB_OWNER", "downloadhub-official")
GITHUB_REPO = env("GITHUB_REPO", "apk-automation-render")
GITHUB_TARGET_BRANCH = env("GITHUB_TARGET_BRANCH", "main")
GITHUB_RELEASE_TAG = env("GITHUB_RELEASE_TAG", "render-test-v1")
GITHUB_RELEASE_TITLE = env("GITHUB_RELEASE_TITLE", "Render Test")
GITHUB_MAKE_LATEST = env("GITHUB_MAKE_LATEST", "false").lower() in {
    "1", "true", "yes"
}
GITHUB_TOKEN = env("GITHUB_TOKEN")

# ---------------- Blogger ----------------
BLOG_ID = env("BLOG_ID")

# Render is headless. The value must be an authorized-user OAuth token JSON,
# not the client-secret JSON downloaded from Google Cloud.
GOOGLE_TOKEN_JSON = env("GOOGLE_TOKEN_JSON")
GOOGLE_TOKEN_FILE = env("GOOGLE_TOKEN_FILE", "/tmp/google-token.json")

APP_TO_BLOGGER_PAGE = {
    "moviebox": env("BLOGGER_PAGE_MOVIEBOX"),
    "remini": env("BLOGGER_PAGE_REMINI"),
    "snaptube": env("BLOGGER_PAGE_SNAPTUBE"),
    "duolingo": env("BLOGGER_PAGE_DUOLINGO"),
    "lark_player": env("BLOGGER_PAGE_LARK_PLAYER"),
    "nodevideo": env("BLOGGER_PAGE_NODEVIDEO"),
}

# The bot replaces hrefs whose URL contains one of these provider markers.
PROVIDER_URL_MARKERS = {
    "gplinks": ("gplinks.co",),
    "oii": ("oii.io",),
    "ouo": ("ouo.io",),
}

# The test Blogger page may still contain a direct GitHub Release URL from an
# earlier test repository. Restrict the default matcher to this GitHub owner.
# If a different test URL is required, set BLOGGER_DIRECT_GITHUB_MARKERS as a
# comma-separated list in Render.
def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = env(name)
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


DIRECT_GITHUB_URL_MARKERS = _csv_env(
    "BLOGGER_DIRECT_GITHUB_MARKERS",
    (
        
        f"https://github.com/{GITHUB_OWNER}/",
    ),
)

# ---------------- Shorteners ----------------
GPLINKS_API_KEY = env("GPLINKS_API_KEY")
OII_API_KEY = env("OII_API_KEY")
OUO_API_KEY = env("OUO_API_KEY")

# ---------------- File handling ----------------
DOWNLOAD_DIR = env("DOWNLOAD_DIR", "/tmp/apk-automation-downloads")
BACKUP_DIR = env("BACKUP_DIR", "/tmp/apk-automation-backups")
LOG_DIR = env("LOG_DIR", "/tmp/apk-automation-logs")

# 0 means no application-level limit. Telegram Local Bot API currently
# supports downloads without the cloud 20 MB download limit.
MAX_APK_BYTES = int(env("MAX_APK_BYTES", "0"))
KEEP_SUCCESSFUL_DOWNLOAD = env("KEEP_SUCCESSFUL_DOWNLOAD", "0").lower() in {
    "1", "true", "yes"
}
HTTP_CONNECT_TIMEOUT = int(env("HTTP_CONNECT_TIMEOUT", "60"))
HTTP_READ_TIMEOUT = int(env("HTTP_READ_TIMEOUT", "3600"))

# ---------------- Safety / behavior ----------------
APP_ALIASES = {
    "moviebox": ("moviebox",),
    "remini": ("remini",),
    "snaptube": ("snaptube", "snap tube"),
    "duolingo": ("duolingo",),
    "lark_player": ("lark_player", "larkplayer", "lark player"),
    "nodevideo": ("nodevideo", "node video"),
}

ONE_JOB_AT_A_TIME = True
VERIFY_ASSET_SIZE = True
CLEAN_LOCAL_API_SOURCE_AFTER_COPY = True

if GOOGLE_TOKEN_JSON:
    try:
        json.loads(GOOGLE_TOKEN_JSON)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_TOKEN_JSON is not valid JSON.") from exc
