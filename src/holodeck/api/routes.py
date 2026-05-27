from __future__ import annotations

import asyncio
import json
import logging
import uuid
from functools import lru_cache
from typing import AsyncIterator, Awaitable, Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..agents.director import (
    Director,
    DirectorOutput,
    apply_delta,
    append_beat,
    maybe_update_synopsis,
)
from ..config import settings
from ..speculation import SpeculationStore, speculate
from ..storage import SessionStore
from ..video import VideoProvider, get_provider
from ..video.base import GeneratedClip
from ..video.export import export_session
from ..world.state import Beat, WorldState

log = logging.getLogger(__name__)

router = APIRouter()

T = TypeVar("T")

# Heartbeat for the SSE stream. Proxies (nginx/cloudflare) drop idle
# connections at ~60s; the Runway provider can poll for longer than that.
KEEPALIVE_INTERVAL_S = 10.0


@lru_cache(maxsize=1)
def get_director() -> Director:
    return Director()


@lru_cache(maxsize=1)
def get_store() -> SessionStore:
    return SessionStore()


@lru_cache(maxsize=1)
def get_video() -> VideoProvider:
    return get_provider()


@lru_cache(maxsize=1)
def get_speculation_store() -> SpeculationStore:
    return SpeculationStore()


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
        "speculative_pregen": settings.speculative_pregen_enabled,
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


@router.get("/session/{session_id}/export")
async def export_session_mp4(
    session_id: str,
    store: SessionStore = Depends(get_store),
) -> FileResponse:
    state = store.load(session_id)
    if not state:
        raise HTTPException(404, "session not found")
    if not state.beats:
        raise HTTPException(400, "session has no beats to export")
    out = await export_session(state)
    if out is None:
        raise HTTPException(500, "export failed (see server logs)")
    return FileResponse(
        out,
        media_type="video/mp4",
        filename=f"holodeck-{session_id[:8]}.mp4",
    )


async def _await_with_keepalive(coro: Awaitable[T]) -> AsyncIterator:
    """Yield SSE keepalive comments every KEEPALIVE_INTERVAL_S until coro is done.

    The final yielded value is the coroutine's result, wrapped in a single-element
    tuple so the caller can distinguish it from heartbeat bytes via isinstance.
    Long awaits (Director call, video generation) wrap themselves in this so
    proxies don't kill the SSE connection.
    """
    task = asyncio.create_task(coro)  # type: ignore[arg-type]
    while True:
        done, _ = await asyncio.wait({task}, timeout=KEEPALIVE_INTERVAL_S)
        if task in done:
            yield (task.result(),)
            return
        yield b": keepalive\n\n"


@router.post("/turn", response_model=TurnResponse)
async def turn(
    req: TurnRequest,
    store: SessionStore = Depends(get_store),
    video: VideoProvider = Depends(get_video),
    spec: SpeculationStore = Depends(get_speculation_store),
) -> TurnResponse:
    director = get_director()
    lock = await _session_lock(req.session_id)
    async with lock:
        state = store.load(req.session_id)
        if not state:
            raise HTTPException(404, "session not found")

        hit = spec.lookup(req.session_id, len(state.beats), req.user_input)
        if hit is not None:
            plan, clip = hit
            log.info("speculation HIT for session=%s", req.session_id)
        else:
            plan = director.plan(state, req.user_input)
            last_frame: Optional[str] = state.beats[-1].last_frame_url if state.beats else None
            clip = await video.generate(
                plan.scene_prompt,
                seconds=settings.clip_seconds,
                resolution=settings.clip_resolution,
                last_frame_url=last_frame,
            )

        apply_delta(state, plan.state_delta)
        beat = append_beat(state, req.user_input, plan, clip.video_url)
        beat.last_frame_url = clip.last_frame_url
        maybe_update_synopsis(director, state)
        store.save(state)
        spec.invalidate(req.session_id)
        spec.schedule(req.session_id, speculate(spec, director, video, state))
        return TurnResponse(beat=beat, state=state)


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


@router.get("/turn/stream")
async def turn_stream(
    session_id: str,
    user_input: str,
    store: SessionStore = Depends(get_store),
    video: VideoProvider = Depends(get_video),
    spec: SpeculationStore = Depends(get_speculation_store),
) -> StreamingResponse:
    """SSE variant of /turn.

    Streams `planning → narration → generating → beat → done`. Emits SSE
    comment heartbeats during long awaits so proxies don't kill the stream.
    Hits the speculation cache if the user input matches a pre-rendered
    candidate at the current beat count, in which case `generating` is skipped.
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

                hit = spec.lookup(session_id, len(state.beats), user_input)
                plan: DirectorOutput
                clip: GeneratedClip

                if hit is not None:
                    plan, clip = hit
                    log.info("speculation HIT (stream) for session=%s", session_id)
                    apply_delta(state, plan.state_delta)
                    yield _sse(
                        "narration",
                        {
                            "narration": plan.narration,
                            "scene_prompt": plan.scene_prompt,
                            "state": json.loads(state.model_dump_json()),
                            "speculation_hit": True,
                        },
                    )
                else:
                    plan_result = None
                    async for item in _await_with_keepalive(
                        asyncio.to_thread(director.plan, state, user_input)
                    ):
                        if isinstance(item, tuple):
                            plan_result = item[0]
                        else:
                            yield item
                    assert plan_result is not None
                    plan = plan_result
                    apply_delta(state, plan.state_delta)

                    yield _sse(
                        "narration",
                        {
                            "narration": plan.narration,
                            "scene_prompt": plan.scene_prompt,
                            "state": json.loads(state.model_dump_json()),
                            "speculation_hit": False,
                        },
                    )

                    yield _sse("generating", {"provider": video.name})
                    last_frame = state.beats[-1].last_frame_url if state.beats else None
                    clip_result = None
                    async for item in _await_with_keepalive(
                        video.generate(
                            plan.scene_prompt,
                            seconds=settings.clip_seconds,
                            resolution=settings.clip_resolution,
                            last_frame_url=last_frame,
                        )
                    ):
                        if isinstance(item, tuple):
                            clip_result = item[0]
                        else:
                            yield item
                    assert clip_result is not None
                    clip = clip_result

                beat = append_beat(state, user_input, plan, clip.video_url)
                beat.last_frame_url = clip.last_frame_url

                synopsis_updated = await asyncio.to_thread(maybe_update_synopsis, director, state)
                store.save(state)
                spec.invalidate(session_id)
                spec.schedule(session_id, speculate(spec, director, video, state))

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
