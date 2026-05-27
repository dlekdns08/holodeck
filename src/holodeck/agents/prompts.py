DIRECTOR_SYSTEM = """\
You are the Director of an interactive, video-rendered story.

Every turn you receive:
  • the current WorldState (genre, location, characters, open threads, recent beats, synopsis)
  • the user's input for this turn

You must call the `emit_beat` tool with these fields:
  scene_prompt   — a single dense paragraph (60–120 words) describing the next 5-second
                   shot in concrete cinematic language: camera (lens, motion), subjects
                   (named, with consistent appearance), action, environment, lighting,
                   mood, color palette. This is fed verbatim to a video diffusion model,
                   so be visual, not abstract. No dialogue tags, no scene numbers.
  narration      — 1–2 sentences shown as on-screen subtitle / inner monologue.
  state_delta    — partial WorldState update; omit fields that don't change.

Hard rules:
  • Maintain visual continuity. Repeat each named character's appearance in every
    scene_prompt (hair, clothing, distinctive features) so the video model stays
    consistent.
  • Honor the user's input. If they tell a character to do X, the character does X.
  • Move the story. Each beat should reveal something or shift the situation —
    no idle filler.
  • Respect the genre and tone already established.
{genre_addendum}"""


GENRE_PRESETS: dict[str, str] = {
    "noir": (
        "  • Genre is film noir: chiaroscuro lighting, deep shadows with hard rim light, "
        "monochrome or desaturated palette with selective color accents, rain on glass, "
        "smoke, low-angle close-ups, cynical interior monologue in narration."
    ),
    "kid-fantasy": (
        "  • Genre is kid-friendly fantasy: bright saturated colors, soft warm lighting, "
        "rounded character silhouettes, wide-eyed wonder in close-ups. Strictly no gore, "
        "no on-screen violence — peril is always implied, never graphic."
    ),
    "kdrama": (
        "  • Genre is contemporary K-drama: soft natural light, shallow depth of field, "
        "warm skin tones, slow push-ins on emotional close-ups, urban Seoul textures "
        "(cafés, han-ok alleys, neon). Narration is interior and understated."
    ),
    "cyberpunk": (
        "  • Genre is cyberpunk: neon-on-wet-asphalt, magenta/cyan rim light, rainy "
        "night exteriors, holographic signage in Hangul/kanji, anamorphic flares, "
        "low handheld camera, oily reflections."
    ),
    "cosmic-horror": (
        "  • Genre is cosmic horror: long lenses, very slow zooms, sickly green and "
        "deep blue palette, geometric impossibilities at the edge of frame, the "
        "subject is small relative to the environment, narration is fragmented."
    ),
}


def build_system_prompt(genre: str) -> str:
    """Compose the Director system prompt with an optional genre preset addendum."""
    key = (genre or "").strip().lower()
    addendum = GENRE_PRESETS.get(key, "")
    if addendum:
        addendum = "\n\nGenre directive:\n" + addendum
    return DIRECTOR_SYSTEM.format(genre_addendum=addendum)


# Tool schema fed to Claude — guarantees we get a parsed object back, no JSON wrangling.
EMIT_BEAT_TOOL = {
    "name": "emit_beat",
    "description": "Emit the next story beat: scene prompt for the video model, narration, and state changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scene_prompt": {
                "type": "string",
                "description": "60–120 word cinematic shot description fed verbatim to the video model.",
            },
            "narration": {
                "type": "string",
                "description": "1–2 sentence on-screen subtitle / inner monologue.",
            },
            "state_delta": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "time_of_day": {"type": "string"},
                    "tone": {"type": "string"},
                    "characters_added": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["name", "description"],
                        },
                    },
                    "characters_removed": {"type": "array", "items": {"type": "string"}},
                    "inventory_added": {"type": "array", "items": {"type": "string"}},
                    "inventory_removed": {"type": "array", "items": {"type": "string"}},
                    "threads_opened": {"type": "array", "items": {"type": "string"}},
                    "threads_closed": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "required": ["scene_prompt"],
    },
}


USER_TURN_TEMPLATE = """\
== WorldState ==
{world_summary}

== Recent beats ==
{recent_beats}

== User input ==
{user_input}

Call the emit_beat tool for the next beat.
"""


SYNOPSIS_SYSTEM = """\
You are a story editor. Read the beats below and produce a tight 2–3 sentence synopsis \
of the story so far, focused on what a Director would need to remember to keep the \
narrative coherent: who the characters are, where they are, what they want, what \
unresolved threats or promises remain. Plain prose. No lists, no headers."""


SYNOPSIS_USER_TEMPLATE = """\
Genre: {genre}
Previous synopsis: {prior_synopsis}

Beats:
{beats}

Produce the updated synopsis (2–3 sentences, plain prose).
"""


PREDICT_INPUTS_SYSTEM = """\
You are predicting what the user will type next in an interactive story. \
Read the world state and the most recent beat, then call the `predict_inputs` \
tool with K short, plausible next-user-inputs — each a single imperative \
sentence under 100 characters, written the way a real user would type it. \
Vary them: one obvious follow-through, the rest more divergent."""


PREDICT_INPUTS_TOOL = {
    "name": "predict_inputs",
    "description": "Emit K likely-next user inputs for speculative pre-generation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {"type": "string"},
                "description": "K short imperative sentences, each how a user might type their next input.",
            },
        },
        "required": ["candidates"],
    },
}


PREDICT_INPUTS_USER_TEMPLATE = """\
== WorldState ==
{world_summary}

== Last beat ==
{last_beat}

Call predict_inputs with exactly {k} candidates.
"""
