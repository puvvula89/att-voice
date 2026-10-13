"""Re-extract a single tutorial into the device's JSON.
Usage: python one.py <device> <os> <slug>"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

import extract as X

dev, osv, slug = sys.argv[1:4]
href = f"#/tutorial/{dev}/{osv}/{slug}"
out = pathlib.Path(__file__).parent.parent / "raw" / f"{dev}.json"
data = json.loads(out.read_text())
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    rec = X.extract_one(pg, href, dev, osv)
    rec["category"] = "Common Issues & Fixes"
    data[rec["id"]] = rec
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(dev, "|", rec["title"], "| paths:", [(pp["choices"], len(pp["steps"])) for pp in rec.get("paths", [])], "| records:", len(data))
    b.close()
