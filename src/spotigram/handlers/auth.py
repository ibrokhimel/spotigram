from __future__ import annotations

import asyncio
import time

from telegram import Update
from telegram.ext import Application, ContextTypes

from spotigram.config import Settings
from spotigram.crypto import encrypt_str
from spotigram.db import Database
from spotigram.oauth import parse_callback_url
from spotigram.spotify import SpotifyService


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _spotify(context: ContextTypes.DEFAULT_TYPE) -> SpotifyService:
    return context.application.bot_data["spotify"]


def _fernet(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["fernet"]


async def resolve_user_token(context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> str | None:
    cached = context.application.bot_data.get("oauth_plain", {}).get(telegram_id)
    if cached:
        return cached["access_token"]
    row = await _db(context).get_oauth(telegram_id)
    if not row or not row.get("access_token"):
        return None
    try:
        from spotigram.crypto import decrypt_str

        return decrypt_str(_fernet(context), row["access_token"])
    except Exception:
        return None


async def complete_oauth(app: Application, code: str, state: str) -> None:
    db: Database = app.bot_data["db"]
    telegram_id = await db.consume_oauth_state(state)
    if not telegram_id:
        raise RuntimeError("Login expired. Send /login again.")
    spotify: SpotifyService = app.bot_data["spotify"]
    token_info = await asyncio.to_thread(spotify.exchange_code, code)
    if isinstance(token_info, str):
        token_info = {"access_token": token_info, "refresh_token": "", "expires_at": int(time.time()) + 3600}
    access = token_info["access_token"]
    refresh = token_info.get("refresh_token") or ""
    expires_at = int(token_info.get("expires_at") or (time.time() + 3600))
    fernet = app.bot_data["fernet"]
    me = await asyncio.to_thread(spotify.me, access)
    name = me.get("display_name") or me.get("id") or "Spotify user"
    await db.save_oauth(
        telegram_id,
        name,
        encrypt_str(fernet, access),
        encrypt_str(fernet, refresh) if refresh else "",
        expires_at,
    )
    app.bot_data.setdefault("oauth_plain", {})[telegram_id] = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": expires_at,
        "display_name": name,
    }
    await app.bot.send_message(
        telegram_id,
        f"Logged in as {name}. You can use /library, or keep pasting public links.",
    )


async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = _db(context)
    if not await db.is_approved(update.effective_user.id):
        return
    import secrets

    state = secrets.token_urlsafe(16)
    expires = int(time.time()) + 600
    await db.put_oauth_state(state, update.effective_user.id, expires)
    url = _spotify(context).authorize_url(state)
    await update.message.reply_text(
        "Optional Spotify login — only for Liked Songs and private playlists.\n\n"
        f"Open this link:\n{url}\n\n"
        "If the page fails to load on your phone, copy the URL from the address bar "
        "(it contains code=) and paste it here."
    )


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = _db(context)
    if not await db.is_approved(update.effective_user.id):
        return
    await db.delete_oauth(update.effective_user.id)
    context.application.bot_data.get("oauth_plain", {}).pop(update.effective_user.id, None)
    await update.message.reply_text("Logged out of Spotify. Public links still work.")


async def on_oauth_paste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    text = (update.message.text or "") if update.message else ""
    parsed = parse_callback_url(text)
    if not parsed:
        return False
    code, state = parsed
    try:
        await complete_oauth(context.application, code, state)
    except Exception as exc:
        if update.message:
            await update.message.reply_text(f"Login failed: {exc}")
    return True
