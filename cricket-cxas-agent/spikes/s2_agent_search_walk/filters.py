"""Spike: how well does Agent Search find the right tutorial when step text is hidden?

  create <env> <catalog_dir>   two data stores with all tutorials:
                               spike-meta   searches title, summary, symptoms
                               spike-steps  also searches step text (not retrievable)
  score  <env> <catalog_dir>   run phrases.json against both stores (device filter on and off)
                               and against the current local search; print top-1 / top-3
  cleanup <env>                delete both data stores
"""
import base64
import hashlib
import zlib
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(sys.argv[2])
PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
COLL = f"projects/{PROJECT}/locations/global/collections/default_collection"
STORES = {"spike-meta": False, "spike-steps": True}
HERE = Path(__file__).parent


def schema(with_steps: bool) -> dict:
    s = lambda **k: {"type": "string", "retrievable": True, **k}  # noqa: E731
    props = {
        "title": s(searchable=True),
        "summary": s(searchable=True),
        "symptoms": {"type": "array", "items": s(searchable=True)},
        "category": s(searchable=True, indexable=True),
        "kind": s(indexable=True),
        "device": s(indexable=True),
        "tutorial_id": s(),
        "steps_b64": s(),
    }
    if with_steps:
        props["steps_text"] = {"type": "string", "searchable": True, "retrievable": False}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": props}


def records(catalog_dir: str):
    for f in sorted(Path(catalog_dir).glob("*.json")):
        cat = json.load(open(f))
        by_title = {t["title"]: t for t in cat["tutorials"]}
        for t in cat["tutorials"]:
            t = json.loads(json.dumps(t))
            for path in t["paths"]:
                for st in path["steps"]:
                    st["how_to"] = [{"title": x, "steps": [{"heading": y["heading"], "text": y["text"], "notes": y["notes"]}
                                                          for y in by_title[x]["paths"][0]["steps"]]}
                                    for x in st["links"] if x in by_title]
            yield {
                "device": cat["device"], "tutorial_id": t["id"], "kind": t["kind"], "title": t["title"],
                "category": t.get("category", ""), "summary": t.get("summary", ""),
                "symptoms": t.get("symptoms", []),
                "steps_b64": base64.urlsafe_b64encode(zlib.compress(json.dumps({"paths": t["paths"]}, ensure_ascii=False).encode(), 9)).decode(),
                "steps_text": " ".join(f"{s.get('heading', '')} {s['text']}" for p in t["paths"] for s in p["steps"]),
            }


def doc_id(r) -> str:
    return hashlib.sha1(f"{r['device']}/{r['tutorial_id']}".encode()).hexdigest()


def create(catalog_dir):
    from google.cloud import discoveryengine_v1 as de
    dsc, sc, docs = de.DataStoreServiceClient(), de.SchemaServiceClient(), de.DocumentServiceClient()
    recs = list(records(catalog_dir))
    print("records", len(recs))
    only = sys.argv[4] if len(sys.argv) > 4 else None
    for sid, with_steps in STORES.items():
        if only and sid != only:
            continue
        ds = f"{COLL}/dataStores/{sid}"
        try:
            dsc.create_data_store(parent=COLL, data_store_id=sid, data_store=de.DataStore(
                display_name=sid, industry_vertical=de.IndustryVertical.GENERIC,
                solution_types=[de.SolutionType.SOLUTION_TYPE_SEARCH],
                content_config=de.DataStore.ContentConfig.NO_CONTENT)).result(timeout=600)
            print(sid, "created")
        except Exception as e:  # noqa: BLE001
            print(sid, "create:", type(e).__name__, str(e)[:160])
        sc.update_schema(request=de.UpdateSchemaRequest(schema=de.Schema(name=f"{ds}/schemas/default_schema",
                                          json_schema=json.dumps(schema(with_steps))))).result(timeout=600)
        print(sid, "schema set")
        keep = None if with_steps else "steps_text"
        batch = [de.Document(id=doc_id(r), struct_data={k: v for k, v in r.items() if k != keep}) for r in recs]
        for i in range(0, len(batch), 100):
            op = docs.import_documents(de.ImportDocumentsRequest(
                parent=f"{ds}/branches/default_branch",
                inline_source=de.ImportDocumentsRequest.InlineSource(documents=batch[i:i + 100]),
                reconciliation_mode=de.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL))
            res = op.result(timeout=900)
            if res.error_samples:
                print("  errors", [e.message for e in res.error_samples[:3]])
        print(sid, "imported", len(batch))


def search(sid, q, device, use_filter, n=3):
    from google.cloud import discoveryengine_v1 as de
    req = de.SearchRequest(serving_config=f"{COLL}/dataStores/{sid}/servingConfigs/default_search",
                           query=q, page_size=n if use_filter else 10,
                           filter=f'device: ANY("{device}")' if use_filter else "")
    for i in range(5):
        try:
            res = de.SearchServiceClient().search(req)
            break
        except Exception as e:  # noqa: BLE001
            print("  retry", type(e).__name__, str(e)[:150]); time.sleep(10 * (i + 1))
    hits = [(r.document.struct_data["device"], r.document.struct_data["tutorial_id"]) for r in res.results]
    return [t for d, t in hits if d == device][:n]  # filter-off: count only the caller's device, as ranked


def score(catalog_dir):
    sys.path.insert(0, str(Path(catalog_dir).resolve().parents[1]))
    from knowledge.catalog import Catalog
    cat = Catalog.load(catalog_dir)
    phrases = json.load(open(HERE / "phrases.json"))
    variants = {"local (today)": lambda p: [r["id"] for r in cat.search(p["device"], p["q"], 3)]}
    for sid in STORES:
        variants[f"{sid} +filter"] = lambda p, s=sid: search(s, p["q"], p["device"], True)
        variants[f"{sid} no filter"] = lambda p, s=sid: search(s, p["q"], p["device"], False)
    out, rows = {}, []
    for name, fn in variants.items():
        top1 = top3 = 0
        for p in phrases:
            got = fn(p)
            ok = lambda t: any(t.startswith(o) for o in p["ok"])  # noqa: E731
            h1, h3 = bool(got) and ok(got[0]), any(ok(t) for t in got)
            top1, top3 = top1 + h1, top3 + h3
            rows.append({"variant": name, "q": p["q"], "device": p["device"], "top1": h1, "top3": h3, "got": got})
        out[name] = (top1, top3)
        print(f"{name:22s} top1 {top1}/{len(phrases)}  top3 {top3}/{len(phrases)}")
    json.dump(rows, open(HERE / "results.json", "w"), indent=1)


def cleanup():
    from google.cloud import discoveryengine_v1 as de
    for sid in STORES:
        de.DataStoreServiceClient().delete_data_store(name=f"{COLL}/dataStores/{sid}").result(timeout=600)
        print("deleted", sid)


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"create": lambda: create(sys.argv[3]), "score": lambda: score(sys.argv[3]), "cleanup": cleanup}[cmd]()
