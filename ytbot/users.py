"""The invite-only allow-list and the auth filters built on top of it.

Access is invite-only: the owner (OWNER_ID) is always allowed; everyone else
must join through a one-time invite link. The allow-list is persisted to
DATA_DIR/users.json so it survives restarts.
"""

import json
import time
from pathlib import Path

from telegram.ext import filters

from .config import OWNER_ID, USERS_FILE, log


class UserStore:
    """The people allowed to use the bot, plus outstanding invite codes.

    Persisted atomically to users.json (write to a temp file, then rename). The
    owner is implicit — never stored here — so `is_authorized` checks it too.
    """

    def __init__(self, path: Path = USERS_FILE) -> None:
        self.path = path
        # uid -> {"username": str, "joined": epoch}
        self.authorized: dict[int, dict] = {}
        # code -> {"created": epoch}. One-time: burned the moment it's redeemed.
        self.invites: dict[str, dict] = {}

    def load(self) -> None:
        if not self.path.exists():
            self.authorized, self.invites = {}, {}
            return
        try:
            data = json.loads(self.path.read_text())
            self.authorized = {int(k): v for k, v in data.get("authorized", {}).items()}
            self.invites = dict(data.get("invites", {}))
        except Exception:  # noqa: BLE001 - corrupt file shouldn't take the bot down
            log.exception("could not read %s — starting with an empty user list", self.path)
            self.authorized, self.invites = {}, {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(
            {
                "authorized": {str(k): v for k, v in self.authorized.items()},
                "invites": self.invites,
            },
            indent=2,
        ))
        tmp.replace(self.path)

    def is_authorized(self, uid: int) -> bool:
        return uid == OWNER_ID or uid in self.authorized

    def new_invite(self, code: str) -> None:
        """Register a fresh one-time invite code and persist it."""
        self.invites[code] = {"created": time.time()}
        self.save()

    def redeem_invite(self, code: str, uid: int, username: str) -> bool:
        """Burn `code` and admit `uid`. Returns False if the code is unknown."""
        if code not in self.invites:
            return False
        del self.invites[code]  # one-time: burn it immediately
        self.authorized[uid] = {"username": username, "joined": time.time()}
        self.save()
        return True

    def remove_user(self, uid: int) -> None:
        """Drop a user from the allow-list and persist."""
        self.authorized.pop(uid, None)
        self.save()


# The single process-wide store. `load()` is called once at startup (app.main).
store = UserStore()


class _AuthorizedFilter(filters.MessageFilter):
    """Dynamic filter: matches messages from the owner or any invited user.

    A static filters.User() can't be used because the allow-list changes at
    runtime as people are invited or kicked.
    """

    def filter(self, message) -> bool:
        u = message.from_user
        return bool(u and store.is_authorized(u.id))


AUTH = _AuthorizedFilter()
OWNER = filters.User(user_id=OWNER_ID)
