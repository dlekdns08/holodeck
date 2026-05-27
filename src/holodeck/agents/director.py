from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from ..world.state import Beat, Character, WorldState
from .prompts import (
    EMIT_BEAT_TOOL,
    PREDICT_INPUTS_SYSTEM,
    PREDICT_INPUTS_TOOL,
    PREDICT_INPUTS_USER_TEMPLATE,
    SYNOPSIS_SYSTEM,
    SYNOPSIS_USER_TEMPLATE,
    USER_TURN_TEMPLATE,
    build_system_prompt,
)

log = logging.getLogger(__name__)

# Update the rolling synopsis once we've accumulated this many beats past the last one.
SYNOPSIS_EVERY = 6


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

    Uses Anthropic tool_use so the response is already a parsed object. Marks
    the system prompt + tools block as cacheable so repeat turns in the same
    session hit the prompt cache. Retries the tool call once if the input
    fails our local schema validation. Falls back to a deterministic stub when
    no API key is configured.
    """

    def __init__(self) -> None:
        self._client = None
        if settings.anthropic_api_key:
            try:
                from anthropic import Anthropic

                self._client = Anthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                log.warning("anthropic package missing — using stub Director")

    @property
    def using_stub(self) -> bool:
        return self._client is None

    def plan(self, state: WorldState, user_input: str) -> DirectorOutput:
        if self._client is None:
            return self._stub(state, user_input)

        user_msg = USER_TURN_TEMPLATE.format(
            world_summary=state.summary(),
            recent_beats=self._format_recent(state),
            user_input=user_input,
        )

        last_err: Optional[Exception] = None
        for attempt in range(2):
            resp = self._client.messages.create(
                model=settings.director_model,
                max_tokens=1024,
                # System and tools are stable per-session — mark both cacheable so
                # turns 2+ get a prompt-cache hit on the bulk of the input tokens.
                system=[
                    {
                        "type": "text",
                        "text": build_system_prompt(state.genre),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=[{**EMIT_BEAT_TOOL, "cache_control": {"type": "ephemeral"}}],
                tool_choice={"type": "tool", "name": "emit_beat"},
                messages=[{"role": "user", "content": user_msg}],
            )

            for block in resp.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "emit_beat":
                    try:
                        return DirectorOutput.model_validate(block.input)
                    except ValidationError as e:
                        last_err = e
                        if attempt == 0:
                            log.warning("emit_beat input failed validation, retrying once: %s", e)
                            break  # re-issue the request
                        log.error("emit_beat input failed validation on retry: %s\n%s", e, block.input)
                        raise

            else:
                # Loop fell through without finding a tool_use block.
                if attempt == 0:
                    log.warning("Director returned no emit_beat tool_use, retrying once")
                    continue
                log.error("Director returned no emit_beat tool_use on retry: %s", resp.content)
                raise RuntimeError("Director did not emit the expected tool call")

        # Defensive — only reachable if both attempts fell out without raising/returning.
        raise RuntimeError(f"Director failed after retry: {last_err}")

    def summarize(self, state: WorldState) -> str:
        """Produce a short prose synopsis of the story so far. Uses up to the last 20 beats."""
        if self._client is None:
            return self._stub_synopsis(state)

        beats_text = self._format_for_synopsis(state.beats[-20:])
        user_msg = SYNOPSIS_USER_TEMPLATE.format(
            genre=state.genre,
            prior_synopsis=state.synopsis or "(none)",
            beats=beats_text,
        )
        resp = self._client.messages.create(
            model=settings.director_model,
            max_tokens=400,
            system=SYNOPSIS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()

    def candidate_inputs(self, state: WorldState, k: int) -> list[str]:
        """Predict K plausible next user inputs for speculative pre-generation.

        Returns an empty list if Claude isn't configured or the call fails — the
        caller treats this as "no speculation this turn" and moves on.
        """
        if self._client is None or k <= 0:
            return []

        last_beat = state.beats[-1] if state.beats else None
        last_beat_text = (
            f"[{last_beat.index}] user: {last_beat.user_input}\n    scene: {last_beat.scene_prompt[:200]}…"
            if last_beat
            else "(no beats yet — opening turn)"
        )
        user_msg = PREDICT_INPUTS_USER_TEMPLATE.format(
            world_summary=state.summary(),
            last_beat=last_beat_text,
            k=k,
        )
        try:
            resp = self._client.messages.create(
                model=settings.director_model,
                max_tokens=400,
                system=PREDICT_INPUTS_SYSTEM,
                tools=[PREDICT_INPUTS_TOOL],
                tool_choice={"type": "tool", "name": "predict_inputs"},
                messages=[{"role": "user", "content": user_msg}],
            )
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "predict_inputs":
                    candidates = block.input.get("candidates") or []
                    return [c.strip() for c in candidates if isinstance(c, str) and c.strip()][:k]
        except Exception as e:
            log.warning("candidate_inputs failed (continuing without speculation): %s", e)
        return []

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
    def _format_for_synopsis(beats: list[Beat]) -> str:
        if not beats:
            return "(no beats yet)"
        return "\n".join(
            f"[{b.index}] user said: {b.user_input}\n    scene: {b.scene_prompt}"
            for b in beats
        )

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

    @staticmethod
    def _stub_synopsis(state: WorldState) -> str:
        return (
            f"A {state.genre or 'open'} story with {len(state.beats)} beats so far. "
            f"(stub synopsis — set ANTHROPIC_API_KEY to enable Claude.)"
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


def maybe_update_synopsis(director: Director, state: WorldState) -> bool:
    """Refresh the rolling synopsis if enough new beats have piled up. Returns True if updated."""
    new_beats = len(state.beats) - state.synopsis_through_beat
    if new_beats < SYNOPSIS_EVERY:
        return False
    try:
        state.synopsis = director.summarize(state)
        state.synopsis_through_beat = len(state.beats)
        return True
    except Exception as e:
        log.warning("synopsis update failed (continuing): %s", e)
        return False
