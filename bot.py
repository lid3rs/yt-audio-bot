"""Personal Telegram bot: send it a YouTube link, get the audio track back.

Usage in chat:
  <YouTube link>   -> downloads the audio and sends it as a playable track
  /list            -> numbered list of audio files stored on the server
  /delete N        -> delete file number N from the last /list (a bare "N" works too)
  /delete all      -> delete every stored file
  /start, /help    -> short usage note

Only the Telegram user with id ALLOWED_USER_ID is served; everyone else is ignored.
"""

import asyncio
import logging
import math
import os
import re
import subprocess
import time
from pathlib import Path

import yt_dlp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("yt-audio-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
# The Bot API rejects uploads over 50 MB, so anything bigger gets re-encoded and,
# if that is still not enough, cut into parts that each fit.
MAX_SEND_MB = float(os.environ.get("MAX_SEND_MB", "49"))
FALLBACK_BITRATE_K = int(os.environ.get("FALLBACK_BITRATE_K", "64"))
# bgutil PO-token provider (companion container) — YouTube demands these tokens
# from datacenter IPs ("Sign in to confirm you're not a bot"). Empty disables.
POT_PROVIDER_URL = os.environ.get("POT_PROVIDER_URL", "")
# Auto-delete stored audio after this many hours (0 disables the sweep).
CLEANUP_HOURS = float(os.environ.get("CLEANUP_HOURS", "24"))
# yt-dlp player clients; web/mweb consume PO tokens, which datacenter IPs need.
PLAYER_CLIENTS = [c.strip() for c in os.environ.get("PLAYER_CLIENTS", "web,mweb").split(",") if c.strip()]

MAX_SEND_BYTES = int(MAX_SEND_MB * 1024 * 1024)
UPLOAD_WRITE_TIMEOUT = 1800  # seconds; a 49 MB upload on a slow VPS link can be slow
AUDIO_EXTS = {".m4a", ".mp3", ".opus", ".ogg", ".webm", ".aac", ".flac", ".wav"}
URL_RE = re.compile(r"https?://\S+")

ONLY_ME = filters.User(user_id=ALLOWED_USER_ID)

def _help_text() -> str:
    cookies = DATA_DIR / "cookies.txt"
    return (
        "Send me a YouTube link and I'll reply with the audio track.\n\n"
        "/list — show stored audio files\n"
        "/delete N — delete file N from the last list (or just send the number)\n"
        "/delete all — wipe everything stored\n\n"
        f"Files are auto-deleted after {CLEANUP_HOURS:.0f} h — no cleanup needed.\n"
        + ("🍪 YouTube cookies are installed."
           if cookies.exists()
           else "No YouTube cookies installed — send me a cookies.txt file if YouTube demands sign-in.")
    )


# --------------------------------------------------------------------------- #
# Blocking helpers (run via asyncio.to_thread)                                #
# --------------------------------------------------------------------------- #

def _download(url: str) -> tuple[Path, dict]:
    """Download the audio track of `url` into DATA_DIR as .m4a."""
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(DATA_DIR / "%(title).120B [%(id)s].%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}
        ],
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if POT_PROVIDER_URL:
        opts["extractor_args"] = {
            "youtubepot-bgutilhttp": {"base_url": [POT_PROVIDER_URL]},
            # The default android_vr client ignores PO tokens and is exactly what
            # datacenter IPs get blocked on; web/mweb consume the provider's tokens.
            "youtube": {"player_client": PLAYER_CLIENTS},
        }
    cookies = DATA_DIR / "cookies.txt"
    if cookies.exists():
        opts["cookiefile"] = str(cookies)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info and "entries" in info:
            info = info["entries"][0]
        path = Path(ydl.prepare_filename(info)).with_suffix(".m4a")

    if not path.exists():
        raise FileNotFoundError(f"yt-dlp finished but {path.name} is missing")
    return path, info


def _duration_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def _shrink_or_split(path: Path) -> list[Path]:
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
    seg_time = math.ceil(_duration_seconds(small) / parts_needed)
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


def _stored_files() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return sorted(
        (p for p in DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS),
        key=lambda p: p.stat().st_mtime,
    )


def _fmt_size(n: float) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


# --------------------------------------------------------------------------- #
# Handlers                                                                    #
# --------------------------------------------------------------------------- #

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_help_text())


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept a Netscape cookies.txt sent in chat and install it for yt-dlp."""
    msg = update.effective_message
    doc = msg.document
    if not doc or (doc.file_name or "").lower() != "cookies.txt":
        await msg.reply_text("If that's YouTube cookies, name the file cookies.txt and send again.")
        return
    file = await doc.get_file()
    await file.download_to_drive(DATA_DIR / "cookies.txt")
    await msg.reply_text("🍪 Cookies installed — send your link again.")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    m = URL_RE.search(msg.text or "")
    if not m:
        await msg.reply_text("That doesn't look like a link.\n\n" + _help_text())
        return
    url = m.group(0)

    status = await msg.reply_text("⏳ Downloading audio…")
    try:
        path, info = await asyncio.to_thread(_download, url)
        files = await asyncio.to_thread(_shrink_or_split, path)
    except Exception as e:  # noqa: BLE001 - anything yt-dlp/ffmpeg throws ends up here
        log.exception("failed to fetch %s", url)
        await status.edit_text(f"❌ Failed: {str(e)[:600]}")
        return

    context.chat_data.pop("listing", None)  # stored /list numbering is stale now
    n = len(files)
    for i, f in enumerate(files, 1):
        await status.edit_text("📤 Uploading…" if n == 1 else f"📤 Uploading part {i}/{n}…")
        title = info.get("title") or f.stem
        if n > 1:
            title = f"{title} — part {i}/{n}"
        try:
            with f.open("rb") as fh:
                await msg.reply_audio(
                    audio=fh,
                    title=title,
                    performer=info.get("uploader") or info.get("channel"),
                    duration=info.get("duration") if n == 1 else None,
                    filename=f.name,
                    write_timeout=UPLOAD_WRITE_TIMEOUT,
                )
        except Exception as e:  # noqa: BLE001
            log.exception("failed to send %s", f)
            await status.edit_text(f"❌ Downloaded, but sending failed: {str(e)[:600]}")
            return
    await status.delete()


def _render_list(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Build the numbered listing and remember it for number-based deletion."""
    files = _stored_files()
    if not files:
        context.chat_data.pop("listing", None)
        return "Nothing stored — the audio folder is empty."
    context.chat_data["listing"] = [str(p) for p in files]
    lines = []
    for i, p in enumerate(files, 1):
        name = p.stem if len(p.stem) <= 64 else p.stem[:63] + "…"
        lines.append(f"{i}. {name}  ({_fmt_size(p.stat().st_size)})")
    total = sum(p.stat().st_size for p in files)
    lines.append(f"\nTotal: {len(files)} file(s), {_fmt_size(total)}")
    lines.append("Delete one with /delete <number> — or just send me the number.")
    return "\n".join(lines)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_render_list(context))


async def _delete_by_token(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
    msg = update.effective_message

    if token.lower() == "all":
        files = _stored_files()
        for p in files:
            p.unlink(missing_ok=True)
        context.chat_data.pop("listing", None)
        await msg.reply_text(f"🗑 Deleted {len(files)} file(s).")
        return

    listing = context.chat_data.get("listing")
    if not listing:
        await msg.reply_text("Run /list first, then tell me the number to delete.")
        return
    if not token.isdigit() or not 1 <= int(token) <= len(listing):
        await msg.reply_text(f"Give me a number between 1 and {len(listing)} (see /list).")
        return

    path = Path(listing[int(token) - 1])
    path.unlink(missing_ok=True)
    await msg.reply_text(f"🗑 Deleted: {path.stem}\n\n{_render_list(context)}")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            "Tell me what to delete: /delete <number> or /delete all"
        )
        return
    await _delete_by_token(update, context, context.args[0])


async def msg_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _delete_by_token(update, context, update.effective_message.text.strip())


async def unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    log.warning("Ignoring message from unauthorized user id=%s username=%s",
                getattr(u, "id", "?"), getattr(u, "username", "?"))


async def _cleanup_loop() -> None:
    while True:
        cutoff = time.time() - CLEANUP_HOURS * 3600
        for p in _stored_files():
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                log.info("auto-deleted after %.0fh: %s", CLEANUP_HOURS, p.name)
        await asyncio.sleep(1800)


_background_tasks = set()


async def _post_init(app: Application) -> None:
    if CLEANUP_HOURS > 0:
        task = asyncio.create_task(_cleanup_loop())
        _background_tasks.add(task)  # keep a reference so the task isn't GC'd
        log.info("auto-cleanup enabled: files older than %.0fh are removed", CLEANUP_HOURS)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(120)
        .pool_timeout(30)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler(["start", "help"], cmd_help, filters=ONLY_ME))
    app.add_handler(CommandHandler("list", cmd_list, filters=ONLY_ME))
    app.add_handler(CommandHandler(["delete", "del"], cmd_delete, filters=ONLY_ME))
    app.add_handler(MessageHandler(ONLY_ME & filters.Regex(r"^\s*\d+\s*$"), msg_number))
    app.add_handler(MessageHandler(ONLY_ME & filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(ONLY_ME & filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(MessageHandler(~ONLY_ME, unauthorized))

    log.info("Bot up; audio stored in %s, send cap %s", DATA_DIR, _fmt_size(MAX_SEND_BYTES))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
