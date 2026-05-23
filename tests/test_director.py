from __future__ import annotations

from holodeck.agents.director import (
    Director,
    SYNOPSIS_EVERY,
    append_beat,
    maybe_update_synopsis,
)
from holodeck.agents.prompts import GENRE_PRESETS, build_system_prompt
from holodeck.world.state import WorldState


def _stub_director() -> Director:
    d = Director()
    # Force the stub path even if the host has ANTHROPIC_API_KEY set in env.
    d._client = None  # type: ignore[attr-defined]
    return d


def test_stub_plan_produces_valid_output_with_no_api_key():
    d = _stub_director()
    state = WorldState(session_id="t", location="a rain-slick alley")
    out = d.plan(state, "Juno steps into the light.")
    assert out.scene_prompt
    assert "rain-slick alley" in out.scene_prompt
    assert "Juno" in out.scene_prompt or "figure" in out.scene_prompt


def test_genre_preset_injected_into_system_prompt():
    sys = build_system_prompt("noir")
    assert "noir" in sys.lower()
    assert "chiaroscuro" in sys


def test_unknown_genre_yields_clean_system_prompt():
    sys = build_system_prompt("totally-made-up-genre")
    # No genre directive section appended.
    assert "Genre directive" not in sys


def test_all_genre_presets_are_non_empty():
    for k, v in GENRE_PRESETS.items():
        assert v.strip(), f"empty preset for {k}"


def test_maybe_update_synopsis_only_fires_after_threshold():
    d = _stub_director()
    state = WorldState(session_id="t")
    # Below threshold: no-op.
    for i in range(SYNOPSIS_EVERY - 1):
        out = d.plan(state, f"input {i}")
        append_beat(state, f"input {i}", out, video_url="/static/placeholder.mp4")
    assert maybe_update_synopsis(d, state) is False
    assert state.synopsis == ""

    # One more beat tips us over the threshold.
    out = d.plan(state, "final")
    append_beat(state, "final", out, video_url="/static/placeholder.mp4")
    assert maybe_update_synopsis(d, state) is True
    assert state.synopsis
    assert state.synopsis_through_beat == len(state.beats)
