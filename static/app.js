const $ = (id) => document.getElementById(id);

let sessionId = localStorage.getItem("holodeck.session") || null;
let busy = false;
let currentStream = null;

async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

function setStatus(text) { $("status").textContent = text; }

function setBusy(b, stage) {
  busy = b;
  const loading = $("loading");
  loading.classList.toggle("hidden", !b);
  if (b && stage) loading.textContent = stage;
  $("turnBtn").disabled = b || !sessionId;
}

function renderState(state) {
  $("state").textContent = JSON.stringify(state, null, 2);
  $("turnBtn").disabled = busy || !state;
}

function showNarrationEarly(narration, scenePrompt) {
  // Narration arrives before the video. Show it immediately so the user has
  // *something* to read during the 5–30s diffusion wait.
  $("narration").textContent = narration || "";
  $("scenePrompt").textContent = scenePrompt || "";
}

function playBeat(beat) {
  const p = $("player");
  p.src = beat.video_url;
  p.load();
  p.play().catch(() => {});
  $("narration").textContent = beat.narration || "";
}

function closeStream() {
  if (currentStream) {
    currentStream.close();
    currentStream = null;
  }
}

function runTurnStreaming(userInput) {
  return new Promise((resolve, reject) => {
    if (!sessionId || !userInput.trim()) return resolve();
    closeStream();
    setBusy(true, "asking the director…");

    const url = `/api/turn/stream?session_id=${encodeURIComponent(sessionId)}`
      + `&user_input=${encodeURIComponent(userInput)}`;
    const es = new EventSource(url);
    currentStream = es;

    es.addEventListener("planning", () => setBusy(true, "asking the director…"));

    es.addEventListener("narration", (ev) => {
      const data = JSON.parse(ev.data);
      showNarrationEarly(data.narration, data.scene_prompt);
      renderState(data.state);
      setBusy(true, "rendering the shot…");
    });

    es.addEventListener("generating", (ev) => {
      const data = JSON.parse(ev.data);
      setBusy(true, `rendering with ${data.provider}…`);
    });

    es.addEventListener("beat", (ev) => {
      const data = JSON.parse(ev.data);
      playBeat(data.beat);
      renderState(data.state);
      $("input").value = "";
      if (data.synopsis_updated) setStatus("synopsis refreshed");
    });

    es.addEventListener("done", () => {
      setBusy(false);
      closeStream();
      resolve();
    });

    es.addEventListener("error", (ev) => {
      let msg = "stream error";
      try { msg = JSON.parse(ev.data).message; } catch {}
      setStatus(`error: ${msg}`);
      setBusy(false);
      closeStream();
      reject(new Error(msg));
    });

    es.onerror = () => {
      // Network-level EventSource error (separate from named "error" events).
      if (es.readyState === EventSource.CLOSED) {
        setBusy(false);
        closeStream();
        resolve();
      }
    };
  });
}

async function newStory() {
  const genre = $("genre").value.trim() || "open";
  const opening = $("opening").value.trim() || "The story begins.";
  setBusy(true, "creating session…");
  try {
    const state = await api("/session", {
      method: "POST",
      body: JSON.stringify({ genre, opening }),
    });
    sessionId = state.session_id;
    localStorage.setItem("holodeck.session", sessionId);
    setStatus(`session ${sessionId.slice(0, 8)} · ${state.genre}`);
    renderState(state);
    setBusy(false);
    // Kick the first beat automatically using the opening as user input.
    await runTurnStreaming(opening);
  } catch (e) {
    setStatus(`error: ${e.message}`);
    setBusy(false);
  }
}

async function bootstrap() {
  try {
    const h = await api("/health");
    setStatus(`video: ${h.video_provider} · director: ${h.director_model}`);
  } catch {
    setStatus("offline");
  }
  if (sessionId) {
    try {
      const state = await api(`/session/${sessionId}`);
      setStatus(`resumed ${sessionId.slice(0, 8)} · ${state.genre}`);
      renderState(state);
      const last = state.beats[state.beats.length - 1];
      if (last) playBeat(last);
    } catch {
      localStorage.removeItem("holodeck.session");
      sessionId = null;
    }
  }
}

$("newBtn").addEventListener("click", newStory);
$("turnBtn").addEventListener("click", () => runTurnStreaming($("input").value));
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !busy) runTurnStreaming(e.target.value);
});

bootstrap();
