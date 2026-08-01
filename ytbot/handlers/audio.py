"""The core flow: /help, cookies upload, and turning a link into an audio file."""

import asyncio

import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes

from ..config import (
    POT_PROVIDER_URL,
    UPLOAD_WRITE_TIMEOUT,
    URL_RE,
    USER_QUOTA_MB,
    log,
)
from ..media import download, invalidate_pot_caches, shrink_or_split
from ..storage import enforce_quota, user_dir
from ..text import help_text


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(help_text(update.effective_user.id))


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept a Netscape cookies.txt sent in chat and install it for the sender."""
    msg = update.effective_message
    doc = msg.document
    if not doc or (doc.file_name or "").lower() != "cookies.txt":
        await msg.reply_text("If that's YouTube cookies, name the file cookies.txt and send again.")
        return
    udir = user_dir(update.effective_user.id)
    udir.mkdir(parents=True, exist_ok=True)
    file = await doc.get_file()
    await file.download_to_drive(udir / "cookies.txt")
    await msg.reply_text("🍪 Cookies installed — send your link again.")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    m = URL_RE.search(msg.text or "")
    if not m:
        await msg.reply_text("That doesn't look like a link.\n\n" + help_text(update.effective_user.id))
        return
    url = m.group(0)
    udir = user_dir(update.effective_user.id)
    udir.mkdir(parents=True, exist_ok=True)

    status = await msg.reply_text("⏳ Downloading audio…")
    try:
        try:
            path, info = await asyncio.to_thread(download, url, udir)
        except yt_dlp.utils.DownloadError as e:
            if not (POT_PROVIDER_URL and "403" in str(e)):
                raise
            log.warning("403 from YouTube — flushing PO-token caches and retrying")
            await status.edit_text("⏳ YouTube rejected the tokens — refreshing and retrying…")
            await asyncio.to_thread(invalidate_pot_caches)
            path, info = await asyncio.to_thread(download, url, udir, True)
        files = await asyncio.to_thread(shrink_or_split, path)
    except Exception as e:  # noqa: BLE001 - anything yt-dlp/ffmpeg throws ends up here
        log.exception("failed to fetch %s", url)
        await status.edit_text(f"❌ Failed: {str(e)[:600]}")
        return

    context.chat_data.pop("listing", None)  # stored /list numbering is stale now
    try:
        evicted = await asyncio.to_thread(enforce_quota, udir, {f.name for f in files})
    except Exception:  # noqa: BLE001 - eviction is housekeeping; never fail the send over it
        log.exception("quota enforcement failed for %s", udir)
        evicted = []
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
    if evicted:
        await msg.reply_text(
            f"ℹ️ You hit your {USER_QUOTA_MB:.0f} MB storage cap — "
            f"removed {len(evicted)} older file(s) to make room."
        )
