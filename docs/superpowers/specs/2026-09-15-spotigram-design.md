# Spotigram — Telegram Spotify Downloader Bot

Date: 2026-09-15
Status: approved; implementation in progress
Audience: admin `1406109190` (`@ibrokhimel`) + friends they approve
Runtime: macOS (Docker Compose). Developed from this repo on any OS.

## 1. Problem

Friends want a Telegram bot that:

- Accepts Spotify track / album / playlist / artist links **without** logging into Spotify
- Optionally lets someone `/login` to pick Liked Songs and private playlists
- Asks (via inline buttons) for audio format (MP3 or original) **and audio source** (YouTube or SoundCloud)
- If the chosen source fails a track, automatically try the other source
- For albums/playlists: ZIP or send each song as an audio file
- Queues work when several friends hit it at once
- Sends files up to **2 GB** (local Telegram Bot API)

This is **not** a Spotify stream ripper. The bot never talks to Spotify’s audio CDN or unofficial player APIs. See §4.1 for why.

## 2. How downloads actually work

1. Spotify Web API provides **metadata only** (title, artists, album, duration, cover, track list). This always happens. Spotify is never the audio file source.
2. The user picks an **audio source**: YouTube or SoundCloud (or Auto).
3. spotDL/yt-dlp downloads audio from the chosen source and FFmpeg tags it with the Spotify metadata.
4. If that source fails the track, **immediately try the other source** (YouTube ↔ SoundCloud).
5. If both audio sources fail, send a **Spotify metadata card** (cover + title/artists/album/duration/link). No silent drop, and no Spotify stream rip.
6. The bot sends the file(s) back in Telegram via the **local Bot API** (2 GB cap).

Public links work with a Spotify *app* client-id/secret (client-credentials). `/login` is optional and only needed for Liked Songs and private playlists.

Users are responsible for what they download. The bot is for personal/friend use only, not a public service.

## 3. Goals

- Admin `1406109190` is seeded as the only admin. New users request access; admin approves with an inline button.
- Approved users can download tracks, albums, playlists, and artists from **public Spotify links** with no `/login`.
- `/login` is optional: Liked Songs + that user’s private/collaborative playlists.
- Inline buttons choose format, **audio source** (YouTube or SoundCloud), and (for collections) delivery mode. Chosen source fails → the other source is tried automatically.
- FIFO job queue: max 2 downloads running; everyone else waits with a position.
- Files carry title, artist, album, cover art.
- Single files and ZIP parts up to ~1.9 GB.
- Same Docker Compose stack runs on the host Mac (bot + local Telegram Bot API).

## 4. Non-goals (v1)

- Ripping Spotify’s own audio streams (librespot, TOTP web-player APIs, bjn7/spotifydl, Widevine dumps).
- Public unlisted access (anyone who finds the bot). New users must be approved.
- Web UI, Navidrome/Jellyfin library sync, M3U generation.
- YouTube/SoundCloud links as first-class inputs (Spotify-only in v1).
- FLAC/WAV as format buttons (stick to MP3 and m4a).

## 4.1 Why Spotify stream ripping is out

Spotify does not give apps a downloadable MP3. The player streams **DRM-protected** audio. Tools that “download from Spotify itself” (bjn7/spotifydl, some librespot dumps, TOTP web-player APIs) do this by pretending to be the official client, grabbing encrypted stream URLs, and writing them to disk.

That is out because:

1. **It circumvents DRM.** In the US that is a DMCA 1201 issue; similar anti-circumvention rules exist elsewhere. Building that into this bot is not something we will do.
2. **It bans accounts.** Spotify actively kills unofficial clients. Using the admin’s or a friend’s Spotify login to pull streams is a good way to lose the account.
3. **It is brittle.** Spotify rotates TOTP secrets, tokens, and CDN auth constantly. Those CLIs break for weeks at a time. A friends bot that dies every Spotify patch is useless.
4. **The official API is metadata-only.** Spotify’s developer terms allow reading playlists and track info. They do not allow fetching the audio. We stay on the documented API for metadata.
5. **spotDL / soundcli / every maintained tool already chose the other path:** match the track on YouTube (or similar) and tag it with Spotify metadata. That is the whole architecture.

What we *will* do when you want “Spotify or YouTube”: you pick **YouTube** or **SoundCloud** as the audio source; the other is the automatic fallback. Spotify stays the metadata/tag source. There is no third button that pulls Spotify’s own audio.

A button labeled “Spotify” that actually downloaded YouTube would be a lie, so we will not ship that label.

## 5. Stack

| Piece | Choice | Why |
|---|---|---|
| Language | Python 3.12 | spotDL is Python; Telegram bots in Python are mature |
| Telegram | `python-telegram-bot` v21+ (async), `local_mode=True` | Inline keyboards, `send_audio`, `send_document`, 2 GB local uploads |
| Local Bot API | `aiogram/telegram-bot-api` (or equivalent) in Compose | Public Bot API is 50 MB; local mode is 2 GB |
| Downloader | spotDL v4 (library + subprocess fallback) | Best matcher; tags; lyrics off by default |
| Audio convert | FFmpeg (system, in Docker image) | Required by spotDL |
| yt-dlp JS runtime | Deno (in Docker image) | yt-dlp needs a JS runtime for many YouTube players |
| Spotify metadata | spotipy — client credentials for public links | Official API; no user login required |
| Spotify login (optional) | spotipy — Authorization Code + PKCE | Per-Telegram-user tokens |
| Persistence | SQLite via aiosqlite | Zero ops for a friends bot |
| Config | `.env` + pydantic-settings | |
| Packing | Docker Compose | Mac host; bot + local Bot API together |

We take *ideas* from:

- [spotDL](https://github.com/spotDL/spotify-downloader) — engine
- [xgorn/Spotify-Loader](https://github.com/xgorn/Spotify-Loader) — ZIP vs one-by-one
- [gsoosk/TelegramSpotifyDownloader](https://github.com/gsoosk/TelegramSpotifyDownloader) — progress
- [mralexsaavedra/spotdl-bot](https://github.com/mralexsaavedra/spotdl-bot) — OAuth
- [baairon/soundcli](https://github.com/baairon/soundcli) — original-quality yt-dlp, resume-friendly files

We do **not** vendor or fork those repos. We do **not** use [bjn7/spotifydl](https://github.com/bjn7/spotifydl) (unofficial Spotify stream download) or [Aditya-Jyoti/Spotify-Downloader](https://github.com/Aditya-Jyoti/Spotify-Downloader) (dead pytube).

## 6. Architecture

```
Telegram Cloud
        │
        ▼
  local Bot API  (:8081, 2 GB)
        │
        ▼
  bot handlers (access gate → parse → buttons → enqueue)
        │
        ▼
  SQLite  (users, requests, settings, oauth tokens, jobs)
        │
        ▼
  FIFO worker (max 2 running; rest queued with position)
        │
        ├─ spotipy (always: metadata, never audio)
        ├─ chosen audio source (YouTube or SoundCloud)
        ├─ if that fails: the other source
        ├─ if both fail: Spotify metadata card
        └─ zip splitter at ~1.9 GB
        │
        ▼
  send_audio / send_document via local API  +  cleanup
```

OAuth callback (optional `/login`): aiohttp on `127.0.0.1:8888` (published from Docker). See §10.

## 7. Access control

Hard-coded admin Telegram user ID: **`1406109190`**. Display handle in user-facing copy: **`@ibrokhimel`**.

`TELEGRAM_ADMIN_IDS` defaults to `1406109190` if unset. That ID is always admin + approved, even if someone deletes them from `/users`.

### New user `/start` (not approved)

Bot replies:

> This bot is private. Ask @ibrokhimel to approve you, or wait here.

Then it DMs the admin **one** access-request message (no spam if they `/start` again):

```
New request
@alice (id 999)
First name: Alice
```

Inline buttons: `Approve` · `Deny`

- **Approve:** add `999` to `users`, notify Alice (“You’re in. Send a Spotify link.”), **edit the admin message** — strip the keyboard, set text to `approved @alice`. If they have no username, `approved Alice` (first name) or `approved 999`.
- **Deny:** edit admin message to `denied @alice`, notify Alice (“Not approved.”). Further `/start`s from Alice stay denied unless the admin later `/users add`.
- **Pending `/start` again:** Alice gets “Still waiting. Ask @ibrokhimel or wait.” Admin does **not** get a second button message. If the old request message was deleted, send a fresh one.

### Approved `/start`

Welcome + how-to. Mention that `/login` is optional.

### Admin extras

- `/users` — list approved IDs and pending requests; `/users add <id>` / `/users del <id>` still work as a fallback.
- `/status` — queue, disk, last errors, pending request count.

Friends never see `/users` or `/status`.

## 8. Telegram UX

### Commands

| Command | Who | Behavior |
|---|---|---|
| `/start` | pending | Ask @ibrokhimel / wait; ping admin once with Approve |
| `/start` | approved | Welcome + how-to (`/login` optional) |
| `/start` | denied | “Not approved. Ask @ibrokhimel.” |
| `/help` | approved | Formats, source, delivery, optional login, queue, limits |
| `/login` | approved | **Optional.** Spotify OAuth for Liked Songs + private playlists |
| `/logout` | approved | Drop stored Spotify tokens |
| `/library` | approved + logged in | Liked Songs + paginated playlists |
| `/library` | approved, not logged in | “Optional: /login to browse your playlists. Or just paste a public Spotify link.” |
| `/settings` | approved | Default format, audio source, playlist delivery |
| `/cancel` | approved | Cancel *their* active or queued job |
| `/queue` | approved | Their position and what’s running |
| `/users` | admin | List / add / remove / see pending |
| `/status` | admin | Queue length, disk, last errors |

Pasting a Spotify URL (track, album, playlist, artist, including `spotify:` URIs and `open.spotify.com` links) starts a download. **No login required** for public links.

Search-by-name (`/s Blinding Lights`) is **not** v1.

### Button flow

After a valid link (or a `/library` pick):

1. **Format** (if no saved default):
   - `MP3` — 320 kbps, Telegram-friendly
   - `Original` — m4a (AAC)
2. **Audio source** (if no saved default):
   - `YouTube` — YouTube Music, then YouTube. If that track fails → SoundCloud.
   - `SoundCloud` — SoundCloud first. If that track fails → YouTube.
   - `Auto` — YouTube first, then SoundCloud (same as YouTube pick; offered so friends don’t have to think).
3. **Delivery** if collection (album, playlist, artist, liked) and no saved default:
   - `ZIP`
   - `One by one`
4. Confirm: `Download` · `Cancel`. Restate title, track count, format, **source**, delivery.

`/settings` can pin format, source, and delivery so friends skip the prompts.

There is **no “Spotify” audio-source button.** Spotify is the catalog you pasted; it is not where the file comes from. See §4.1.

Saved defaults still get `Download` / `Change options`.

### Progress

Edit the same status message:

```
Liked Songs · 12/47
Now: Artist — Title
Source: YouTube → SoundCloud fallback
Queued behind 1 job
Audio failed (metadata sent): 1
```

Progress line shows when a track **fell back** (`YouTube miss, trying SoundCloud…`). At the end: audio sent, fallback count, metadata-only count, elapsed time.

### Delivery

- **Single track:** `send_audio` with title, performer, thumbnail (cover), duration. If no audio, send the metadata card instead.
- **One by one:** same, playlist order, small delay for flood limits.
- **ZIP:** tagged files → zip. If archive > 1900 MB, split into `Name-part01.zip`, … each ≤ 1900 MB. `send_document` for each part. Tracks with no audio are listed in `MISSING.txt` inside the zip (not fake audio files).
- After a successful send, delete the local files for that job.

### Spotify metadata card (both audio sources miss)

`send_photo` of the album cover, caption:

```
Artist — Title
Album · 3:24
YouTube and SoundCloud both missed
https://open.spotify.com/track/...
```

Used only after **both** audio sources fail. The job continues with the rest of the playlist. This is not a Spotify audio file.

## 9. Job queue

When too many friends download at once, **nobody is dropped**. They wait.

Rules:

| Rule | Value |
|---|---|
| Running jobs globally | 2 |
| Running jobs per user | 1 |
| Queued jobs per user | 2 extra (3 total in-flight+waiting). Further sends: “Finish or /cancel one first.” |
| Order | FIFO by `created_at` |
| Fairness | A user’s second job never jumps ahead of someone else’s first |

Behavior:

1. Job is inserted `queued`. User message: `Queued · you’re #3. 2 downloads running.`
2. Worker picks the oldest `queued` job whose user has no `running` job, if `running < 2`.
3. On start: edit status to `Starting…` then per-track progress.
4. When a running job finishes, the next queued job is promoted immediately. That user gets `Your turn · starting…`
5. Positions of everyone still queued are refreshed (`you’re #2` → `#1`) on each promotion.
6. `/cancel` removes a queued job without waiting. `/queue` shows: running titles, your position.

Caps that are *not* queue:

| Cap | Value | Reason |
|---|---|---|
| Tracks per job | 200 | Time + provider rate limits |
| Warn before start | > 40 tracks | User must confirm |
| Zip / file part size | 1900 MB | Local Bot API is 2 GB; leave headroom |

If a playlist is 201+ tracks, refuse and tell them to split it.

## 10. Spotify login (optional)

**Default path: paste a public link. Do not `/login`.** Client-credentials cover public tracks, albums, playlists, and artists.

`/login` is only for:

- Liked Songs
- Private and collaborative playlists the user owns/follows
- `/library` browsing

Scopes (read-only): `user-library-read`, `playlist-read-private`, `playlist-read-collaborative`, `user-read-private`.

Flow:

1. `/login` sends a unique Spotify authorize URL (`state` tied to `telegram_id`).
2. Callback server exchanges `code`, stores Fernet-encrypted tokens. Key from `SPOTIGRAM_SECRET` or generated `data/secret.key`.
3. Bot: “Logged in as {display_name}. You can use /library, or keep pasting public links.”

Phone fallback: if `http://127.0.0.1:8888/callback` fails on the phone, paste the address-bar URL back to the bot.

Tokens refresh automatically. `/logout` deletes them. Public-link downloads never require a user token.

Private playlist without login: “This playlist is private. Optional: /login, then try again — or paste a public link.”

## 11. Downloader

Wrapper around spotDL:

- Input: Spotify URL or a list of track URIs (from OAuth playlist fetch).
- Output dir: `data/jobs/<job_id>/`
- Format map:
  - `mp3` → `--format mp3 --bitrate 320k`
  - `original` → `--format m4a`
- Lyrics providers: empty.
- Audio source (user pick), per track:
  - `youtube` → YouTube Music, then YouTube. On failure → SoundCloud.
  - `soundcloud` → SoundCloud. On failure → YouTube Music, then YouTube.
  - `auto` → same as `youtube` (YouTube family first, SoundCloud second).
- Never call Spotify’s audio CDN / unofficial player APIs, even as a last fallback.
- After **both** sources fail: Spotify metadata card (and `MISSING.txt` line for ZIP).
- Overwrite: skip if the file already exists in that job dir (resume).
- Cancellation: cooperative between tracks; kill the current subprocess on `/cancel`.

Per-track invocation so progress, fallback, and skips work. Metadata (title, artists, album, track number, cover) is always taken from Spotify and embedded when audio exists.

## 12. Local Telegram Bot API (2 GB)

Public `api.telegram.org` caps uploads at 50 MB. We run Telegram’s **local Bot API** in Docker so uploads can be **2 GB**.

Compose service `telegram-bot-api`:

- Image: `aiogram/telegram-bot-api:latest` (tdlib official-compatible)
- Env: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` from https://my.telegram.org
- `TELEGRAM_LOCAL=1`
- Volume: `./data/bot-api`
- Port: `8081`

The Python app:

```
base_url = http://telegram-bot-api:8081/bot
base_file_url = http://telegram-bot-api:8081/file/bot
local_mode = True
```

`local_mode` sends **file paths** the API server can read. Job output dirs must be on a volume **shared** with the Bot API container (e.g. `./data` mounted in both).

Native (no Docker) run: user can point `TELEGRAM_BOT_API_URL` at a locally installed `telegram-bot-api`, or we document Docker as the Mac happy path.

If the local API is down at startup, refuse to take jobs and DM the admin.

## 13. Data model (SQLite)

`users`

- `telegram_id` INTEGER PRIMARY KEY
- `username` TEXT NULL
- `first_name` TEXT NULL
- `is_admin` INTEGER NOT NULL DEFAULT 0
- `status` TEXT NOT NULL  -- `approved` | `denied`
- `created_at` TEXT

`access_requests`

- `telegram_id` INTEGER PRIMARY KEY
- `username` TEXT NULL
- `first_name` TEXT NULL
- `status` TEXT  -- `pending` | `approved` | `denied`
- `admin_chat_id` INTEGER
- `admin_message_id` INTEGER
- `created_at` TEXT
- `resolved_at` TEXT NULL

`settings`

- `telegram_id` INTEGER PRIMARY KEY
- `format` TEXT NULL  -- `mp3` | `m4a`
- `source` TEXT NULL  -- `youtube` | `soundcloud` | `auto`
- `delivery` TEXT NULL  -- `zip` | `each`

`oauth`  -- only if they used optional /login

- `telegram_id` INTEGER PRIMARY KEY
- `display_name` TEXT
- `access_token` TEXT  -- Fernet
- `refresh_token` TEXT -- Fernet
- `expires_at` INTEGER

`jobs`

- `id` TEXT PRIMARY KEY  -- uuid
- `telegram_id` INTEGER
- `kind` TEXT  -- track|album|playlist|artist|liked
- `query` TEXT
- `format` TEXT
- `source` TEXT  -- youtube|soundcloud|auto
- `delivery` TEXT  -- zip|each|single
- `status` TEXT  -- queued|running|done|failed|cancelled
- `queue_position` INTEGER NULL
- `total` INTEGER
- `done_count` INTEGER
- `failed_count` INTEGER
- `fallback_count` INTEGER
- `metadata_only_count` INTEGER
- `chat_id` INTEGER
- `status_message_id` INTEGER
- `error` TEXT NULL
- `created_at` TEXT
- `finished_at` TEXT NULL

`oauth_states`

- `state` TEXT PRIMARY KEY
- `telegram_id` INTEGER
- `expires_at` INTEGER  -- 10 minutes

## 14. Config

`.env` (never committed):

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_IDS=1406109190
TELEGRAM_API_ID=                 # my.telegram.org, for local Bot API
TELEGRAM_API_HASH=
TELEGRAM_BOT_API_URL=http://telegram-bot-api:8081
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
SPOTIGRAM_SECRET=                # optional; else data/secret.key
MAX_CONCURRENT_JOBS=2
MAX_TRACKS_PER_JOB=200
WARN_TRACKS=40
ZIP_MAX_MB=1900
ADMIN_HANDLE=@ibrokhimel
```

`.env.example` documents BotFather, my.telegram.org (API ID/hash), Spotify dashboard, FFmpeg.

Admin ID `1406109190` is also a code default so a missing env still seeds the right admin.

## 15. Project layout

```
spotigram/
  README.md
  LICENSE
  .env.example
  .gitignore
  Dockerfile
  docker-compose.yml
  pyproject.toml
  src/spotigram/
    __init__.py
    __main__.py
    config.py
    db.py
    bot.py
    handlers/
      start.py           # access request + approve/deny callbacks
      download.py
      library.py
      auth.py            # optional /login
      admin.py
      settings.py
      queue.py           # /queue
    worker.py            # FIFO, 2 slots, position updates
    downloader.py
    spotify.py
    oauth_server.py
    ziputil.py
    telegram_send.py     # local_mode paths, metadata cards
  tests/
    test_urls.py
    test_ziputil.py
    test_allowlist.py
    test_access_request.py
    test_queue.py
    test_oauth_parse.py
    test_source_fallback.py
    test_metadata_card.py
```

## 16. Docker / Mac run

Two services:

1. `telegram-bot-api` — local Bot API, 2 GB
2. `bot` — Python app, FFmpeg, Deno, spotDL

Shared volume `./data` so the API can read job files. Ports: `8081` (API, internal is enough), `8888` (OAuth). Restart unless-stopped. Init: create DB, seed admin `1406109190`.

Host Mac needs: Docker Desktop, BotFather token, **my.telegram.org API ID + hash**, Spotify developer app with `http://127.0.0.1:8888/callback`.

Native (no Docker) is documented but Docker is the happy path because of the local Bot API binary.

## 17. Error handling

| Case | Behavior |
|---|---|
| First `/start`, not approved | Ask @ibrokhimel / wait; one Approve message to admin |
| Pending `/start` again | “Still waiting…” — no second admin ping |
| Denied | “Not approved. Ask @ibrokhimel.” |
| Bad URL | “Send an open.spotify.com track/album/playlist/artist link.” |
| Private playlist, no login | Offer optional `/login`; do not block public links |
| Chosen source misses a track | Try the other source; note fallback in progress |
| YouTube and SoundCloud both miss | Spotify metadata card; ZIP gets a `MISSING.txt` line |
| All tracks metadata-only | Still finish the job; say no audio matched |
| `/cancel` | Kill subprocess or drop from queue; delete temp files |
| Telegram 429 | Retry with Retry-After |
| Single file > 1900 MB | Skip that file, report it (should be rare at m4a/mp3) |
| Local Bot API down | No new jobs; DM admin |
| FFmpeg/Deno missing | Refuse jobs at startup; DM admin |
| Spotify 429 | Backoff, then fail the job if still blocked |
| Worker crash mid-job | `running` → `queued` on restart; existing files skipped |

Never log access tokens, bot token, or API hash.

## 18. Testing

No live Spotify/YouTube/Telegram in CI.

- URL parser: track/album/playlist/artist, `?si=`, `spotify:` URIs, `open.spotify.com/intl-xx/`.
- Zip splitter: tiny max size → 1 part vs 2 parts.
- Access: seed admin 1406109190; pending → approve edits to `approved @user`; deny; no duplicate admin pings.
- Queue: 3 jobs, concurrency 2 → third stays queued; per-user cap; FIFO; cancel queued.
- OAuth paste parser.
- Provider order: youtube pick falls back to soundcloud; soundcloud pick falls back to youtube; both miss → metadata card.
- Metadata-card caption contents when audio is None.
- `callback_data` ≤ 64 bytes (`d:<token>:<action>`, `a:<id>:ok` / `a:<id>:no` for approve).

## 19. Security

- Access is approve-gated. Admin ID 1406109190 cannot be demoted by `/users del`.
- Approve/deny callbacks only succeed if the clicker is admin.
- OAuth tokens Fernet-encrypted. CSRF `state`, 10-minute TTL, single use.
- Temp dirs per-job, deleted after send.
- Admin commands check `is_admin`.

## 20. Implementation order

1. Skeleton, config, DB, Docker (bot + local Bot API)
2. Access gate: `/start` request, admin Approve → `approved @user`
3. Public-link parse → format + **source** buttons → spotDL one track → `send_audio` via local API
4. Chosen source miss → other source; both miss → Spotify metadata card
5. Playlists/albums: one-by-one + ZIP + 1900 MB split
6. FIFO queue (2 slots, positions, `/queue`, `/cancel`)
7. Optional Spotify `/login` + `/library`
8. Settings defaults
9. Tests + README (BotFather, my.telegram.org, Spotify app, Mac Docker)

## 21. Success criteria

- A stranger `/start`s: they are told to ask `@ibrokhimel` or wait; admin `1406109190` gets an Approve button; pressing it turns the message into `approved @username` and unlocks the user.
- Approved user pastes a **public** track link with **no** `/login`, picks MP3 + YouTube, receives tagged audio.
- User picks SoundCloud: audio comes from SoundCloud; if that track misses, YouTube is tried automatically (and the reverse).
- Both audio sources miss: cover + Spotify metadata card, not a silent skip, and not a Spotify stream file.
- Playlist + Original + ZIP: one or more zip parts, each ≤ 1900 MB, sendable through the local Bot API.
- Three friends download at once: two run, the third sees `you’re #1` then starts when a slot frees.
- `/login` is unused for the public-link path; it only unlocks `/library` and private playlists.
- Docker Compose on Mac is the documented happy path.
