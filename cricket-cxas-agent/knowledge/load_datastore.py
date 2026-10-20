"""Load the tutorial catalog into the Agent Search data store the agent searches.

    python -m knowledge.load_datastore create   # data store and schema (idempotent; prep runs it)
    python -m knowledge.load_datastore load     # upsert every tutorial, delete removed ones
    python -m knowledge.load_datastore delete   # remove the data store (teardown runs it)

One document per tutorial. Search runs on title, summary, symptoms and category; `device` and `kind`
filter; `url` is the public guide the agent can text. The steps travel in `steps_b64` (zlib + url-safe
base64 JSON), which the agent's search callback decodes; the model never sees it. Each step carries
the steps of the tutorials it links to as `how_to`, so the agent can explain "how do I restart it?"
from our content.
"""
import base64
import hashlib
import json
import os
import sys
import zlib
from pathlib import Path

from dotenv import load_dotenv

CATALOG = Path(__file__).parent / "catalog"
# The data store tool silently drops a result whose record is about 16 KB; stay well below.
MAX_STEPS_B64 = 12_000
STEP_FIELDS = ("n", "heading", "text", "notes", "substeps", "options", "warning", "call_ending", "may_drop")


def _env():
    load_dotenv(Path(__file__).parent.parent / ".env")
    project = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
    coll = f"projects/{project}/locations/global/collections/default_collection"
    return coll, f"{coll}/dataStores/{os.environ.get('DATASTORE_ID', 'cricket-tutorials')}"


def schema() -> dict:
    s = lambda **k: {"type": "string", "retrievable": True, **k}  # noqa: E731
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": {
        "title": s(searchable=True),
        "summary": s(searchable=True),
        "symptoms": {"type": "array", "items": s(searchable=True)},
        "category": s(searchable=True, indexable=True),
        "kind": s(indexable=True),
        "device": s(indexable=True),
        "tutorial_id": s(),
        "url": s(),
        "steps_b64": s(),
    }}


def encode_steps(paths: list) -> str:
    return base64.urlsafe_b64encode(zlib.compress(json.dumps({"paths": paths}, ensure_ascii=False).encode(), 9)).decode()


def decode_steps(b64: str) -> dict:
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(b64)).decode())


def records(cat: dict) -> list[dict]:
    """The data store documents for one device's catalog."""
    by_title = {t["title"]: t for t in cat["tutorials"]}
    out = []
    for t in cat["tutorials"]:
        paths = []
        for p in t["paths"]:
            steps = []
            for s in p["steps"]:
                step = {k: s[k] for k in STEP_FIELDS if k in s}
                step["how_to"] = [{"title": x, "steps": [{"heading": y["heading"], "text": y["text"], "notes": y["notes"]}
                                                       for y in by_title[x]["paths"][0]["steps"]]}
                                  for x in s.get("links", []) if x in by_title]
                steps.append(step)
            paths.append({"choices": p["choices"], "steps": steps})
        b64 = encode_steps(paths)
        if len(b64) > MAX_STEPS_B64:
            raise ValueError(f"{cat['device']}/{t['id']}: steps are {len(b64)} bytes encoded, over {MAX_STEPS_B64}")
        out.append({"device": cat["device"], "tutorial_id": t["id"], "kind": t["kind"], "title": t["title"],
                    "category": t.get("category", ""), "summary": t.get("summary", ""),
                    "symptoms": t.get("symptoms", []), "url": t.get("url", ""), "steps_b64": b64})
    return out


def doc_id(rec: dict) -> str:
    return hashlib.sha1(f"{rec['device']}/{rec['tutorial_id']}".encode()).hexdigest()


def create() -> None:
    from google.api_core import exceptions as gax
    from google.cloud import discoveryengine_v1 as de
    coll, ds = _env()
    try:
        de.DataStoreServiceClient().create_data_store(parent=coll, data_store_id=ds.rsplit("/", 1)[-1], data_store=de.DataStore(
            display_name=ds.rsplit("/", 1)[-1], industry_vertical=de.IndustryVertical.GENERIC,
            solution_types=[de.SolutionType.SOLUTION_TYPE_SEARCH],
            content_config=de.DataStore.ContentConfig.NO_CONTENT)).result(timeout=600)
        print("created", ds)
    except gax.AlreadyExists:
        print("exists", ds)
    de.SchemaServiceClient().update_schema(request=de.UpdateSchemaRequest(schema=de.Schema(
        name=f"{ds}/schemas/default_schema", json_schema=json.dumps(schema())))).result(timeout=600)
    print("schema set")


def load(catalog_dir: Path = CATALOG) -> None:
    from google.cloud import discoveryengine_v1 as de
    _, ds = _env()
    branch = f"{ds}/branches/default_branch"
    recs = [r for f in sorted(catalog_dir.glob("*.json")) for r in records(json.loads(f.read_text()))]
    docs = de.DocumentServiceClient()
    batch = [de.Document(id=doc_id(r), struct_data=r) for r in recs]
    for i in range(0, len(batch), 100):
        res = docs.import_documents(de.ImportDocumentsRequest(
            parent=branch, inline_source=de.ImportDocumentsRequest.InlineSource(documents=batch[i:i + 100]),
            reconciliation_mode=de.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL)).result(timeout=900)
        if res.error_samples:
            sys.exit(f"import failed: {[e.message for e in res.error_samples[:3]]}")
    keep = {d.id for d in batch}
    gone = [d.name for d in docs.list_documents(parent=branch) if d.id not in keep]
    for name in gone:
        docs.delete_document(name=name)
    print(f"loaded {len(batch)} tutorials, removed {len(gone)}; search sees changes within a few minutes")


def delete() -> None:
    from google.api_core import exceptions as gax
    from google.cloud import discoveryengine_v1 as de
    _, ds = _env()
    try:
        de.DataStoreServiceClient().delete_data_store(name=ds).result(timeout=600)
        print("deleted", ds)
    except gax.NotFound:
        print("not found", ds)


if __name__ == "__main__":
    {"create": create, "load": load, "delete": delete}[sys.argv[1] if len(sys.argv) > 1 else "load"]()
