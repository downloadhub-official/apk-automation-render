from __future__ import annotations

import logging
from urllib.parse import quote

import requests

import config

logger = logging.getLogger(__name__)


class ShortenerError(RuntimeError):
    pass


def _configured(value: str) -> bool:
    return bool(value and "PASTE_" not in value)


def _extract_url(payload) -> str | None:
    """
    Shortener APIs have changed response shapes over time. Accept common
    JSON/text forms without silently accepting unrelated values.
    """
    if isinstance(payload, dict):
        # Common keys
        for key in (
            "shortenedUrl",
            "short_url",
            "shorturl",
            "short",
            "url",
            "link",
            "shortened",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value

        # Nested common response shapes
        for key in ("data", "result", "response"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                value = _extract_url(nested)
                if value:
                    return value
            elif isinstance(nested, str) and nested.startswith(("http://", "https://")):
                return nested

    if isinstance(payload, list):
        for item in payload:
            value = _extract_url(item)
            if value:
                return value

    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith(("http://", "https://")):
            return text

        # Some APIs may return JSON as text.
        import json
        try:
            decoded = json.loads(text)
            return _extract_url(decoded)
        except Exception:
            pass

    return None


def _request(url: str) -> requests.Response:
    try:
        response = requests.get(
            url,
            timeout=(config.HTTP_CONNECT_TIMEOUT, config.HTTP_READ_TIMEOUT),
            headers={"User-Agent": "APK-Automation-Bot/1.0"},
        )
    except requests.RequestException as exc:
        raise ShortenerError(f"Shortener network error: {exc}") from exc

    if not response.ok:
        raise ShortenerError(
            f"Shortener HTTP {response.status_code}: {response.text[:500]}"
        )
    return response


def shorten_gplinks(long_url: str) -> str:
    if not _configured(config.GPLINKS_API_KEY):
        raise ShortenerError("GPLinks API key is not configured.")

    url = (
        "https://api.gplinks.com/api"
        f"?api={quote(config.GPLINKS_API_KEY)}"
        f"&url={quote(long_url, safe='')}"
    )
    response = _request(url)

    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    short = _extract_url(payload)
    if not short:
        raise ShortenerError(f"GPLinks response did not contain a short URL: {response.text[:500]}")
    return short


def shorten_oii(long_url: str) -> str:
    if not _configured(config.OII_API_KEY):
        raise ShortenerError("Oii.io API key is not configured.")

    url = (
        "https://oii.io/api"
        f"?api={quote(config.OII_API_KEY)}"
        f"&url={quote(long_url, safe='')}"
    )
    response = _request(url)

    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    short = _extract_url(payload)
    if not short:
        raise ShortenerError(f"Oii.io response did not contain a short URL: {response.text[:500]}")
    return short


def shorten_ouo(long_url: str) -> str:
    if not _configured(config.OUO_API_KEY):
        raise ShortenerError("Ouo.io API key is not configured.")

    url = (
        "https://ouo.io/api"
        f"/{quote(config.OUO_API_KEY)}"
        f"?s={quote(long_url, safe='')}"
    )
    response = _request(url)

    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    short = _extract_url(payload)
    if not short:
        raise ShortenerError(f"Ouo.io response did not contain a short URL: {response.text[:500]}")
    return short


def create_short_links(long_url: str) -> dict[str, str]:
    """
    Generate all configured short links.

    If any configured provider fails, the workflow stops before Blogger is
    touched. This prevents a half-updated page.
    """
    result = {}

    providers = [
        ("gplinks", config.GPLINKS_API_KEY, shorten_gplinks),
        ("oii", config.OII_API_KEY, shorten_oii),
        ("ouo", config.OUO_API_KEY, shorten_ouo),
    ]

    missing = [name for name, key, _ in providers if not _configured(key)]
    if missing:
        raise ShortenerError(
            "Required shortener API key(s) are missing: "
            + ", ".join(missing)
            + ". Configure GPLinks, Oii.io and Ouo.io before running the test."
        )

    for name, _key, fn in providers:
        result[name] = fn(long_url)

    return result
