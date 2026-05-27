from __future__ import annotations

from pathlib import Path

from holodeck.storage.sessions import SessionStore
from holodeck.world.state import Character, WorldState


def test_save_and_load_roundtrip(tmp_path: Path):
    store = SessionStore(db_path=tmp_path / "t.db")
    state = WorldState(
        session_id="s1",
        genre="noir",
        location="rooftop",
        characters=[Character(name="Juno", description="silver earring")],
    )
    store.save(state)

    loaded = store.load("s1")
    assert loaded is not None
    assert loaded.location == "rooftop"
    assert loaded.characters[0].name == "Juno"


def test_save_overwrites_same_session_id(tmp_path: Path):
    store = SessionStore(db_path=tmp_path / "t.db")
    s = WorldState(session_id="s1", location="alpha")
    store.save(s)
    s.location = "beta"
    store.save(s)
    assert store.load("s1").location == "beta"
    assert len(store.list_sessions()) == 1


def test_list_sessions_returns_in_recency_order(tmp_path: Path):
    store = SessionStore(db_path=tmp_path / "t.db")
    store.save(WorldState(session_id="old"))
    store.save(WorldState(session_id="new"))
    ids = [r["session_id"] for r in store.list_sessions()]
    assert "old" in ids and "new" in ids


def test_list_sessions_includes_genre_and_beat_count(tmp_path: Path):
    from holodeck.world.state import Beat

    store = SessionStore(db_path=tmp_path / "t.db")
    state = WorldState(session_id="s1", genre="noir")
    state.beats.append(Beat(index=1, user_input="a", scene_prompt="..."))
    state.beats.append(Beat(index=2, user_input="b", scene_prompt="..."))
    store.save(state)

    rows = store.list_sessions()
    assert rows[0]["session_id"] == "s1"
    assert rows[0]["genre"] == "noir"
    assert rows[0]["beats"] == 2


def test_wal_mode_is_enabled(tmp_path: Path):
    import sqlite3

    db = tmp_path / "t.db"
    SessionStore(db_path=db)
    with sqlite3.connect(db) as c:
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
