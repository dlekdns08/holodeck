from __future__ import annotations

from typing import Optional

from ..config import settings
from .base import GeneratedClip


class SoraProvider:
    """OpenAI Sora 2 via the OpenAI video endpoint.

    Stub: complete this once you have access. Rough call shape:

        client = OpenAI(api_key=settings.openai_api_key)
        job = client.videos.generate(
            model="sora-2",
            prompt=prompt,
            seconds=seconds,
            size=resolution,
            reference_image=last_frame_url,
        )
        # poll job until status=='completed', then job.result.url
    """

    name = "sora"

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set — required for SoraProvider")

    async def generate(
        self,
        prompt: str,
        *,
        seconds: int,
        resolution: str,
        last_frame_url: Optional[str] = None,
    ) -> GeneratedClip:
        raise NotImplementedError(
            "SoraProvider is a stub. Wire up the OpenAI video endpoint per the docstring."
        )
