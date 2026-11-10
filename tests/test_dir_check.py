import pytest

from acq4_tools.common.acq4_index import index_text
from acq4_tools.tools.dir_check import (
    DirCheck,
    DirCheckWindow,
    ReportLine,
    build_pdf,
    find_pdflatex,
    report_latex,
    report_text,
)
from conftest import write_index


def run_check(top, **kwargs):
    lines = []
    flagged = DirCheck(top, lines.append, **kwargs).run()
    return flagged, report_text(lines), lines


def test_well_formed_day_has_no_problems(day_tree):
    flagged, text, _ = run_check(day_tree)
    assert flagged == 0
    assert "slice_000" in text and "cell_000" in text and "CCIV_000" in text


def test_parent_of_days_is_checked(day_tree):
    flagged, text, _ = run_check(day_tree.parent)
    assert flagged == 0
    assert str(day_tree) in text


def test_directories_above_the_day_level_are_descended(day_tree):
    top = day_tree.parent.parent
    flagged, text, _ = run_check(top)
    assert flagged == 0
    assert "CCIV_000" in text


def test_folder_with_no_days_is_flagged(tmp_path):
    (tmp_path / "top" / "stuff").mkdir(parents=True)
    flagged, text, _ = run_check(tmp_path / "top")
    assert flagged == 1
    assert "is not a DAY directory" in text


def test_non_slice_directory_is_flagged_and_scan_continues(day_tree):
    write_index(day_tree / "aaa_not_a_slice")
    flagged, text, _ = run_check(day_tree)
    assert flagged == 1
    assert "is not a SLICE directory" in text
    assert "CCIV_000" in text


def test_non_cell_directory_is_flagged(day_tree):
    (day_tree / "slice_000" / "misc").mkdir()
    flagged, text, _ = run_check(day_tree)
    assert flagged == 1
    assert "is not a CELL directory" in text


@pytest.mark.parametrize("name", ["FITC", "TRITC", "fitc"])
def test_label_directory_in_a_slice_is_accepted(day_tree, name):
    label = day_tree / "slice_000" / name
    write_index(label)
    (label / "image_000.tif").write_bytes(b"x")
    flagged, text, _ = run_check(day_tree)
    assert flagged == 0
    assert name in text


def test_directory_inside_a_label_directory_is_flagged(day_tree):
    write_index(day_tree / "slice_000" / "FITC" / "TRITC")
    flagged, text, _ = run_check(day_tree)
    assert flagged == 1
    assert "FITC/TRITC" in text


def test_missing_and_broken_indexes_are_flagged(day_tree):
    (day_tree / ".index").unlink()
    (day_tree / "slice_000" / "cell_000" / ".index").write_text(":::bad", encoding="utf-8")
    flagged, text, _ = run_check(day_tree)
    assert flagged == 2
    assert "No .index file" in text
    assert "Broken Index file" in text


def test_zero_length_data_file_is_flagged_and_scan_continues(day_tree):
    empty = day_tree / "slice_000" / "cell_000" / "CCIV_000" / "000" / "empty.ma"
    empty.write_bytes(b"")
    write_index(day_tree / "slice_000" / "cell_000" / "ZZZ_000")
    flagged, text, _ = run_check(day_tree)
    assert flagged == 1
    assert f"{empty} is empty" in text
    assert "ZZZ_000" in text


def test_date_filters(day_tree):
    assert "slice_000" not in run_check(day_tree, after="2024.3.6")[1]
    assert "slice_000" not in run_check(day_tree, before="2024.3.4")[1]
    assert "slice_000" in run_check(day_tree, after="2024.3.5", before="2024.3.5")[1]


def test_show_protocol_adds_protocol_index(day_tree):
    assert len(run_check(day_tree, show_protocol=True)[2]) > len(run_check(day_tree)[2])


def test_index_text_formats_timestamp_and_lists():
    text = index_text({".": {"__timestamp__": 1000.0, "values": [1, 2], "name": "x"}})
    assert "timestamp" in text
    assert "list/array, len=    2" in text
    assert "name" in text


def test_report_text_omits_page_breaks():
    lines = [ReportLine("a"), ReportLine(page_break=True), ReportLine("b")]
    assert report_text(lines) == "a\nb\n"


@pytest.mark.skipif(find_pdflatex() is None, reason="pdflatex is not installed")
def test_latex_report_compiles(day_tree, tmp_path):
    write_index(day_tree / "bad_name_%#&")
    lines = []
    DirCheck(day_tree, lines.append).run()
    lines.insert(0, ReportLine(page_break=True))
    tex = tmp_path / "report_x.tex"
    tex.write_text(report_latex(lines, "report_x.tex", "/a_b/c%d", "now"), encoding="utf-8")
    pdf = build_pdf(tex, find_pdflatex())
    assert pdf.stat().st_size > 1000
    assert not tex.with_suffix(".aux").exists()


def test_window_runs_and_shows_flags(qtbot, day_tree):
    (day_tree / "slice_000" / "misc").mkdir()
    window = DirCheckWindow()
    qtbot.addWidget(window)
    window.top_dir.setText(str(day_tree))
    window.start_check()
    qtbot.waitUntil(lambda: window.run_button.isEnabled(), timeout=5000)
    assert "is not a CELL directory" in window.output.toPlainText()
    assert "1 problem(s)" in window.statusBar().currentMessage()
    assert window.save_button.isEnabled()
    window.close()


def test_window_rejects_a_bad_date(qtbot, day_tree):
    window = DirCheckWindow()
    qtbot.addWidget(window)
    window.top_dir.setText(str(day_tree))
    window.after.setText("not a date")
    window.start_check()
    assert window.run_button.isEnabled()
    assert "Invalid date" in window.statusBar().currentMessage()
    window.close()
