"""Handler wiring and the run_polling entry point.

`main()` builds the Application, registers every handler in the right order
(auth filters matter), starts the background cleanup task, and polls.
"""

import asyncio

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import BOT_TOKEN, CLEANUP_HOURS, DATA_DIR, MAX_SEND_BYTES, OWNER_ID, log
from .handlers import access, audio, files
from .storage import cleanup_loop, fmt_size
from .users import AUTH, OWNER, store

# Keep references to background tasks so they aren't garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler.

    Telegram infrastructure hiccups (502 Bad Gateway, dropped reads, timeouts)
    are transient and run_polling retries them on its own, so log a one-liner
    instead of a full traceback. Anything else is a real bug — trace it.
    """
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        log.warning("transient Telegram network error (auto-retried): %s", err)
        return
    log.error("unhandled error while processing an update", exc_info=err)


async def _set_command_menu(app: Application) -> None:
    """Populate Telegram's "/" autocomplete menu.

    Everyone sees the user commands; the owner's private chat additionally shows
    the management commands, so the owner's menu is the full list.
    """
    user_cmds = [
        BotCommand("help", "show help"),
        BotCommand("list", "list your stored files"),
        BotCommand("delete", "delete a file: /delete N or /delete all"),
    ]
    owner_cmds = user_cmds + [
        BotCommand("invite", "create a one-time invite link"),
        BotCommand("users", "list invited users"),
        BotCommand("kick", "remove a user: /kick <id>"),
    ]
    try:
        await app.bot.set_my_commands(user_cmds)
        await app.bot.set_my_commands(owner_cmds, scope=BotCommandScopeChat(chat_id=OWNER_ID))
    except Exception:  # noqa: BLE001 - the "/" menu is a nicety; don't block startup
        log.exception("could not set the command menu")


async def _post_init(app: Application) -> None:
    await _set_command_menu(app)
    if CLEANUP_HOURS > 0:
        task = asyncio.create_task(cleanup_loop())
        _background_tasks.add(task)  # keep a reference so the task isn't GC'd
        log.info("auto-cleanup enabled: files older than %.0fh are removed", CLEANUP_HOURS)


async def _post_shutdown(app: Application) -> None:
    for task in _background_tasks:
        task.cancel()


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store.load()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)  # one user's long download must not block others
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(120)
        .pool_timeout(30)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    # /start has no auth filter: it's how invitees join and how anyone gets a reply.
    app.add_handler(CommandHandler("start", access.cmd_start))
    app.add_handler(CommandHandler("help", audio.cmd_help, filters=AUTH))
    # Owner-only management commands.
    app.add_handler(CommandHandler("invite", access.cmd_invite, filters=OWNER))
    app.add_handler(CommandHandler("users", access.cmd_users, filters=OWNER))
    app.add_handler(CommandHandler(["kick", "revoke"], access.cmd_kick, filters=OWNER))
    # Everything below is for any invited user, scoped to their own folder.
    app.add_handler(CommandHandler("list", files.cmd_list, filters=AUTH))
    app.add_handler(CommandHandler(["delete", "del"], files.cmd_delete, filters=AUTH))
    app.add_handler(MessageHandler(AUTH & filters.Regex(r"^\s*\d+\s*$"), files.msg_number))
    app.add_handler(MessageHandler(AUTH & filters.Document.ALL, audio.handle_document))
    app.add_handler(MessageHandler(AUTH & filters.TEXT & ~filters.COMMAND, audio.handle_link))
    app.add_handler(MessageHandler(~AUTH, access.unauthorized))
    app.add_error_handler(on_error)

    log.info("Bot up; owner id %s, %d invited user(s); audio stored in %s, send cap %s",
             OWNER_ID, len(store.authorized), DATA_DIR, fmt_size(MAX_SEND_BYTES))
    app.run_polling(allowed_updates=Update.ALL_TYPES)
