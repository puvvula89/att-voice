"""Extract device tutorials from the Cricket support site into structured JSON.

The tutorials are rendered client-side by the Ozmo device-help widget, so a
crawler sees nothing. This drives a headless browser, enumerates every tutorial
for a device, walks paginated articles, and emits one record per tutorial:

  {id, kind: "procedure"|"article", device, os, title, intro,
   steps: [{n, text, notes: [...], links: [{href, text}]}], url}

Usage:
  python extract.py enumerate <device-slug> <os>            # list only
  python extract.py extract   <device-slug> <os> [filter]   # filter: all|issues|<category text>
Output: out/<device-slug>.json (merged; re-runs update records in place)
"""
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://www.cricketwireless.com/support/device-tutorials"
OUT = Path(__file__).parent.parent / "raw"

STEPS_JS = r"""
() => {
  const lis = [...document.querySelectorAll('#step-list-scroll-container > ol > li')];
  return lis.map(li => {
    const substeps = [...li.querySelectorAll(':scope ol > li')].map(x => (x.querySelector('.step-text-container')||x).innerText.trim()).filter(Boolean);
    const btn = li.querySelector('.step-button');
    const n = btn && btn.dataset.step ? parseInt(btn.dataset.step) : null;
    const txtEl = li.querySelector(':scope .step-text-container') || btn || li;
    const text = txtEl.innerText.replace(/\s+\n/g,'\n').trim();
    const notes = [...li.querySelectorAll(':scope > ul li')].map(x => x.innerText.trim()).filter(Boolean);
    const links = [...li.querySelectorAll('button[aria-label^="View tutorial:"]')].map(b => b.getAttribute('aria-label').replace('View tutorial: ','').trim());
    const options = [...li.querySelectorAll('button.MuiButton-outlined, button.MuiButton-contained')]
      .map(b => b.innerText.trim()).filter(t => t && !t.startsWith('View tutorial'));
    return {n, text, notes, links, options, substeps};
  });
}
"""

IMAGE_JS = r"""
() => {
  const img = document.querySelector('#ocr-device-image-container img');
  return img ? (img.currentSrc || img.src || '').split('?')[0] : '';
}
"""


def capture_images(pg, steps):
    """Click each step button in turn and read the image shown for it."""
    for s in steps:
        s["image_url"] = ""
        if s["n"] is None:
            continue
        btn = pg.locator(
            f"#step-list-scroll-container > ol > li .step-button[data-step='{s['n']}']"
        ).first
        try:
            btn.click(timeout=2000)
            pg.wait_for_timeout(350)
            s["image_url"] = pg.evaluate(IMAGE_JS)
        except Exception:
            pass
    return steps


# Click a choice/next button by its visible label, scoped to the last step.
def click_option(pg, label):
    scope = pg.locator("#step-list-scroll-container > ol > li").last
    btn = scope.locator("button", has_text=label)
    if btn.count() == 0:
        btn = pg.locator("#step-list-scroll-container").locator("button", has_text=label)
    btn.last.click()
    pg.wait_for_timeout(900)


def walk_article(pg, href, max_paths=12):
    """Depth-first walk of an article. Returns a list of paths, each
    {choices:[labels], steps:[...]}; 'Next:' buttons are followed silently,
    multi-option prompts fork the path."""
    paths, pending = [], [[]]   # pending holds full click paths (Next clicks included)
    while pending and len(paths) < max_paths:
        clicks = pending.pop(0)
        goto(pg, href)
        for lbl in clicks:
            click_option(pg, lbl)
        forked = False
        seen = {}  # step index -> links/options observed while that step was active
        for _ in range(40):
            steps = pg.evaluate(STEPS_JS)
            if steps:
                cur = seen.setdefault(len(steps) - 1, {"links": [], "options": []})
                cur["links"] = sorted(set(cur["links"]) | set(steps[-1]["links"]))
                cur["options"] = steps[-1]["options"] or cur["options"]
            opts = steps[-1]["options"] if steps else []
            nexts = [o for o in opts if o.startswith("Next")]
            choices = [o for o in opts if not o.startswith("Next")]
            if nexts:
                click_option(pg, nexts[0]); clicks = clicks + [nexts[0]]
            elif len(choices) > 1:
                pending.extend(clicks + [c] for c in choices)
                forked = True
                break
            elif len(choices) == 1:
                click_option(pg, choices[0]); clicks = clicks + [choices[0]]
            else:
                break
        if not forked:
            final = capture_images(pg, pg.evaluate(STEPS_JS))
            for i, st in enumerate(final):
                if i in seen:
                    st["links"] = sorted(set(st["links"]) | set(seen[i]["links"]))
                    st["options"] = st["options"] or seen[i]["options"]
            chosen = [c for c in clicks if not c.startswith("Next")]
            paths.append({"choices": chosen, "steps": final})
    return paths

HEADER_JS = r"""
() => {
  const w = document.querySelector('.ozmo-global-wrapper') || document.body;
  const t = w.innerText;
  const crumbs = [...document.querySelectorAll('.ozmo-breadcrumbs li a, .ozmo-breadcrumbs li')].map(e => e.innerText.trim()).filter(Boolean);
  const title = crumbs.length ? crumbs[crumbs.length-1] : '';
  let intro = '';
  const i = t.indexOf(title), j = t.indexOf('Less info');
  if (i >= 0 && j > i) intro = t.slice(i + title.length, j).replace(/^[\s\S]*?\n(?=[A-Z])/,'').trim();
  return {title, intro, crumbs};
}
"""


def goto(pg, frag, attempts=3):
    for i in range(attempts):
        try:
            pg.goto(BASE + frag, wait_until="domcontentloaded")
            pg.wait_for_selector("a[href*='#/tutorial/']", state="attached", timeout=30000)
            pg.wait_for_timeout(1500)
            return
        except Exception:
            if i == attempts - 1:
                raise
            pg.wait_for_timeout(5000 * (i + 1))


def enumerate_device(pg, device, osv):
    goto(pg, f"#/tutorial/{device}/{osv}")
    # Expand "Show all" under Common Issues, then every category accordion.
    for el in pg.get_by_text("Show all", exact=True).all():
        try:
            el.click(timeout=1000); pg.wait_for_timeout(600)
        except Exception:
            pass
    heads = pg.eval_on_selector_all("h2,h3", "els => els.map(e => e.innerText.trim())")
    start = heads.index("Browse all support") + 1 if "Browse all support" in heads else 0
    stop = heads.index("Popular Articles") if "Popular Articles" in heads else len(heads)
    cats = [h for h in heads[start:stop] if h]
    links = {}
    for cat in cats:
        try:
            pg.get_by_text(cat, exact=True).first.click(timeout=1500)
            pg.wait_for_timeout(900)
        except Exception:
            continue
        for a in pg.eval_on_selector_all(
            "a[href*='#/tutorial/']",
            "els => els.map(a => [a.getAttribute('href'), a.innerText.trim().split('\\n').filter(Boolean)])",
        ):
            href, lines = a
            if not re.search(rf"#/tutorial/{re.escape(device)}/{re.escape(osv)}/.+", href):
                continue
            if href not in links:
                title = lines[-1] if lines else ""
                links[href] = {"title": title, "category": cat}
    return links


def kind_of(href):
    slug = href.rsplit("/", 1)[-1]
    return "procedure" if slug.startswith("feature_") else "article"


def extract_one(pg, href, device, osv):
    k = kind_of(href)
    paths = walk_article(pg, href) if k == "article" else None
    if paths is None:
        goto(pg, href)
    hdr = pg.evaluate(HEADER_JS)

    def clean(steps):
        for s in steps:
            s["text"] = re.sub(r"^\d+\s*-\s*", "", s["text"]).strip()
            s["text"] = re.sub(r"\nNext: .*$", "", s["text"]).strip()
        return steps

    rec = {
        "id": href.rsplit("/", 1)[-1], "kind": k, "device": device, "os": osv,
        "title": hdr["title"], "intro": hdr["intro"], "url": BASE + href,
    }
    if paths is None:
        rec["steps"] = clean(capture_images(pg, pg.evaluate(STEPS_JS)))
    else:
        for p in paths:
            clean(p["steps"])
        rec["paths"] = paths
        rec["steps"] = paths[0]["steps"]
    return rec


def main():
    cmd, device, osv = sys.argv[1], sys.argv[2], sys.argv[3]
    flt = sys.argv[4] if len(sys.argv) > 4 else "all"
    OUT.mkdir(exist_ok=True)
    out_path = OUT / f"{device}.json"
    data = json.loads(out_path.read_text()) if out_path.exists() else {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        links = enumerate_device(pg, device, osv)
        print(f"enumerated {len(links)} tutorials in {len(set(v['category'] for v in links.values()))} categories")
        if cmd == "enumerate":
            for h, v in links.items():
                print(f"{kind_of(h):9} | {v['category'][:28]:28} | {v['title'][:60]:60} | {h.rsplit('/',1)[-1]}")
            return
        todo = [h for h, v in links.items()
                if flt == "all" or (flt == "issues" and kind_of(h) == "article") or v["category"] == flt]
        t0 = time.time()
        for i, h in enumerate(todo, 1):
            try:
                rec = extract_one(pg, h, device, osv)
                rec["category"] = links[h]["category"]
                data[rec["id"]] = rec
                print(f"[{i}/{len(todo)}] {rec['kind']:9} {len(rec['steps']):2} steps  {rec['title'][:70]}")
            except Exception as e:  # keep going; report at end
                print(f"[{i}/{len(todo)}] FAILED {h}: {e}")
            out_path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        print(f"done {len(todo)} in {time.time()-t0:.0f}s -> {out_path} ({len(data)} records)")
        b.close()


if __name__ == "__main__":
    main()
