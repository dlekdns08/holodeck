"""Speculative pre-generation of likely-next beats.

After a turn completes we ask the Director for K plausible next user inputs,
then in the background render full DirectorOutput + GeneratedClip pairs for
each. On the next /turn, if the actual user input matches a cached candidate
(case-insensitive, punctuation-stripped), we skip both the Director and the
video provider and play back the pre-rendered beat instantly.

Cache is in-memory only — it's a UX optimization, not durable state.
Invariant: entries for a session are valid only while the session is at the
exact beat count they were generated against. Any real turn invalidates them.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .agents.director import Director, DirectorOutput, apply_delta
from .config import settings
from .video.base import GeneratedClip, VideoProvider
from .world.state import WorldState

log = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


@dataclass
class _SessionSpec:
    beats_count: int
    candidates: dict[str, tuple[DirectorOutput, GeneratedClip]] = field(default_factory=dict)


class SpeculationStore:
    """Per-session cache of pre-rendered (DirectorOutput, GeneratedClip) pairs."""

    def __init__(self) -> None:
        self._entries: dict[str, _SessionSpec] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def lookup(
        self,
        session_id: str,
        beats_count: int,
        user_input: str,
    ) -> Optional[tuple[DirectorOutput, GeneratedClip]]:
        spec = self._entries.get(session_id)
        if not spec or spec.beats_count != beats_count:
            return None
        return spec.candidates.get(_normalize(user_input))

    def put(
        self,
        session_id: str,
        beats_count: int,
        user_input: str,
        value: tuple[DirectorOutput, GeneratedClip],
    ) -> None:
        spec = self._entries.get(session_id)
        if spec is None or spec.beats_count != beats_count:
            spec = _SessionSpec(beats_count=beats_count)
            self._entries[session_id] = spec
        spec.candidates[_normalize(user_input)] = value

    def invalidate(self, session_id: str) -> None:
        self._entries.pop(session_id, None)
        t = self._tasks.pop(session_id, None)
        if t and not t.done():
            t.cancel()

    def candidates_for(self, session_id: str, beats_count: int) -> list[str]:
        spec = self._entries.get(session_id)
        if not spec or spec.beats_count != beats_count:
            return []
        return list(spec.candidates.keys())

    def schedule(self, session_id: str, coro) -> None:
        """Replace any in-flight speculation task for this session with `coro`."""
        existing = self._tasks.pop(session_id, None)
        if existing and not existing.done():
            existing.cancel()
        self._tasks[session_id] = asyncio.create_task(coro)


async def speculate(
    store: SpeculationStore,
    director: Director,
    video: VideoProvider,
    state: WorldState,
) -> None:
    """Pre-render K likely-next beats for `state` and stash them in `store`.

    Safe to fire-and-forget — all errors are swallowed and logged.
    """
    if not settings.speculative_pregen_enabled:
        return
    if director.using_stub:
        # The stub Director's output is deterministic from the input string, so
        # caching it just wastes provider cycles.
        return

    try:
        beats_count = len(state.beats)
        candidates = await asyncio.to_thread(
            director.candidate_inputs, state, settings.speculative_pregen_k
        )
        if not candidates:
            return

        for guess in candidates:
            try:
                # Each speculation works on its own copy so apply_delta doesn't
                # mutate the real session state.
                projected = copy.deepcopy(state)
                plan = await asyncio.to_thread(director.plan, projected, guess)
                apply_delta(projected, plan.state_delta)

                last_frame = projected.beats[-1].last_frame_url if projected.beats else None
                clip = await video.generate(
                    plan.scene_prompt,
                    seconds=settings.clip_seconds,
                    resolution=settings.clip_resolution,
                    last_frame_url=last_frame,
                )
                store.put(state.session_id, beats_count, guess, (plan, clip))
                log.info(
                    "speculation cached: session=%s beats=%d input=%r",
                    state.session_id, beats_count, guess[:60],
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("speculation candidate failed (%r): %s", guess[:60], e)
    except asyncio.CancelledError:
        log.info("speculation cancelled for %s", state.session_id)
        raise
    except Exception as e:
        log.warning("speculation pass failed: %s", e)
