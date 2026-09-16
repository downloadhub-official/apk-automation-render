from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

import config

logger = logging.getLogger(__name__)


class TelegramLocalFileError(RuntimeError):
    """Raised when a Local Bot API file cannot be safely resolved or copied."""


def _inside_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _redact_secret(text: str) -> str:
    value = str(text or "")
    token = str(config.TELEGRAM_BOT_TOKEN or "").strip()
    return value.replace(token, "<BOT_TOKEN>") if token else value


def _safe_relative(value: str) -> PurePosixPath:
    value = unquote(str(value or "").strip())
    if not value or "\x00" in value or "\\" in value:
        raise TelegramLocalFileError("Unsafe Local Bot API file path.")
    path = PurePosixPath(value.lstrip("/"))
    if not path.parts or any(p in {"", ".", ".."} for p in path.parts):
        raise TelegramLocalFileError("Unsafe Local Bot API file path.")
    return path


def _resolve_file_path(file_path: str) -> Path:
    """Resolve the absolute local path returned by Telegram Local Bot API.

    Telegram's local server documents that getFile can return an absolute local
    path. The bot and API run in the same Render container, so no Windows bind
    mount or token-directory translation is needed here.
    """
    raw = str(file_path or "").strip()
    if not raw:
        raise TelegramLocalFileError("Telegram getFile returned an empty file_path.")

    root = Path(config.LOCAL_BOT_API_CONTAINER_DIR).resolve()
    parsed = urlparse(raw)

    if parsed.scheme in {"http", "https"}:
        path = unquote(parsed.path or "")
        marker = "/file/bot"
        if not path.startswith(marker):
            raise TelegramLocalFileError("Unsupported Local Bot API file URL.")
        tail = path[len(marker):]
        slash = tail.find("/")
        if slash < 0:
            raise TelegramLocalFileError("Local Bot API file URL has no file path.")
        relative = _safe_relative(tail[slash + 1 :])
        candidate = root.joinpath(*relative.parts)
    else:
        decoded = unquote(raw)
        posix = PurePosixPath(decoded)
        try:
            relative = posix.relative_to(PurePosixPath(config.LOCAL_BOT_API_CONTAINER_DIR))
            candidate = root.joinpath(*relative.parts)
        except ValueError:
            # Some builds can return a storage-relative path.
            relative = _safe_relative(decoded)
            candidate = root.joinpath(*relative.parts)

    if not _inside_root(root, candidate):
        raise TelegramLocalFileError("Local Bot API file path escaped its storage directory.")
    return candidate


def copy_local_bot_api_file(tg_file, destination: Path) -> tuple[Path, int]:
    """Wait for and copy the Local Bot API file without loading it into RAM."""
    file_path = str(getattr(tg_file, "file_path", "") or "")
    expected_size = getattr(tg_file, "file_size", None)
    try:
        expected_size = int(expected_size) if expected_size is not None else None
    except (TypeError, ValueError):
        expected_size = None
    if expected_size is not None and expected_size < 0:
        expected_size = None

    timeout = max(1, int(config.LOCAL_BOT_API_FILE_TIMEOUT_SECONDS))
    deadline = time.monotonic() + timeout
    source: Path | None = None

    while time.monotonic() < deadline:
        try:
            candidate = _resolve_file_path(file_path)
            if candidate.is_file():
                source = candidate
                break
        except (OSError, TelegramLocalFileError):
            pass
        time.sleep(0.5)

    if source is None:
        raise TelegramLocalFileError(
            "❌ Timed out waiting for Local Bot API file. "
            f"Returned path: {_redact_secret(file_path)}"
        )

    # Wait until the expected size is present and stable.
    stable = 0
    last_size = -1
    while time.monotonic() < deadline:
        try:
            current = source.stat().st_size
        except OSError as exc:
            raise TelegramLocalFileError("Permission error reading Local Bot API storage.") from exc

        if current <= 0:
            raise TelegramLocalFileError("Local Bot API file is empty (0 bytes).")

        if expected_size is not None:
            if current == expected_size:
                stable += 1
                if stable >= 2:
                    break
            elif current == last_size:
                stable += 1
                if stable >= 3:
                    raise TelegramLocalFileError(
                        f"Local Bot API file size mismatch: expected {expected_size}, got {current}."
                    )
            else:
                stable = 0
        else:
            if current == last_size:
                stable += 1
                if stable >= 4:
                    break
            else:
                stable = 0
        last_size = current
        time.sleep(0.5)
    else:
        raise TelegramLocalFileError("❌ Timed out waiting for Local Bot API file to finish writing.")

    source_size = source.stat().st_size
    if expected_size is not None and source_size != expected_size:
        raise TelegramLocalFileError(
            f"Local Bot API source size mismatch: expected {expected_size}, got {source_size}."
        )

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)

    try:
        # Prefer a hard-link to avoid duplicating a 300–400 MB APK on disk.
        os.link(source, destination)
        logger.info("APK working file created as hard-link: %s", destination)
    except OSError:
        try:
            shutil.copyfile(source, destination)
            logger.info("APK working file created by streamed filesystem copy: %s", destination)
        except OSError as exc:
            raise TelegramLocalFileError("Failed to copy APK from Local Bot API storage.") from exc

    final_size = destination.stat().st_size
    if final_size != source_size or (expected_size is not None and final_size != expected_size):
        destination.unlink(missing_ok=True)
        raise TelegramLocalFileError(
            f"Copied APK size mismatch: source={source_size}, destination={final_size}."
        )

    if config.CLEAN_LOCAL_API_SOURCE_AFTER_COPY:
        try:
            source.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove Local Bot API source: %s", _redact_secret(str(source)))

    return source, final_size
