"""Stitch a session's beats into a single mp4 via ffmpeg concat.

We cache the output keyed on (session_id, beat_count) so re-exporting a
session that hasn't advanced is a no-op disk read. Each clip is resolved to
a local path first (remote clips are downloaded by frames.resolve_local_video).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from ..config import CACHE_DIR
from ..world.state import WorldState
from .frames import resolve_local_video

log = logging.getLogger(__name__)

EXPORTS_DIR = CACHE_DIR / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _output_path(state: WorldState) -> Path:
    return EXPORTS_DIR / f"{state.session_id}__beats-{len(state.beats)}.mp4"


async def export_session(state: WorldState) -> Optional[Path]:
    """Concatenate every beat's clip into one mp4 and return the local path.

    Returns None if ffmpeg is missing, there are no beats, or any clip can't
    be resolved. Cached by (session_id, beat_count).
    """
    if not _have_ffmpeg():
        log.warning("ffmpeg not on PATH — cannot export session")
        return None
    if not state.beats:
        return None

    out = _output_path(state)
    if out.exists():
        return out

    locals_: list[Path] = []
    for beat in state.beats:
        if not beat.video_url:
            log.warning("beat %d has no video_url — skipping export", beat.index)
            continue
        p = await resolve_local_video(beat.video_url)
        if p is None:
            log.warning("beat %d clip %s could not be resolved — aborting export", beat.index, beat.video_url)
            return None
        locals_.append(p)

    if not locals_:
        return None

    # The concat demuxer wants a manifest file with one `file '...'` line each.
    # Paths are written absolute with single-quote escaping so spaces are safe.
    manifest = EXPORTS_DIR / f"{state.session_id}__beats-{len(state.beats)}.txt"
    manifest.write_text(
        "\n".join(f"file '{str(p.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for p in locals_)
    )

    # Re-encode (not -c copy) because mixed sources (mock placeholder + Runway
    # clips) can have different codecs/timebases that the concat demuxer chokes
    # on. h264/aac is the safe lowest common denominator for browser playback.
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-f", "concat",
        "-safe", "0",
        "-i", str(manifest),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(out),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not out.exists():
        log.warning("ffmpeg concat failed: %s", stderr.decode(errors="ignore"))
        return None

    return out
