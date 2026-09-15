from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from spotigram.access import (
    approved_text,
    denied_start_text,
    denied_text,
    pending_start_text,
    private_start_text,
)
from spotigram.config import Settings
from spotigram.db import Database
from spotigram.identity import HELP

WELCOME = (
    "Spotigram is ready.\n\n"
    "Paste a Spotify track, album, playlist, or artist link.\n"
    "Default: MP3 from YouTube. Change that in /settings.\n\n"
    "/login is optional — only for Liked Songs and private playlists.\n"
    "/settings · /queue · /cancel · /help"
)


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user = update.effective_user
    db = _db(context)
    settings = _settings(context)
    handle = settings.admin_handle

    if await db.is_approved(user.id):
        await update.message.reply_text(WELCOME)
        return

    existing = await db.get_user(user.id)
    if existing and existing.status == "denied":
        await update.message.reply_text(denied_start_text(handle))
        return

    req = await db.get_request(user.id)
    if req and req.status == "pending":
        await update.message.reply_text(pending_start_text(handle))
        return

    await update.message.reply_text(private_start_text(handle))
    admin_id = settings.admin_ids[0]
    uname = user.username or ""
    body = f"New request\n@{uname} (id {user.id})\nFirst name: {user.first_name or ''}".strip()
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"a:{user.id}:ok"),
                InlineKeyboardButton("Deny", callback_data=f"a:{user.id}:no"),
            ]
        ]
    )
    msg = await context.bot.send_message(admin_id, body, reply_markup=keyboard)
    await db.upsert_pending_request(
        user.id, user.username, user.first_name, admin_id, msg.message_id
    )


async def on_access_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    db = _db(context)
    if not await db.is_admin(query.from_user.id):
        await query.answer("Nope.")
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, uid_s, action = parts
    uid = int(uid_s)
    req = await db.get_request(uid)
    username = req.username if req else None
    first_name = req.first_name if req else None
    if action == "ok":
        await db.approve_user(uid, username, first_name)
        await query.edit_message_text(approved_text(username, first_name, uid))
        try:
            await context.bot.send_message(uid, "You're in. Send a Spotify link.")
        except Exception:
            pass
    else:
        await db.deny_user(uid)
        await query.edit_message_text(denied_text(username, first_name, uid))
        try:
            await context.bot.send_message(uid, "Not approved.")
        except Exception:
            pass
    await query.answer()


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _db(context).is_approved(update.effective_user.id):
        return
    await update.message.reply_text(HELP)
