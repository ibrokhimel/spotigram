from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from telegram.ext import Application

from spotigram.config import Settings
from spotigram.crypto import decrypt_str
from spotigram.db import Database, JobRow
from spotigram.downloader import TrackDownloader
from spotigram.models import TrackMeta
from spotigram.progress import LiveStatus
from spotigram.spotify import SpotifyService
from spotigram.telegram_send import send_audio, send_document
from spotigram.urls import SpotifyRef, parse_spotify
from spotigram.ziputil import make_zip_parts

log = logging.getLogger("spotigram.worker")


class Worker:
    def __init__(
        self,
        app: Application,
        db: Database,
        settings: Settings,
        spotify: SpotifyService,
        downloader: TrackDownloader,
    ):
        self.app = app
        self.db = db
        self.settings = settings
        self.spotify = spotify
        self.downloader = downloader
        self._running_tasks: set[asyncio.Task] = set()

    async def loop(self) -> None:
        await self.db.requeue_running()
        while True:
            self._running_tasks = {t for t in self._running_tasks if not t.done()}
            if len(self._running_tasks) < self.settings.max_concurrent_jobs:
                job = await self.db.claim_next(self.settings.max_concurrent_jobs)
                if job:
                    task = asyncio.create_task(self._safe_run(job))
                    self._running_tasks.add(task)
                    continue
            await asyncio.sleep(0.4)

    async def _safe_run(self, job: JobRow) -> None:
        try:
            await self.run_job(job)
        except Exception:
            log.exception("job %s crashed", job.id)
            await self.db.finish_job(job.id, "failed", "internal error")
            if job.chat_id:
                try:
                    await self.app.bot.send_message(job.chat_id, "Job failed. Try again later.")
                except Exception:
                    pass

    async def run_job(self, job: JobRow) -> None:
        bot = self.app.bot
        dest = self.settings.jobs_dir / job.id
        dest.mkdir(parents=True, exist_ok=True)
        token = None
        cached = self.app.bot_data.get("oauth_plain", {}).get(job.telegram_id)
        if cached:
            token = cached["access_token"]
        else:
            oauth = await self.db.get_oauth(job.telegram_id)
            if oauth and oauth.get("access_token"):
                try:
                    token = decrypt_str(self.app.bot_data["fernet"], oauth["access_token"])
                except Exception:
                    token = None

        tracks = await self._load_tracks(job, token)
        if self.downloader.is_cancelled(job.id):
            await self.db.finish_job(job.id, "cancelled")
            shutil.rmtree(dest, ignore_errors=True)
            return
        if not tracks:
            await self._edit(job, "No tracks found.")
            await self.db.finish_job(job.id, "failed", "no tracks")
            shutil.rmtree(dest, ignore_errors=True)
            return

        await self.db.update_progress(job.id, done=0)
        audio_files: list[Path] = []
        missing: list[TrackMeta] = []
        done = failed = fallback = meta_only = 0
        local = self.settings.uses_local_bot_api

        live = LiveStatus(lambda text: self._edit(job, text), job.title or "Download")
        live.set(total=len(tracks), index=0, step="Downloading…")
        await live.start()
        outcomes: list = [None] * len(tracks)
        try:
            sem = asyncio.Semaphore(max(1, self.settings.max_parallel_tracks))

            async def _one(index: int, track: TrackMeta) -> None:
                async with sem:
                    if self.downloader.is_cancelled(job.id):
                        return
                    live.set(
                        index=index + 1,
                        total=len(tracks),
                        track=f"{track.artists} — {track.name}",
                    )
                    track_dir = dest / f"{index:03d}_{track.id}"
                    outcomes[index] = await self.downloader.download_track(
                        job.id,
                        track,
                        track_dir,
                        job.format or "mp3",
                        job.source or "youtube",
                        on_status=None,
                    )

            await asyncio.gather(
                *[_one(i, t) for i, t in enumerate(tracks)],
                return_exceptions=True,
            )
            if self.downloader.is_cancelled(job.id):
                await self.db.finish_job(job.id, "cancelled")
                shutil.rmtree(dest, ignore_errors=True)
                return

            for index, track in enumerate(tracks):
                outcome = outcomes[index]
                if isinstance(outcome, Exception) or outcome is None:
                    failed += 1
                    continue
                live.set(
                    index=index + 1,
                    total=len(tracks),
                    track=f"{track.artists} — {track.name}",
                )
                if outcome.status == "audio" and outcome.path:
                    if outcome.used_fallback:
                        fallback += 1
                    audio_files.append(outcome.path)
                    if job.delivery in {"each", "single"}:
                        try:
                            await send_audio(
                                bot,
                                job.chat_id,
                                outcome.path,
                                title=track.name,
                                performer=track.artists,
                                local_mode=local,
                                thumb=outcome.thumb,
                            )
                            done += 1
                        except Exception as exc:
                            log.exception("send audio failed")
                            failed += 1
                            try:
                                await bot.send_message(
                                    job.chat_id,
                                    f"Got the audio but Telegram refused the upload:\n{exc}",
                                )
                            except Exception:
                                pass
                    else:
                        done += 1
                elif outcome.status == "metadata_only":
                    meta_only += 1
                    missing.append(track)
                else:
                    failed += 1
                await self.db.update_progress(
                    job.id,
                    done=done,
                    failed=failed,
                    fallback=fallback,
                    metadata_only=meta_only,
                )
        finally:
            await live.stop()

        missing_path = dest / "MISSING.txt"
        if missing and job.delivery == "zip":
            missing_path.write_text(
                "Tracks with no YouTube/SoundCloud match:\n"
                + "\n".join(f"{t.artists} — {t.name} {t.url}" for t in missing),
                encoding="utf-8",
            )

        if job.delivery == "zip":
            pack = list(audio_files)
            if missing_path.exists() and missing_path.stat().st_size:
                pack.append(missing_path)
            if pack:
                parts = make_zip_parts(
                    pack,
                    dest,
                    _safe_stem(job.title or "playlist"),
                    self.settings.zip_max_bytes,
                )
                for i, part in enumerate(parts, start=1):
                    cap = f"{job.title} ({i}/{len(parts)})" if len(parts) > 1 else job.title or ""
                    await send_document(bot, job.chat_id, part, local, caption=cap)
            elif meta_only:
                await self.app.bot.send_message(
                    job.chat_id,
                    "No audio file could be downloaded for this playlist.",
                )

        summary = (
            f"Done: {job.title}\n"
            f"Files sent: {done} · Fallback: {fallback} · Missed: {meta_only + failed}"
        )
        await self._edit(job, summary)
        await self.db.finish_job(job.id, "done")
        shutil.rmtree(dest, ignore_errors=True)

    async def _load_tracks(self, job: JobRow, token: str | None) -> list[TrackMeta]:
        cached: list[TrackMeta] | None = self.app.bot_data.get("job_tracks", {}).get(job.id)
        if cached:
            return cached
        if job.kind == "liked":
            if not token:
                return []
            col = await asyncio.to_thread(
                self.spotify.liked_songs, token, self.settings.max_tracks_per_job
            )
            return col.tracks
        ref = parse_spotify(job.query)
        if not ref:
            ref = SpotifyRef(job.kind, job.query)
        try:
            col = await asyncio.to_thread(
                self.spotify.fetch, ref, token, self.settings.max_tracks_per_job
            )
        except Exception:
            log.exception("spotify fetch failed")
            return []
        return col.tracks

    async def _edit(self, job: JobRow, text: str) -> None:
        if not job.chat_id or not job.status_message_id:
            return
        try:
            await self.app.bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.status_message_id,
                text=text[:4000],
            )
        except Exception:
            pass


def _safe_stem(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return (cleaned or "playlist")[:80]
