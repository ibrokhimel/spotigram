from __future__ import annotations

import asyncio
import os
import shutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from spotigram.fallback import other_source_label, provider_attempts
from spotigram.match import pick_best_entry, search_queries, search_query as build_search_query
from spotigram.models import TrackMeta
from spotigram.progress import classify_line, parse_percent

AUDIO_EXTS = {".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".webm"}
THUMB_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
ATTEMPT_TIMEOUT_S = 90

StatusCb = Callable[[str, str, float | None], None]


@dataclass
class DownloadOutcome:
    status: str  # audio | metadata_only | failed
    path: Path | None
    used_fallback: bool
    source_label: str
    thumb: Path | None = None


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIPY_CLIENT_ID",
        "SPOTIPY_CLIENT_SECRET",
    ):
        env.pop(key, None)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _deno_runtime() -> str | None:
    candidates = [
        Path.home() / ".spotdl" / "deno.exe",
        Path.home() / ".spotdl" / "deno",
        shutil.which("deno"),
    ]
    for item in candidates:
        if not item:
            continue
        path = Path(item)
        if path.exists():
            return f"deno:{path}"
    return None


def _ytdlp_bin() -> str:
    return shutil.which("yt-dlp") or "yt-dlp"


def search_query(track: TrackMeta) -> str:
    return build_search_query(track.artists, track.name)


def ytdlp_format_args(fmt: str) -> list[str]:
    """Respect the user's format button. Never prefer webm when they asked for mp3."""
    if fmt == "mp3":
        return [
            "-f",
            "ba/140/251",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
        ]
    return ["-f", "140/bestaudio[ext=m4a]/bestaudio[ext=mp4]/ba"]


def _ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


class TrackDownloader:
    def __init__(self, jobs_dir: Path, spotdl_bin: str | None = None):
        self.jobs_dir = jobs_dir
        self.spotdl_bin = spotdl_bin or shutil.which("spotdl") or "spotdl"
        self._procs: dict[str, list[asyncio.subprocess.Process]] = defaultdict(list)
        self.cancelled: set[str] = set()

    def cancel(self, job_id: str) -> None:
        self.cancelled.add(job_id)
        for proc in list(self._procs.get(job_id, [])):
            if proc.returncode is None:
                proc.kill()

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self.cancelled

    async def download_track(
        self,
        job_id: str,
        track: TrackMeta,
        dest: Path,
        fmt: str,
        source: str,
        on_status: StatusCb | None = None,
    ) -> DownloadOutcome:
        dest.mkdir(parents=True, exist_ok=True)
        attempts = provider_attempts(source)
        last_error = ""
        for index, providers in enumerate(attempts):
            if self.is_cancelled(job_id):
                return DownloadOutcome("failed", None, False, "cancelled")
            label = other_source_label(index, source)
            if on_status:
                on_status(f"Searching {label}…", "", None)
            path, error, thumb = await self._run_ytdlp(
                job_id, track, dest, providers[0], fmt, on_status
            )
            if path:
                return DownloadOutcome(
                    "audio",
                    path,
                    used_fallback=index > 0,
                    source_label=label,
                    thumb=thumb,
                )
            last_error = error
        return DownloadOutcome(
            "metadata_only",
            None,
            used_fallback=True,
            source_label=last_error or "none",
        )

    async def _resolve_youtube(
        self,
        job_id: str,
        track: TrackMeta,
        query: str,
        on_status: StatusCb | None,
    ) -> str | None:
        import json

        cmd = [
            _ytdlp_bin(),
            "--ignore-config",
            "--no-plugin-dirs",
            "--flat-playlist",
            "-J",
            f"ytsearch8:{query}",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_child_env(),
            )
        except FileNotFoundError:
            return f"ytsearch1:{query}"
        self._procs[job_id].append(proc)
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        finally:
            lst = self._procs.get(job_id, [])
            if proc in lst:
                lst.remove(proc)
        try:
            payload = json.loads(stdout.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError:
            return None
        entries = payload.get("entries") or []
        best = pick_best_entry(entries, track.artists, track.name)
        if not best:
            return None
        vid = best.get("id") or best.get("url")
        if not vid:
            return None
        if on_status:
            on_status("Found a match", best.get("title") or vid, None)
        if str(vid).startswith("http"):
            return str(vid)
        return f"https://www.youtube.com/watch?v={vid}"

    async def _run_ytdlp(
        self,
        job_id: str,
        track: TrackMeta,
        dest: Path,
        provider: str,
        fmt: str,
        on_status: StatusCb | None,
    ) -> tuple[Path | None, str, Path | None]:
        before = {p.name for p in dest.iterdir()} if dest.exists() else set()
        queries = search_queries(track.artists, track.name)
        query = queries[0] if queries else search_query(track)
        if on_status:
            on_status("Matching the right video…", query, None)
        if provider == "soundcloud":
            url = f"scsearch1:{query}"
        else:
            url = None
            last_miss = ""
            for q in queries:
                if on_status:
                    on_status("Matching the right video…", q, None)
                url = await self._resolve_youtube(job_id, track, q, on_status)
                if url:
                    break
                last_miss = q
            if not url:
                return None, f"no matching video for {last_miss or query}", None
        out_tmpl = str(dest / "%(title).80s.%(ext)s")
        cmd = [
            _ytdlp_bin(),
            "--ignore-config",
            "--no-plugin-dirs",
            "--no-playlist",
            "--no-mtime",
            "--newline",
            "--write-thumbnail",
            "--convert-thumbnails",
            "jpg",
            *ytdlp_format_args(fmt),
            "-o",
            out_tmpl,
            url,
        ]
        deno = _deno_runtime()
        if deno:
            cmd.extend(["--js-runtimes", deno])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=_child_env(),
            )
        except FileNotFoundError:
            return None, "yt-dlp missing", None
        self._procs[job_id].append(proc)
        chunks: list[str] = []
        try:
            assert proc.stdout is not None

            async def _read() -> None:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", "replace").strip()
                    if not text:
                        continue
                    chunks.append(text)
                    if on_status:
                        step = classify_line(text) or "Downloading audio…"
                        on_status(step, text[-140:], parse_percent(text))

            await asyncio.wait_for(_read(), timeout=ATTEMPT_TIMEOUT_S)
            await asyncio.wait_for(proc.wait(), timeout=20)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            return None, "timed out", None
        except asyncio.CancelledError:
            proc.kill()
            raise
        finally:
            lst = self._procs.get(job_id, [])
            if proc in lst:
                lst.remove(proc)
        if self.is_cancelled(job_id):
            return None, "cancelled", None
        after = [p for p in dest.iterdir() if p.name not in before]
        audio = [p for p in after if p.suffix.lower() in AUDIO_EXTS]
        thumbs = [p for p in after if p.suffix.lower() in THUMB_EXTS]
        if not audio:
            err = "\n".join(chunks)[-400:]
            return None, err or f"exit {proc.returncode}", None
        converted = await self._ensure_format(job_id, audio[0], fmt, on_status)
        thumb = await self._ensure_thumb(thumbs[0]) if thumbs else None
        return converted, "", thumb

    async def _ensure_format(
        self,
        job_id: str,
        path: Path,
        fmt: str,
        on_status: StatusCb | None,
    ) -> Path:
        want_mp3 = fmt == "mp3"
        if want_mp3 and path.suffix.lower() == ".mp3":
            return path
        if not want_mp3 and path.suffix.lower() in {".m4a", ".mp4"}:
            return path
        if not want_mp3:
            return path
        out = path.with_suffix(".mp3")
        if on_status:
            on_status("Converting to MP3…", path.name, None)
        cmd = [
            _ffmpeg_bin(),
            "-y",
            "-i",
            str(path),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "320k",
            str(out),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._procs[job_id].append(proc)
        try:
            await asyncio.wait_for(proc.communicate(), timeout=60)
        finally:
            lst = self._procs.get(job_id, [])
            if proc in lst:
                lst.remove(proc)
        if out.exists() and out.stat().st_size > 256:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return out
        return path

    async def _ensure_thumb(self, path: Path) -> Path | None:
        out = path.with_name(path.stem + "_cover.jpg")
        proc = await asyncio.create_subprocess_exec(
            _ffmpeg_bin(),
            "-y",
            "-i",
            str(path),
            "-vf",
            "scale=320:320:force_original_aspect_ratio=decrease",
            "-q:v",
            "4",
            str(out),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await asyncio.wait_for(proc.communicate(), timeout=20)
        if out.exists() and out.stat().st_size > 32:
            return out
        if path.suffix.lower() in {".jpg", ".jpeg"} and path.exists():
            return path
        return None
