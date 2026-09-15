from __future__ import annotations

import asyncio
import secrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from spotigram.config import Settings
from spotigram.db import Database
from spotigram.handlers.auth import on_oauth_paste, resolve_user_token
from spotigram.models import Wizard
from spotigram.handlers.settings import resolved_prefs
from spotigram.progress import pulse_while
from spotigram.spotify import SpotifyService
from spotigram.urls import parse_spotify

FORMAT_LABELS = {"mp3": "MP3", "m4a": "Original"}
SOURCE_LABELS = {"youtube": "YouTube", "soundcloud": "SoundCloud", "auto": "Auto"}
DELIVERY_LABELS = {"zip": "ZIP", "each": "One by one", "single": "Single"}


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _spotify(context: ContextTypes.DEFAULT_TYPE) -> SpotifyService:
    return context.application.bot_data["spotify"]


def _wizards(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Wizard]:
    return context.application.bot_data.setdefault("wizards", {})


async def require_approved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if await _db(context).is_approved(user.id):
        return True
    if update.message:
        await update.message.reply_text("This bot is private. Use /start to request access.")
    elif update.callback_query:
        await update.callback_query.answer("Not approved.")
    return False


def _format_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("MP3", callback_data=f"f:{token}:mp3"),
                InlineKeyboardButton("Original", callback_data=f"f:{token}:m4a"),
            ],
            [InlineKeyboardButton("Cancel", callback_data=f"x:{token}")],
        ]
    )


def _source_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("YouTube", callback_data=f"s:{token}:youtube"),
                InlineKeyboardButton("SoundCloud", callback_data=f"s:{token}:soundcloud"),
            ],
            [InlineKeyboardButton("Auto", callback_data=f"s:{token}:auto")],
            [InlineKeyboardButton("Cancel", callback_data=f"x:{token}")],
        ]
    )


def _delivery_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("ZIP", callback_data=f"v:{token}:zip"),
                InlineKeyboardButton("One by one", callback_data=f"v:{token}:each"),
            ],
            [InlineKeyboardButton("Cancel", callback_data=f"x:{token}")],
        ]
    )


def _confirm_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Download", callback_data=f"g:{token}"),
                InlineKeyboardButton("Cancel", callback_data=f"x:{token}"),
            ]
        ]
    )


def _summary(wiz: Wizard) -> str:
    n = len(wiz.tracks)
    bits = [
        f"{wiz.title}",
        f"{n} track" + ("s" if n != 1 else ""),
        FORMAT_LABELS.get(wiz.format or "", wiz.format or "?"),
        SOURCE_LABELS.get(wiz.source or "", wiz.source or "?"),
    ]
    if wiz.kind != "track":
        bits.append(DELIVERY_LABELS.get(wiz.delivery or "", wiz.delivery or "?"))
    return " · ".join(bits)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not await require_approved(update, context):
        return
    text = update.message.text or ""
    if "code=" in text and "state=" in text:
        if await on_oauth_paste(update, context):
            return
    ref = parse_spotify(text)
    if not ref:
        await update.message.reply_text(
            "Send an open.spotify.com track/album/playlist/artist link."
        )
        return
    await _begin_wizard(update, context, ref.kind, ref.url, user_token=None)


async def _begin_wizard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    kind: str,
    query: str,
    user_token: str | None,
    title_hint: str | None = None,
) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    settings = _settings(context)
    db = _db(context)
    ok, reason = await db.enqueue_allowed(user.id)
    if not ok:
        target = update.message or (update.callback_query and update.callback_query.message)
        if target:
            await target.reply_text(reason)
        return
    token = user_token or await resolve_user_token(context, user.id)
    status_msg = None
    if update.message:
        status_msg = await update.message.reply_text("Looking up Spotify metadata…")
    elif update.callback_query:
        await update.callback_query.answer()
        status_msg = await context.bot.send_message(chat.id, "Looking up Spotify metadata…")
    async def _edit(text: str) -> None:
        try:
            await status_msg.edit_text(text)
        except Exception:
            pass

    try:
        if kind == "liked":
            if not token:
                await status_msg.edit_text("Optional: /login first to fetch Liked Songs.")
                return
            col = await pulse_while(
                asyncio.to_thread(
                    _spotify(context).liked_songs, token, settings.max_tracks_per_job
                ),
                _edit,
                "Loading Liked Songs…",
            )
        else:
            ref = parse_spotify(query)
            if not ref:
                await status_msg.edit_text("Could not parse that Spotify link.")
                return
            col = await pulse_while(
                asyncio.to_thread(
                    _spotify(context).fetch,
                    ref,
                    token if kind in {"playlist", "liked"} else None,
                    settings.max_tracks_per_job,
                ),
                _edit,
                "Looking up that Spotify link…",
            )
    except Exception as exc:
        msg = str(exc)
        if "404" in msg or "Not Found" in msg:
            await status_msg.edit_text(
                "This playlist is private. Optional: /login, then try again — or paste a public link."
            )
            return
        await status_msg.edit_text(f"Spotify lookup failed: {exc}")
        return

    if not col.tracks:
        await status_msg.edit_text("No tracks found.")
        return
    if len(col.tracks) > settings.max_tracks_per_job:
        await status_msg.edit_text(
            f"Too many tracks ({len(col.tracks)}). Cap is {settings.max_tracks_per_job}. Split it."
        )
        return

    prefs = resolved_prefs(await db.get_settings(user.id))
    token_s = secrets.token_hex(4)
    wiz = Wizard(
        token=token_s,
        telegram_id=user.id,
        chat_id=chat.id,
        kind=kind,
        query=query,
        title=title_hint or col.title,
        tracks=col.tracks,
        format=prefs["format"],
        source=prefs["source"],
        delivery="single" if kind == "track" else prefs.get("delivery"),
    )
    _wizards(context)[token_s] = wiz
    if wiz.kind == "track" or wiz.delivery:
        await _enqueue_job(context, wiz, status_msg)
        return
    await _advance(context, status_msg, wiz, settings)


async def _advance(context, message, wiz: Wizard, settings: Settings) -> None:
    if wiz.kind != "track" and not wiz.delivery:
        await message.edit_text("How should I send the playlist?", reply_markup=_delivery_kb(wiz.token))
        return
    if wiz.kind != "track" and len(wiz.tracks) > settings.warn_tracks and not wiz.warned:
        wiz.warned = True
        await message.edit_text(
            f"{_summary(wiz)}\n\nThat's {len(wiz.tracks)} tracks. Download anyway?",
            reply_markup=_confirm_kb(wiz.token),
        )
        return
    await message.edit_text(_summary(wiz), reply_markup=_confirm_kb(wiz.token))


async def on_wizard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    if not await require_approved(update, context):
        return
    data = query.data
    action, _, rest = data.partition(":")
    token = rest.split(":")[0] if ":" in rest else rest
    value = rest.split(":")[1] if ":" in rest else ""
    wizards = _wizards(context)
    wiz = wizards.get(token)
    if not wiz or wiz.telegram_id != query.from_user.id:
        await query.answer("Expired. Send the link again.")
        return
    settings = _settings(context)
    if action == "x":
        wizards.pop(token, None)
        await query.edit_message_text("Cancelled.")
        await query.answer()
        return
    if action == "f":
        wiz.format = value
    elif action == "s":
        wiz.source = value
    elif action == "v":
        wiz.delivery = value
    elif action == "g":
        await _enqueue_job(context, wiz, query.message)
        await query.answer()
        return
    await query.answer()
    await _advance(context, query.message, wiz, settings)


async def _enqueue_job(context, wiz: Wizard, status_message) -> None:
    db = _db(context)
    ok, reason = await db.enqueue_allowed(wiz.telegram_id)
    if not ok:
        await status_message.edit_text(reason)
        return
    delivery = wiz.delivery or "single"
    if wiz.kind == "track":
        delivery = "single"
    job = await db.create_job(
        wiz.telegram_id,
        wiz.kind,
        wiz.query,
        wiz.format or "mp3",
        wiz.source or "youtube",
        delivery,
        wiz.chat_id,
        status_message.message_id,
        wiz.title,
        len(wiz.tracks),
    )
    context.application.bot_data.setdefault("job_tracks", {})[job.id] = wiz.tracks
    _wizards(context).pop(wiz.token, None)
    pos = await db.position_for(job.id)
    running = await db.running_count()
    if pos and pos > 0 and running >= _settings(context).max_concurrent_jobs:
        await status_message.edit_text(
            f"Queued · you're #{pos}. {running} downloads running."
        )
    else:
        fmt = FORMAT_LABELS.get(wiz.format or "", wiz.format or "MP3")
        src = SOURCE_LABELS.get(wiz.source or "", wiz.source or "YouTube")
        await status_message.edit_text(f"Queued: {wiz.title} · {fmt} · {src}")
