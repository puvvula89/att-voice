"""Publish the architecture as an editable Google Slides deck and export it as .pptx.

Uses the Google Workspace CLI (`gws`), logged in with the presentations and drive.file scopes.

    python3 slides.py icons  --out <icon-urls.json>                 # upload icons/png, write name -> URL map
    python3 slides.py apply  --requests slides-requests.json [--presentation <id>]   # create or rebuild the deck
    python3 slides.py thumb  --presentation <id> --out <file.png>   # render the slide for checking
    python3 slides.py export --presentation <id> --out architecture.pptx

The Slides API fetches images by URL, so `icons` uploads each PNG to a Drive folder with anyone-with-link read
access. The deck copies the bytes in; the folder can be deleted once the deck is built.
"""
import argparse
import json
import pathlib
import subprocess
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent


def gws(*args, cwd=None):
    out = subprocess.run(["gws", *args], capture_output=True, text=True, cwd=cwd)
    body = "\n".join(l for l in out.stdout.splitlines() if "keyring" not in l)
    d = json.loads(body) if body.strip() else {}
    if isinstance(d, dict) and "error" in d:
        raise SystemExit(json.dumps(d["error"], indent=1))
    return d


def cmd_icons(a):
    out = pathlib.Path(a.out)
    urls = json.loads(out.read_text()) if out.exists() else {}
    folder = urls.get("_folder") or gws("drive", "files", "create", "--json", json.dumps(
        {"name": a.folder, "mimeType": "application/vnd.google-apps.folder"}))["id"]
    urls["_folder"] = folder
    for png in sorted((HERE / "icons" / "png").glob("*.png")):
        if png.stem in urls:
            continue
        f = gws("drive", "files", "create", "--json", json.dumps({"name": png.name, "parents": [folder]}),
                "--upload", png.name, cwd=png.parent)
        gws("drive", "permissions", "create", "--params", json.dumps({"fileId": f["id"]}),
            "--json", json.dumps({"role": "reader", "type": "anyone"}))
        urls[png.stem] = f"https://drive.google.com/uc?export=view&id={f['id']}"
        print("uploaded", png.stem)
    out.write_text(json.dumps(urls, indent=1))
    print(f"{len(urls) - 1} icons mapped in {out}")


def cmd_apply(a):
    body = json.loads(pathlib.Path(a.requests).read_text())
    pid = a.presentation or gws("slides", "presentations", "create", "--json", json.dumps({"title": a.title}))["presentationId"]
    cur = gws("slides", "presentations", "get", "--params", json.dumps({"presentationId": pid, "fields": "slides.objectId"}))
    dels = [{"deleteObject": {"objectId": s["objectId"]}} for s in cur.get("slides", [])]
    gws("slides", "presentations", "batchUpdate", "--params", json.dumps({"presentationId": pid}),
        "--json", json.dumps({"requests": dels + body["requests"]}))
    print(f"https://docs.google.com/presentation/d/{pid}/edit")


def cmd_thumb(a):
    pres = gws("slides", "presentations", "get", "--params", json.dumps({"presentationId": a.presentation, "fields": "slides.objectId"}))
    page = pres["slides"][0]["objectId"]
    t = gws("slides", "presentations", "pages", "getThumbnail", "--params", json.dumps(
        {"presentationId": a.presentation, "pageObjectId": page, "thumbnailProperties.thumbnailSize": "LARGE"}))
    pathlib.Path(a.out).write_bytes(urllib.request.urlopen(t["contentUrl"], timeout=60).read())
    print("wrote", a.out)


def cmd_export(a):
    out = pathlib.Path(a.out).resolve()
    subprocess.run(["gws", "drive", "files", "export", "--params", json.dumps(
        {"fileId": a.presentation, "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}),
        "-o", str(out)], check=True, capture_output=True)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("icons"); p.add_argument("--out", required=True); p.add_argument("--folder", default="architecture-icons")
    p.set_defaults(fn=cmd_icons)
    p = sub.add_parser("apply"); p.add_argument("--requests", required=True); p.add_argument("--presentation")
    p.add_argument("--title", default="Cricket Care Troubleshooting Agent - Architecture"); p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("thumb"); p.add_argument("--presentation", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_thumb)
    p = sub.add_parser("export"); p.add_argument("--presentation", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_export)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
