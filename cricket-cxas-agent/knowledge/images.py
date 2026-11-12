"""Copy the tutorial step images into the private images bucket the chat channel serves them from.

    python -m knowledge.images sync     # copy every catalog image not yet in the bucket (content.sh runs it)

Each image is stored under a short name made from its source URL (image_name), which is also what the
data store records carry per step. The bucket stays private: the support server signs short-lived
links for the step being shown (support_mcp/tools_images.py).
"""
import hashlib
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

CATALOG = Path(__file__).parent / "catalog"
TYPES = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png"}


def image_name(url: str) -> str:
    """Short, stable object name for a source image URL: 16 hex of its hash plus the extension."""
    ext = url.rsplit(".", 1)[-1].lower()
    return f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.{ext}"


def bucket_name() -> str:
    load_dotenv(Path(__file__).parent.parent / ".env")
    project = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
    return os.environ.get("IMAGES_BUCKET") or f"{project}-cricket-tutorial-images"


def catalog_images() -> dict[str, str]:
    """{object name: source URL} for every step image in the catalog."""
    out = {}
    for f in sorted(CATALOG.glob("*.json")):
        for t in json.loads(f.read_text())["tutorials"]:
            for p in t["paths"]:
                for s in p["steps"]:
                    if s.get("image_url"):
                        out[image_name(s["image_url"])] = s["image_url"]
    return out


def sync(workers: int = 4) -> None:
    from google.cloud import storage

    bucket = storage.Client().bucket(bucket_name())
    have = {b.name for b in bucket.list_blobs()}
    todo = {n: u for n, u in catalog_images().items() if n not in have}
    print(f"{len(have)} in gs://{bucket.name}, {len(todo)} to copy")

    def copy(item):
        name, url = item
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read()
        bucket.blob(name).upload_from_string(data, content_type=TYPES.get(name.rsplit(".", 1)[-1], "image/jpeg"))

    failed = 0
    with ThreadPoolExecutor(workers) as pool:
        for i, result in enumerate(pool.map(lambda it: _try(copy, it), todo.items()), 1):
            failed += result is not None
            if result:
                print("failed", result)
            if i % 250 == 0:
                print(f"{i}/{len(todo)}")
    print(f"done: {len(todo) - failed} copied, {failed} failed")


def _try(fn, item):
    try:
        fn(item)
    except Exception as e:  # report and continue; a re-run copies only what is missing
        return f"{item[0]} {item[1]}: {e}"


if __name__ == "__main__":
    if sys.argv[1:] == ["sync"]:
        sync()
    else:
        sys.exit(__doc__)
