"""Behavior of the two tools that were already graphical."""

import numpy as np
import pytest
import tifffile
from pyqtgraph import configfile

from acq4_tools.app import create_application
from acq4_tools.common.history import history_store
from acq4_tools.tools import fix_directory_order as FDO
from acq4_tools.tools import fix_objscale as FOS
from conftest import write_index


def write_image_protocol(directory, objective="4x 0.1na ACHROPLAN", scale=(1.0e-6, -1.0e-6, 1.0)):
    directory.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(directory / "image_000.tif", np.arange(100, dtype=np.uint16).reshape(10, 10))
    entry = {
        "__timestamp__": 1000.0,
        "objective": objective,
        "binning": (1, 1),
        "transform": {"scale": scale},
        "deviceTransform": {"scale": scale},
    }
    configfile.writeConfigFile({".": {"__timestamp__": 1000.0}, "image_000.tif": entry},
                               str(directory / ".index"))
    return directory


@pytest.fixture
def objscale(qtbot):
    create_application()
    tool = FOS.FixObjective(objective_data=FOS.load_objective_data())
    tool.set_window()
    qtbot.addWidget(tool.win)
    yield tool
    tool.win.close()


def test_objective_table_is_copied_for_the_user(objscale, isolated_config):
    assert (isolated_config / "fix_objective_data.cfg").is_file()
    assert "RetigaR1" in objscale.objective_data["Cameras"]
    assert "LastFile" not in objscale.objective_data


def test_quit_closes_only_the_window(objscale):
    closed = []
    objscale.win.closed.connect(lambda: closed.append(True))
    objscale.win.show()
    objscale.quit()
    assert closed == [True]


def test_opening_a_protocol_records_history(objscale, tmp_path):
    protocol = write_image_protocol(tmp_path / "2024.03.05_000" / "slice_000")
    objscale.getProtocolDir(recent_path=str(protocol))
    assert history_store().get(FOS._HISTORY_KEY) == [str(protocol)]
    assert objscale._current_file == "image_000.tif"


def test_unreadable_protocol_is_not_recorded(objscale, tmp_path):
    objscale.getProtocolDir(recent_path=str(tmp_path / "absent"))
    assert history_store().get(FOS._HISTORY_KEY) == []


def _choose_new_objective(tool, name):
    tool.ptreedata.param("New Objective").setValue(name)


def test_preview_does_not_write(objscale, tmp_path):
    protocol = write_image_protocol(tmp_path / "2024.03.05_000")
    before = (protocol / ".index").read_bytes()
    objscale.getProtocolDir(recent_path=str(protocol))
    _choose_new_objective(objscale, "40x 0.75na W ACHROPLAN")
    objscale.view_proposed_changes(write=False)
    assert (protocol / ".index").read_bytes() == before
    assert "NOT modified" in objscale.change_text.toPlainText()


def test_apply_writes_new_scale_and_note(objscale, tmp_path):
    protocol = write_image_protocol(tmp_path / "2024.03.05_000")
    objscale.getProtocolDir(recent_path=str(protocol))
    _choose_new_objective(objscale, "40x 0.75na W ACHROPLAN")
    objscale.view_proposed_changes(write=True)
    entry = configfile.readConfigFile(str(protocol / ".index"))["image_000.tif"]
    assert entry["objective"] == "40x 0.75na W ACHROPLAN"
    assert entry["transform"]["scale"][0] == pytest.approx(objscale.pixelsize / 40.0)
    assert entry["deviceTransform"]["scale"][1] == pytest.approx(-objscale.pixelsize / 40.0)
    assert "4x 0.1na ACHROPLAN" in entry["note"]


@pytest.fixture
def dir_order(qtbot):
    create_application()
    tool = FDO.FixDirectoryOrder()
    tool.set_window()
    qtbot.addWidget(tool.win)
    yield tool
    tool.win.close()


def test_clean_day_needs_no_changes(dir_order, day_tree):
    dir_order.load_day(day_tree)
    assert FDO.FixDirectoryOrder._count_problems(dir_order.model) == 0
    assert "No reordering required" in dir_order.banner.text()
    assert history_store().get(FDO._HISTORY_KEY) == [str(day_tree)]


def test_choosing_a_subdirectory_resolves_to_its_day(dir_order, day_tree):
    dir_order.load_day(day_tree / "slice_000" / "cell_000")
    assert dir_order.day_dir == day_tree


def test_not_a_day_is_reported(dir_order, tmp_path):
    dir_order.load_day(tmp_path)
    assert dir_order.day_dir is None
    assert "Not an acq4 day" in dir_order.status_path.text()
    assert history_store().get(FDO._HISTORY_KEY) == []


def test_misplaced_cell_is_relocated_under_preceding_slice(dir_order, day_tree):
    write_index(day_tree / "slice_001", 2000.0)
    write_index(day_tree / "cell_001", 2500.0)
    dir_order.load_day(day_tree)
    assert FDO.FixDirectoryOrder._count_problems(dir_order.model) == 1
    slices = {p.source.name: p for p in dir_order.proposed.children
              if p.source.kind == "slice"}
    moved = [c for c in slices["slice_001"].children if c.source.name == "cell_001"]
    assert moved and moved[0].change == "relocate"
    assert dir_order._arrow_pairs


def test_name_collision_at_destination_is_a_conflict(dir_order, day_tree):
    write_index(day_tree / "cell_000", 1500.0)
    dir_order.load_day(day_tree)
    slice_node = next(p for p in dir_order.proposed.children if p.source.kind == "slice")
    assert "conflict" in [c.change for c in slice_node.children]


def test_nested_label_is_hoisted(dir_order, day_tree):
    write_index(day_tree / "slice_000" / "FITC", 1150.0)
    write_index(day_tree / "slice_000" / "FITC" / "TRITC", 1160.0)
    dir_order.load_day(day_tree)
    slice_node = next(p for p in dir_order.proposed.children if p.source.kind == "slice")
    assert ("TRITC", "hoist") in [(c.source.name, c.change) for c in slice_node.children]


def test_directory_order_never_changes_the_tree(dir_order, day_tree):
    write_index(day_tree / "cell_001", 2500.0)
    before = sorted(str(p) for p in day_tree.rglob("*"))
    dir_order.load_day(day_tree)
    assert sorted(str(p) for p in day_tree.rglob("*")) == before
