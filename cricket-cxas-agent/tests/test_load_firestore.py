import pathlib

from knowledge.catalog import read_catalog_dir
from knowledge.content_store import FirestoreSource
from knowledge.load_firestore import content_hash, content_version, doc_id, plan_upserts, write
from tests.fakes import FakeDB

CAT = pathlib.Path(__file__).parent.parent / "knowledge" / "catalog"
REC = {"device": "d", "id": "t1", "kind": "article", "title": "T", "intro": "", "url": "u", "category": "",
       "paths": [{"choices": [], "steps": []}]}


def test_hash_ignores_bookkeeping_fields():
    assert content_hash(REC) == content_hash({**REC, "content_hash": "x", "updated_at": "y"})
    assert content_hash(REC) != content_hash({**REC, "title": "Other"})


def test_plan_writes_changed_and_new_and_deletes_removed():
    other = {**REC, "id": "t2"}
    existing = {doc_id("d", "t1"): content_hash(REC), doc_id("d", "gone"): "h"}
    writes, deletes = plan_upserts([REC, other], existing)
    assert [i for i, _ in writes] == [doc_id("d", "t2")]
    assert deletes == [doc_id("d", "gone")]


def test_version_is_order_independent():
    assert content_version(["a", "b"]) == content_version(["b", "a"])


def test_written_content_reads_back_as_the_same_catalog():
    devices, tutorials = read_catalog_dir(CAT)
    db = FakeDB()
    write(db, devices, tutorials)
    src = FirestoreSource(db)
    assert src.version()
    assert src.load().search("galaxy-a15-5g", "texts won't send")[0]["kind"] == "article"


def test_second_write_with_no_changes_writes_nothing():
    devices, tutorials = read_catalog_dir(CAT)
    db = FakeDB()
    write(db, devices, tutorials)
    v = FirestoreSource(db).version()
    assert write(db, devices, tutorials) == (0, 0)
    assert FirestoreSource(db).version() == v
