from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from ..config import settings
from ..world.state import Beat, Character, WorldState
from .prompts import DIRECTOR_SYSTEM, USER_TURN_TEMPLATE

log = logging.getLogger(__name__)


class StateDelta(BaseModel):
    location: Optional[str] = None
    time_of_day: Optional[str] = None
    tone: Optional[str] = None
    characters_added: list[Character] = Field(default_factory=list)
    characters_removed: list[str] = Field(default_factory=list)
    inventory_added: list[str] = Field(default_factory=list)
    inventory_removed: list[str] = Field(default_factory=list)
    threads_opened: list[str] = Field(default_factory=list)
    threads_closed: list[str] = Field(default_factory=list)


class DirectorOutput(BaseModel):
    scene_prompt: str
    narration: str = ""
    state_delta: StateDelta = Field(default_factory=StateDelta)


class Director:
    """Wraps Claude to plan the next beat from world state + user input.

    Falls back to a deterministic stub if no API key is configured, so the loop
    still runs end-to-end during local dev.
    """

    def __init__(self) -> None:
        self._client = None
        if settings.anthropic_api_key:
            try:
                from anthropic import Anthropic

                self._client = Anthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                log.warning("anthropic package missing — using stub Director")

    def plan(self, state: WorldState, user_input: str) -> DirectorOutput:
        if self._client is None:
            return self._stub(state, user_input)

        recent = self._format_recent(state)
        user_msg = USER_TURN_TEMPLATE.format(
            world_summary=state.summary(),
            recent_beats=recent,
            user_input=user_input,
        )

        # TODO: enable prompt caching on DIRECTOR_SYSTEM once the prompt stabilizes.
        resp = self._client.messages.create(
            model=settings.director_model,
            max_tokens=1024,
            system=DIRECTOR_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text").strip()
        return self._parse(text)

    @staticmethod
    def _format_recent(state: WorldState) -> str:
        beats = state.recent_beats(4)
        if not beats:
            return "(none — this is the opening beat)"
        return "\n".join(
            f"[{b.index}] user: {b.user_input}\n    scene: {b.scene_prompt[:160]}…"
            for b in beats
        )

    @staticmethod
    def _parse(text: str) -> DirectorOutput:
        # Strip code fences if the model added them despite instructions.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return DirectorOutput.model_validate(json.loads(text))
        except Exception as e:
            log.error("Director returned unparseable JSON: %s\n---\n%s", e, text)
            raise

    @staticmethod
    def _stub(state: WorldState, user_input: str) -> DirectorOutput:
        idx = len(state.beats) + 1
        loc = state.location or "an unremarkable room with dust motes drifting in afternoon light"
        return DirectorOutput(
            scene_prompt=(
                f"Cinematic 35mm shot, slow dolly-in. {loc}. A figure reacts to: "
                f"'{user_input}'. Soft natural lighting, muted color palette, "
                f"shallow depth of field. Beat {idx} of an ongoing story."
            ),
            narration=f"(stub director — set ANTHROPIC_API_KEY to enable Claude.) Beat {idx}.",
            state_delta=StateDelta(),
        )


def apply_delta(state: WorldState, delta: StateDelta) -> WorldState:
    if delta.location:
        state.location = delta.location
    if delta.time_of_day:
        state.time_of_day = delta.time_of_day
    if delta.tone:
        state.tone = delta.tone

    if delta.characters_removed:
        state.characters = [c for c in state.characters if c.name not in delta.characters_removed]
    existing = {c.name for c in state.characters}
    for c in delta.characters_added:
        if c.name not in existing:
            state.characters.append(c)

    state.inventory = [i for i in state.inventory if i not in delta.inventory_removed]
    for item in delta.inventory_added:
        if item not in state.inventory:
            state.inventory.append(item)

    state.open_threads = [t for t in state.open_threads if t not in delta.threads_closed]
    for t in delta.threads_opened:
        if t not in state.open_threads:
            state.open_threads.append(t)

    return state


def append_beat(state: WorldState, user_input: str, out: DirectorOutput, video_url: str) -> Beat:
    beat = Beat(
        index=len(state.beats) + 1,
        user_input=user_input,
        scene_prompt=out.scene_prompt,
        narration=out.narration,
        video_url=video_url,
    )
    state.beats.append(beat)
    return beat
