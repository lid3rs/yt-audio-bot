"""YouTube download and audio post-processing (yt-dlp + ffmpeg).

These functions block, so callers run them via asyncio.to_thread.
"""

import math
import subprocess
import urllib.request
from pathlib import Path

import yt_dlp

from .config import (
    DATA_DIR,
    FALLBACK_BITRATE_K,
    MAX_SEND_BYTES,
    PLAYER_CLIENTS,
    POT_PROVIDER_URL,
    log,
)


def invalidate_pot_caches() -> None:
    """Ask the bgutil provider to drop its cached tokens.

    YouTube revokes integrity tokens well before their advertised TTL; the
    provider keeps deriving PO tokens from the dead one and every media request
    answers 403 until the caches are flushed.
    """
    for endpoint in ("/invalidate_it", "/invalidate_caches"):
        try:
            req = urllib.request.Request(POT_PROVIDER_URL + endpoint, method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception:  # noqa: BLE001 - provider may be mid-restart; retry will tell
            log.warning("PO-token cache invalidation via %s failed", endpoint)


def download(
    url: str,
    user_dir: Path,
    fresh: bool = False,
    player_clients: list[str] | None = None,
) -> tuple[Path, dict]:
    """Download the audio track of `url` into `user_dir` as .m4a.

    With fresh=True yt-dlp's on-disk cache is bypassed too, so a retry after a
    token flush cannot reuse a stale cached PO token or player signature.

    player_clients overrides both yt-dlp's own choice and the PLAYER_CLIENTS env
    var for this one call; handle_link uses it to route around a client that
    YouTube is currently breaking.
    """
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(user_dir / "%(title).120B [%(id)s].%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}
        ],
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    extractor_args = {}
    if POT_PROVIDER_URL:
        extractor_args["youtubepot-bgutilhttp"] = {"base_url": [POT_PROVIDER_URL]}
    # Only override the player client when explicitly asked. yt-dlp's default
    # set already consumes the provider's PO tokens and, unlike a pinned
    # web/mweb, avoids the media-stream 403 that datacenter IPs hit on some
    # videos (verified: web/mweb 403, default downloads the same video).
    clients = player_clients or PLAYER_CLIENTS
    if clients:
        extractor_args["youtube"] = {"player_client": clients}
    if extractor_args:
        opts["extractor_args"] = extractor_args
    # Per-user cookies win; a shared DATA_DIR/cookies.txt is the fallback.
    for cookies in (user_dir / "cookies.txt", DATA_DIR / "cookies.txt"):
        if cookies.exists():
            opts["cookiefile"] = str(cookies)
            break
    if fresh:
        opts["cachedir"] = False

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info and "entries" in info:
            info = info["entries"][0]
        path = Path(ydl.prepare_filename(info)).with_suffix(".m4a")

    if not path.exists():
        raise FileNotFoundError(f"yt-dlp finished but {path.name} is missing")
    return path, info


def duration_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def shrink_or_split(path: Path) -> list[Path]:
    """Return files that each fit under the upload cap.

    Oversized files are first re-encoded to mono AAC at FALLBACK_BITRATE_K
    (plenty for falling-asleep listening); if the result is still too big it is
    cut into equal parts. Intermediate oversized files are deleted.
    """
    if path.stat().st_size <= MAX_SEND_BYTES:
        return [path]

    small = path.with_name(f"{path.stem} ({FALLBACK_BITRATE_K}k).m4a")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vn",
         "-c:a", "aac", "-b:a", f"{FALLBACK_BITRATE_K}k", "-ac", "1", str(small)],
        check=True,
    )
    path.unlink()
    if small.stat().st_size <= MAX_SEND_BYTES:
        return [small]

    parts_needed = math.ceil(small.stat().st_size / (MAX_SEND_BYTES * 0.95))
    seg_time = math.ceil(duration_seconds(small) / parts_needed)
    # '%' in a title would be read by ffmpeg as a pattern directive
    pattern = small.with_name(f"{small.stem.replace('%', '%%')} part%02d.m4a")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(small), "-c", "copy",
         "-f", "segment", "-segment_time", str(seg_time),
         "-reset_timestamps", "1", str(pattern)],
        check=True,
    )
    small.unlink()

    prefix = f"{small.stem} part"
    parts = sorted(
        p for p in small.parent.iterdir()
        if p.name.startswith(prefix) and p.suffix == ".m4a"
    )
    if not parts:
        raise RuntimeError("splitting produced no files")
    return parts
