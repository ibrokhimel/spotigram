from __future__ import annotations

import logging
from pathlib import Path

from telegram import Bot, BotCommand, InputProfilePhotoStatic

log = logging.getLogger("spotigram.identity")

PFP = Path(__file__).resolve().parents[2] / "assets" / "bot-pfp.jpg"

COMMANDS = [
    BotCommand("start", "How this bot works"),
    BotCommand("help", "Command list"),
    BotCommand("settings", "MP3, YouTube, playlist delivery"),
    BotCommand("queue", "What's downloading"),
    BotCommand("cancel", "Stop your current download"),
    BotCommand("login", "Optional: connect Spotify"),
    BotCommand("logout", "Disconnect Spotify"),
    BotCommand("library", "Your playlists after /login"),
]

SHORT = "Paste a Spotify link. Get MP3s."
LONG = (
    "Send a Spotify track, album, or playlist link. "
    "Spotigram finds the audio on YouTube and sends it as an MP3. "
    "Defaults: YouTube + MP3, playlists sent song by song. "
    "Change that in /settings. Private bot — ask the owner for access."
)

HELP = (
    "Paste a Spotify link. Default is MP3 from YouTube.\n\n"
    "/start — how it works\n"
    "/help — this list\n"
    "/settings — format, source, ZIP vs one-by-one\n"
    "/queue — your place in line\n"
    "/cancel — stop your download\n"
    "/login — optional Spotify login\n"
    "/logout — disconnect Spotify\n"
    "/library — liked songs and playlists (after login)"
)


async def apply_bot_identity(bot: Bot) -> None:
    try:
        await bot.set_my_commands(COMMANDS)
    except Exception:
        log.exception("set_my_commands failed")
    try:
        await bot.set_my_short_description(SHORT)
    except Exception:
        log.exception("set_my_short_description failed")
    try:
        await bot.set_my_description(LONG)
    except Exception:
        log.exception("set_my_description failed")
    if PFP.exists():
        try:
            await bot.set_my_profile_photo(InputProfilePhotoStatic(photo=PFP))
        except Exception:
            log.exception("set_my_profile_photo failed")
