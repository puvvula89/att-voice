import json

import pytest

from knowledge import load_datastore as ld

CAT = {"device": "iphone-13", "tutorials": [
    {"id": "wifi", "kind": "article", "title": "Wi-Fi slow", "summary": "Fix slow Wi-Fi.", "symptoms": ["wifi slow"],
     "paths": [{"choices": [], "steps": [
         {"n": 1, "heading": "Restart", "text": "Restart your iPhone.", "notes": [], "substeps": [], "options": [],
          "warning": None, "call_ending": True, "may_drop": False, "image_url": "x", "links": ["Power off"]}]}]},
    {"id": "power", "kind": "procedure", "title": "Power off", "paths": [{"choices": [], "steps": [
        {"n": 1, "heading": "", "text": "Hold the Side button.", "notes": [], "links": []}]}]}]}


def test_records_carry_compressed_steps_with_linked_how_to():
    recs = ld.records(CAT)
    assert [r["tutorial_id"] for r in recs] == ["wifi", "power"]
    step = ld.decode_steps(recs[0]["steps_b64"])["paths"][0]["steps"][0]
    assert step["how_to"] == [{"title": "Power off", "steps": [
        {"heading": "", "text": "Hold the Side button.", "notes": []}]}]
    assert step["call_ending"] is True and step["may_drop"] is False
    assert "image_url" not in step and "links" not in step


def test_records_reject_steps_too_large_for_the_search_tool(monkeypatch):
    monkeypatch.setattr(ld, "MAX_STEPS_B64", 10)
    with pytest.raises(ValueError, match="wifi"):
        ld.records(CAT)


def test_doc_id_is_stable_per_device_and_tutorial():
    r = ld.records(CAT)[0]
    assert ld.doc_id(r) == ld.doc_id(json.loads(json.dumps(r))) != ld.doc_id({**r, "device": "moto-g-2025"})


def test_whole_catalog_fits():
    for f in sorted(ld.CATALOG.glob("*.json")):
        ld.records(json.loads(f.read_text()))
