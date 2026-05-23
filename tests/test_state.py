from __future__ import annotations

from holodeck.agents.director import StateDelta, apply_delta
from holodeck.world.state import Character, WorldState


def _state() -> WorldState:
    return WorldState(session_id="t")


def test_apply_delta_sets_scalars():
    s = _state()
    apply_delta(s, StateDelta(location="rooftop", time_of_day="dusk", tone="tense"))
    assert s.location == "rooftop"
    assert s.time_of_day == "dusk"
    assert s.tone == "tense"


def test_apply_delta_adds_characters_idempotent():
    s = _state()
    juno = Character(name="Juno", description="dark coat, silver earring")
    apply_delta(s, StateDelta(characters_added=[juno]))
    apply_delta(s, StateDelta(characters_added=[juno]))
    assert [c.name for c in s.characters] == ["Juno"]


def test_apply_delta_removes_character():
    s = _state()
    s.characters = [
        Character(name="Juno", description="x"),
        Character(name="Kane", description="y"),
    ]
    apply_delta(s, StateDelta(characters_removed=["Juno"]))
    assert [c.name for c in s.characters] == ["Kane"]


def test_apply_delta_inventory_dedupes_and_removes():
    s = _state()
    apply_delta(s, StateDelta(inventory_added=["torch", "torch", "key"]))
    assert s.inventory == ["torch", "key"]
    apply_delta(s, StateDelta(inventory_removed=["torch"]))
    assert s.inventory == ["key"]


def test_apply_delta_threads_open_close():
    s = _state()
    apply_delta(s, StateDelta(threads_opened=["who is Juno?", "find the key"]))
    apply_delta(s, StateDelta(threads_closed=["find the key"]))
    assert s.open_threads == ["who is Juno?"]


def test_summary_mentions_synopsis_when_present():
    s = _state()
    s.synopsis = "Juno is hunting Kane through the rain."
    assert "Juno is hunting Kane" in s.summary()


def test_summary_handles_empty_synopsis():
    s = _state()
    out = s.summary()
    assert "no synopsis yet" in out
