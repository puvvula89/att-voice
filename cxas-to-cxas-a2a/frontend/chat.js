import { renderComponent } from "./components.js?v=2";
import {
  startMic,
  playFrame,
  unlockAudio,
  flushPlayback,
  closePlayback,
  isAgentSpeaking,
} from "./audio.js";

// Unified CXAS client: ONE session, either modality.
//
// Unlike the ADK bundle (separate voice page + chat page, separate sessions),
// there is a single connection here carrying both typed and spoken turns. The
// relay holds one CXAS bidirectional session whose `session` never changes, so
// the user can tap the mic, talk, then type — and it stays one conversation.
//
// The identity anchor is the CXAS **session id** (CXAS sessions are scoped to an
// app and keyed by session id; there is no cross-app user_id store like ADK's).
let ws = null;
let stopMic = null; // non-null while the mic is live

// Voice mode LATCHES. The moment the user first turns the mic on, the
// conversation becomes a spoken one and every later agent reply is played —
// even for turns the user chooses to type. A user who never touches the mic
// stays in a silent, text-only conversation. Reset only on a new session.
let voiceMode = false;

function micLive() {
  return stopMic !== null;
}

function teardown() {
  agentBody = null;
  voiceMode = false;   // a fresh session starts text-only until the mic is used
  if (stopMic) { try { stopMic(); } catch (e) {} stopMic = null; }
  closePlayback();
  if (ws) {
    try { ws.onmessage = null; ws.onclose = null; ws.close(); } catch (e) {}
    ws = null;
  }
}

const RELAY_URL =
  (typeof window !== "undefined" && window.RELAY_URL) || "ws://localhost:8000";

// ---------------------------------------------------------------------------
// Identity — the CXAS session id
// ---------------------------------------------------------------------------
function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, (c) =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16),
  );
}

const userInput = document.getElementById("user-id");

function setSessionId(id) {
  userInput.value = id || "";
}
function currentSessionId() {
  return (userInput.value || "").trim();
}
userInput.addEventListener("change", () => setSessionId(currentSessionId()));
document.getElementById("generate").onclick = () => setSessionId(uuid());

// ---------------------------------------------------------------------------
// Transcript
// ---------------------------------------------------------------------------
function appendTranscript(role, text) {
  const log = document.getElementById("transcript");
  const bubble = document.createElement("div");
  bubble.className = "bubble " + role;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = role === "agent" ? "AT&T" : "You";
  const body = document.createElement("span");
  body.className = "msg";
  body.textContent = text;
  bubble.append(who, body);
  log.append(bubble);
  log.scrollTop = log.scrollHeight;
  return body;
}

// CXAS streams the agent's reply as text fragments across many messages, so a
// turn is accumulated into ONE bubble and closed on turn_complete. Without this
// a single sentence would render as a dozen separate bubbles.
let agentBody = null;

function appendAgentDelta(text) {
  const log = document.getElementById("transcript");
  if (!agentBody) agentBody = appendTranscript("agent", "");
  agentBody.textContent += text;
  log.scrollTop = log.scrollHeight;
}

function closeAgentTurn() {
  // Drop an empty bubble (audio-only turn with no text).
  if (agentBody && !agentBody.textContent.trim()) {
    const b = agentBody.parentElement;
    if (b && b.parentElement) b.parentElement.removeChild(b);
  }
  agentBody = null;
}

function setStatus(label, cls) {
  const pill = document.getElementById("status");
  pill.textContent = label;
  pill.className = "status " + cls;
}

function showRawComponent(payload) {
  const el = document.getElementById("raw-json");
  if (el) el.textContent = JSON.stringify(payload, null, 2);
}

// ---------------------------------------------------------------------------
// On-screen choices (same one-shot semantics as the ADK chat client)
// ---------------------------------------------------------------------------
let awaitingResponse = false;
const uiRoot = () => document.getElementById("ui-root");

function lockSelection() {
  awaitingResponse = true;
  const r = uiRoot();
  r.style.opacity = "0.55";
  r.style.pointerEvents = "none";
}
function unlockSelection() {
  awaitingResponse = false;
  const r = uiRoot();
  r.style.opacity = "";
  r.style.pointerEvents = "";
}

function sendAction(selection, label) {
  if (awaitingResponse) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  closeAgentTurn();
  appendTranscript("user", label || selection);
  lockSelection();
  setStatus("AT&T is responding…", "agent");
  // A tapped choice is just a text turn on the same session.
  ws.send(JSON.stringify({ type: "user_message", text: selection }));
}

// ---------------------------------------------------------------------------
// Message routing
// ---------------------------------------------------------------------------
function endChat() {
  const root = document.getElementById("ui-root");
  root.innerHTML = "";
  const p = document.createElement("p");
  p.textContent = "Conversation ended. Thank you for contacting AT&T.";
  root.append(p);
  composerEnabled(false);
  teardown();
  const startBtn = document.getElementById("start");
  startBtn.disabled = false;
  startBtn.textContent = "Start";
  setStatus("Idle", "idle");
}

function handleMessage(e) {
  const msg = JSON.parse(e.data);

  if (msg.type === "session_info") {
    if (msg.session_id) setSessionId(msg.session_id);
    if (msg.resumed && msg.pending_ui) {
      showRawComponent(msg.pending_ui);
      unlockSelection();
      renderComponent(msg.pending_ui, sendAction);
    }
    return;
  }
  if (msg.type === "session_end") { endChat(); return; }

  // Agent speech. CXAS synthesizes audio for every turn, including typed ones —
  // we play it once the conversation has become a spoken one (see voiceMode).
  if (msg.type === "audio") {
    if (voiceMode) playFrame(msg.data);
    return;
  }

  // Barge-in: the user talked over the agent — drop queued audio immediately.
  if (msg.type === "interrupted") { flushPlayback(); return; }

  // Streamed fragment of the agent's reply.
  if (msg.type === "agent_delta") {
    appendAgentDelta(msg.text);
    return;
  }

  if (msg.type === "turn_complete") {
    closeAgentTurn();
    setStatus(
      micLive() ? "Listening…" : voiceMode ? "Voice on · type or talk" : "Connected",
      "listening",
    );
    return;
  }
  if (msg.type === "transcript") {
    if (msg.text && msg.text.trim()) {
      if (msg.role === "agent") { appendAgentDelta(msg.text); closeAgentTurn(); }
      else appendTranscript(msg.role, msg.text);
    }
    return;
  }
  if (msg.type === "ui_event") {
    showRawComponent(msg.payload);
    unlockSelection();
    setStatus("Connected", "listening");
    renderComponent(msg.payload, sendAction);
    return;
  }
  if (msg.type === "error") {
    appendTranscript("agent", msg.text || "Something went wrong.");
    return;
  }
}

// ---------------------------------------------------------------------------
// Composer: text + mic, both on the same socket/session
// ---------------------------------------------------------------------------
const msgInput = document.getElementById("msg");
const sendBtn = document.getElementById("send");
const micBtn = document.getElementById("mic");

function composerEnabled(on) {
  msgInput.disabled = !on;
  sendBtn.disabled = !on;
  micBtn.disabled = !on;
  if (on) msgInput.focus();
}

function sendMessage() {
  const text = (msgInput.value || "").trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  closeAgentTurn();
  appendTranscript("user", text);
  flushPlayback();   // typing over the agent cuts it off, same as speaking would
  ws.send(JSON.stringify({ type: "user_message", text }));
  msgInput.value = "";
  setStatus("AT&T is responding…", "agent");
}

sendBtn.onclick = sendMessage;
msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); sendMessage(); }
});

// Mic toggle. Frames are gated while the agent is speaking (half-duplex) so the
// model never hears itself through the speakers; CXAS's own barge-in still
// applies once playback drains.
async function toggleMic() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  if (micLive()) {
    try { stopMic(); } catch (e) {}
    stopMic = null;
    micBtn.classList.remove("live");
    micBtn.title = "Talk";
    // voiceMode intentionally NOT cleared — replies stay spoken.
    setStatus("Voice on · type or talk", "listening");
    return;
  }

  await unlockAudio();   // must happen in the click handler or playback is silent
  try {
    stopMic = await startMic((b64) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (isAgentSpeaking()) return;                 // half-duplex gate
      ws.send(JSON.stringify({ type: "audio", data: b64 }));
    });
    voiceMode = true;            // latched: replies are spoken from here on
    micBtn.classList.add("live");
    micBtn.title = "Stop talking";
    setStatus("Listening…", "listening");
  } catch (err) {
    appendTranscript("agent", "Microphone unavailable — you can still type.");
    setStatus("Connected", "listening");
  }
}

micBtn.onclick = toggleMic;

const startBtn = document.getElementById("start");
startBtn.onclick = async () => {
  let sessionId = currentSessionId();
  if (!sessionId) { sessionId = uuid(); setSessionId(sessionId); }
  teardown();
  startBtn.disabled = true;
  document.getElementById("transcript").innerHTML = "";
  document.getElementById("raw-json").textContent = "";
  setStatus("Connecting…", "agent");

  await unlockAudio();   // Start is a user gesture — unlock playback here too

  ws = new WebSocket(`${RELAY_URL}/session/${encodeURIComponent(sessionId)}`);
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "start" }));
    composerEnabled(true);
    setStatus("Connected", "listening");
    startBtn.textContent = "Connected";
  };
  ws.onmessage = handleMessage;
  // The button keeps saying "Connected" unless we reset it here, so a socket
  // that opened and then died leaves the page claiming it is connected while
  // every control is greyed out — the UI contradicting itself.
  ws.onclose = () => {
    composerEnabled(false);
    setStatus("Idle", "idle");
    startBtn.disabled = false;
    startBtn.textContent = "Start";
  };
  ws.onerror = () => setStatus("Idle", "idle");
};

window.addEventListener("pagehide", teardown);
