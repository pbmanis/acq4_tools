import pytest
from pyqtgraph.Qt import QtWidgets

from acq4_tools.tools.empty_index import (
    EmptyIndexWindow,
    directory_level,
    find_small_index_files,
)


def test_finds_empty_index_at_every_level(day_tree):
    targets = [
        day_tree / "slice_000" / ".index",
        day_tree / "slice_000" / "cell_000" / "CCIV_000" / "000" / ".index",
    ]
    for target in targets:
        target.write_text("", encoding="utf-8")
    findings = find_small_index_files(day_tree.parent)
    assert sorted(f.path for f in findings) == sorted(targets)
    assert sorted(f.level for f in findings) == ["protocol run", "slice"]


def test_threshold_and_appledouble_files(day_tree):
    (day_tree / "._.index").write_bytes(b"")  # macOS sidecar, not an index
    (day_tree / ".index").write_text("12345", encoding="utf-8")
    assert [f.size for f in find_small_index_files(day_tree, threshold=6)] == [5]
    assert find_small_index_files(day_tree, threshold=5) == []


def test_check_callback_can_stop_the_walk(day_tree):
    class Stop(Exception):
        pass

    def check():
        raise Stop

    with pytest.raises(Stop):
        find_small_index_files(day_tree, check=check)


@pytest.mark.parametrize(
    "name,level",
    [("2024.03.05_000", "day"), ("slice_001", "slice"), ("cell_002", "cell"),
     ("pair_000", "cell"), ("000", "protocol run"), ("000_001", "protocol run"),
     ("CCIV_000", "protocol/other")],
)
def test_directory_level(name, level):
    assert directory_level(name) == level


def test_window_scans_and_remembers_directory(qtbot, day_tree):
    (day_tree / "slice_000" / ".index").write_text("", encoding="utf-8")
    window = EmptyIndexWindow()
    qtbot.addWidget(window)
    window.top_dir.setText(str(day_tree))
    window.start_scan()
    qtbot.waitUntil(lambda: window.scan_button.isEnabled(), timeout=5000)
    assert window.table.rowCount() == 1
    assert window.table.item(0, 2).text() == "slice"
    assert str(day_tree) in [window.top_dir.combo.itemText(i)
                             for i in range(window.top_dir.combo.count())]
    window.close()


def test_window_reports_a_bad_directory(qtbot, tmp_path):
    window = EmptyIndexWindow()
    qtbot.addWidget(window)
    window.top_dir.setText(str(tmp_path / "absent"))
    window.start_scan()
    assert window.scan_button.isEnabled()
    assert "Not a directory" in window.statusBar().currentMessage()
    window.close()
