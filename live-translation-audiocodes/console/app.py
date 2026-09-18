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
import statistics

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from bridge import settings

RECORDINGS = os.environ.get("RECORDINGS_DIR", "recordings")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
POLL_S = 0.4
# Onsets closer together than this are treated as one spoken turn (see `_turns`).
TURN_GAP_S = float(os.environ.get("TURN_GAP_S", "6"))

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
            for key, *_ in HOPS:
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
        for key in ("send_ms", "ttfa_ms", "ttft_ms", "first_send_ms", "total_ms"):
            measured = next((u[key] for u in group if u.get(key) is not None), None)
            if measured is not None:
                turn[key] = measured
        arrival = next((u["arrival_ts"] for u in group if u.get("arrival_ts")), None)
        if arrival:
            turn["arrival_ts"] = arrival
        turns.append(turn)
    return turns


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
        vals = [d[key] for d in durations if key in d]
        entry = {"key": key, "label": label, "description": description, "n": len(vals)}
        if vals:
            entry.update(min=min(vals), median=round(statistics.median(vals)), max=max(vals))
        stats[key] = entry
    totals = [u["total_ms"] for u in utterances if u.get("total_ms") is not None]
    if totals:
        stats["total"] = {"key": "total", "label": "Onset to hand-off", "n": len(totals),
                          "min": min(totals), "median": round(statistics.median(totals)),
                          "max": max(totals)}
    return stats


# --- API ---------------------------------------------------------------------
def _summary(directions: dict) -> dict:
    """One view of the whole call: how much of the delay is the model, and how much
    is everything we control. This is the headline the dashboard leads with."""
    turns = [t for d in directions.values() for t in d["utterances"]]
    durations = [_hop_durations(t) for t in turns]
    complete = [d for d in durations if len(d) == len(HOPS)]

    def median(vals):
        return round(statistics.median(vals)) if vals else None

    model = median([d["ttfa_ms"] for d in complete])
    bridge = median([d["send_ms"] + d["first_send_ms"] for d in complete])
    total = median([sum(d.values()) for d in complete])

    components = []
    for key, label, note, value in (
        ("model", "Gemini Live Translate", "Producing the translated audio", model),
        ("bridge", "Bridge", "Buffering audio in and handing it back out", bridge),
    ):
        entry = {"key": key, "label": label, "note": note, "median_ms": value}
        if value is not None and total:
            entry["share"] = round(value / total, 4)
        components.append(entry)

    return {"median_ms": total, "measured": len(complete), "turns": len(turns),
            "components": components}


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
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "console.html"))


@app.get("/dashboard")
def dashboard():
    return FileResponse(os.path.join(STATIC, "dashboard.html"))


@app.get("/static/{name}")
def static(name: str):
    path = os.path.join(STATIC, os.path.basename(name))
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path)
