from __future__ import annotations

import asyncio
import json
import logging
import uuid
from functools import lru_cache
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agents.director import Director, apply_delta, append_beat, maybe_update_synopsis
from ..config import settings
from ..storage import SessionStore
from ..video import VideoProvider, get_provider
from ..world.state import Beat, WorldState

log = logging.getLogger(__name__)

router = APIRouter()


# Lazy singletons so provider stubs that raise in __init__ (missing API keys) don't
# blow up module import. Each is built at first use.
@lru_cache(maxsize=1)
def get_director() -> Director:
    return Director()


@lru_cache(maxsize=1)
def get_store() -> SessionStore:
    return SessionStore()


@lru_cache(maxsize=1)
def get_video() -> VideoProvider:
    return get_provider()


# Per-session lock registry. Prevents two concurrent /turn calls for the same
# session from racing on beat indices or last_frame state.
_session_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _session_lock(session_id: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _session_locks[session_id] = lock
        return lock


class NewSessionRequest(BaseModel):
    genre: str = "open"
    opening: str = "The story begins."


class TurnRequest(BaseModel):
    session_id: str
    user_input: str


class TurnResponse(BaseModel):
    beat: Beat
    state: WorldState


@router.get("/health")
def health(video: VideoProvider = Depends(get_video)) -> dict:
    director = get_director()
    return {
        "ok": True,
        "video_provider": video.name,
        "director_model": settings.director_model if not director.using_stub else "stub",
    }


@router.post("/session", response_model=WorldState)
def new_session(
    req: NewSessionRequest,
    store: SessionStore = Depends(get_store),
) -> WorldState:
    state = WorldState(session_id=str(uuid.uuid4()), genre=req.genre)
    state.open_threads.append(req.opening)
    store.save(state)
    return state


@router.get("/session/{session_id}", response_model=WorldState)
def get_session(session_id: str, store: SessionStore = Depends(get_store)) -> WorldState:
    state = store.load(session_id)
    if not state:
        raise HTTPException(404, "session not found")
    return state


@router.get("/sessions")
def list_sessions(store: SessionStore = Depends(get_store)) -> list[dict]:
    return store.list_sessions()


@router.post("/turn", response_model=TurnResponse)
async def turn(
    req: TurnRequest,
    store: SessionStore = Depends(get_store),
    video: VideoProvider = Depends(get_video),
) -> TurnResponse:
    director = get_director()
    lock = await _session_lock(req.session_id)
    async with lock:
        state = store.load(req.session_id)
        if not state:
            raise HTTPException(404, "session not found")

        plan = director.plan(state, req.user_input)
        apply_delta(state, plan.state_delta)

        last_frame: Optional[str] = state.beats[-1].last_frame_url if state.beats else None
        clip = await video.generate(
            plan.scene_prompt,
            seconds=settings.clip_seconds,
            resolution=settings.clip_resolution,
            last_frame_url=last_frame,
        )

        beat = append_beat(state, req.user_input, plan, clip.video_url)
        beat.last_frame_url = clip.last_frame_url
        maybe_update_synopsis(director, state)
        store.save(state)
        return TurnResponse(beat=beat, state=state)


def _sse(event: str, data: dict) -> bytes:
    """Encode a Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


@router.get("/turn/stream")
async def turn_stream(
    session_id: str,
    user_input: str,
    store: SessionStore = Depends(get_store),
    video: VideoProvider = Depends(get_video),
) -> StreamingResponse:
    """SSE variant of /turn.

    Streams events in this order so the UI can react incrementally:
      planning      — director invoked
      narration     — narration + scene_prompt + updated state available
      generating    — handed off to the video provider
      beat          — final beat with video_url ready to play
      done          — terminal frame
      error         — emitted on any failure; stream then closes
    EventSource only does GET, so this endpoint is GET — note that user_input
    rides on the query string.
    """
    director = get_director()

    async def gen() -> AsyncIterator[bytes]:
        lock = await _session_lock(session_id)
        async with lock:
            try:
                state = store.load(session_id)
                if not state:
                    yield _sse("error", {"message": "session not found"})
                    return

                yield _sse("planning", {"session_id": session_id})

                # Director call is sync — push it to a thread so we don't block
                # the event loop (and so the SSE keepalive can flow).
                plan = await asyncio.to_thread(director.plan, state, user_input)
                apply_delta(state, plan.state_delta)

                yield _sse(
                    "narration",
                    {
                        "narration": plan.narration,
                        "scene_prompt": plan.scene_prompt,
                        "state": json.loads(state.model_dump_json()),
                    },
                )

                yield _sse("generating", {"provider": video.name})

                last_frame = state.beats[-1].last_frame_url if state.beats else None
                clip = await video.generate(
                    plan.scene_prompt,
                    seconds=settings.clip_seconds,
                    resolution=settings.clip_resolution,
                    last_frame_url=last_frame,
                )

                beat = append_beat(state, user_input, plan, clip.video_url)
                beat.last_frame_url = clip.last_frame_url

                synopsis_updated = await asyncio.to_thread(maybe_update_synopsis, director, state)
                store.save(state)

                yield _sse(
                    "beat",
                    {
                        "beat": json.loads(beat.model_dump_json()),
                        "state": json.loads(state.model_dump_json()),
                        "synopsis_updated": synopsis_updated,
                    },
                )
                yield _sse("done", {})
            except Exception as e:
                log.exception("turn_stream failed")
                yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
