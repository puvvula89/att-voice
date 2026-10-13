import json, pathlib
RAW = pathlib.Path(__file__).parent.parent / "knowledge" / "raw"

def test_every_step_has_image_url_key():
    for f in RAW.glob("*.json"):
        for rec in json.loads(f.read_text()).values():
            for s in rec["steps"]:
                assert "image_url" in s, f"{f.name}:{rec['id']} step {s['n']}"
