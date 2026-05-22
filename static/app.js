const $ = (id) => document.getElementById(id);

let sessionId = localStorage.getItem("holodeck.session") || null;
let busy = false;

async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

function setStatus(text) { $("status").textContent = text; }
function setBusy(b) {
  busy = b;
  $("loading").classList.toggle("hidden", !b);
  $("turnBtn").disabled = b || !sessionId;
}

function renderState(state) {
  $("state").textContent = JSON.stringify(state, null, 2);
  $("turnBtn").disabled = busy || !state;
}

function playBeat(beat) {
  const p = $("player");
  p.src = beat.video_url;
  p.load();
  p.play().catch(() => {});
  $("narration").textContent = beat.narration || "";
}

async function newStory() {
  const genre = $("genre").value.trim() || "open";
  const opening = $("opening").value.trim() || "The story begins.";
  setBusy(true);
  try {
    const state = await api("/session", {
      method: "POST",
      body: JSON.stringify({ genre, opening }),
    });
    sessionId = state.session_id;
    localStorage.setItem("holodeck.session", sessionId);
    setStatus(`session ${sessionId.slice(0, 8)} · ${state.genre}`);
    renderState(state);
    // Kick the first beat automatically using the opening as user input.
    await runTurn(opening);
  } catch (e) {
    setStatus(`error: ${e.message}`);
  } finally {
    setBusy(false);
  }
}

async function runTurn(userInput) {
  if (!sessionId || !userInput.trim()) return;
  setBusy(true);
  try {
    const { beat, state } = await api("/turn", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, user_input: userInput }),
    });
    playBeat(beat);
    renderState(state);
    $("input").value = "";
  } catch (e) {
    setStatus(`error: ${e.message}`);
  } finally {
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
$("turnBtn").addEventListener("click", () => runTurn($("input").value));
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !busy) runTurn(e.target.value);
});

bootstrap();
