/* Latency dashboard: where the time went on one finished call.

   Hops are cumulative stamps from speech onset, so each bar segment is the
   difference from the previous stamp. Hue identifies the direction, lightness the
   stage — the same encoding the live console uses. */

const HOPS = [
  { key: "send_ms", label: "Send buffer", note: "Audio waiting for a full 100 ms chunk" },
  { key: "ttfa_ms", label: "Model", note: "Gemini Live Translate producing audio" },
  { key: "first_send_ms", label: "Forward", note: "Handing translated audio to the call" },
];

const SHADES = {
  "caller-to-agent": ["--caller-1", "--caller-2", "--caller-3"],
  "agent-to-caller": ["--agent-1", "--agent-2", "--agent-3"],
};

const DIRECTION_NAMES = {
  "caller-to-agent": "Caller to agent",
  "agent-to-caller": "Agent to caller",
  loopback: "Loopback",
};

const els = {
  form: document.getElementById("lookup"),
  input: document.getElementById("conv-input"),
  conv: document.getElementById("conv"),
  recent: document.getElementById("recent"),
  error: document.getElementById("error"),
  report: document.getElementById("report"),
};

const ms = (v) => (v == null ? "—" : `${v} ms`);
const secs = (v) => (v == null ? "—" : `${(v / 1000).toFixed(2)}s`);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

function segments(u) {
  const out = [];
  let prev = 0;
  for (const hop of HOPS) {
    if (u[hop.key] == null) return out;
    out.push({ ...hop, ms: Math.max(0, u[hop.key] - prev) });
    prev = u[hop.key];
  }
  return out;
}

function showError(message) {
  els.error.hidden = false;
  els.error.className = "error";
  els.error.textContent = message;
  els.report.replaceChildren();
}

/* --- pieces ---------------------------------------------------------------- */
/* The dashboard answers one question first: of the delay a caller hears, how much
   is the model and how much is ours. Detail comes after, for whoever wants it. */

const COMPONENT_COLOR = { model: "var(--caller-2)", bridge: "var(--agent-2)" };

function tiles(data) {
  const s = data.summary || {};
  const model = (s.components || []).find((c) => c.key === "model") || {};
  const box = el("div", "tiles");

  const tile = (label, value, unit, note) => {
    const wrap = el("div", "tile");
    const v = el("div", "tile-value");
    v.append(value);
    if (unit) v.append(el("span", "tile-unit", unit));
    wrap.append(el("div", "tile-label", label), v, el("div", "tile-note", note));
    return wrap;
  };

  const sec = (v) => (v == null ? "—" : (v / 1000).toFixed(2));
  box.append(
    tile("Typical delay", sec(s.median_ms), s.median_ms == null ? "" : "s",
      "What a caller waits between speaking and the translation going out"),
    tile("Model's share", model.share == null ? "—" : Math.round(model.share * 100),
      model.share == null ? "" : "%", "The rest is everything we control"),
    tile("Turns measured", `${s.measured ?? 0}`, `/${s.turns ?? 0}`,
      "Turns with a complete end-to-end timing"),
  );
  return box;
}

/* One bar, two parts. This is the whole executive story. */
function split(data) {
  const s = data.summary || {};
  const parts = (s.components || []).filter((c) => c.median_ms != null);
  const body = el("div", "card-body");

  if (!parts.length) {
    body.append(el("p", "section-note", "No turn on this call was measured end to end."));
    return body;
  }

  const total = parts.reduce((a, c) => a + c.median_ms, 0) || 1;
  const bar = el("div", "split");
  parts.forEach((c) => {
    const seg = el("div", "split-seg");
    seg.style.flex = `${c.median_ms} 0 0`;
    seg.style.background = COMPONENT_COLOR[c.key] || "var(--ink-faint)";
    seg.title = `${c.label}: ${c.median_ms} ms`;
    bar.append(seg);
  });
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label",
    parts.map((c) => `${c.label} ${c.median_ms} milliseconds`).join(", "));

  const keys = el("div", "split-keys");
  parts.forEach((c) => {
    const item = el("div", "split-key");
    const sw = el("span", "legend-swatch");
    sw.style.background = COMPONENT_COLOR[c.key] || "var(--ink-faint)";
    const head = el("div", "split-key-head");
    head.append(sw, el("b", null, c.label));
    item.append(head,
      el("div", "split-key-value", `${(c.median_ms / 1000).toFixed(2)}s`),
      el("div", "split-key-note",
        `${Math.round((c.median_ms / total) * 100)}% of the delay — ${c.note}`));
    keys.append(item);
  });

  body.append(bar, keys);
  return body;
}

function legend(direction) {
  const box = el("div", "legend");
  const shades = SHADES[direction] || SHADES["caller-to-agent"];
  HOPS.forEach((hop, i) => {
    const item = el("div", "legend-item");
    const sw = el("span", "legend-swatch");
    sw.style.background = `var(${shades[i]})`;
    item.append(sw, document.createTextNode(`${hop.label} — ${hop.note}`));
    box.appendChild(item);
  });
  return box;
}

function chart(direction, utterances) {
  const measured = utterances.filter((u) => segments(u).length === HOPS.length);
  if (!measured.length) return el("p", "section-note", "No fully measured utterances.");

  const max = Math.max(...measured.map((u) => u.total_ms));
  const shades = SHADES[direction] || SHADES["caller-to-agent"];
  const box = el("div");

  measured.forEach((u) => {
    const rowEl = el("div", "chart-row");
    rowEl.append(el("div", "n", `#${u.n}`));

    const track = el("div");
    const stack = el("div", "stack");
    stack.style.width = `${(u.total_ms / max) * 100}%`;
    segments(u).forEach((s, i) => {
      const seg = el("span");
      seg.style.flex = `${s.ms} 0 0`;
      seg.style.background = `var(${shades[i]})`;
      seg.title = `${s.label}: ${s.ms} ms`;
      stack.appendChild(seg);
    });
    stack.setAttribute("role", "img");
    stack.setAttribute("aria-label", segments(u)
      .map((s) => `${s.label} ${s.ms} milliseconds`).join(", "));
    track.appendChild(stack);
    rowEl.append(track, el("div", "total", secs(u.total_ms)));
    box.appendChild(rowEl);
  });
  return box;
}

function statsTable(stats) {
  const table = el("table");
  const head = el("tr");
  ["Hop", "Measured", "Min", "Median", "Max"].forEach((h) => head.appendChild(el("th", null, h)));
  table.appendChild(el("thead")).appendChild(head);

  const body = el("tbody");
  [...HOPS.map((h) => h.key), "total"].forEach((key) => {
    const s = stats[key];
    if (!s) return;
    const tr = el("tr");
    tr.append(
      el("td", null, s.label),
      el("td", null, String(s.n)),
      el("td", null, ms(s.min)),
      el("td", null, ms(s.median)),
      el("td", null, ms(s.max)),
    );
    body.appendChild(tr);
  });
  table.appendChild(body);
  return table;
}

function transcriptTable(utterances) {
  const table = el("table");
  const head = el("tr");
  ["#", "Spoken", "Translated", "Delay"].forEach((h, i) =>
    head.appendChild(el("th", i === 1 || i === 2 ? "text" : null, h)));
  table.appendChild(el("thead")).appendChild(head);

  const body = el("tbody");
  utterances.forEach((u) => {
    const tr = el("tr");
    tr.append(
      el("td", null, `#${u.n}`),
      el("td", "text", u.source || "—"),
      el("td", "text", u.translation || "—"),
      el("td", null, secs(u.total_ms)),
    );
    body.appendChild(tr);
  });
  table.appendChild(body);
  return table;
}

function caveat() {
  const box = el("div", "notice");
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("width", "18");
  icon.setAttribute("height", "18");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("fill", "currentColor");
  icon.setAttribute("aria-hidden", "true");
  icon.innerHTML = '<path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 15h-2v-6h2Zm0-8h-2V7h2Z"/>';
  box.append(icon);
  const text = el("div");
  text.append(
    el("p", null, "Every figure is measured inside the bridge: from the moment a chunk of "
      + "speech is loud enough to register, to the moment translated audio is handed to "
      + "AudioCodes."),
    el("p", null, "Two legs are missing because nothing in the audio path timestamps them — "
      + "the caller's phone to the bridge, and the bridge to the other phone's earpiece. "
      + "Measure those together by placing a call in echo mode and timing the round trip "
      + "acoustically."),
  );
  box.append(text);
  return box;
}

/* --- page ------------------------------------------------------------------ */
function card(title, subtitle, body, dirName) {
  const box = el("div", "card");
  const head = el("div", "card-head");
  const h2 = el("h2");
  if (dirName) {
    const key = el("span", "dir-key");
    key.style.background = `var(${(SHADES[dirName] || SHADES["caller-to-agent"])[1]})`;
    h2.append(key);
  }
  h2.append(document.createTextNode(title));
  head.append(h2);
  if (subtitle) head.append(el("p", null, subtitle));
  box.append(head, body);
  return box;
}

/* Each direction is one card with three tabs, so a long call stays scannable. */
function renderDirection(name, d) {
  const panels = {
    breakdown: (() => {
      const body = el("div", "card-body");
      body.append(legend(name), chart(name, d.utterances));
      return body;
    })(),
    hops: (() => {
      const body = el("div", "card-body flush");
      body.append(statsTable(d.stats));
      return body;
    })(),
    transcript: (() => {
      const body = el("div", "card-body flush");
      body.append(transcriptTable(d.utterances));
      return body;
    })(),
  };

  const wrap = el("div");
  const tabs = el("div", "tabs");
  const labels = { breakdown: "Per utterance", hops: "Per hop", transcript: "Transcript" };
  const buttons = {};

  const select = (key) => {
    Object.entries(panels).forEach(([k, panel]) => { panel.hidden = k !== key; });
    Object.entries(buttons).forEach(([k, b]) => {
      b.setAttribute("aria-selected", String(k === key));
    });
  };

  Object.keys(panels).forEach((key) => {
    const b = el("button", null, labels[key]);
    b.type = "button";
    b.setAttribute("role", "tab");
    b.addEventListener("click", () => select(key));
    buttons[key] = b;
    tabs.append(b);
  });
  tabs.setAttribute("role", "tablist");

  wrap.append(tabs, ...Object.values(panels));
  select("breakdown");

  return card(
    DIRECTION_NAMES[name] || name,
    `${d.utterances.length} utterance${d.utterances.length === 1 ? "" : "s"}. `
    + "Each bar is one utterance, split into the stages that make up its delay.",
    wrap, name);
}

function render(data) {
  els.error.hidden = true;
  els.conv.textContent = data.conv;
  const report = el("div");

  report.append(tiles(data));
  report.append(card("Where the delay comes from",
    "Median across every measured turn in both directions.", split(data)));

  // Detail sits below the headline, collapsed, for whoever wants to dig in.
  const detail = el("details", "detail");
  detail.append(el("summary", null, "Detail by direction"));
  Object.entries(data.directions).forEach(([name, d]) =>
    detail.append(renderDirection(name, d)));
  detail.append(caveat());
  report.append(detail);

  els.report.replaceChildren(report);
}

async function load(conv) {
  if (!conv) return;
  els.input.value = conv;
  const url = new URL(window.location);
  url.searchParams.set("conv", conv);
  history.replaceState(null, "", url);

  try {
    const res = await fetch(`api/calls/${encodeURIComponent(conv)}`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.detail || `Could not load conversation ${conv}.`);
      return;
    }
    render(await res.json());
  } catch (e) {
    showError(`Could not reach the console service: ${e.message}`);
  }
}

async function showRecent() {
  try {
    const { calls } = await (await fetch("api/calls")).json();
    if (!calls.length) {
      els.recent.textContent = "No recorded calls yet.";
      return;
    }
    els.recent.replaceChildren(document.createTextNode("Recent: "));
    calls.slice(0, 5).forEach((c, i) => {
      if (i) els.recent.append(document.createTextNode(", "));
      const b = el("button", null, c.conv);
      b.type = "button";
      b.addEventListener("click", () => load(c.conv));
      els.recent.append(b);
    });
  } catch {
    els.recent.textContent = "";
  }
}

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  load(els.input.value.trim());
});

showRecent();
load(new URLSearchParams(window.location.search).get("conv"));
