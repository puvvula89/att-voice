import pathlib

import pytest

from knowledge.catalog import Catalog, read_catalog_dir
from knowledge.content_store import CatalogCache, LocalSource, make_source

CAT = pathlib.Path(__file__).parent.parent / "knowledge" / "catalog"


def test_from_records_matches_load():
    devices, tutorials = read_catalog_dir(CAT)
    a, b = Catalog.load(CAT), Catalog.from_records(devices, tutorials)
    assert a.devices() == b.devices()
    assert a.search("iphone-13", "can't make calls") == b.search("iphone-13", "can't make calls")


class FakeSource:
    def __init__(self):
        self.v, self.loads, self.fail_version = "1", 0, False

    def version(self):
        if self.fail_version:
            raise RuntimeError("store down")
        return self.v

    def load(self):
        self.loads += 1
        return Catalog.load(CAT)


def test_cache_reloads_only_when_version_changes_after_interval():
    src, now = FakeSource(), [0.0]
    cache = CatalogCache(src, check_every=60, clock=lambda: now[0])
    cache.get(); cache.get()
    assert src.loads == 1
    now[0] = 61; cache.get()
    assert src.loads == 1            # version unchanged
    src.v = "2"; now[0] = 70; cache.get()
    assert src.loads == 1            # interval not elapsed since last check
    now[0] = 122; cache.get()
    assert src.loads == 2


def test_cache_keeps_serving_when_version_check_fails():
    src, now = FakeSource(), [0.0]
    cache = CatalogCache(src, check_every=1, clock=lambda: now[0])
    first = cache.get()
    src.fail_version = True; now[0] = 5
    assert cache.get() is first


def test_cache_raises_when_nothing_ever_loaded():
    src = FakeSource(); src.fail_version = True
    with pytest.raises(RuntimeError):
        CatalogCache(src).get()


def test_make_source_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("CONTENT_BACKEND", "s3")
    with pytest.raises(ValueError):
        make_source()


def test_local_source_version_changes_with_files(tmp_path):
    (tmp_path / "a.json").write_text('{"device":"d","os":"1","label":"D","tutorials":[]}')
    src = LocalSource(tmp_path)
    assert src.version() != "0" and src.load().devices()[0]["device"] == "d"


def test_tools_return_error_when_content_unavailable(monkeypatch):
    from support_mcp import tools_procedures as P

    class Down:
        def get(self):
            raise RuntimeError("no content")

    monkeypatch.setattr(P, "_cache", Down())
    assert P.find_tutorials("iphone-13", "calls") == P.CONTENT_ERROR
    assert P.get_tutorial("iphone-13", "x") == P.CONTENT_ERROR


def test_send_guide_link_says_it_could_not_send_when_content_unavailable(monkeypatch):
    from support_mcp import tools_outreach as O
    from support_mcp import tools_procedures as P

    class Down:
        def get(self):
            raise RuntimeError("no content")

    monkeypatch.setattr(P, "_cache", Down())
    r = O.send_guide_link("cust_2001", "L1", "iphone-13", "x")
    assert r["sent"] is False and r["message"]
