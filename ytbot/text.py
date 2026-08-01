"""User-facing text: the help message and the numbered file listing.

Kept in one place so the wording is easy to find and tweak. `render_list` also
records the listing in chat_data so a later bare number can address a file.
"""

from pathlib import Path

from .config import CLEANUP_HOURS, DATA_DIR, OWNER_ID, USER_QUOTA_BYTES, USER_QUOTA_MB
from .storage import fmt_size, stored_files, user_dir


def help_text(uid: int) -> str:
    has_cookies = (user_dir(uid) / "cookies.txt").exists() or (DATA_DIR / "cookies.txt").exists()
    lines = [
        "Send me a YouTube link and I'll reply with the audio track.",
        "",
        "Commands",
        "/help — show this message",
        "/list — show your stored audio files",
        "/delete N — delete file N from your last list (or just send the number)",
        "/delete all — wipe everything you've stored",
    ]
    if uid == OWNER_ID:
        lines += [
            "",
            "Owner commands",
            "/invite — create a one-time invite link to share",
            "/users — list invited users and unused invite links",
            "/kick <id> — remove a user and delete their stored files",
        ]
    lines += [""]
    if USER_QUOTA_BYTES > 0:
        lines.append(
            f"Your storage cap is {USER_QUOTA_MB:.0f} MB — when you hit it, your "
            "oldest files are removed automatically."
        )
    lines += [
        f"Files are auto-deleted after {CLEANUP_HOURS:.0f} h — no cleanup needed.",
        ("🍪 YouTube cookies are installed."
         if has_cookies
         else "No YouTube cookies installed — send me a cookies.txt file if YouTube demands sign-in."),
    ]
    return "\n".join(lines)


def render_list(context, directory: Path) -> str:
    """Build the numbered listing and remember it for number-based deletion."""
    files = stored_files(directory)
    if not files:
        context.chat_data.pop("listing", None)
        return "Nothing stored — your audio folder is empty."
    context.chat_data["listing"] = [str(p) for p in files]
    lines = []
    for i, p in enumerate(files, 1):
        name = p.stem if len(p.stem) <= 64 else p.stem[:63] + "…"
        lines.append(f"{i}. {name}  ({fmt_size(p.stat().st_size)})")
    total = sum(p.stat().st_size for p in files)
    if USER_QUOTA_BYTES > 0:
        lines.append(f"\nTotal: {len(files)} file(s), {fmt_size(total)} of {USER_QUOTA_MB:.0f} MB")
    else:
        lines.append(f"\nTotal: {len(files)} file(s), {fmt_size(total)}")
    lines.append("Delete one with /delete <number> — or just send me the number.")
    return "\n".join(lines)
