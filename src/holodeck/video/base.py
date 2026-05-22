from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class GeneratedClip:
    video_url: str           # served URL or absolute path
    last_frame_url: Optional[str] = None  # for image-to-video continuity on next call
    raw: dict | None = None  # provider-specific response payload


class VideoProvider(Protocol):
    name: str

    async def generate(
        self,
        prompt: str,
        *,
        seconds: int,
        resolution: str,
        last_frame_url: Optional[str] = None,
    ) -> GeneratedClip:
        ...
