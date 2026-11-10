import tarfile

import pytest
from pyqtgraph.Qt import QtWidgets

from acq4_tools.tools import day_slice_archive as DSA
from conftest import write_index


@pytest.fixture
def archive_tree(day_tree):
    """Adds slice-level media, a label directory, and files to be left out."""
    slice_dir = day_tree / "slice_000"
    (slice_dir / "image_000.tif").write_bytes(b"image")
    write_index(slice_dir / "FITC")
    (slice_dir / "FITC" / "video_000.ma").write_bytes(b"video")
    (slice_dir / ".DS_Store").write_bytes(b"junk")
    (slice_dir / "._image_000.tif").write_bytes(b"junk")
    (day_tree / "log.txt").write_text("day-level log", encoding="utf-8")
    return day_tree


def names(tar_path):
    with tarfile.open(tar_path) as tar:
        return set(tar.getnames())


DAY = "2024.03.05_000"
EXPECTED = {
    DAY,
    f"{DAY}/.index",
    f"{DAY}/slice_000",
    f"{DAY}/slice_000/.index",
    f"{DAY}/slice_000/image_000.tif",
    f"{DAY}/slice_000/FITC",
    f"{DAY}/slice_000/FITC/.index",
    f"{DAY}/slice_000/FITC/video_000.ma",
}


def test_archive_of_a_day_has_day_index_slice_and_labels_but_no_cells(archive_tree, tmp_path):
    output = tmp_path / "out.tar"
    DSA.write_archive(DSA.plan_archive(archive_tree), output)
    assert names(output) == EXPECTED


def test_archive_of_a_parent_keeps_the_chosen_directory_name(archive_tree, tmp_path):
    output = tmp_path / "out.tar"
    DSA.write_archive(DSA.plan_archive(archive_tree.parent), output)
    assert names(output) == {f"data/{name}" for name in EXPECTED}


def test_days_are_found_at_any_depth(day_tree):
    top = day_tree.parent.parent
    assert DSA.find_day_dirs(top) == [day_tree]


def test_contents_are_returned_with_sizes(archive_tree, tmp_path):
    contents = dict(DSA.write_archive(DSA.plan_archive(archive_tree), tmp_path / "o.tar"))
    assert contents[f"{DAY}/slice_000/image_000.tif"] == 5


def test_directories_precede_their_files(archive_tree, tmp_path):
    output = tmp_path / "out.tar"
    DSA.write_archive(DSA.plan_archive(archive_tree), output)
    with tarfile.open(output) as tar:
        order = tar.getnames()
    assert order.index(DAY) < order.index(f"{DAY}/.index")
    assert order.index(f"{DAY}/slice_000/FITC") < order.index(f"{DAY}/slice_000/FITC/.index")


def test_missing_index_files_are_reported(archive_tree):
    (archive_tree / ".index").unlink()
    (archive_tree / "slice_000" / ".index").unlink()
    plan = DSA.plan_archive(archive_tree)
    assert plan.missing_index == [archive_tree, archive_tree / "slice_000"]


def test_output_inside_the_tree_is_not_archived_into_itself(archive_tree):
    output = archive_tree / "slice_000" / "out.tar"
    output.write_bytes(b"previous")
    plan = DSA.plan_archive(archive_tree)
    assert output in plan.members
    DSA.write_archive(plan, output)
    assert f"{DAY}/slice_000/out.tar" not in names(output)


def test_cancel_leaves_no_output(archive_tree, tmp_path):
    class Stop(Exception):
        pass

    calls = []

    def check():
        calls.append(1)
        if len(calls) > 2:
            raise Stop

    output = tmp_path / "out.tar"
    with pytest.raises(Stop):
        DSA.write_archive(DSA.plan_archive(archive_tree), output, check=check)
    assert list(tmp_path.glob("out.tar*")) == []


def test_source_data_are_not_changed(archive_tree, tmp_path):
    before = sorted(str(p) for p in archive_tree.rglob("*"))
    DSA.write_archive(DSA.plan_archive(archive_tree), tmp_path / "out.tar")
    assert sorted(str(p) for p in archive_tree.rglob("*")) == before


def test_window_writes_archive_and_lists_contents(qtbot, archive_tree, tmp_path, monkeypatch):
    output = tmp_path / "out.tar"
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(output), "")
    )
    window = DSA.DaySliceArchiveWindow()
    qtbot.addWidget(window)
    window.top_dir.setText(str(archive_tree))
    window.start_archive()
    qtbot.waitUntil(lambda: window.make_button.isEnabled(), timeout=5000)
    assert names(output) == EXPECTED
    assert f"{DAY}/.index" in window.output.toPlainText()
    assert "8 items" in window.statusBar().currentMessage()
    window.close()
