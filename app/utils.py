from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


def normalize(text: str) -> str:
    text = (text or "").casefold()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def identify_app(filename: str, aliases: dict[str, tuple[str, ...]]) -> str | None:
    """
    Identify an app from the filename, case-insensitively.

    We deliberately require exactly one app match.
    0 matches -> unknown app.
    >1 matches -> ambiguous app, caller must stop.
    """
    haystack = normalize(Path(filename).stem)
    matches = []

    for app, app_aliases in aliases.items():
        for alias in app_aliases:
            if normalize(alias) in haystack:
                matches.append(app)
                break

    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]
    if len(unique) == 0:
        return None

    raise ValueError(
        "Ambiguous app filename: matches multiple apps: " + ", ".join(unique)
    )


def safe_filename(name: str) -> str:
    name = Path(name).name
    if not name or name in {".", ".."}:
        raise ValueError("Invalid filename")
    if "\x00" in name:
        raise ValueError("Invalid filename")
    return name


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    n = float(value)
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{value} B"


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def first_nonempty(values: Iterable[str | None]) -> str | None:
    for value in values:
        if value:
            return value
    return None
