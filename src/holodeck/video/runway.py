from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

import httpx

from ..config import settings
from .base import GeneratedClip
from .frames import extract_last_frame

log = logging.getLogger(__name__)


class RunwayProvider:
    """Runway Gen-4 via REST API.

    Polls the task endpoint with a bounded timeout. When the job succeeds we
    extract the final frame to keep image-to-video continuity on the next call.
    """

    name = "runway"
    BASE_URL = "https://api.dev.runwayml.com/v1"
    POLL_INTERVAL_S = 3.0
    POLL_TIMEOUT_S = 240.0

    def __init__(self) -> None:
        if not settings.runway_api_key:
            raise RuntimeError("RUNWAY_API_KEY not set — required for RunwayProvider")
        self._headers = {
            "Authorization": f"Bearer {settings.runway_api_key}",
            "X-Runway-Version": "2025-11-06",
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        prompt: str,
        *,
        seconds: int,
        resolution: str,
        last_frame_url: Optional[str] = None,
    ) -> GeneratedClip:
        payload: dict = {
            "model": "gen4_turbo",
            "promptText": prompt,
            "duration": seconds,
            "ratio": "1280:720" if resolution == "720p" else "1920:1080",
        }
        if last_frame_url:
            payload["promptImage"] = last_frame_url

        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{self.BASE_URL}/image_to_video",
                headers=self._headers,
                json=payload,
            )
            r.raise_for_status()
            task_id = r.json()["id"]

            deadline = asyncio.get_event_loop().time() + self.POLL_TIMEOUT_S
            while True:
                if asyncio.get_event_loop().time() > deadline:
                    raise RuntimeError(f"Runway task {task_id} timed out after {self.POLL_TIMEOUT_S}s")

                s = await client.get(f"{self.BASE_URL}/tasks/{task_id}", headers=self._headers)
                s.raise_for_status()
                data = s.json()
                status = data.get("status")
                if status == "SUCCEEDED":
                    video_url = data["output"][0]
                    next_last_frame = await extract_last_frame(
                        video_url, key=f"runway_{uuid.uuid4().hex[:12]}"
                    )
                    return GeneratedClip(
                        video_url=video_url,
                        last_frame_url=next_last_frame,
                        raw=data,
                    )
                if status in ("FAILED", "CANCELLED"):
                    raise RuntimeError(f"Runway task {task_id} ended: {status}")
                await asyncio.sleep(self.POLL_INTERVAL_S)
