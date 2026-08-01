"""Managing stored files: /list, /delete <n|all>, and the bare-number shortcut."""

from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from ..storage import stored_files, user_dir
from ..text import render_list


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        render_list(context, user_dir(update.effective_user.id))
    )


async def _delete_by_token(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
    msg = update.effective_message
    udir = user_dir(update.effective_user.id)

    if token.lower() == "all":
        files = stored_files(udir)
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
    await msg.reply_text(f"🗑 Deleted: {path.stem}\n\n{render_list(context, udir)}")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            "Tell me what to delete: /delete <number> or /delete all"
        )
        return
    await _delete_by_token(update, context, context.args[0])


async def msg_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _delete_by_token(update, context, update.effective_message.text.strip())
