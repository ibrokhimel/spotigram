from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from spotigram.access import HARDCODED_ADMIN_ID, mention
from spotigram.db import Database


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = _db(context)
    if not await db.is_admin(update.effective_user.id):
        return
    args = context.args or []
    if len(args) >= 2 and args[0] in {"add", "del"}:
        try:
            uid = int(args[1])
        except ValueError:
            await update.message.reply_text("Need a numeric Telegram id.")
            return
        if args[0] == "add":
            await db.add_user(uid)
            await update.message.reply_text(f"Approved {uid}.")
        else:
            if uid == HARDCODED_ADMIN_ID:
                await update.message.reply_text("Can't demote the owner.")
                return
            await db.remove_user(uid)
            await update.message.reply_text(f"Denied {uid}.")
        return
    users = await db.list_users()
    pending = await db.list_pending_requests()
    lines = ["Users:"]
    for u in users:
        flag = "admin" if u.is_admin else u.status
        lines.append(f"· {mention(u.username, u.first_name, u.telegram_id)} ({u.telegram_id}) {flag}")
    if pending:
        lines.append("\nPending:")
        for r in pending:
            lines.append(f"· {mention(r.username, r.first_name, r.telegram_id)} ({r.telegram_id})")
    await update.message.reply_text("\n".join(lines)[:4000])


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = _db(context)
    if not await db.is_admin(update.effective_user.id):
        return
    running = await db.running_jobs()
    queued = await db.queued_jobs()
    pending = await db.list_pending_requests()
    lines = [
        f"Running: {len(running)}",
        *[f"  · {j.title or j.id} (user {j.telegram_id})" for j in running],
        f"Queued: {len(queued)}",
        *[f"  · {j.title or j.id} (user {j.telegram_id})" for j in queued],
        f"Pending access: {len(pending)}",
    ]
    await update.message.reply_text("\n".join(lines)[:4000])
