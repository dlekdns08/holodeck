from __future__ import annotations

from typing import Optional

import httpx

from ..config import settings
from .base import GeneratedClip


class RunwayProvider:
    """Runway Gen-4 via REST API.

    Stub with the request shape pre-filled — verify against current Runway docs
    before relying on it; their schema shifts.
    """

    name = "runway"
    BASE_URL = "https://api.dev.runwayml.com/v1"

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

            # Poll until done. TODO: replace with webhook for production.
            while True:
                s = await client.get(f"{self.BASE_URL}/tasks/{task_id}", headers=self._headers)
                s.raise_for_status()
                data = s.json()
                status = data.get("status")
                if status == "SUCCEEDED":
                    return GeneratedClip(
                        video_url=data["output"][0],
                        last_frame_url=None,
                        raw=data,
                    )
                if status in ("FAILED", "CANCELLED"):
                    raise RuntimeError(f"Runway task {task_id} ended: {status}")
                # else: PENDING / RUNNING — keep polling
                import asyncio
                await asyncio.sleep(3.0)
