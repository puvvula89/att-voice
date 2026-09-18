"""Console service: live call transcript and a post-call latency dashboard.

Runs as its own process so nothing here shares an event loop with the audio path.
It never talks to the bridge: the bridge appends events to
`recordings/<conv>/events.jsonl`, and this service tails and replays those files.

  uvicorn console.app:app --port 8081
"""
from __future__ import annotations

import asyncio
import json
import os
import math
import statistics

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from bridge import settings

RECORDINGS = os.environ.get("RECORDINGS_DIR", "recordings")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
POLL_S = 0.4
# Onsets closer together than this are treated as one spoken turn (see `_turns`).
TURN_GAP_S = float(os.environ.get("TURN_GAP_S", "6"))

# What the dashboard charts. `speech_ms` is not a delay -- it is how long the
# speaker talked -- but every other stamp runs from speech onset, so it has to be
# subtracted before the model's own speed is visible. Reporting it explicitly is
# what keeps a four-second sentence from reading as a four-second model.
SPEECH = ("speech_ms", "Speech", "Speech onset to the last chunk carrying voice")
MODEL = ("model_ms", "Model", "End of speech to the first translated audio back")

# Hops the dashboard charts, in the order audio travels. `send_ms` is the bridge's
# own 100 ms send buffer; splitting it out keeps it from being charged to the model.
HOPS = [
    ("send_ms", "Send buffer", "Speech onset to the chunk leaving for the model"),
    ("ttfa_ms", "Model", "Chunk sent to first translated audio back"),
    ("first_send_ms", "Forward", "First translated audio to the telephony leg"),
]
app = FastAPI(title="Live translation console")


# --- reading the bridge's event files ---------------------------------------
def _conv_dir(conv: str) -> str:
    # conv ids come from the URL; keep them inside the recordings directory.
    if not conv or os.path.sep in conv or conv.startswith("."):
        raise HTTPException(400, "Invalid conversation id")
    path = os.path.join(RECORDINGS, conv)
    if not os.path.isdir(path):
        raise HTTPException(404, f"No recording for conversation {conv}")
    return path


def _events_path(conv: str) -> str:
    return os.path.join(_conv_dir(conv), "events.jsonl")


def _read_events(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # a half-written line while the call is still live
    return out


def _list_calls() -> list[dict]:
    if not os.path.isdir(RECORDINGS):
        return []
    calls = []
    for name in os.listdir(RECORDINGS):
        p = os.path.join(RECORDINGS, name, "events.jsonl")
        if os.path.exists(p):
            calls.append({"conv": name, "modified": os.path.getmtime(p)})
    return sorted(calls, key=lambda c: c["modified"], reverse=True)


def _current_conv() -> str | None:
    calls = _list_calls()
    return calls[0]["conv"] if calls else None


# --- shaping events into utterances -----------------------------------------
def _build(events: list[dict]) -> dict:
    """Group raw events into per-direction utterances with their hop timings."""
    directions: dict[str, dict] = {}
    for e in events:
        d = directions.setdefault(e.get("direction", "?"), {"utterances": {}})
        # Calls recorded before the end-of-call row was re-keyed carry `n` instead.
        n = e.get("utterance", e.get("n"))
        ev = e.get("event")
        if ev == "transcript":
            if n is None:
                continue
            u = d["utterances"].setdefault(n, {"n": n})
            key = "source" if e.get("kind") == "input" else "translation"
            u[key] = (u.get(key) or "") + (e.get("text") or "")
            u.setdefault(f"{key}_language", e.get("language"))
        elif n is not None:
            u = d["utterances"].setdefault(n, {"n": n})
            if ev == "speech_onset":
                u["onset_ts"] = e.get("ts")
            for key in (SPEECH[0], *(k for k, *_ in HOPS)):
                if key in e:
                    u[key] = e[key]
            if ev == "utterance" and "ttft_ms" in e:  # end-of-call row: every hop at once
                u["ttft_ms"] = e["ttft_ms"]

    out = {"directions": {}}
    for name, d in directions.items():
        us = [d["utterances"][k] for k in sorted(d["utterances"])]
        for u in us:
            # Total is measured to the telephony hand-off; the PSTN legs on either
            # side carry no timestamps and are deliberately absent.
            u["total_ms"] = u.get("first_send_ms")
            _derive_model(u)
            if u.get("onset_ts") and u.get("first_send_ms") is not None:
                u["arrival_ts"] = round(u["onset_ts"] + u["first_send_ms"] / 1000, 3)
        turns = _turns(us)
        out["directions"][name] = {"utterances": turns, "stats": _stats(turns)}
    return out


def _turns(utterances: list[dict], gap_s: float = TURN_GAP_S) -> list[dict]:
    """Merge utterances that belong to one spoken turn.

    Speech onset is detected by energy, but the model segments on meaning, so a
    single sentence often spans several onsets -- its transcript arrives split
    across them. Utterances that follow each other closely are joined back into
    one turn, and the turn takes the first latency actually measured within it.
    """
    ordered = sorted(utterances, key=lambda u: (u.get("onset_ts") or 0, u["n"]))
    groups: list[list[dict]] = []
    for u in ordered:
        onset = u.get("onset_ts")
        if groups and onset is not None:
            prev = groups[-1][-1].get("onset_ts")
            if prev is not None and onset - prev <= gap_s:
                groups[-1].append(u)
                continue
        groups.append([u])

    turns = []
    for group in groups:
        head = group[0]
        turn = {"n": head["n"], "onset_ts": head.get("onset_ts"),
                "parts": [u["n"] for u in group]}
        for key in ("source", "translation"):
            text = "".join(u.get(key) or "" for u in group).strip()
            if text:
                turn[key] = text
        for key in ("speech_ms", "send_ms", "ttfa_ms", "ttft_ms", "first_send_ms", "total_ms"):
            measured = next((u[key] for u in group if u.get(key) is not None), None)
            if measured is not None:
                turn[key] = measured
        _derive_model(turn)
        arrival = next((u["arrival_ts"] for u in group if u.get("arrival_ts")), None)
        if arrival:
            turn["arrival_ts"] = arrival
        turns.append(turn)
    return turns


def _derive_model(u: dict) -> None:
    """The model's own latency: from the moment the speaker stopped to the first
    translated audio. Negative means the model began before the speaker finished --
    simultaneous translation, not a measurement error, so it is kept and flagged
    rather than clamped to zero."""
    speech, ttfa = u.get("speech_ms"), u.get("ttfa_ms")
    if speech is None or ttfa is None:
        return
    u["model_ms"] = ttfa - speech
    u["overlapped"] = u["model_ms"] < 0


def _percentile(vals: list[int], pct: float) -> int:
    """Nearest-rank percentile. A max over twenty turns is one outlier; p95 is the
    number a voice product is actually judged on."""
    ordered = sorted(vals)
    i = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[i]


def _measure(key: str, label: str, description: str, vals: list[int]) -> dict:
    entry = {"key": key, "label": label, "description": description, "n": len(vals)}
    if vals:
        entry.update(min=min(vals), median=round(statistics.median(vals)),
                     p95=_percentile(vals, 95), max=max(vals))
    return entry


def _hop_durations(u: dict) -> dict:
    """Each hop's own duration. The stamps are cumulative from speech onset, so a
    hop is the gap since the previous stamp -- charging `first_send_ms` in full
    would report the model's time as the forwarding time."""
    out, prev = {}, 0
    for key, *_ in HOPS:
        if u.get(key) is None:
            break
        out[key] = max(0, u[key] - prev)
        prev = u[key]
    return out


def _stats(utterances: list[dict]) -> dict:
    """Per-hop min/median/max over each hop's own duration, plus the end-to-end total."""
    durations = [_hop_durations(u) for u in utterances]
    stats = {}
    for key, label, description in HOPS:
        stats[key] = _measure(key, label, description,
                              [d[key] for d in durations if key in d])
    for key, label, description in (SPEECH, MODEL):
        stats[key] = _measure(key, label, description,
                              [u[key] for u in utterances if u.get(key) is not None])
    totals = [u["total_ms"] for u in utterances if u.get("total_ms") is not None]
    if totals:
        stats["total"] = _measure("total", "Onset to hand-off",
                                  "Everything the bridge can see, end to end", totals)
    return stats


# --- API ---------------------------------------------------------------------
# One averaged utterance, told as the journey a single turn makes. Each leg is
# (key, label, the moment it ends). The first leg carries no timing: nothing in
# the audio path between the speaker's mouth and the bridge timestamps anything,
# so it is drawn as a gap rather than silently folded into the model's number.
LEGS = [
    ("pstn_in", "Phone network", "Speaking starts", "Audio reaches the bridge"),
    ("buffer", "Bridge", "Audio reaches the bridge", "Sent to the model"),
    ("model", "Live Translate", "Sent to the model", "First translated audio back"),
    ("forward", "Bridge", "First translated audio back", "Onto the listener's leg"),
]

# The model's leg splits in two, and the split is the difference between "how fast
# did it translate" and "how fast did the caller hear it". `ttft` is the first
# translated text token; `ttfa` is the first audio. The gap between them is the
# model turning that token into speech.
MODEL_PARTS = [
    ("ttft", "To first token", "Understanding the speech and translating it"),
    ("vocalize", "To first audio", "Turning that first token into speech"),
]


def _text_timed(turns: list[dict]) -> list[dict]:
    """Turns whose first-text stamp can be trusted against their first-audio stamp.

    Text and audio are attributed by separate burst detectors, and on a noisy leg
    they can disagree -- a turn reporting its first text *after* its first audio,
    or text with no audio at all. Those orderings are impossible, so rather than
    chart a negative synthesis time the turn is left out of the split.
    """
    return [t for t in turns
            if t.get("ttft_ms") is not None and t.get("ttfa_ms") is not None
            and t.get("send_ms") is not None
            and t["send_ms"] <= t["ttft_ms"] <= t["ttfa_ms"]]


def _model_parts(turns: list[dict], model_mean: int | None) -> list[dict]:
    """Split the model's leg into reaching the first token, then voicing it."""
    usable = _text_timed(turns)
    if not usable or not model_mean:
        return []
    to_token = round(statistics.fmean(t["ttft_ms"] - t["send_ms"] for t in usable))
    to_audio = round(statistics.fmean(t["ttfa_ms"] - t["ttft_ms"] for t in usable))
    span = to_token + to_audio
    parts = []
    for key, label, note in MODEL_PARTS:
        value = to_token if key == "ttft" else to_audio
        parts.append({"key": key, "label": label, "note": note, "mean_ms": value,
                      "n": len(usable),
                      "share": round(value / span, 4) if span else None})
    return parts


def _summary(directions: dict) -> dict:
    """One averaged utterance, leg by leg, so the model's own time is plain.

    The question this page exists to answer is how long Gemini Live Translate takes
    to put its first translated token on the wire. That is `ttfa - send`: from the
    moment audio actually left for the model to the moment the first token came
    back. Everything else is shown beside it for scale.
    """
    turns = [t for d in directions.values() for t in d["utterances"]]
    unanswered = sum(1 for t in turns if t.get("first_send_ms") is None)
    # A turn only counts once all three stamps exist; a partial one would understate
    # whichever leg is missing rather than be visibly absent.
    full = [t for t in turns if all(t.get(k) is not None for k, *_ in HOPS)]

    def avg(vals):
        return round(statistics.fmean(vals)) if vals else None

    measured = {
        "buffer": [t["send_ms"] for t in full],
        "model": [t["ttfa_ms"] - t["send_ms"] for t in full],
        "forward": [t["first_send_ms"] - t["ttfa_ms"] for t in full],
    }
    total = avg([t["first_send_ms"] for t in full])

    legs = []
    for key, owner, start, end in LEGS:
        vals = measured.get(key)
        leg = {"key": key, "owner": owner, "start": start, "end": end,
               "model": key == "model", "n": len(vals) if vals else 0}
        if vals:
            leg["mean_ms"] = avg(vals)
            leg["p95_ms"] = _percentile(vals, 95)
            leg["share"] = round(leg["mean_ms"] / total, 4) if total else None
        else:
            # Named, sized at nothing, and labelled -- leadership should see that
            # this leg exists and that we cannot yet put a number on it.
            leg["unmeasured"] = True
        if key == "model":
            leg["parts"] = _model_parts(full, leg.get("mean_ms"))
        legs.append(leg)

    out = {"mean_ms": total, "measured": len(full), "turns": len(turns),
           "unanswered": unanswered, "legs": legs}
    if measured["model"]:
        vals = measured["model"]
        out["model"] = {"mean_ms": avg(vals), "p95_ms": _percentile(vals, 95),
                        "min_ms": min(vals), "max_ms": max(vals), "n": len(vals)}
        ttft = [t["ttft_ms"] - t["send_ms"] for t in _text_timed(full)]
        if ttft:
            out["first_token"] = {"mean_ms": avg(ttft), "p95_ms": _percentile(ttft, 95),
                                  "n": len(ttft)}
    # The strongest evidence of speed is not a duration at all: on these turns the
    # first translated token was already on the wire before the speaker had stopped.
    simultaneous = [t for t in full
                    if t.get("speech_ms") is not None and t["ttfa_ms"] < t["speech_ms"]]
    if any(t.get("speech_ms") is not None for t in full):
        out["simultaneous"] = {"n": len(simultaneous),
                               "of": sum(1 for t in full if t.get("speech_ms") is not None)}
    return out


@app.get("/api/settings")
def get_settings():
    return {"caller_language": settings.caller_language(), "languages": settings.LANGUAGES}


@app.put("/api/settings")
def put_settings(body: dict):
    code = (body or {}).get("caller_language")
    if not code or not isinstance(code, str) or len(code) > 16:
        raise HTTPException(400, "caller_language must be a BCP-47 language code")
    settings.save({"caller_language": code})
    return {"caller_language": settings.caller_language()}


@app.get("/api/hops")
def hops():
    return {"hops": [{"key": k, "label": l, "description": d} for k, l, d in HOPS]}


@app.get("/api/calls")
def calls():
    return {"calls": _list_calls(), "current": _current_conv()}


@app.get("/api/calls/{conv}")
def call(conv: str):
    events = _read_events(_events_path(conv))
    if not events:
        raise HTTPException(404, f"No events recorded for conversation {conv}")
    built = _build(events)
    built["conv"] = conv
    built["summary"] = _summary(built["directions"])
    built["started"] = min(e["ts"] for e in events if "ts" in e)
    built["ended"] = max(e["ts"] for e in events if "ts" in e)
    return built


@app.get("/api/live")
async def live():
    """Tail the most recent call's events, following it if a new call starts."""
    async def stream():
        conv, offset = None, 0
        while True:
            latest = _current_conv()
            if latest != conv:
                conv, offset = latest, 0
                yield f"event: conversation\ndata: {json.dumps({'conv': conv})}\n\n"
            if conv:
                path = _events_path(conv)
                try:
                    with open(path, encoding="utf-8") as f:
                        f.seek(offset)
                        lines = f.readlines()
                        offset = f.tell()
                except OSError:
                    lines = []
                for line in lines:
                    line = line.strip()
                    if line:
                        yield f"data: {line}\n\n"
            else:
                yield ": waiting for a call\n\n"
            await asyncio.sleep(POLL_S)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# --- pages -------------------------------------------------------------------
# The console is redeployed far more often than it is read, and a stale cached
# console.js silently reverts the UI to an older build. Nothing here is heavy
# enough for caching to be worth that.
NO_CACHE = {"Cache-Control": "no-store, must-revalidate"}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "console.html"), headers=NO_CACHE)


@app.get("/dashboard")
def dashboard():
    return FileResponse(os.path.join(STATIC, "dashboard.html"), headers=NO_CACHE)


@app.get("/static/{name}")
def static(name: str):
    path = os.path.join(STATIC, os.path.basename(name))
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path, headers=NO_CACHE)
