"""Per-user file storage: locating folders, listing, quota, auto-cleanup.

Every user's downloads live in DATA_DIR/<uid>/, and every operation here is
scoped to a single user's folder — one user never sees or touches another's.
"""

import asyncio
import time
from pathlib import Path

from .config import AUDIO_EXTS, CLEANUP_HOURS, DATA_DIR, USER_QUOTA_BYTES, log


def user_dir(uid: int) -> Path:
    return DATA_DIR / str(uid)


def stored_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return sorted(
        (p for p in base.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS),
        key=lambda p: p.stat().st_mtime,
    )


def enforce_quota(directory: Path, keep_names: set[str] | None = None) -> list[Path]:
    """Delete the user's oldest files until the folder fits USER_QUOTA_BYTES.

    Files named in `keep_names` (the just-finished download) are never evicted,
    so a single download bigger than the whole quota is still delivered — only
    *older* files are removed to make room. Returns what was deleted.
    """
    if USER_QUOTA_BYTES <= 0:
        return []
    keep_names = keep_names or set()
    files = stored_files(directory)  # oldest first
    total = sum(p.stat().st_size for p in files)
    evicted: list[Path] = []
    for p in files:
        if total <= USER_QUOTA_BYTES:
            break
        if p.name in keep_names:
            continue
        total -= p.stat().st_size
        p.unlink(missing_ok=True)
        evicted.append(p)
        log.info("quota: evicted %s from user %s", p.name, directory.name)
    return evicted


def fmt_size(n: float) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


async def cleanup_loop() -> None:
    """Background sweep: delete stored audio older than CLEANUP_HOURS."""
    while True:
        cutoff = time.time() - CLEANUP_HOURS * 3600
        for udir in (p for p in DATA_DIR.iterdir() if p.is_dir()) if DATA_DIR.exists() else []:
            for p in stored_files(udir):
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                    log.info("auto-deleted after %.0fh: %s", CLEANUP_HOURS, p.name)
        await asyncio.sleep(1800)
