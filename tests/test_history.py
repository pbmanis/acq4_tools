import json

from acq4_tools.common.history import HistoryStore


def test_add_puts_newest_first_and_removes_duplicates(tmp_path):
    store = HistoryStore(tmp_path / "h.json")
    store.add("k", "a")
    store.add("k", "b")
    store.add("k", "a")
    assert store.get("k") == ["a", "b"]


def test_add_caps_entries(tmp_path):
    store = HistoryStore(tmp_path / "h.json")
    for i in range(5):
        store.add("k", str(i), max_entries=3)
    assert store.get("k") == ["4", "3", "2"]


def test_persists_across_instances_and_keys_are_separate(tmp_path):
    path = tmp_path / "h.json"
    HistoryStore(path).add("one", "/a")
    HistoryStore(path).add("two", "/b")
    assert HistoryStore(path).get("one") == ["/a"]
    assert HistoryStore(path).get("two") == ["/b"]


def test_remove(tmp_path):
    store = HistoryStore(tmp_path / "h.json")
    store.add("k", "a")
    store.add("k", "b")
    assert store.remove("k", "a") == ["b"]


def test_settings_do_not_disturb_history(tmp_path):
    store = HistoryStore(tmp_path / "h.json")
    store.add("k", "a")
    store.set_setting("flag", False)
    assert store.get_setting("flag") is False
    assert store.get_setting("absent", 3) == 3
    assert store.get("k") == ["a"]


def test_corrupt_file_is_set_aside(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("{not json", encoding="utf-8")
    store = HistoryStore(path)
    assert store.get("k") == []
    assert path.with_suffix(".corrupt").read_text(encoding="utf-8") == "{not json"
    store.add("k", "a")
    assert json.loads(path.read_text(encoding="utf-8"))["history"]["k"] == ["a"]
