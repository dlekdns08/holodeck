from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Character(BaseModel):
    name: str
    description: str
    reference_image_url: Optional[str] = None


class Beat(BaseModel):
    """A single rendered moment in the story."""

    index: int
    user_input: str
    scene_prompt: str
    narration: str = ""
    video_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorldState(BaseModel):
    session_id: str
    genre: str = "open"
    location: str = ""
    time_of_day: str = ""
    tone: str = ""
    characters: list[Character] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)

    def recent_beats(self, n: int = 4) -> list[Beat]:
        return self.beats[-n:]

    def summary(self) -> str:
        chars = ", ".join(f"{c.name} ({c.description})" for c in self.characters) or "—"
        threads = "; ".join(self.open_threads) or "—"
        return (
            f"Genre: {self.genre}\n"
            f"Location: {self.location or '—'}\n"
            f"Time: {self.time_of_day or '—'}\n"
            f"Tone: {self.tone or '—'}\n"
            f"Characters: {chars}\n"
            f"Open threads: {threads}\n"
            f"Beats so far: {len(self.beats)}"
        )
