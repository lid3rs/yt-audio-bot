"""Configuration: environment variables, derived constants, logging.

Importing this module reads the environment, so BOT_TOKEN and the owner id must
be set (exactly as when the old single-file bot.py was imported).
"""

import logging
import os
import re
from pathlib import Path

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("yt-audio-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
# OWNER_ID is the admin who can invite/kick. ALLOWED_USER_ID is the old name for
# the same thing, kept so existing .env files keep working.
OWNER_ID = int(os.environ.get("OWNER_ID") or os.environ["ALLOWED_USER_ID"])
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
USERS_FILE = DATA_DIR / "users.json"
# The Bot API rejects uploads over 50 MB, so anything bigger gets re-encoded and,
# if that is still not enough, cut into parts that each fit.
MAX_SEND_MB = float(os.environ.get("MAX_SEND_MB", "49"))
FALLBACK_BITRATE_K = int(os.environ.get("FALLBACK_BITRATE_K", "64"))
# bgutil PO-token provider (companion container) — YouTube demands these tokens
# from datacenter IPs ("Sign in to confirm you're not a bot"). Empty disables.
POT_PROVIDER_URL = os.environ.get("POT_PROVIDER_URL", "")
# Auto-delete stored audio after this many hours (0 disables the sweep).
CLEANUP_HOURS = float(os.environ.get("CLEANUP_HOURS", "24"))
# Per-user storage cap. When a user's folder grows past this, their oldest files
# are evicted to make room for the newest download (0 disables the cap).
USER_QUOTA_MB = float(os.environ.get("USER_QUOTA_MB", "500"))
# yt-dlp player clients. Empty = let yt-dlp choose its own (actively maintained)
# default set. Pinning web/mweb turned out to be worse: their media URLs 403 from
# datacenter IPs for some videos, while yt-dlp's default set picks a client that
# downloads them. Set PLAYER_CLIENTS only to force a specific client for a video.
PLAYER_CLIENTS = [c.strip() for c in os.environ.get("PLAYER_CLIENTS", "").split(",") if c.strip()]

MAX_SEND_BYTES = int(MAX_SEND_MB * 1024 * 1024)
USER_QUOTA_BYTES = int(USER_QUOTA_MB * 1024 * 1024)
UPLOAD_WRITE_TIMEOUT = 1800  # seconds; a 49 MB upload on a slow VPS link can be slow
AUDIO_EXTS = {".m4a", ".mp3", ".opus", ".ogg", ".webm", ".aac", ".flac", ".wav"}
URL_RE = re.compile(r"https?://\S+")
