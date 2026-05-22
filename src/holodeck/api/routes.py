from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.director import Director, apply_delta, append_beat
from ..config import settings
from ..storage import SessionStore
from ..video import get_provider
from ..world.state import Beat, WorldState

router = APIRouter()

_director = Director()
_store = SessionStore()
_video = get_provider()


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
def health() -> dict:
    return {
        "ok": True,
        "video_provider": _video.name,
        "director_model": settings.director_model if settings.anthropic_api_key else "stub",
    }


@router.post("/session", response_model=WorldState)
def new_session(req: NewSessionRequest) -> WorldState:
    state = WorldState(session_id=str(uuid.uuid4()), genre=req.genre)
    state.open_threads.append(req.opening)
    _store.save(state)
    return state


@router.get("/session/{session_id}", response_model=WorldState)
def get_session(session_id: str) -> WorldState:
    state = _store.load(session_id)
    if not state:
        raise HTTPException(404, "session not found")
    return state


@router.get("/sessions")
def list_sessions() -> list[dict]:
    return _store.list_sessions()


@router.post("/turn", response_model=TurnResponse)
async def turn(req: TurnRequest) -> TurnResponse:
    state = _store.load(req.session_id)
    if not state:
        raise HTTPException(404, "session not found")

    plan = _director.plan(state, req.user_input)
    apply_delta(state, plan.state_delta)

    last_frame: Optional[str] = state.beats[-1].last_frame_url if state.beats else None
    clip = await _video.generate(
        plan.scene_prompt,
        seconds=settings.clip_seconds,
        resolution=settings.clip_resolution,
        last_frame_url=last_frame,
    )

    beat = append_beat(state, req.user_input, plan, clip.video_url)
    beat.last_frame_url = clip.last_frame_url
    _store.save(state)
    return TurnResponse(beat=beat, state=state)
