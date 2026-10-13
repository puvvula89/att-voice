import pathlib

import pytest

from knowledge.catalog import Catalog

CAT = pathlib.Path(__file__).parent.parent / "knowledge" / "catalog"


@pytest.fixture(scope="module")
def cat():
    return Catalog.load(CAT)


def test_four_devices(cat):
    assert {d["device"] for d in cat.devices()} == {
        "iphone-13", "moto-g-2025", "moto-g-stylus-5g-2024", "galaxy-a15-5g"}


def test_symptom_search_finds_calls_article_on_every_device(cat):
    for d in cat.devices():
        top = cat.search(d["device"], "I can't make calls")[0]
        assert top["kind"] == "article" and "calls" in top["title"].lower(), d


def test_platform_wording_does_not_leak_across_devices(cat):
    top = cat.search("galaxy-a15-5g", "my messages won't send")[0]
    assert top["kind"] == "article" and "text" in top["title"].lower()
    top = cat.search("iphone-13", "my texts won't send")[0]
    assert top["kind"] == "article" and "message" in top["title"].lower()


def test_get_returns_single_path_for_procedure(cat):
    t = cat.get("iphone-13", "feature_network_reset-resetting-your-iphone-s-settings-and-network-settings")
    assert t.kind == "procedure" and len(t.paths) == 1 and t.paths[0].choices == []
    assert [s["n"] for s in t.paths[0].steps] == [1, 2, 3, 4, 5]


def test_get_unknown_device_raises(cat):
    with pytest.raises(KeyError):
        cat.get("pixel-9", "anything")
