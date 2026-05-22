# Holodeck

LLM agent + video diffusion = infinite interactive story engine.

The loop:

```
user input ─┐
            ▼
      Director (Claude)        ←─ world state, history, character bible
            │
            ▼
   next-scene prompt
            │
            ▼
  Video Provider (Veo / Sora / Runway / Mock)
            │
            ▼
       5s clip ──► browser ──► user input ──► ...
```

## Quick start

```bash
cd holodeck
uv sync                       # or: pip install -e .
cp .env.example .env          # leave keys blank to use the mock provider
uv run uvicorn holodeck.main:app --reload
open http://localhost:8000
```

The mock video provider returns a placeholder clip so the full loop runs without
any API keys. Plug a real provider in by setting `VIDEO_PROVIDER=veo` (or `sora`,
`runway`) and the corresponding key in `.env`.

## Layout

| Path | Role |
|---|---|
| `src/holodeck/agents/director.py` | LLM that turns world state + user input into the next scene prompt |
| `src/holodeck/world/state.py` | `WorldState` — characters, location, beat history |
| `src/holodeck/video/base.py` | `VideoProvider` interface; one impl per backend |
| `src/holodeck/storage/sessions.py` | SQLite-backed session persistence |
| `src/holodeck/api/routes.py` | FastAPI endpoints powering the web UI |
| `static/` | Vanilla JS playback + input UI |

## Next steps (not built yet)

- Last-frame extraction for visual continuity (image-to-video conditioning)
- Character reference images injected into every shot
- Streaming video playback while the next clip is generating
- Branching / save-state UI

See inline `TODO` notes in each module.
