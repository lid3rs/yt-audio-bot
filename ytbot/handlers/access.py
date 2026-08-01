"""Joining and administration: /start, /invite, /users, /kick, and the
catch-all reply to anyone who isn't invited.
"""

import secrets
import shutil

from telegram import Update
from telegram.ext import ContextTypes

from ..config import OWNER_ID, log
from ..storage import user_dir
from ..text import help_text
from ..users import store


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start, including /start <invite-code> from an invite link."""
    user = update.effective_user
    msg = update.effective_message
    code = context.args[0] if context.args else None

    if store.is_authorized(user.id):
        await msg.reply_text(help_text(user.id))
        return

    if code and store.redeem_invite(code, user.id, user.username or user.full_name):
        user_dir(user.id).mkdir(parents=True, exist_ok=True)
        await msg.reply_text(
            "✅ You're in! Send me a YouTube link and I'll reply with the audio.\n\n"
            + help_text(user.id)
        )
        try:
            await context.bot.send_message(
                OWNER_ID,
                f"👤 {user.full_name} (@{user.username or '—'}, id {user.id}) joined via invite.",
            )
        except Exception:  # noqa: BLE001 - notifying the owner is best-effort
            pass
        return

    if code:
        await msg.reply_text(
            "This invite link is invalid or has already been used. "
            "Ask the owner for a fresh one."
        )
        return

    await msg.reply_text("🔒 This bot is invite-only. Ask the owner for an invite link.")


async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    code = secrets.token_urlsafe(6)
    store.new_invite(code)
    username = context.bot.username
    link = f"https://t.me/{username}?start={code}"
    await update.effective_message.reply_text(
        "🎟 One-time invite link — valid until the first person taps it:\n"
        f"{link}\n\n"
        "Send it to whoever you want to invite."
    )


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not store.authorized:
        await update.effective_message.reply_text(
            "No invited users yet. Use /invite to add someone."
        )
        return
    lines = ["Invited users:"]
    for uid, meta in store.authorized.items():
        lines.append(f"• {meta.get('username', '?')} — id {uid}")
    lines.append(f"\nUnused invite links: {len(store.invites)}")
    lines.append("Remove someone with /kick <id>.")
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text("Usage: /kick <user id>  (see /users).")
        return
    uid = int(context.args[0])
    if uid == OWNER_ID:
        await update.effective_message.reply_text("You can't kick yourself.")
        return
    if uid not in store.authorized:
        await update.effective_message.reply_text("That id isn't on the list (see /users).")
        return
    store.remove_user(uid)
    shutil.rmtree(user_dir(uid), ignore_errors=True)
    await update.effective_message.reply_text(
        f"🗑 Removed user {uid} and deleted their stored files."
    )


async def unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    log.warning("Ignoring message from unauthorized user id=%s username=%s",
                getattr(u, "id", "?"), getattr(u, "username", "?"))
    msg = update.effective_message
    if msg:
        await msg.reply_text("🔒 This bot is invite-only. Ask the owner for an invite link.")
