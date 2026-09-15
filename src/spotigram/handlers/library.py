from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from spotigram.crypto import decrypt_str
from spotigram.db import Database
from spotigram.handlers.download import _begin_wizard
from spotigram.spotify import SpotifyService


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _spotify(context: ContextTypes.DEFAULT_TYPE) -> SpotifyService:
    return context.application.bot_data["spotify"]


async def _token(context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> str | None:
    cached = context.application.bot_data.get("oauth_plain", {}).get(telegram_id)
    if cached:
        return cached["access_token"]
    row = await _db(context).get_oauth(telegram_id)
    if not row or not row.get("access_token"):
        return None
    try:
        return decrypt_str(context.application.bot_data["fernet"], row["access_token"])
    except Exception:
        return None


async def cmd_library(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = _db(context)
    if not await db.is_approved(update.effective_user.id):
        return
    token = await _token(context, update.effective_user.id)
    if not token:
        await update.message.reply_text(
            "Optional: /login to browse your playlists. Or just paste a public Spotify link."
        )
        return
    playlists = await asyncio.to_thread(_spotify(context).user_playlists, token)
    buttons = [[InlineKeyboardButton("Liked Songs", callback_data="lib:liked")]]
    for pid, name, total in playlists[:40]:
        label = f"{name} ({total})"
        buttons.append([InlineKeyboardButton(label[:64], callback_data=f"lib:pl:{pid}")])
    await update.message.reply_text(
        "Your library:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def on_library_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    db = _db(context)
    if not await db.is_approved(query.from_user.id):
        await query.answer("Not approved.")
        return
    token = await _token(context, query.from_user.id)
    if query.data == "lib:liked":
        await _begin_wizard(update, context, "liked", "liked", user_token=token, title_hint="Liked Songs")
        return
    if query.data.startswith("lib:pl:"):
        pid = query.data.split(":", 2)[2]
        url = f"https://open.spotify.com/playlist/{pid}"
        await _begin_wizard(update, context, "playlist", url, user_token=token)
        return
    await query.answer()
