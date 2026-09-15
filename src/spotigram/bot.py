from __future__ import annotations

import asyncio
import logging

import pytz
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    JobQueue,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

_orig_scheduler_configuration = JobQueue.scheduler_configuration.fget


def _scheduler_configuration(self):  # type: ignore[no-untyped-def]
    cfg = _orig_scheduler_configuration(self)
    cfg["timezone"] = pytz.UTC
    return cfg


JobQueue.scheduler_configuration = property(_scheduler_configuration)

from spotigram.config import Settings, load_settings
from spotigram.crypto import load_fernet
from spotigram.db import Database
from spotigram.downloader import TrackDownloader
from spotigram.handlers.admin import cmd_status, cmd_users
from spotigram.handlers.auth import cmd_login, cmd_logout, complete_oauth, on_oauth_paste
from spotigram.handlers.download import on_text, on_wizard_callback
from spotigram.handlers.library import cmd_library, on_library_callback
from spotigram.handlers.queue import cmd_cancel, cmd_queue
from spotigram.handlers.settings import cmd_settings, on_settings_callback
from spotigram.handlers.start import cmd_help, cmd_start, on_access_callback
from spotigram.oauth_server import start_oauth_server
from spotigram.spotify import SpotifyService
from spotigram.worker import Worker

log = logging.getLogger("spotigram")


async def _post_init(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    db: Database = application.bot_data["db"]
    await db.connect()
    await db.seed_admins(settings.admin_ids)

    async def oauth_complete(code: str, state: str) -> None:
        await complete_oauth(application, code, state)

    application.bot_data["oauth_complete"] = oauth_complete
    runner = await start_oauth_server(application, settings.oauth_host, settings.oauth_port)
    application.bot_data["oauth_runner"] = runner

    worker = Worker(
        application,
        db,
        settings,
        application.bot_data["spotify"],
        application.bot_data["downloader"],
    )
    application.bot_data["worker"] = worker
    asyncio.create_task(worker.loop())
    from spotigram.spotify import _ensure_spotdl_client

    asyncio.create_task(asyncio.to_thread(_ensure_spotdl_client))
    from spotigram.identity import apply_bot_identity

    await apply_bot_identity(application.bot)
    log.info("Spotigram ready. Admin ids=%s", settings.admin_ids)


async def _post_shutdown(application: Application) -> None:
    runner = application.bot_data.get("oauth_runner")
    if runner:
        await runner.cleanup()
    db: Database | None = application.bot_data.get("db")
    if db:
        await db.close()


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or load_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    log.info("Public Spotify lookups use spotDL (official API requires Premium)")

    file_request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=120.0,
        media_write_timeout=120.0,
    )
    updates_request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=30.0,
    )
    builder = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .request(file_request)
        .get_updates_request(updates_request)
        .job_queue(None)
    )
    if settings.uses_local_bot_api:
        builder = (
            builder.base_url(settings.bot_api_base)
            .base_file_url(settings.bot_api_file_base)
            .local_mode(True)
        )
        log.info("Using local Bot API at %s (2 GB uploads)", settings.telegram_bot_api_url)
    else:
        log.warning("TELEGRAM_BOT_API_URL unset — public API 50 MB cap applies")

    app = builder.post_init(_post_init).post_shutdown(_post_shutdown).build()
    db = Database(settings.db_path)
    fernet = load_fernet(settings.spotigram_secret or None, settings.data_dir)
    spotify = SpotifyService(
        settings.spotify_client_id,
        settings.spotify_client_secret,
        settings.spotify_redirect_uri,
    )
    downloader = TrackDownloader(settings.jobs_dir)

    app.bot_data["settings"] = settings
    app.bot_data["db"] = db
    app.bot_data["fernet"] = fernet
    app.bot_data["spotify"] = spotify
    app.bot_data["downloader"] = downloader
    app.bot_data["wizards"] = {}
    app.bot_data["job_tracks"] = {}
    app.bot_data["oauth_plain"] = {}

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CommandHandler("library", cmd_library))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(on_access_callback, pattern=r"^a:"))
    app.add_handler(CallbackQueryHandler(on_settings_callback, pattern=r"^st:"))
    app.add_handler(CallbackQueryHandler(on_library_callback, pattern=r"^lib:"))
    app.add_handler(CallbackQueryHandler(on_wizard_callback, pattern=r"^[fsvgx]:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    async def _on_error(update: object, context) -> None:
        err = context.error
        log.warning("update failed: %s", err)

    app.add_error_handler(_on_error)
    return app


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = load_settings()
    app = build_application(settings)
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=-1,
        drop_pending_updates=True,
        timeout=20,
        poll_interval=1.0,
    )
