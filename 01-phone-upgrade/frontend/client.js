import { startMic, playFrame, unlockAudio, isAgentSpeaking } from "./audio.js";
import { renderComponent } from "./components.js";

// The WebSocket is opened only when the user clicks "Start call" (below). The
// relay sends a (call_start) greeting trigger on connect, so connecting on page
// load would make the agent greet — and the AudioContext is still suspended then,
// so it would also be a gesture-less play. Connect on the gesture instead.
let ws = null;

// Relay endpoint. Set by config.js (loaded before this module). The deploy
// script writes config.js with the deployed relay's wss URL; the committed
// default is ws://localhost:8000 for local dev.
const RELAY_URL =
  (typeof window !== "undefined" && window.RELAY_URL) || "ws://localhost:8000";

// Persisted across reloads/reconnects so an interrupted call resumes where it
// left off (cleared once a call ends — see endCall). The relay/agent resume this
// session_id if it still exists, else start fresh and return a new one.
const SESSION_KEY = "pu_session_id";

function sendAction(selection) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "user_action", selection }));
  }
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
  localStorage.removeItem(SESSION_KEY); // call finished — next call starts fresh
  const startBtn = document.getElementById("start");
  startBtn.disabled = false;
  startBtn.textContent = "Start call";
}

function handleMessage(e) {
  const msg = JSON.parse(e.data);
  if (msg.type === "session_info") {
    localStorage.setItem(SESSION_KEY, msg.session_id);   // persist for reconnect
    if (msg.resumed && msg.pending_ui) {                 // land back on the last screen
      showRawComponent(msg.pending_ui);
      renderComponent(msg.pending_ui, sendAction);
    }
    return;
  }
  if (msg.type === "session_end") { endCall(); return; }
  if (msg.type === "transcript") { appendTranscript(msg.role, msg.text, msg.final); return; }
  if (msg.type === "ui_event") {
    showRawComponent(msg.payload);                // raw response the customer can inspect
    renderComponent(msg.payload, sendAction);     // ...and how it renders
    return;
  }
  const parts = msg.content?.parts || [];
  for (const part of parts) {
    const b64 = part.inlineData?.data;
    if (b64) {
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
  startBtn.disabled = true;
  document.getElementById("transcript").innerHTML = "";  // fresh log per call
  document.getElementById("raw-json").textContent = "";  // and a fresh JSON panel
  await unlockAudio();                                   // unlock playback within the gesture
  ws = new WebSocket(`${RELAY_URL}/ws/demo-user`);
  // Opening frame: resume the stored session_id (or null → fresh). Must be the
  // first frame, so send it on open before any mic audio goes out.
  ws.onopen = () =>
    ws.send(JSON.stringify({ type: "start", session_id: localStorage.getItem(SESSION_KEY) }));
  ws.onmessage = handleMessage;
  await startMic((b64) => {
    // Half-duplex: don't send mic audio while the agent is speaking, or it hears
    // itself through the speakers and advances without your input.
    if (ws && ws.readyState === WebSocket.OPEN && !isAgentSpeaking()) {
      ws.send(JSON.stringify({ type: "audio", data: b64 }));
    }
  });
  startBtn.textContent = "Listening…";
};

startStatusLoop();
