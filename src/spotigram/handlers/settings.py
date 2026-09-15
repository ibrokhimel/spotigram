from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from spotigram.db import Database

DEFAULT_FORMAT = "mp3"
DEFAULT_SOURCE = "youtube"
DEFAULT_DELIVERY = "each"


def resolved_prefs(prefs: dict) -> dict[str, str | None]:
    return {
        "format": prefs.get("format") or DEFAULT_FORMAT,
        "source": prefs.get("source") or DEFAULT_SOURCE,
        "delivery": prefs.get("delivery") or DEFAULT_DELIVERY,
    }


def prefs_text(prefs: dict) -> str:
    r = resolved_prefs(prefs)
    return (
        "Defaults — used on every link. Change them here anytime.\n"
        f"Format: {r['format']}\n"
        f"Source: {r['source']}\n"
        f"Playlist: {r['delivery'] or DEFAULT_DELIVERY}"
    )


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = _db(context)
    if not await db.is_approved(update.effective_user.id):
        return
    prefs = await db.get_settings(update.effective_user.id)
    text = prefs_text(prefs)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("MP3", callback_data="st:format:mp3"),
                InlineKeyboardButton("Original", callback_data="st:format:m4a"),
            ],
            [
                InlineKeyboardButton("YouTube", callback_data="st:source:youtube"),
                InlineKeyboardButton("SoundCloud", callback_data="st:source:soundcloud"),
                InlineKeyboardButton("Auto", callback_data="st:source:auto"),
            ],
            [
                InlineKeyboardButton("ZIP", callback_data="st:delivery:zip"),
                InlineKeyboardButton("One by one", callback_data="st:delivery:each"),
            ],
            [InlineKeyboardButton("Reset to MP3 + YouTube", callback_data="st:clear")],
        ]
    )
    await update.message.reply_text(text, reply_markup=kb)


async def on_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    db = _db(context)
    if not await db.is_approved(query.from_user.id):
        await query.answer("Not approved.")
        return
    parts = query.data.split(":")
    uid = query.from_user.id
    if parts[1] == "clear":
        await db.conn.execute("DELETE FROM settings WHERE telegram_id=?", (uid,))
        await db.conn.commit()
        await db.set_settings(uid, format=DEFAULT_FORMAT, source=DEFAULT_SOURCE)
        await query.edit_message_text(prefs_text(await db.get_settings(uid)))
        await query.answer("Reset to MP3 + YouTube")
        return
    field, value = parts[1], parts[2]
    kwargs = {field: value}
    await db.set_settings(uid, **kwargs)
    await query.answer(f"Saved {field}={value}")
    await query.edit_message_text(prefs_text(await db.get_settings(uid)))
