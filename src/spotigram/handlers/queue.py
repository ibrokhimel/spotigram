from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from spotigram.db import Database
from spotigram.downloader import TrackDownloader


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _downloader(context: ContextTypes.DEFAULT_TYPE) -> TrackDownloader:
    return context.application.bot_data["downloader"]


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = _db(context)
    if not await db.is_approved(update.effective_user.id):
        return
    running = await db.running_jobs()
    queued = await db.queued_jobs()
    lines = [f"{len(running)} running, {len(queued)} queued."]
    for j in running:
        lines.append(f"▶ {j.title or j.id}")
    mine = [j for j in queued if j.telegram_id == update.effective_user.id]
    for j in mine:
        pos = await db.position_for(j.id)
        lines.append(f"you’re #{pos}: {j.title or j.id}")
    if not mine and not any(j.telegram_id == update.effective_user.id for j in running):
        lines.append("You have no jobs.")
    await update.message.reply_text("\n".join(lines))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = _db(context)
    if not await db.is_approved(update.effective_user.id):
        return
    ids = await db.cancel_user_jobs(update.effective_user.id)
    dl = _downloader(context)
    for job_id in ids:
        dl.cancel(job_id)
    if not ids:
        await update.message.reply_text("Nothing to cancel.")
        return
    await update.message.reply_text(f"Cancelled {len(ids)} job(s).")
