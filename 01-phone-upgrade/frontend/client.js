import { startMic, playFrame, unlockAudio } from "./audio.js";
import { renderComponent } from "./components.js";

const ws = new WebSocket(`ws://localhost:8000/ws/demo-user`);

function sendAction(selection) {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "user_action", selection }));
  }
}

let _audioChunks = 0;

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "ui_event") { renderComponent(msg.payload, sendAction); return; }
  const parts = msg.content?.parts || [];
  for (const part of parts) {
    const b64 = part.inlineData?.data;
    if (b64) {
      _audioChunks++;
      if (_audioChunks === 1) console.log("[audio] first chunk received from server");
      try {
        playFrame(b64);
      } catch (err) {
        console.error("[audio] playFrame threw:", err);
      }
    }
  }
};

// Audio playback (and mic) must start from a user gesture, or the browser keeps
// the AudioContext suspended and no model audio is heard.
const startBtn = document.getElementById("start");
startBtn.onclick = async () => {
  startBtn.disabled = true;
  await unlockAudio();
  await startMic((b64) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "audio", data: b64 }));
    }
  });
  startBtn.textContent = "Listening…";
};
