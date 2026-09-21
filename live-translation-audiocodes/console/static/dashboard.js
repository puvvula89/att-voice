/* Latency dashboard: where the time went on one finished call.

   Hops are cumulative stamps from speech onset, so each bar segment is the
   difference from the previous stamp. Hue identifies the direction, lightness the
   stage — the same encoding the live console uses.

   The page leads with one averaged turn drawn as a journey, because the question it
   is opened to answer is how long Live Translate takes to put translated speech on
   the wire. That is the leg from audio leaving the bridge to the first translated
   audio coming back; the bridge's own legs sit either side of it for scale. */

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

/* A turn, in the order it actually happened: the speaker talking, then the model,
   then the bridge handing audio back. Speech leads because it comes first in time
   and because seeing it is the point — the stages after it are what the system
   owns. Falls back to the raw hops when a call predates end-of-speech timing. */
function segments(u) {
  const hops = [];
  let prev = 0;
  for (const hop of HOPS) {
    if (u[hop.key] == null) return [];
    hops.push({ ...hop, ms: Math.max(0, u[hop.key] - prev) });
    prev = u[hop.key];
  }
  if (u.speech_ms == null || u.model_ms == null) return hops;

  const bridge = hops[0].ms + hops[2].ms;   // send buffer in, forwarding out
  return [
    { key: "speech_ms", label: "Speaker talking", speaker: true, ms: u.speech_ms,
      note: "Not a delay — how long the turn took to say" },
    { key: "model_ms", label: "Model", ms: Math.max(0, u.model_ms),
      note: u.overlapped
        ? "Began before the speaker finished"
        : "From the speaker stopping to translated audio" },
    { key: "bridge_ms", label: "Bridge", ms: bridge,
      note: "Buffering audio in and handing it back out" },
  ];
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

const COMPONENT_COLOR = { speech: "var(--ink-faint)", model: "var(--caller-2)",
                          bridge: "var(--agent-2)" };

function tiles(data) {
  const s = data.summary || {};
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
  const m = s.model;
  const perDir = s.per_direction || [];
  const slowest = perDir.slice().sort((a, b) => b.mean_ms - a.mean_ms)[0];
  const sim = s.simultaneous;

  // The model's own leg leads and everything else is context for it: this page is
  // shown to answer "how fast is Live Translate", not "how slow is the call". The
  // audio leg is that leg -- the one end-to-end measurement of the model, and the
  // only one the listener experiences. The transcript stamp sits behind it as a
  // hint, never in front of it.
  box.append(
    tile("Model, first audio", m ? sec(m.mean_ms) : "—", m ? "s" : "",
      "Audio leaving the bridge to the first translated audio coming back"),
    tile("Slowest direction", slowest ? sec(slowest.mean_ms) : "—", slowest ? "s" : "",
      slowest ? `${DIRECTION_NAMES[slowest.key] || slowest.key}, bridge in to bridge out`
              : "Only one direction was measured"),
    tile("Everything else", sec((s.mean_ms ?? 0) - (m ? m.mean_ms : 0)),
      s.mean_ms == null ? "" : "s",
      "Every stage the bridge owns, added together"),
    tile("Turns measured", `${s.measured ?? 0}`, `/${s.turns ?? 0}`,
      s.unanswered ? `${s.unanswered} spoken turn(s) drew no translation at all`
                   : "Every spoken turn drew a translation"),
  );
  if (sim && sim.n) {
    box.append(el("p", "section-note",
      `On ${sim.n} of ${sim.of} turns the first translated audio was already on the wire `
      + "before the speaker had finished — simultaneous, not delayed."));
  }
  return box;
}

/* The averaged utterance, drawn as the journey one turn makes. Proportional, so
   the model's leg is the picture. The phone-network leg carries no timestamps, so
   it is drawn as a gap and labelled -- sizing it would be inventing a number. */
function journey(data) {
  const s = data.summary || {};
  const body = el("div", "card-body");
  const legs = (s.legs || []).filter((l) => l.mean_ms != null || l.unmeasured);
  if (!legs.length) {
    body.append(el("p", "section-note", "No turn on this call was measured end to end."));
    return body;
  }

  // The bridge's legs are ~1% of the total, so pure proportional sizing crushes
  // them to a few pixels and their labels become unreadable. Each segment keeps a
  // floor wide enough to read; the model still takes every pixel that is left, so
  // it stays unmistakably the picture.
  const flexOf = (leg) => (leg.unmeasured ? "0 0 112px" : `${Math.max(leg.mean_ms, 1)} 0 0`);

  const track = el("div", "journey");
  legs.forEach((leg) => {
    const seg = el("div", leg.unmeasured ? "journey-seg journey-unmeasured"
                                         : "journey-seg");
    seg.style.flex = flexOf(leg);
    if (leg.model) seg.classList.add("journey-model");
    seg.append(el("div", "journey-owner", leg.owner),
               el("div", "journey-time", leg.unmeasured ? "not measured"
                                                        : secs(leg.mean_ms)));
    if (!leg.unmeasured && leg.share != null) {
      seg.append(el("div", "journey-share", `${Math.round(leg.share * 100)}%`));
    }
    seg.title = `${leg.start} → ${leg.end}`;
    track.append(seg);
  });

  // Each boundary label sits under the left edge of the segment it opens, so the
  // marks track the picture instead of being spaced evenly against it.
  const marks = el("div", "journey-marks");
  legs.forEach((leg) => {
    const mk = el("div", "journey-mark", leg.start);
    mk.style.flex = flexOf(leg);
    marks.append(mk);
  });
  const last = el("div", "journey-mark last", legs[legs.length - 1].end);
  marks.append(last);

  track.setAttribute("role", "img");
  track.setAttribute("aria-label", legs.map((l) =>
    `${l.owner}: ${l.unmeasured ? "not measured" : secs(l.mean_ms)}`).join(", "));

  body.append(track, marks);

  // The same measurement, split by who was speaking. Each direction runs its own
  // session into its own target language, so they are not interchangeable -- and an
  // average across both hides which one a listener is actually waiting on.
  const perDir = s.per_direction || [];
  if (perDir.length > 1) {
    const widest = Math.max(...perDir.map((d) => d.mean_ms));
    const box = el("div", "dirbars");
    perDir.forEach((d) => {
      const row = el("div", "dirbar-row");
      const shades = SHADES[d.key] || SHADES["caller-to-agent"];
      row.append(el("div", "dirbar-label", DIRECTION_NAMES[d.key] || d.key));
      const track2 = el("div", "dirbar-track");
      const fill = el("div", "dirbar-fill");
      fill.style.width = `${(d.mean_ms / widest) * 100}%`;
      fill.style.background = `var(${shades[1]})`;
      track2.append(fill);
      row.append(track2, el("div", "dirbar-time", secs(d.mean_ms)));
      row.title = `${d.n} turn(s), p95 ${secs(d.p95_ms)}`;
      box.append(row);
    });
    body.append(el("p", "section-note dirbars-head",
      "Bridge in to bridge out, by who was speaking:"), box);
  }

  body.append(el("p", "section-note",
    `Average of ${s.measured ?? 0} measured turn(s) across both directions, end to end `
    + `${secs(s.mean_ms)} from the bridge hearing speech to translated audio leaving it. `
    + "The phone-network leg between the speaker and the bridge carries no timestamps, "
    + "so it is shown but not sized."));
  return body;
}

/* One bar. Speech is shown alongside the delays but is never counted as one:
   it is the speaker's own time, and folding it into the model's number is the
   single mistake this page exists to prevent. */
function split(data) {
  const s = data.summary || {};
  const parts = (s.components || []).filter((c) => c.median_ms != null);
  const body = el("div", "card-body");

  if (!parts.length) {
    body.append(el("p", "section-note", "No turn on this call was measured end to end."));
    return body;
  }

  // Speech sizes the bar so the system's stages are seen against it, but it is
  // never part of the delay the shares are computed from.
  const delay = parts.filter((c) => !c.speaker)
    .reduce((a, c) => a + c.median_ms, 0) || 1;
  const bar = el("div", "split");
  parts.forEach((c) => {
    const seg = el("div", "split-seg");
    seg.style.flex = `${c.median_ms} 0 0`;
    seg.style.backgroundColor = COMPONENT_COLOR[c.key] || "var(--ink-faint)";
    seg.title = `${c.label}: ${c.median_ms} ms`;
    if (c.speaker) seg.classList.add("split-seg-speaker");
    bar.append(seg);
  });
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label",
    parts.map((c) => `${c.label} ${c.median_ms} milliseconds`).join(", "));

  const keys = el("div", "split-keys");
  parts.forEach((c) => {
    const item = el("div", "split-key");
    const sw = el("span", "legend-swatch");
    sw.style.backgroundColor = COMPONENT_COLOR[c.key] || "var(--ink-faint)";
    const head = el("div", "split-key-head");
    head.append(sw, el("b", null, c.label));
    item.append(head,
      el("div", "split-key-value", `${(c.median_ms / 1000).toFixed(2)}s`),
      el("div", "split-key-note", c.speaker
        ? c.note
        : `${Math.round((c.median_ms / delay) * 100)}% of the delay — ${c.note}`));
    keys.append(item);
  });

  body.append(bar, keys);
  if (s.speech_unmeasured) {
    body.append(el("p", "section-note",
      "This call was recorded before end-of-speech timing existed, so the model figure "
      + "runs from the start of speech and still carries however long the speaker "
      + "talked. It is not comparable with a newer call's model figure."));
  }
  body.append(el("p", "section-note",
    "Each figure is that stage's own median, so they describe a typical turn rather "
    + "than adding up to one. A turn where the model answered before the speaker "
    + "finished is counted as nought, not as negative time."));
  return body;
}

function legend(direction, sample) {
  const box = el("div", "legend");
  const shades = SHADES[direction] || SHADES["caller-to-agent"];
  (sample && sample.length ? sample : HOPS).forEach((hop, i) => {
    const item = el("div", "legend-item");
    const sw = el("span", "legend-swatch");
    sw.style.backgroundColor = `var(${shades[i]})`;
    if (hop.speaker) sw.classList.add("split-seg-speaker");
    item.append(sw, document.createTextNode(`${hop.label} — ${hop.note}`));
    box.appendChild(item);
  });
  return box;
}

function chart(direction, utterances) {
  const measured = utterances.filter((u) => segments(u).length);
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
      seg.style.backgroundColor = `var(${shades[i]})`;
      if (s.speaker) seg.classList.add("split-seg-speaker");
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

/* Speech against the translated audio answering it, both anchored to the same zero
   (speech onset), which is what makes them comparable: every stamp in `metrics.py`
   is measured from that instant. The picture is the overlap -- a turn where the
   translation starts before the speech bar ends was being interpreted live, not
   after the fact. Colour carries it; the numbers are in the other tabs.

   The translated audio's end is not timestamped anywhere, so its bar fades out
   instead of drawing a finish line the data does not have. */
function overlapChart(direction, utterances) {
  const usable = utterances.filter((u) => u.speech_ms != null && u.ttfa_ms != null);
  if (!usable.length) return null;

  const max = Math.max(...usable.map((u) => Math.max(u.speech_ms, u.ttfa_ms * 1.35)));
  const shades = SHADES[direction] || SHADES["caller-to-agent"];
  const box = el("div");

  const key = el("div", "overlap-legend");
  [[shades[0], "Speech reaching the bridge"],
   [shades[2], "Translated audio coming back"]].forEach(([shade, label]) => {
    const item = el("div");
    const sw = el("span", "key");
    sw.style.background = `var(${shade})`;
    item.append(sw, document.createTextNode(label));
    key.append(item);
  });
  box.append(key);

  usable.forEach((u) => {
    const row = el("div", "overlap-row");
    row.append(el("div", "n", `#${u.n}`));

    const track = el("div", "overlap-track");
    const pct = (ms) => `${(ms / max) * 100}%`;

    const speech = el("div", "overlap-bar");
    const spoken = el("span", "fill");
    spoken.style.width = pct(u.speech_ms);
    spoken.style.background = `var(${shades[0]})`;
    speech.append(spoken);

    const audio = el("div", "overlap-bar");
    const gap = el("span", "pad");
    gap.style.width = pct(u.ttfa_ms);
    const heard = el("span", "fill open");
    heard.style.width = pct(Math.max(max - u.ttfa_ms, max * 0.04));
    heard.style.background = `var(${shades[2]})`;
    audio.append(gap, heard);

    const overlap = u.speech_ms - u.ttfa_ms;
    const caption = overlap > 0
      ? `Translation began ${secs(overlap)} before the speaker finished`
      : `Translation began ${secs(-overlap)} after the speaker finished`;
    track.append(speech, audio);
    track.title = `Spoke for ${secs(u.speech_ms)}; translated audio back at `
                + `${secs(u.ttfa_ms)}. ${caption}.`;
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", track.title);

    row.append(track, el("div", "total", overlap > 0 ? secs(overlap) : "—"));
    box.appendChild(row);
  });
  return box;
}

/* Every stage, with what it means beside it -- the table is read by people who did
   not build the bridge, and a bare row label does not tell them whose time it is.

   Every row is a positive duration. The turns where translation began before the
   speaker finished and the turns where it did not are separate rows, because one
   signed number cannot be read down a min/median/max column -- there the smallest
   figure is the largest head start. Rows with nothing measured are dropped: an empty
   row invites the reader to wonder what broke. */
function statsTable(stats) {
  const table = el("table");
  const head = el("tr");
  ["Stage", "Measured", "Min", "Median", "p95", "Max"].forEach((h, i) =>
    head.appendChild(el("th", i === 0 ? "text" : null, h)));
  table.appendChild(el("thead")).appendChild(head);

  const body = el("tbody");
  ["speech_ms", "head_start_ms", "late_ms", ...HOPS.map((h) => h.key), "total"]
      .forEach((key) => {
    const s = stats[key];
    if (!s || !s.n) return;                 // nothing measured; do not print a blank row
    const fmt = ms;
    const tr = el("tr");
    const label = el("td", "text");
    label.append(el("div", "stage-name", s.label));
    if (s.description) label.append(el("div", "stage-note", s.description));
    tr.append(
      label,
      el("td", null, String(s.n)),
      el("td", null, fmt(s.min)),
      el("td", null, fmt(s.median)),
      el("td", null, fmt(s.p95)),
      el("td", null, fmt(s.max)),
    );
    if (key === "speech_ms") tr.classList.add("row-muted");   // not a delay
    if (key === "head_start_ms") tr.classList.add("row-good");
    body.appendChild(tr);
  });
  table.appendChild(body);
  return table;
}

function transcriptTable(utterances) {
  const table = el("table");
  const head = el("tr");
  ["#", "Spoken", "Translated", "Spoke for", "Model", "Caller waited"].forEach((h, i) =>
    head.appendChild(el("th", i === 1 || i === 2 ? "text" : null, h)));
  table.appendChild(el("thead")).appendChild(head);

  const body = el("tbody");
  utterances.forEach((u) => {
    const tr = el("tr");
    tr.append(
      el("td", null, `#${u.n}`),
      el("td", "text", u.source || "—"),
      el("td", "text", u.translation || "—"),
      el("td", "muted", secs(u.speech_ms)),
      el("td", null, u.overlapped ? `overlap ${secs(Math.abs(u.model_ms))}` : secs(u.model_ms)),
      el("td", null, secs(u.total_ms)),
    );
    if (u.total_ms == null) tr.classList.add("row-unanswered");
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
      const sample = (d.utterances.map(segments).find((x) => x.length)) || [];
      body.append(legend(name, sample), chart(name, d.utterances));
      return body;
    })(),
    overlap: (() => {
      const body = el("div", "card-body");
      const chartEl = overlapChart(name, d.utterances);
      body.append(chartEl || el("p", "section-note",
        "This call carries no end-of-speech timing, so speech and translation "
        + "cannot be placed on one axis."));
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
  const labels = { breakdown: "Per utterance", overlap: "Speech vs translation",
                   hops: "Per stage", transcript: "Transcript" };
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
  report.append(card("Where an average turn's time goes",
    "Averaged across every measured turn in both directions.", journey(data)));

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
