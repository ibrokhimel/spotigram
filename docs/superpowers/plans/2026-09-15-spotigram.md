# Spotigram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a private Telegram bot that turns Spotify links into tagged audio files (YouTube/SoundCloud with fallback), with admin approval, a FIFO queue, optional Spotify login, and 2 GB sends via the local Bot API.

**Architecture:** Python 3.12 app (`python-telegram-bot`) talks to a local Telegram Bot API container. Spotify Web API is metadata-only. Audio comes from spotDL/yt-dlp. SQLite holds users, jobs, and optional OAuth tokens. A worker runs at most two jobs and queues the rest.

**Tech Stack:** Python 3.12, python-telegram-bot 21+, spotDL, spotipy, aiosqlite, pydantic-settings, aiohttp, FFmpeg, Deno, Docker Compose, local telegram-bot-api.

**Spec:** `docs/superpowers/specs/2026-09-15-spotigram-design.md`

## Global Constraints

- Admin Telegram ID is always `1406109190`; user-facing handle `@ibrokhimel`.
- No Spotify audio CDN / unofficial player APIs / librespot / TOTP rippers.
- Audio sources: `youtube` | `soundcloud` | `auto`; chosen source fails → the other; both fail → metadata card.
- Formats: `mp3` (320k) | `m4a` (original). Delivery: `zip` | `each` | `single`.
- File/zip parts ≤ 1900 MB. Tracks per job ≤ 200. Warn if > 40.
- Global running jobs = 2; 1 running per user; 2 extra queued per user.
- `/login` is optional. Public links use client-credentials.
- `callback_data` ≤ 64 bytes.
- Tests never hit live Spotify, YouTube, or Telegram.

## File map

| File | Responsibility |
|---|---|
| `src/spotigram/config.py` | Env settings, admin IDs, paths |
| `src/spotigram/crypto.py` | Fernet load/generate |
| `src/spotigram/urls.py` | Parse Spotify URLs/URIs |
| `src/spotigram/fallback.py` | Provider attempt order |
| `src/spotigram/ziputil.py` | Zip a folder, split by max bytes |
| `src/spotigram/queue.py` | Pure FIFO pick-next + per-user caps |
| `src/spotigram/db.py` | SQLite schema and queries |
| `src/spotigram/access.py` | Display names, approve copy |
| `src/spotigram/spotify.py` | Metadata + optional user library |
| `src/spotigram/oauth.py` | Authorize URL, code exchange, paste-URL parse |
| `src/spotigram/oauth_server.py` | aiohttp `:8888/callback` |
| `src/spotigram/downloader.py` | spotDL subprocess per track + cancel |
| `src/spotigram/telegram_send.py` | send_audio / send_document / metadata card, flood retry |
| `src/spotigram/worker.py` | Claim jobs, download, deliver, cleanup |
| `src/spotigram/bot.py` | Application, local_mode, handler wiring |
| `src/spotigram/handlers/*.py` | start/approve, download wizard, auth, library, settings, admin, queue |
| `src/spotigram/__main__.py` | `python -m spotigram` |
| `tests/test_*.py` | Pure unit tests for the above |

### Task 1: Skeleton + URL parser

Create `pyproject.toml`, package, `urls.py`. Test intl URLs, `?si=`, `spotify:` URIs.

Produces: `parse_spotify(text) -> SpotifyRef | None` with `kind` in `track|album|playlist|artist` and canonical `id`.

### Task 2: Access copy + fallback + zip + queue (pure)

- `access.mention(username, first_name, id)` → `@alice` / `Alice` / `999`
- `access.approved_text(...)` → `approved @alice`
- `fallback.provider_attempts(source)` → `[["youtube-music","youtube"],["soundcloud"]]` or reversed
- `ziputil.make_zip_parts(files, dest_dir, stem, max_bytes)` → list of part paths
- `queue.can_enqueue(jobs, user_id, max_running_per_user=1, max_queued_per_user=2)`
- `queue.pick_next(jobs, max_running=2)` oldest queued whose user is not already running

### Task 3: DB + crypto

aiosqlite schema from spec §13. Seed admin `1406109190`. Approve/deny requests. Job claim under a lock.

### Task 4: Spotify metadata + OAuth parse (no live network in tests)

`parse_callback_url` extracts `code`+`state`. `spotify.py` wraps spotipy; tests mock the client.

### Task 5: Downloader

Per-track subprocess `spotdl download <url> --audio ... --format ... --output ...`. Kill on cancel. After attempt 1 fails, attempt 2. Both fail → `metadata_only`. Never pass a Spotify stream URL to ffmpeg.

### Task 6: Bot handlers + worker + Docker

Access gate, wizard buttons, FIFO worker, local Bot API compose, README.

---

This session executes the plan **inline** (user said go).
