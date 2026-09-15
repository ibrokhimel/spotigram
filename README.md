# Spotigram

A private Telegram bot that turns **Spotify links** into tagged audio files.

Spotify is used for **metadata only** (title, artists, album, cover, track list). Audio is downloaded from **YouTube** or **SoundCloud** via [spotDL](https://github.com/spotDL/spotify-downloader). If the source you pick misses a track, the other is tried automatically. Spotify’s own audio streams are never ripped.

Built for one admin and a few friends. Not a public service.

## What it does

- Paste a Spotify track / album / playlist / artist link
- Inline buttons: **MP3** or **Original (m4a)**, **YouTube** / **SoundCloud** / **Auto**, and for playlists **ZIP** or **one by one**
- Chosen source fails → the other source is tried
- Both miss → a Spotify cover + info card (not a Spotify audio file)
- FIFO queue (2 downloads at a time)
- New users `/start` → they are told to ask **@ibrokhimel** or wait; you get **Approve / Deny**. Approve edits that message to `approved @username`
- `/login` is **optional** (Liked Songs and private playlists only)
- Files up to **2 GB** via Telegram’s local Bot API

Admin Telegram ID is always `1406109190`.

## Mac setup (Docker)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Create a bot with [@BotFather](https://t.me/BotFather). Copy the token.
3. Get **API ID** and **API hash** from [my.telegram.org](https://my.telegram.org) (needed for 2 GB uploads).
4. Create a Spotify app at the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). Add redirect URI exactly:
   `http://127.0.0.1:8888/callback`
5. Copy env and fill it in:

   ```bash
   cp .env.example .env
   ```

6. Start:

   ```bash
   docker compose up --build
   ```

7. Open Telegram, `/start` the bot (you’re already admin), paste a Spotify link.

Friends: they `/start`, you tap **Approve**. The button message becomes `approved @theirname`.

### Optional Spotify login (friends on phones)

`/login` opens Spotify. If the redirect to `127.0.0.1` fails on the phone, copy the URL from the address bar (`...callback?code=...`) and paste it into the bot.

## Native run (no Docker)

Needs Python 3.12+, [FFmpeg](https://ffmpeg.org/), and [Deno](https://deno.com) (for yt-dlp):

```bash
brew install ffmpeg
brew install deno
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# fill .env — leave TELEGRAM_BOT_API_URL empty to use the public 50 MB API
python -m spotigram
```

Without the local Bot API, Telegram rejects files over 50 MB.

## Commands

| Command | Who | What |
|---|---|---|
| `/start` | anyone | Welcome, or request access |
| `/help` | approved | How to use |
| `/login` `/logout` | approved | Optional Spotify account |
| `/library` | logged in | Liked Songs + your playlists |
| `/settings` | approved | Default format / source / delivery |
| `/queue` `/cancel` | approved | Job queue |
| `/users` `/status` | admin | Allowlist and queue |

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

No live Spotify, YouTube, or Telegram calls.

## Legal

You are responsible for what you download. This bot matches public YouTube/SoundCloud audio to Spotify metadata. It does not download Spotify’s DRM-protected streams.
