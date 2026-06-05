import { startMic, playFrame, unlockAudio, isAgentSpeaking, closePlayback } from "./audio.js?v=4";
import { renderComponent } from "./components.js?v=2";

// The WebSocket is opened only when the user clicks "Start call" (below). The
// relay sends a (call_start) greeting trigger on connect, so connecting on page
// load would make the agent greet — and the AudioContext is still suspended then,
// so it would also be a gesture-less play. Connect on the gesture instead.
let ws = null;
let micStop = null;        // stop() handle for the active mic capture
let agentStarted = false;  // true once the agent produces its first output this call (see mic gate)

// Fully release the previous call: stop the mic and close the socket. Called
// before starting a new call and when a call ends, so repeated calls in one tab
// don't leave a stale mic feeding audio into the next session.
function teardown() {
  if (micStop) { try { micStop(); } catch (e) {} micStop = null; }
  if (ws) {
    try { ws.onmessage = null; ws.onclose = null; ws.close(); } catch (e) {}
    ws = null;
  }
  // Deliberately do NOT close the playback AudioContext here. ctx.close() kills
  // audio scheduled ahead of real time — that chopped the agent's goodbye on
  // session_end — and the close()/recreate churn intermittently hit the browser's
  // AudioContext limit so the next greeting never played. Keep one context per page
  // (reused, correct pitch); it's released on pagehide.
}

// Relay endpoint. Set by config.js (loaded before this module). The deploy
// script writes config.js with the deployed relay's wss URL; the committed
// default is ws://localhost:8000 for local dev.
const RELAY_URL =
  (typeof window !== "undefined" && window.RELAY_URL) || "ws://localhost:8000";

// The user_id is the cross-channel anchor: Generate a fresh one to start a new
// conversation, or paste one from another channel (chat <-> voice) to resume that
// same session. The session_id is resolved server-side from this user_id — the
// human only ever carries the id. NOT persisted: the field starts empty on every
// page load so each demo is stateless (a reload yields a blank field — Generate
// again, or paste an id to resume).
function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, (c) =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16),
  );
}

const userInput = document.getElementById("user-id");

function setUserId(id) {
  userInput.value = id || "";   // session-only; never persisted across reloads
}

function currentUserId() {
  return (userInput.value || "").trim();
}

// Field starts empty every load — no localStorage/URL seeding. Generate mints a
// fresh id; Paste resumes an existing one.
userInput.addEventListener("change", () => setUserId(currentUserId()));
document.getElementById("generate").onclick = () => setUserId(uuid());

// A tapped on-screen choice is a turn, but the model only transcribes *speech* —
// a click is never spoken, so without this it leaves no trace in the log. And the
// screen stays clickable for the ~1s until the agent's next render, so a second
// tap fires a duplicate turn. Echo the choice, then freeze the screen until the
// next render. (components.js passes the display label as the 2nd arg.)
let awaitingResponse = false;
function lockSelection() {
  awaitingResponse = true;
  const r = document.getElementById("ui-root");
  r.style.opacity = "0.55";          // visual "registered, working…" cue
  r.style.pointerEvents = "none";    // belt-and-suspenders vs. the flag
}
function unlockSelection() {
  awaitingResponse = false;
  const r = document.getElementById("ui-root");
  r.style.opacity = "";
  r.style.pointerEvents = "";
}

function sendAction(selection, label) {
  if (awaitingResponse) return;                          // a choice is already in flight — ignore re-taps
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (label) appendTranscript("user", label, true);      // show the tapped choice like a spoken turn
  lockSelection();                                       // freeze the screen so it can't be double-submitted
  ws.send(JSON.stringify({ type: "user_action", selection }));
}

// ---------------------------------------------------------------------------
// Transcript (chat log)
// ---------------------------------------------------------------------------

// One in-progress bubble per role; deltas append, a final chunk replaces + locks.
const curBubble = { user: null, agent: null };
let lastUserAt = 0; // performance.now() of the last user-transcript delta

function appendTranscript(role, text, final) {
  const log = document.getElementById("transcript");
  let bubble = curBubble[role];
  if (!bubble) {
    bubble = document.createElement("div");
    bubble.className = "bubble " + role;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = role === "agent" ? "AT&T" : "You";
    const body = document.createElement("span");
    body.className = "msg";
    bubble.append(who, body);
    log.append(bubble);
    curBubble[role] = bubble;
  }
  const body = bubble.querySelector(".msg");
  if (final) {
    body.textContent = text;   // cumulative full text — replace to avoid drift
    curBubble[role] = null;    // lock; the next utterance starts a fresh bubble
  } else {
    body.textContent += text;  // streaming delta
  }
  log.scrollTop = log.scrollHeight;
  if (role === "user") lastUserAt = performance.now();
}

// ---------------------------------------------------------------------------
// Speaking indicator
// ---------------------------------------------------------------------------

function startStatusLoop() {
  const pill = document.getElementById("status");
  setInterval(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      pill.textContent = "Idle";
      pill.className = "status idle";
    } else if (isAgentSpeaking()) {
      pill.textContent = "AT&T speaking";
      pill.className = "status agent";
    } else if (performance.now() - lastUserAt < 800) {
      pill.textContent = "You speaking";
      pill.className = "status user";
    } else {
      pill.textContent = "Listening";
      pill.className = "status listening";
    }
  }, 150);
}

function showRawComponent(payload) {
  const el = document.getElementById("raw-json");
  if (el) el.textContent = JSON.stringify(payload, null, 2);
}

// ---------------------------------------------------------------------------
// Message routing
// ---------------------------------------------------------------------------

function endCall() {
  const root = document.getElementById("ui-root");
  root.innerHTML = "";
  const p = document.createElement("p");
  p.textContent = "Call ended. Thank you for contacting AT&T.";
  root.append(p);
  curBubble.user = curBubble.agent = null;
  teardown();   // stop mic + close socket so the next call starts clean
  // Keep the user_id in the field so it can be reused or copied to another
  // channel; click Generate for a fresh identity to start a new conversation.
  const startBtn = document.getElementById("start");
  startBtn.disabled = false;
  startBtn.textContent = "Start call";
}

function handleMessage(e) {
  const msg = JSON.parse(e.data);
  if (msg.type === "session_info") {
    if (msg.resumed && msg.pending_ui) {                 // land back on the last screen
      showRawComponent(msg.pending_ui);
      unlockSelection();                                 // resumed screen is interactive
      renderComponent(msg.pending_ui, sendAction);
    }
    return;
  }
  if (msg.type === "session_end") { endCall(); return; }
  if (msg.type === "transcript") { agentStarted = true; appendTranscript(msg.role, msg.text, msg.final); return; }
  if (msg.type === "ui_event") {
    agentStarted = true;
    showRawComponent(msg.payload);                // raw response the customer can inspect
    unlockSelection();                            // next screen rendered → selection re-enabled
    renderComponent(msg.payload, sendAction);     // ...and how it renders
    return;
  }
  const parts = msg.content?.parts || [];
  for (const part of parts) {
    const b64 = part.inlineData?.data;
    if (b64) {
      agentStarted = true;                        // greeting/agent audio has begun → mic may send
      try {
        playFrame(b64);
      } catch (err) {
        console.error("[audio] playFrame failed:", err);
      }
    }
  }
}

// Audio playback (and mic) must start from a user gesture, or the browser keeps
// the AudioContext suspended and no model audio is heard.
const startBtn = document.getElementById("start");
startBtn.onclick = async () => {
  let userId = currentUserId();
  if (!userId) { userId = uuid(); setUserId(userId); }   // none chosen → fresh identity
  teardown();                                            // release any previous call first
  startBtn.disabled = true;
  document.getElementById("transcript").innerHTML = "";  // fresh log per call
  document.getElementById("raw-json").textContent = "";  // and a fresh JSON panel
  await unlockAudio();                                   // unlock playback within the gesture
  agentStarted = false;                                  // gate the mic until the greeting starts
  const socket = new WebSocket(`${RELAY_URL}/ws/${encodeURIComponent(userId)}`);
  ws = socket;
  // Opening frame must be first (before any mic audio). The session_id is resolved
  // server-side from user_id, so we just signal start.
  socket.onopen = () => socket.send(JSON.stringify({ type: "start" }));
  socket.onmessage = handleMessage;
  // Surface an unexpected drop (e.g. the engine erroring out before greeting) so
  // the user can just click Start again instead of reloading. teardown() nulls this
  // handler first, so it only fires for genuine failures, not our own closes.
  socket.onclose = () => {
    if (ws !== socket) return;
    ws = null;
    startBtn.disabled = false;
    startBtn.textContent = "Start call";
  };
  socket.onerror = () => { try { socket.close(); } catch (e) {} };
  micStop = await startMic((b64) => {
    // Half-duplex + startup gate: never send mic audio (a) before the agent's first
    // output this call (`agentStarted`) or (b) while the agent is speaking. (a) is
    // critical: streaming mic during the engine's busy greeting/setup phase overflows
    // its inbound queue (QueueFull -> 1011 "Reasoning Engine Execution failed", no
    // greeting). (b) stops the agent hearing itself through the speakers. Guard on the
    // captured `socket` so a torn-down call's mic can't send to a new one.
    if (
      socket.readyState === WebSocket.OPEN && ws === socket &&
      agentStarted && !isAgentSpeaking()
    ) {
      socket.send(JSON.stringify({ type: "audio", data: b64 }));
    }
  });
  startBtn.textContent = "Listening…";
};

startStatusLoop();

// Deterministically release the call on navigation/refresh: the browser drops the
// WS on unload eventually, but pagehide closes it (and stops the mic) immediately,
// so the relay sees the close right away and the next load starts clean.
window.addEventListener("pagehide", () => { teardown(); closePlayback(); });
