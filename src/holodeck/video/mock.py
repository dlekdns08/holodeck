from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Optional

from ..config import CACHE_DIR
from .base import GeneratedClip


class MockProvider:
    """Returns a placeholder clip + writes the prompt to a sidecar JSON file.

    Use this to verify the full loop runs without burning real API credits.
    The /static endpoint serves the placeholder.
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
        # Simulate generation latency so the UI's loading state is exercised.
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

        return GeneratedClip(
            video_url="/static/placeholder.mp4",
            last_frame_url=None,
            raw={"mock": True, "sidecar": str(sidecar)},
        )
