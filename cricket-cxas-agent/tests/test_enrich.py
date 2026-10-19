from knowledge.enrich import Enricher, apply, unique_steps

REC = {"id": "t", "title": "Restart", "intro": "", "paths": [
    {"choices": ["A"], "steps": [
        {"n": 1, "text": "Hold the Side button to launch Gemini.", "call_ending": True},
        {"n": 2, "text": "Turn your phone off.", "call_ending": True}]},
    {"choices": ["B"], "steps": [
        {"n": 1, "text": "Hold the Side button to launch Gemini.", "call_ending": True},
        {"n": 2, "text": "Erase all content and settings.", "call_ending": False}]}]}

RESULT = {"summary": "Restart the phone.", "symptoms": ["phone frozen"], "steps": [
    {"n": 1, "call_ending": False, "reason": "launches an app"},
    {"n": 2, "call_ending": True, "reason": "powers off"},
    {"n": 3, "call_ending": True, "reason": "erases and restarts"}]}


def test_unique_steps_dedupes_across_branches_in_order():
    assert [s["text"][:4] for s in unique_steps(REC)] == ["Hold", "Turn", "Eras"]


def test_apply_overrides_flags_everywhere_and_reports_disagreements():
    rec, diffs = apply(REC, RESULT)
    assert rec["summary"] == "Restart the phone." and rec["symptoms"] == ["phone frozen"]
    assert [s["call_ending"] for p in rec["paths"] for s in p["steps"]] == [False, True, False, True]
    assert {(d["flag"], d["rule"], d["gemini"]) for d in diffs} == {
        ("call_ending", True, False), ("call_ending", False, True)}


def test_apply_keeps_rule_flags_for_steps_gemini_skipped():
    rec, _ = apply(REC, {"summary": "", "symptoms": [], "steps": []})
    assert rec["paths"][1]["steps"][1]["call_ending"] is False


def test_enricher_sends_numbered_unique_steps():
    seen = {}

    def fake(prompt):
        seen["p"] = prompt
        return RESULT

    out = Enricher(fake).label("iphone-13", REC)
    assert out == RESULT and "3. Erase all content" in seen["p"] and seen["p"].count("Hold the Side") == 1


def test_build_applies_cached_labels_only_when_the_hash_matches(tmp_path, monkeypatch):
    import json

    from knowledge import build_catalog, enrich
    monkeypatch.setattr(enrich, "OUT", tmp_path)
    raw = build_catalog.build_unlabelled("iphone-13")
    first, second = raw["tutorials"][0], raw["tutorials"][1]
    label = {"summary": "S", "symptoms": ["zz-unique-symptom"], "steps": []}
    (tmp_path / "iphone-13.json").write_text(json.dumps({
        first["id"]: {"hash": enrich.content_hash(first), "result": label},
        second["id"]: {"hash": "stale", "result": label}}))
    doc = build_catalog.build("iphone-13")
    by_id = {t["id"]: t for t in doc["tutorials"]}
    assert by_id[first["id"]]["symptoms"] == ["zz-unique-symptom"]
    assert "symptoms" not in by_id[second["id"]]


def test_symptoms_feed_search(tmp_path):
    from knowledge.catalog import Catalog
    rec = {"device": "d", "id": "t", "kind": "article", "title": "Battery", "intro": "", "url": "", "category": "",
           "paths": [{"choices": [], "steps": []}], "symptoms": ["phone dies by lunchtime"]}
    other = {**rec, "id": "u", "title": "Wi-Fi", "symptoms": []}
    cat = Catalog.from_records([{"device": "d", "os": "1", "label": "D"}], [rec, other])
    assert cat.search("d", "dies by lunchtime")[0]["id"] == "t"


def test_enrich_device_retries_rate_limits(tmp_path, monkeypatch):
    from google.genai import errors

    from knowledge import enrich
    monkeypatch.setattr(enrich, "OUT", tmp_path)
    monkeypatch.setattr(enrich.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] < 3:
            raise errors.ClientError(429, {"error": {"code": 429, "message": "busy", "status": "RESOURCE_EXHAUSTED"}})
        return RESULT

    cache = enrich.enrich_device("d", [REC], Enricher(flaky), workers=1)
    assert REC["id"] in cache and calls["n"] == 3


def test_enricher_sends_the_options_of_a_menu_prompt_step():
    seen = {}
    rec = {"id": "m", "title": "Reset", "intro": "", "paths": [{"choices": [], "steps": [
        {"n": 1, "text": "From this screen, you can perform a variety of actions:",
         "notes": ["Reset Network Settings - resets just your network settings."], "call_ending": True}]}]}
    Enricher(lambda p: seen.setdefault("p", p) and RESULT).label("iphone-13", rec)
    assert "actions: Reset Network Settings" in seen["p"]


def test_review_sets_risk_per_step_and_reports_stale_entries():
    from knowledge.build_catalog import apply_review
    rec = {"id": "t", "paths": [{"choices": [], "steps": [
        {"n": 1, "text": "Tap Delete eSIM again.", "call_ending": True, "may_drop": False},
        {"n": 2, "text": "Tap Delete eSIM again.", "call_ending": True, "may_drop": False},
        {"n": 3, "text": "Forget and rejoin Wi-Fi.", "call_ending": True, "may_drop": False}]}]}
    out, stale = apply_review(rec, [
        {"n": 1, "text": "Tap Delete eSIM again.", "risk": "safe"},
        {"n": 3, "text": "Forget and rejoin Wi-Fi.", "risk": "may_drop"},
        {"n": 4, "text": "Gone.", "risk": "drops"}])
    assert [(s["call_ending"], s["may_drop"]) for s in out["paths"][0]["steps"]] == [
        (False, False), (True, False), (False, True)]
    assert [e["n"] for e in stale] == [4]
