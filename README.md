# yt-audio-bot

A tiny self-hosted Telegram bot: send it a YouTube link, it replies with the
audio track as a playable file. Built for one thing — listening to talks and
podcasts from YouTube while falling asleep, without keeping a video app open.

Single-user by design (the bot only answers your Telegram account), runs as two
small Docker containers, opens no ports.

## How it works

| You send | Bot does |
|---|---|
| a YouTube link | downloads the audio with yt-dlp, sends it back as a playable track |
| `/list` | numbered list of files stored on the server, with sizes |
| `/delete 3` (or just `3` after a `/list`) | deletes file 3, shows the updated list |
| `/delete all` | deletes everything |
| a `cookies.txt` file | installs YouTube cookies (see below) |
| `/help` | usage note + whether cookies are installed |

Stored files are **auto-deleted after 24 h** (`CLEANUP_HOURS`), so you never
have to clean up — `/delete` exists for when you want something gone sooner.

### The moving parts

- **yt-audio-bot** — Python bot: [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot),
  [yt-dlp](https://github.com/yt-dlp/yt-dlp), ffmpeg, and [deno](https://deno.com)
  (JS runtime yt-dlp needs for YouTube's signature challenges).
- **bgutil-provider** — [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider),
  generates the PO tokens YouTube demands from datacenter IPs.

### Telegram's 50 MB bot limit

Bots can't upload files over 50 MB. Oversized audio is automatically re-encoded
to 64 kbps mono (fine for speech); if a file is still too big after that, it's
split into parts sent as separate tracks. A 1-hour talk arrives as one ~30 MB file.

## Setup

### 1. Create your Telegram bot (2 minutes, free)

1. In Telegram, search for **@BotFather** — the official bot-creation bot
   (it has a blue verified checkmark).
2. Send it `/newbot`.
3. It asks for a **display name** — anything you like, e.g. `My Audio Bot`.
4. It asks for a **username** — must be unique and end in `bot`,
   e.g. `mysleepy_audio_bot`.
5. BotFather replies with an **HTTP API token** that looks like
   `1234567890:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`. That's your `BOT_TOKEN` —
   treat it like a password; anyone who has it controls the bot.

### 2. Find your Telegram user id

Message **@userinfobot** — it replies with your numeric id (e.g. `123456789`).
That's your `ALLOWED_USER_ID`. The bot answers **only** this account and
silently ignores everyone else, so nobody but you can use your server.

### 3. Configure and run

```bash
cp .env.example .env    # fill in BOT_TOKEN and ALLOWED_USER_ID
docker compose up -d --build
```

### 4. Start the chat

Bots can't message you first: open `t.me/<your_bot_username>` (or find the bot
by its username in search), press **Start**, and send it a YouTube link. The
first reply can take a minute while the containers finish starting.

### Or deploy to a server with a registry + Portainer

Fill in the deploy section of `.env` (registry image name, Portainer URL, API
key, endpoint id), then:

```bash
./deploy.sh
```

The script builds the image for your server's platform, pushes it to your
registry, and creates/updates the Portainer stack through the API with a forced
image pull. Run it again to redeploy — no versioning, no manual Portainer steps.
If your Portainer has a self-signed certificate, pin it with
`PORTAINER_TLS_FINGERPRINT` instead of disabling TLS verification.

## YouTube on server IPs: PO tokens and cookies

Running yt-dlp from a datacenter IP usually hits
`Sign in to confirm you're not a bot`. Two layers deal with this:

1. **PO tokens** (automatic): the bgutil provider container generates them and
   the bot requests the `web`/`mweb` player clients, which accept them.
2. **Self-healing on 403** (automatic): YouTube revokes its integrity tokens
   long before their advertised lifetime, which turns into sudden
   `HTTP Error 403: Forbidden` on downloads that worked hours earlier. When
   that happens the bot flushes the provider's token caches
   (`/invalidate_it` + `/invalidate_caches`) and retries once with yt-dlp's
   cache bypassed — you just see "refreshing and retrying" instead of an error.
3. **Cookies** (one-time, if your IP is blocked even with tokens): log into
   YouTube in an **incognito window** — ideally with a spare Google account —
   export cookies with a "Get cookies.txt LOCALLY"-style extension (Netscape
   format, *not* JSON), close the window without logging out, and **send the
   file to the bot in Telegram**. It installs them itself and confirms with 🍪.
   Cookies survive restarts and are never listed or auto-deleted.

yt-dlp itself is upgraded on every container start, so when YouTube breaks
something (it does, regularly), restarting the container is the fix.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — (required) | BotFather token |
| `ALLOWED_USER_ID` | — (required) | your numeric Telegram id; sole allowed user |
| `DATA_DIR` | `/data` | where audio files are stored |
| `CLEANUP_HOURS` | `24` | auto-delete stored audio older than this; `0` disables |
| `MAX_SEND_MB` | `49` | re-encode/split threshold |
| `FALLBACK_BITRATE_K` | `64` | bitrate for the shrink re-encode |
| `POT_PROVIDER_URL` | — | bgutil provider URL (`http://bgutil-provider:4416` in the stack); empty disables |
| `PLAYER_CLIENTS` | `web,mweb` | yt-dlp player clients to use when the PO provider is on |

## License

MIT — see [LICENSE](LICENSE). Downloading YouTube content may violate YouTube's
Terms of Service; use for personal, non-infringing purposes at your own risk.
