from __future__ import annotations

import zipfile
from pathlib import Path


def make_zip_parts(
    files: list[Path],
    dest_dir: Path,
    stem: str,
    max_bytes: int,
) -> list[Path]:
    """Pack files into one or more zip archives, each ≤ max_bytes.

    Files larger than max_bytes on their own are placed in their own zip
    (the archive may then exceed the cap; the caller reports that).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not files:
        return []

    parts: list[Path] = []
    current: list[Path] = []
    current_size = 0
    overhead = 1024  # zip headers per file, conservative

    def flush() -> None:
        nonlocal current, current_size
        if not current:
            return
        index = len(parts) + 1
        path = dest_dir / f"{stem}-part{index:02d}.zip"
        _write_zip(path, current)
        parts.append(path)
        current = []
        current_size = 0

    for file in files:
        size = file.stat().st_size + overhead
        if current and current_size + size > max_bytes:
            flush()
        current.append(file)
        current_size += size
        if current_size >= max_bytes:
            flush()
    flush()

    if len(parts) == 1:
        single = dest_dir / f"{stem}.zip"
        parts[0].replace(single)
        return [single]
    return parts


def _write_zip(path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            zf.write(file, arcname=file.name)
