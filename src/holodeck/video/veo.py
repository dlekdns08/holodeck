from __future__ import annotations

from typing import Optional

from ..config import settings
from .base import GeneratedClip


class VeoProvider:
    """Google Veo 3 via the google-genai SDK.

    Stub: fill in once you've enabled Vertex AI / Gemini API access. The actual
    call shape (as of 2026) is roughly:

        client = genai.Client(api_key=settings.google_api_key)
        op = client.models.generate_videos(
            model="veo-3.0-generate-001",
            prompt=prompt,
            config={"duration_seconds": seconds, "resolution": resolution,
                    "image": last_frame_url},
        )
        # poll op until done, then download op.result.generated_videos[0]
    """

    name = "veo"

    def __init__(self) -> None:
        if not settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY not set — required for VeoProvider")

    async def generate(
        self,
        prompt: str,
        *,
        seconds: int,
        resolution: str,
        last_frame_url: Optional[str] = None,
    ) -> GeneratedClip:
        raise NotImplementedError(
            "VeoProvider is a stub. Wire up google-genai per the docstring above."
        )
