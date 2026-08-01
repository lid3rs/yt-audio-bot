"""Multi-user Telegram bot that turns YouTube links into audio files.

The package is split by concern:

  config    — environment variables, derived constants, logging
  users     — the invite-only allow-list (UserStore) and auth filters
  media     — yt-dlp download and ffmpeg post-processing
  storage   — per-user file storage: listing, quota, auto-cleanup
  text      — user-facing strings (help message, file listing)
  handlers  — the Telegram command/message handlers
  app       — handler wiring and the run_polling entry point (main)

`bot.py` at the repository root is a thin shim that calls `ytbot.app.main`.
"""
