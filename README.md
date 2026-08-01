# yt-audio-bot

A tiny self-hosted Telegram bot: send it a YouTube link, it replies with the
audio track as a playable file. Built for one thing — listening to talks and
podcasts from YouTube while falling asleep, without keeping a video app open.

Invite-only and multi-user: you (the owner) hand out one-time invite links, and
each invited person only ever sees **their own** downloads — nobody can see
anyone else's files. Runs as two small Docker containers and opens no ports.

## How it works

| You send | Bot does |
|---|---|
| a YouTube link | downloads the audio with yt-dlp, sends it back as a playable track |
| `/list` | numbered list of **your** stored files, with sizes |
| `/delete 3` (or just `3` after a `/list`) | deletes your file 3, shows the updated list |
| `/delete all` | deletes everything **you** have stored |
| a `cookies.txt` file | installs YouTube cookies for you (see below) |
| `/help` | usage note + whether cookies are installed |

Owner-only (the account in `OWNER_ID` / `ALLOWED_USER_ID`):

| You send | Bot does |
|---|---|
| `/invite` | creates a one-time `t.me/<bot>?start=…` link to hand to someone |
| `/users` | lists invited users and how many invite links are still unused |
| `/kick 12345` | removes that user and deletes their stored files |

Each user's files live in a per-user folder (`DATA_DIR/<user_id>/`), so `/list`,
`/delete` and the auto-cleanup only ever touch the caller's own files.

Stored files are **auto-deleted after 24 h** (`CLEANUP_HOURS`), so you never
have to clean up — `/delete` exists for when you want something gone sooner.
Each user also has a **storage cap** (`USER_QUOTA_MB`, default 500 MB): when a
new download would push them over it, their **oldest** files are erased first to
make room — so no single user can fill the server's disk. The file just
requested is always kept, even if it alone is larger than the cap.

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
That's your `ALLOWED_USER_ID` (a.k.a. `OWNER_ID`): the **owner** account. The
owner is the only one who can `/invite` and `/kick`; everyone else is turned
away until they join through an invite link.

### 3. Configure and run

```bash
cp .env.example .env    # fill in BOT_TOKEN and ALLOWED_USER_ID
docker compose up -d --build
```

### 4. Start the chat

Bots can't message you first: open `t.me/<your_bot_username>` (or find the bot
by its username in search), press **Start**, and send it a YouTube link. The
first reply can take a minute while the containers finish starting.

### 5. Invite other people (optional)

Send the bot `/invite`. It replies with a one-time link like
`https://t.me/<your_bot>?start=Kd9fA2`. Forward that link to whoever you want to
add — the **first** person to tap it presses Start, is granted access, and can
immediately send their own YouTube links. The link is burned on first use, so
generate a fresh `/invite` per person.

Invited users only see their own downloads; they can't `/invite`, `/kick`, or
list anyone else's files. Use `/users` to see who's in and `/kick <id>` to
remove someone (which also deletes their stored files). The allow-list is saved
to `DATA_DIR/users.json`, so invites and members survive restarts.

Downloads run concurrently, so one person's long download doesn't hold up
anyone else.

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
| `ALLOWED_USER_ID` | — (required) | owner's numeric Telegram id (legacy name; `OWNER_ID` is the alias) |
| `OWNER_ID` | falls back to `ALLOWED_USER_ID` | owner who can `/invite` and `/kick`; others join by invite link |
| `DATA_DIR` | `/data` | per-user audio folders + `users.json` allow-list live here |
| `CLEANUP_HOURS` | `24` | auto-delete stored audio older than this; `0` disables |
| `USER_QUOTA_MB` | `500` | per-user storage cap; oldest files are erased when a user exceeds it; `0` = unlimited |
| `MAX_SEND_MB` | `49` | re-encode/split threshold |
| `FALLBACK_BITRATE_K` | `64` | bitrate for the shrink re-encode |
| `POT_PROVIDER_URL` | — | bgutil provider URL (`http://bgutil-provider:4416` in the stack); empty disables |
| `PLAYER_CLIENTS` | `web,mweb` | yt-dlp player clients to use when the PO provider is on |

## License

MIT — see [LICENSE](LICENSE). Downloading YouTube content may violate YouTube's
Terms of Service; use for personal, non-infringing purposes at your own risk.
