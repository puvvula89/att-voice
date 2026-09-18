/* Live console: tails the bridge's event stream and draws one row per utterance.

   A row is a crossing. The source card sits in the speaker's lane, the translation
   in the other lane, and the centre column carries how long the crossing took plus
   the hop breakdown that makes it up. */

const HOPS = [
  { key: "send_ms", label: "Send buffer" },
  { key: "ttfa_ms", label: "Model" },
  { key: "first_send_ms", label: "Forward" },
];

// Lightness steps within each direction's hue: hue says who, lightness says stage.
const SHADES = {
  "caller-to-agent": ["--caller-1", "--caller-2", "--caller-3"],
  "agent-to-caller": ["--agent-1", "--agent-2", "--agent-3"],
};

const els = {
  conv: document.getElementById("conv"),
  count: document.getElementById("count"),
  median: document.getElementById("median"),
  last: document.getElementById("last"),
  status: document.getElementById("status"),
  rows: document.getElementById("rows"),
  lanes: document.getElementById("lanes"),
  empty: document.getElementById("empty"),
  dash: document.getElementById("dash-link"),
};

let conv = null;
const utterances = new Map(); // "direction/n" -> utterance

const clock = (ts) => {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
};

const secs = (ms) => (ms == null ? "—" : `${(ms / 1000).toFixed(2)}s`);

function setStatus(state, text) {
  els.status.dataset.state = state;
  els.status.textContent = text;
}

function reset(next) {
  conv = next;
  utterances.clear();
  els.rows.replaceChildren();
  els.conv.textContent = next || "waiting";
  els.dash.href = next ? `dashboard?conv=${encodeURIComponent(next)}` : "dashboard";
  render();
}

function apply(e) {
  // Calls recorded before the end-of-call row was re-keyed carry `n` instead.
  const n = e.utterance ?? e.n;
  if (n == null) return;
  const id = `${e.direction}/${n}`;
  let u = utterances.get(id);
  if (!u) {
    u = { id, direction: e.direction, n, order: utterances.size };
    utterances.set(id, u);
  }
  if (e.event === "speech_onset") u.onset_ts = e.ts;
  if (e.event === "transcript") {
    const key = e.kind === "input" ? "source" : "translation";
    u[key] = (u[key] || "") + (e.text || "");
    if (key === "translation" && u.arrival_ts == null) u.text_ts = e.ts;
  }
  for (const { key } of HOPS) if (e[key] != null) u[key] = e[key];
  if (u.onset_ts && u.first_send_ms != null) {
    u.arrival_ts = u.onset_ts + u.first_send_ms / 1000;
  }
}

/* Each hop's own duration: the stamps are cumulative from speech onset. */
function segments(u) {
  const out = [];
  let prev = 0;
  for (const { key, label } of HOPS) {
    if (u[key] == null) return out;
    out.push({ key, label, ms: Math.max(0, u[key] - prev) });
    prev = u[key];
  }
  return out;
}

/* One mark carries both facts: it points the way the audio travelled, and its
   segments show what the delay was made of. */
function flow(u, fromCaller) {
  const segs = segments(u);
  const el = document.createElement("div");
  el.className = "flow" + (fromCaller ? "" : " reverse");

  const bar = document.createElement("div");
  bar.className = "hopbar";
  const shades = SHADES[u.direction] || SHADES["caller-to-agent"];

  if (segs.length) {
    segs.forEach((s, i) => {
      const span = document.createElement("span");
      span.style.flex = `${s.ms} 0 0`;
      span.style.background = `var(${shades[i]})`;
      span.title = `${s.label}: ${s.ms} ms`;
      bar.appendChild(span);
    });
    el.setAttribute("role", "img");
    el.setAttribute("aria-label",
      segs.map((s) => `${s.label} ${s.ms} milliseconds`).join(", "));
  } else {
    bar.classList.add("waiting");
    bar.appendChild(document.createElement("span"));
    el.setAttribute("aria-label", "translation in flight");
  }

  const head = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  head.setAttribute("viewBox", "0 0 7 8");
  head.setAttribute("width", "7");
  head.setAttribute("height", "8");
  head.setAttribute("class", "flow-head");
  head.setAttribute("aria-hidden", "true");
  head.innerHTML = `<path d="M1.2 1.2 L5.6 4 L1.2 6.8" fill="none" stroke="currentColor"
    stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>`;

  el.append(bar, head);
  return el;
}

function card(kind, text, timeLabel, ts, agentSide) {
  const el = document.createElement("div");
  el.className = `card-utt ${kind}` + (text ? "" : " pending") + (agentSide ? " agent-side" : "");
  const body = document.createElement("div");
  body.className = "utt-text";
  body.textContent = text || (kind === "source" ? "listening…" : "translating…");
  el.appendChild(body);
  if (ts) {
    const time = document.createElement("div");
    time.className = "utt-time";
    time.innerHTML = `${timeLabel} <b>${clock(ts)}</b>`;
    el.appendChild(time);
  }
  return el;
}

function row(u) {
  const el = document.createElement("div");
  el.className = `row ${u.direction}`;
  const fromCaller = u.direction === "caller-to-agent";

  // The source always sits in its own speaker's lane; the translation faces it.
  const source = card("source", u.source, "spoken", u.onset_ts, !fromCaller);
  const translation = card("translation", u.translation, "delivered",
    u.arrival_ts || u.text_ts, fromCaller);

  const spine = document.createElement("div");
  spine.className = "spine";
  const flight = document.createElement("div");
  flight.className = "flight";
  const value = document.createElement("div");
  value.className = "delta-value";
  value.textContent = secs(u.first_send_ms);
  const label = document.createElement("div");
  label.className = "delta-label";
  label.textContent = u.first_send_ms == null ? "in flight" : "to hand-off";
  flight.append(value, label);

  spine.append(flight, flow(u, fromCaller));

  el.append(fromCaller ? source : translation, spine, fromCaller ? translation : source);
  return el;
}

/* Speech onset is detected by energy but the model segments on meaning, so one
   sentence often spans several onsets. Onsets close together are shown as one turn.
   Mirrors `_turns` in app.py -- keep TURN_GAP_S in step with it. */
const TURN_GAP_S = 6;

function toTurns(list) {
  const turns = [];
  for (const u of list) {
    const prev = turns[turns.length - 1];
    if (prev && prev.direction === u.direction && u.onset_ts && prev.onset_last
        && u.onset_ts - prev.onset_last <= TURN_GAP_S) {
      prev.onset_last = u.onset_ts;
      prev.source = (prev.source || "") + (u.source || "");
      prev.translation = (prev.translation || "") + (u.translation || "");
      for (const { key } of HOPS) if (prev[key] == null && u[key] != null) prev[key] = u[key];
      if (!prev.arrival_ts && u.arrival_ts) prev.arrival_ts = u.arrival_ts;
      if (!prev.text_ts && u.text_ts) prev.text_ts = u.text_ts;
      continue;
    }
    turns.push({ ...u, onset_last: u.onset_ts });
  }
  return turns;
}

function render() {
  const ordered = [...utterances.values()].sort(
    (a, b) => (a.onset_ts || 0) - (b.onset_ts || 0) || a.order - b.order);
  const list = toTurns(ordered);

  els.rows.replaceChildren(...list.map(row));
  els.empty.hidden = list.length > 0;
  els.lanes.hidden = list.length === 0;
  els.count.textContent = String(list.length);

  const measured = list.map((u) => u.first_send_ms).filter((v) => v != null);
  const sorted = [...measured].sort((a, b) => a - b);
  els.median.textContent = sorted.length
    ? secs(sorted[Math.floor(sorted.length / 2)])
    : "—";
  els.last.textContent = measured.length ? secs(measured[measured.length - 1]) : "—";
}

/* The caller's language. A translation session opens when a call starts, so a change
   here takes effect on the next call, never the one already running. */
async function languagePicker() {
  const select = document.getElementById("caller-language");
  if (!select) return;
  try {
    const { caller_language: current, languages } = await (await fetch("api/settings")).json();
    select.replaceChildren(...languages.map((l) => {
      const o = document.createElement("option");
      o.value = l.code;
      o.textContent = l.name;
      o.selected = l.code === current;
      return o;
    }));
    select.addEventListener("change", async () => {
      select.disabled = true;
      try {
        await fetch("api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ caller_language: select.value }),
        });
        note(`Applies from the next call — ${select.selectedOptions[0].textContent}`);
      } catch {
        note("Could not save that. The next call keeps the current language.");
      } finally {
        select.disabled = false;
      }
    });
  } catch {
    select.closest(".picker")?.remove();
  }
}

function note(text) {
  let el = document.getElementById("setting-note");
  if (!el) {
    el = document.createElement("div");
    el.id = "setting-note";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.hidden = false;
  clearTimeout(note.timer);
  note.timer = setTimeout(() => { el.hidden = true; }, 4000);
}

function connect() {
  const source = new EventSource("api/live");

  source.addEventListener("conversation", (msg) => {
    const next = JSON.parse(msg.data).conv;
    if (next !== conv) reset(next);
    setStatus(next ? "live" : "waiting",
      next ? "Receiving" : "Waiting for a call");
  });

  source.onmessage = (msg) => {
    const e = JSON.parse(msg.data);
    if (e.event === "summary") {
      setStatus("ended", "Call ended");
    } else {
      apply(e);
      render();
      if (els.status.dataset.state !== "live") setStatus("live", "Receiving");
    }
  };

  source.onerror = () => setStatus("waiting", "Reconnecting");
}

languagePicker();
connect();
