from __future__ import annotations

import asyncio
import logging
import re
from io import BytesIO
from pathlib import Path

from telegram import Bot, InputFile
from telegram.error import NetworkError, RetryAfter, TimedOut

log = logging.getLogger("spotigram.send")

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, fallback: str = "audio.m4a") -> str:
    cleaned = _UNSAFE.sub("_", name).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    if len(cleaned) > 80:
        stem, dot, ext = cleaned.rpartition(".")
        if dot:
            cleaned = stem[:70] + "." + ext[:10]
        else:
            cleaned = cleaned[:80]
    return cleaned


async def _retry(fn, retries: int = 4):
    last = None
    for attempt in range(retries):
        try:
            return await fn()
        except RetryAfter as exc:
            last = exc
            await asyncio.sleep(exc.retry_after + 0.5)
        except TimedOut as exc:
            last = exc
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2)
        except NetworkError as exc:
            last = exc
            msg = str(exc).lower()
            if "too large" in msg or "entity" in msg:
                raise
            if attempt == retries - 1:
                raise
            await asyncio.sleep(1.5)
    if last:
        raise last
    return None


def _thumb_input(thumb: Path | None) -> InputFile | None:
    if not thumb or not thumb.exists() or thumb.stat().st_size < 32:
        return None
    data = thumb.read_bytes()
    name = "cover.jpg" if thumb.suffix.lower() in {".jpg", ".jpeg"} else thumb.name
    return InputFile(BytesIO(data), filename=name)


async def send_audio(
    bot: Bot,
    chat_id: int,
    path: Path,
    *,
    title: str,
    performer: str,
    local_mode: bool,
    thumb: Path | None = None,
) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    log.info("uploading audio %s (%s bytes) thumb=%s", path.name, size, bool(thumb))
    if size < 256:
        raise ValueError(f"audio file too small ({size} bytes)")
    filename = safe_filename(path.name, fallback=f"audio{path.suffix or '.mp3'}")

    async def _send():
        audio = (
            path.resolve().as_posix()
            if local_mode
            else InputFile(BytesIO(path.read_bytes()), filename=filename)
        )
        await bot.send_audio(
            chat_id=chat_id,
            audio=audio,
            title=title[:64] or None,
            performer=performer[:64] or None,
            thumbnail=_thumb_input(thumb),
            filename=filename,
            read_timeout=120,
            write_timeout=120,
        )

    await _retry(_send)


async def send_document(bot: Bot, chat_id: int, path: Path, local_mode: bool, caption: str = "") -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    log.info("uploading %s (%s bytes)", path.name, size)
    if size < 256:
        raise ValueError(f"audio file too small ({size} bytes)")
    if not local_mode and size > 49 * 1024 * 1024:
        raise ValueError(f"file is {size} bytes; public Bot API cap is 50 MB")

    filename = safe_filename(path.name, fallback=f"audio{path.suffix or '.m4a'}")

    async def _send():
        if local_mode:
            # Local Bot API reads the file from disk (up to 2 GB).
            await bot.send_document(
                chat_id=chat_id,
                document=path.resolve().as_posix(),
                filename=filename,
                caption=(caption[:1024] or None),
                read_timeout=120,
                write_timeout=120,
            )
            return
        payload = BytesIO(path.read_bytes())
        payload.name = filename
        await bot.send_document(
            chat_id=chat_id,
            document=InputFile(payload, filename=filename),
            caption=(caption[:1024] or None),
            read_timeout=120,
            write_timeout=120,
        )

    await _retry(_send)
