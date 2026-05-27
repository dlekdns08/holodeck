from __future__ import annotations

from holodeck.agents.director import DirectorOutput
from holodeck.speculation import SpeculationStore, _normalize
from holodeck.video.base import GeneratedClip


def _entry(prompt: str = "ok") -> tuple[DirectorOutput, GeneratedClip]:
    return DirectorOutput(scene_prompt=prompt), GeneratedClip(video_url="/x.mp4")


def test_lookup_returns_none_on_empty_store():
    s = SpeculationStore()
    assert s.lookup("sid", 0, "anything") is None


def test_put_then_lookup_hits_with_normalized_input():
    s = SpeculationStore()
    e = _entry()
    s.put("sid", 3, "Open the door.", e)
    # Same beats_count, equivalent input under normalization.
    assert s.lookup("sid", 3, "OPEN the DOOR!") is e
    assert s.lookup("sid", 3, "open the door") is e


def test_lookup_misses_when_beats_count_advances():
    s = SpeculationStore()
    e = _entry()
    s.put("sid", 3, "go left", e)
    assert s.lookup("sid", 4, "go left") is None


def test_put_invalidates_old_entries_when_beats_count_changes():
    s = SpeculationStore()
    s.put("sid", 3, "old guess", _entry())
    s.put("sid", 4, "new guess", _entry("new"))
    assert s.lookup("sid", 3, "old guess") is None
    assert s.lookup("sid", 4, "new guess") is not None


def test_invalidate_clears_session():
    s = SpeculationStore()
    s.put("sid", 1, "a", _entry())
    s.invalidate("sid")
    assert s.lookup("sid", 1, "a") is None


def test_normalize_strips_punctuation_and_case():
    assert _normalize("Hello, WORLD!!!") == "hello world"
    assert _normalize("  Multiple   spaces  ") == "multiple   spaces"
