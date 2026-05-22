from ..config import settings
from .base import GeneratedClip, VideoProvider
from .mock import MockProvider
from .runway import RunwayProvider
from .sora import SoraProvider
from .veo import VeoProvider


def get_provider() -> VideoProvider:
    name = settings.video_provider
    if name == "mock":
        return MockProvider()
    if name == "veo":
        return VeoProvider()
    if name == "sora":
        return SoraProvider()
    if name == "runway":
        return RunwayProvider()
    raise ValueError(f"Unknown VIDEO_PROVIDER: {name}")


__all__ = [
    "GeneratedClip",
    "VideoProvider",
    "MockProvider",
    "VeoProvider",
    "SoraProvider",
    "RunwayProvider",
    "get_provider",
]
