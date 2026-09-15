from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

_UNSET = object()
FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")

EditFn = Callable[[str], Awaitable[Any]]


def bar(pct: float | None, width: int = 12) -> str:
    if pct is None:
        return "░" * width
    filled = int(round(max(0.0, min(100.0, pct)) / 100.0 * width))
    filled = min(width, max(0, filled))
    return "█" * filled + "░" * (width - filled)


def parse_percent(line: str) -> float | None:
    match = _PCT.search(line)
    if not match:
        return None
    value = float(match.group(1))
    if 0 <= value <= 100:
        return value
    return None


def classify_line(line: str) -> str | None:
    low = line.lower()
    if "processing query" in low or "searching" in low:
        return "Searching for a match…"
    if "found" in low and "http" in low:
        return "Match found"
    if "download" in low:
        return "Downloading audio…"
    if "convert" in low or "ffmpeg" in low:
        return "Converting with FFmpeg…"
    if "embed" in low or "metadata" in low:
        return "Writing tags…"
    if "error" in low or "failed" in low:
        return "Hit a snag, retrying if we can…"
    return None


class LiveStatus:
    def __init__(self, edit: EditFn, title: str):
        self.edit = edit
        self.title = title
        self.track = ""
        self.step = "Starting…"
        self.detail = ""
        self.pct: float | None = None
        self.index = 0
        self.total = 1
        self._i = 0
        self._t0 = time.monotonic()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def set(
        self,
        *,
        track: str | None = None,
        step: str | None = None,
        detail: str | None = None,
        pct: Any = _UNSET,
        index: int | None = None,
        total: int | None = None,
    ) -> None:
        if track is not None:
            self.track = track
        if step is not None:
            self.step = step
        if detail is not None:
            self.detail = detail
        if pct is not _UNSET:
            self.pct = pct
        if index is not None:
            self.index = index
        if total is not None:
            self.total = total

    def render(self) -> str:
        if self.total:
            line = f"{self.index}/{self.total}"
        else:
            line = self.title
        if self.track:
            line = f"{line}  {self.track}"
        elif self.step:
            line = f"{line}  {self.step}"
        return line[:400]

    async def start(self) -> None:
        self._stop.clear()
        self._t0 = time.monotonic()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:
                pass
            self._task = None

    async def _loop(self) -> None:
        last = ""
        while not self._stop.is_set():
            text = self.render()
            if text != last:
                try:
                    await self.edit(text)
                except Exception:
                    pass
                last = text
            self._i += 1
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass


async def pulse_while(awaitable: Awaitable, edit: EditFn, title: str):
    live = LiveStatus(edit, title)
    live.set(step=title, index=0, total=0)
    await live.start()
    try:
        return await awaitable
    finally:
        await live.stop()
