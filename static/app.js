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
  $("exportBtn").disabled = b || !sessionId;
}

function renderState(state) {
  $("state").textContent = JSON.stringify(state, null, 2);
  $("turnBtn").disabled = busy || !state;
  $("exportBtn").disabled = busy || !state || !state.beats || state.beats.length === 0;
}

function showNarrationEarly(narration, scenePrompt, hit) {
  $("narration").textContent = narration || "";
  $("scenePrompt").textContent = scenePrompt || "";
  if (hit) setStatus("⚡ speculation hit — instant beat");
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

async function refreshSessionPicker() {
  try {
    const rows = await api("/sessions");
    const picker = $("sessionPicker");
    picker.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = `↩ resume… (${rows.length})`;
    picker.appendChild(placeholder);
    for (const row of rows) {
      const opt = document.createElement("option");
      opt.value = row.session_id;
      const ts = (row.updated_at || "").replace("T", " ").slice(0, 16);
      opt.textContent = `${row.session_id.slice(0, 8)} · ${row.genre} · ${row.beats}b · ${ts}`;
      if (row.session_id === sessionId) opt.selected = true;
      picker.appendChild(opt);
    }
  } catch (e) {
    /* picker is non-critical; ignore */
  }
}

async function selectSession(id) {
  if (!id || id === sessionId) return;
  try {
    const state = await api(`/session/${id}`);
    sessionId = id;
    localStorage.setItem("holodeck.session", id);
    setStatus(`resumed ${id.slice(0, 8)} · ${state.genre}`);
    renderState(state);
    const last = state.beats[state.beats.length - 1];
    if (last) playBeat(last);
  } catch (e) {
    setStatus(`error: ${e.message}`);
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
      showNarrationEarly(data.narration, data.scene_prompt, data.speculation_hit);
      renderState(data.state);
      setBusy(true, data.speculation_hit ? "playing pre-rendered beat…" : "rendering the shot…");
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
      refreshSessionPicker();
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
    refreshSessionPicker();
    await runTurnStreaming(opening);
  } catch (e) {
    setStatus(`error: ${e.message}`);
    setBusy(false);
  }
}

function exportMp4() {
  if (!sessionId) return;
  // Triggers the browser's download flow against /api/session/{id}/export.
  window.location.href = `/api/session/${sessionId}/export`;
}

async function bootstrap() {
  try {
    const h = await api("/health");
    setStatus(`video: ${h.video_provider} · director: ${h.director_model}`
      + (h.speculative_pregen ? " · spec✓" : ""));
  } catch {
    setStatus("offline");
  }
  refreshSessionPicker();
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
$("exportBtn").addEventListener("click", exportMp4);
$("sessionPicker").addEventListener("change", (e) => selectSession(e.target.value));
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !busy) runTurnStreaming(e.target.value);
});

bootstrap();
