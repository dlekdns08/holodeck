from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Optional

from ..config import CACHE_DIR
from .base import GeneratedClip
from .frames import extract_last_frame


class MockProvider:
    """Returns the placeholder clip and exercises the full continuity pipeline.

    On each call we:
      1. write a sidecar JSON capturing the prompt (useful for offline review)
      2. extract the last frame of the placeholder clip so the next call gets a
         real `last_frame_url` to feed into image-to-video conditioning
    No API credits burned.
    """

    name = "mock"

    async def generate(
        self,
        prompt: str,
        *,
        seconds: int,
        resolution: str,
        last_frame_url: Optional[str] = None,
    ) -> GeneratedClip:
        await asyncio.sleep(0.6)

        h = hashlib.sha1(prompt.encode()).hexdigest()[:12]
        sidecar = CACHE_DIR / f"{h}.json"
        sidecar.write_text(
            json.dumps(
                {
                    "prompt": prompt,
                    "seconds": seconds,
                    "resolution": resolution,
                    "last_frame_url": last_frame_url,
                },
                indent=2,
            )
        )

        video_url = "/static/placeholder.mp4"
        next_last_frame = await extract_last_frame(video_url, key=f"mock_{h}")

        return GeneratedClip(
            video_url=video_url,
            last_frame_url=next_last_frame,
            raw={"mock": True, "sidecar": str(sidecar)},
        )
