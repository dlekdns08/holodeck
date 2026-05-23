"""Frame-extraction helpers used to keep visual continuity across beats.

Strategy: after a clip is generated we pull its final frame to a local JPEG. That
frame becomes the conditioning image for the next clip (image-to-video), keeping
the camera/character/scene anchored. ffmpeg is required at runtime; if it's
missing we degrade gracefully (no last_frame_url → next clip falls back to
text-to-video).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..config import CACHE_DIR

log = logging.getLogger(__name__)

FRAMES_DIR = CACHE_DIR / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


async def _resolve_local_video(video_url: str) -> Optional[Path]:
    """Return a local path to the video, downloading if it's remote.

    Returns None if we can't get one.
    """
    if video_url.startswith("/static/"):
        # Served from the package's static/ directory.
        from ..main import STATIC_DIR

        candidate = STATIC_DIR / video_url[len("/static/") :]
        return candidate if candidate.exists() else None

    if video_url.startswith("/cache/"):
        candidate = CACHE_DIR / video_url[len("/cache/") :]
        return candidate if candidate.exists() else None

    parsed = urlparse(video_url)
    if parsed.scheme in ("http", "https"):
        h = hashlib.sha1(video_url.encode()).hexdigest()[:16]
        local = FRAMES_DIR / f"src_{h}.mp4"
        if not local.exists():
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    r = await client.get(video_url)
                    r.raise_for_status()
                    local.write_bytes(r.content)
            except Exception as e:
                log.warning("could not fetch clip %s for frame extraction: %s", video_url, e)
                return None
        return local

    candidate = Path(video_url)
    return candidate if candidate.exists() else None


async def extract_last_frame(video_url: str, key: str) -> Optional[str]:
    """Extract the final frame of `video_url` to a JPEG and return its served URL.

    `key` is used to name the output file (typically a beat id or hash).
    Returns None if extraction fails — the caller should treat this as "no
    continuity image available" and fall back to text-to-video on the next beat.
    """
    if not _have_ffmpeg():
        log.info("ffmpeg not on PATH — skipping last-frame extraction")
        return None

    local = await _resolve_local_video(video_url)
    if local is None:
        return None

    out_path = FRAMES_DIR / f"{key}.jpg"

    # -sseof -0.05 seeks ~50ms before EOF, which reliably lands on the final frame
    # across most containers without doing a full decode.
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-sseof", "-0.05",
        "-i", str(local),
        "-vsync", "passthrough",
        "-q:v", "3",
        "-frames:v", "1",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not out_path.exists():
        log.warning("ffmpeg last-frame extraction failed: %s", stderr.decode(errors="ignore"))
        return None

    return f"/cache/frames/{out_path.name}"
