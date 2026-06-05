import { renderComponent } from "./components.js";

// Chat counterpart to client.js. Same identity anchor (user_id) and same Screen
// components — only the transport (text over WS to the relay's /chat path) and the
// lack of audio differ. The relay proxies each turn to the chat Agent Engine's
// async_stream_query; resume across channels happens server-side by user_id.
let ws = null;

const RELAY_URL =
  (typeof window !== "undefined" && window.RELAY_URL) || "ws://localhost:8000";

// ---------------------------------------------------------------------------
// Identity (the cross-channel handoff token) — mirrors client.js
// ---------------------------------------------------------------------------
const USER_KEY = "pu_user_id";

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, (c) =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16),
  );
}

const userInput = document.getElementById("user-id");

function setUserId(id) {
  userInput.value = id || "";
  if (id) localStorage.setItem(USER_KEY, id);
}
function currentUserId() {
  return (userInput.value || "").trim();
}
(function initUserId() {
  const fromUrl = new URLSearchParams(location.search).get("uid");
  setUserId(fromUrl || localStorage.getItem(USER_KEY) || "");
})();
userInput.addEventListener("change", () => setUserId(currentUserId()));
document.getElementById("generate").onclick = () => setUserId(uuid());

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

function sendAction(selection) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "user_action", selection }));
  }
}

// ---------------------------------------------------------------------------
// Message routing
// ---------------------------------------------------------------------------
function endChat() {
  const root = document.getElementById("ui-root");
  root.innerHTML = "";
  const p = document.createElement("p");
  p.textContent = "Chat ended. Thank you for contacting AT&T.";
  root.append(p);
  composerEnabled(false);
  const startBtn = document.getElementById("start");
  startBtn.disabled = false;
  startBtn.textContent = "Start chat";
  setStatus("Idle", "idle");
}

function handleMessage(e) {
  const msg = JSON.parse(e.data);
  if (msg.type === "session_info") {
    if (msg.resumed && msg.pending_ui) {       // land back on the last screen
      showRawComponent(msg.pending_ui);
      renderComponent(msg.pending_ui, sendAction);
    }
    return;
  }
  if (msg.type === "session_end") { endChat(); return; }
  if (msg.type === "transcript") {
    if (msg.text && msg.text.trim()) appendTranscript(msg.role, msg.text);
    return;
  }
  if (msg.type === "ui_event") {
    showRawComponent(msg.payload);
    renderComponent(msg.payload, sendAction);
    return;
  }
}

// ---------------------------------------------------------------------------
// Composer + connection
// ---------------------------------------------------------------------------
const msgInput = document.getElementById("msg");
const sendBtn = document.getElementById("send");

function composerEnabled(on) {
  msgInput.disabled = !on;
  sendBtn.disabled = !on;
  if (on) msgInput.focus();
}

function sendMessage() {
  const text = (msgInput.value || "").trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  appendTranscript("user", text);            // echo locally
  ws.send(JSON.stringify({ type: "user_message", text }));
  msgInput.value = "";
}

sendBtn.onclick = sendMessage;
msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); sendMessage(); }
});

const startBtn = document.getElementById("start");
startBtn.onclick = () => {
  let userId = currentUserId();
  if (!userId) { userId = uuid(); setUserId(userId); }   // none chosen → fresh identity
  startBtn.disabled = true;
  document.getElementById("transcript").innerHTML = "";
  document.getElementById("raw-json").textContent = "";
  setStatus("Connecting…", "agent");
  ws = new WebSocket(`${RELAY_URL}/chat/${encodeURIComponent(userId)}`);
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "start" }));   // opening frame → greet / welcome-back
    composerEnabled(true);
    setStatus("Connected", "listening");
    startBtn.textContent = "Connected";
  };
  ws.onmessage = handleMessage;
  ws.onclose = () => { composerEnabled(false); setStatus("Idle", "idle"); };
  ws.onerror = () => setStatus("Idle", "idle");
};
