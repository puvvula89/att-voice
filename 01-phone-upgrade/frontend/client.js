import { startMic, playFrame, unlockAudio, isAgentSpeaking } from "./audio.js";
import { renderComponent } from "./components.js";

// The WebSocket is opened only when the user clicks "Start call" (below). The
// relay sends a (call_start) greeting trigger on connect, so connecting on page
// load would make the agent greet — and the AudioContext is still suspended then,
// so it would also be a gesture-less play. Connect on the gesture instead.
let ws = null;

function sendAction(selection) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "user_action", selection }));
  }
}

function endCall() {
  const root = document.getElementById("ui-root");
  root.innerHTML = "";
  const p = document.createElement("p");
  p.textContent = "Call ended. Thank you for contacting AT&T.";
  root.append(p);
  const startBtn = document.getElementById("start");
  startBtn.disabled = false;
  startBtn.textContent = "Start call";
}

function handleMessage(e) {
  const msg = JSON.parse(e.data);
  if (msg.type === "session_end") { endCall(); return; }
  if (msg.type === "ui_event") { renderComponent(msg.payload, sendAction); return; }
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
  await unlockAudio();                                   // unlock playback within the gesture
  ws = new WebSocket(`ws://localhost:8000/ws/demo-user`); // connect → relay greets now
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
