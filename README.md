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

## What's wired up

- **Last-frame extraction** — every clip's final frame is pulled with ffmpeg
  (`/cache/frames/…`) and fed to the next call as `last_frame_url` for
  image-to-video continuity. Mock and Runway providers both participate.
- **Director via `tool_use`** — Claude returns a typed `emit_beat` tool call
  instead of free-form JSON, so parsing can't fail. Auto-retries once if the
  tool input fails local validation.
- **Prompt caching** — the system prompt and `emit_beat` tool schema are
  marked `cache_control: ephemeral`, so turns 2+ in a session hit Anthropic's
  prompt cache.
- **Rolling synopsis memory** — every 6 beats the Director summarizes the story
  so far into `WorldState.synopsis`, which is injected back into the system
  prompt. The 4-beat window no longer caps long-run coherence.
- **Genre presets** — `noir / kid-fantasy / kdrama / cyberpunk / cosmic-horror`
  add a tone-specific directive to the system prompt.
- **SSE turn endpoint** (`GET /api/turn/stream`) — emits `planning → narration
  → generating → beat → done` so the UI can show narration and the scene prompt
  immediately, before the 5–30s diffusion wait. Sends `: keepalive` comments
  every 10s during long awaits so proxies don't drop the connection.
- **Speculative pre-generation** — `SPECULATIVE_PREGEN_ENABLED=true` makes the
  Director predict K likely-next user inputs after each beat and render them
  in the background; a matching real input plays instantly.
- **Session picker** — `/api/sessions` now returns `{session_id, genre, beats,
  updated_at}`; the header dropdown resumes any prior session.
- **mp4 export** — `GET /api/session/{id}/export` stitches the session's beats
  into a single h264/aac mp4 via ffmpeg concat (re-encodes to normalize mixed
  sources). The UI exposes an Export button.
- **Session locks + SQLite WAL** — concurrent `/turn` calls on the same session
  serialize cleanly; readers and writers don't block each other.
- **Test suite** — `pytest -q` covers state mutation, the stub Director, genre
  presets, synopsis triggering, storage round-trips, and the speculation cache.

## Next steps (not built yet)

- Character reference images injected into every shot
  (the `Character.reference_image_url` field is wired through but not populated)
- Branching / save-state UI on top of the linear beat list
- Wire up Veo and Sora providers (Runway is functional; the other two are stubs)

See inline `TODO` notes in each module.
