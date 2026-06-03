import { startMic, playFrame } from "./audio.js";
import { renderComponent } from "./components.js";

const ws = new WebSocket(`ws://localhost:8000/ws/demo-user`);

function sendAction(selection) {
  ws.send(JSON.stringify({ type: "user_action", selection }));
}

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "ui_event") { renderComponent(msg.payload, sendAction); return; }
  const parts = msg.content?.parts || [];
  for (const part of parts) {
    const b64 = part.inlineData?.data;
    if (b64) playFrame(b64);
  }
};

ws.onopen = () => startMic((b64) => ws.send(JSON.stringify({ type: "audio", data: b64 })));
