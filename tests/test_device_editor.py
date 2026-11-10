import pytest
from pyqtgraph.Qt import QtWidgets

from acq4_tools.common.config_document import ConfigDocument, ConfigError, parse_text
from acq4_tools.tools.device_editor import AddDeviceDialog
from acq4_tools.tools.rig_analysis import (
    BOARD_MODELS,
    Terminal,
    analyze,
    channel_name,
    device_examples,
    read_alternates,
    read_boards,
    rename_device,
    write_alternates,
    write_boards,
)
from acq4_tools.tools.rig_config import RigConfigWindow

StandardButton = QtWidgets.QMessageBox.StandardButton

RIG = """# my rig
DAQ:
    driver: 'NiDAQ'
    defaultAIMode: 'nrse'  # the default

Stage:
    driver: 'MockStage'
    scale: 1.0, 1.0, 1.0  # to meters

Scope:
    driver: 'Microscope'
    parentDevice: 'Stage'

Amp:
    driver: 'DAQGeneric'
    mock: True
    channels:
        Cmd:
            device: 'DAQ'
            channel: '/Dev1/ao0'
            type: 'ao'

# An older camera
# Camera:
#     driver: 'PVCam'
#     parentDevice: 'Scope'
#     #comment: inside

# Laser:
#     driver: 'Laser'
#     power: 10*mW
"""


@pytest.fixture
def no_dialogs(monkeypatch):
    def fail(box):
        pytest.fail(f"unexpected dialog: {box.text()}")

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fail)


@pytest.fixture
def rig(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "devices.cfg"
    path.write_text(RIG, encoding="utf-8")
    window = RigConfigWindow()
    assert window.open_file(str(path))
    yield window, window.device_editor
    # Not registered with qtbot: it would close the window first, and the
    # question about unsaved changes would wait forever.
    window.saved_text = window.doc.text()
    window.close()
    window.deleteLater()


def select(editor, name, active=True):
    row = next(r for r, d in enumerate(editor.analysis.devices)
               if d.name == name and d.active == active)
    editor.table.selectRow(row)


def row_for(editor, *path):
    item = editor.tree.invisibleRootItem()
    for key in path:
        item = next(item.child(i) for i in range(item.childCount()) if item.child(i).text(0) == key)
    return item


def choose(editor, *path, text):
    combo = editor.tree.itemWidget(row_for(editor, *path), 1)
    combo.setCurrentText(text)
    combo.activated.emit(combo.currentIndex())


def values(window, *path):
    return window.doc.value(window.doc.node(*path))


# ------------------------------------------------------------------
# the document
# ------------------------------------------------------------------
def test_comment_and_uncomment_round_trip():
    doc = ConfigDocument(RIG)
    doc.comment_block(doc.node("Amp"))
    assert doc.node("Amp") is None
    assert "#         Cmd:" in doc.text()
    devices = analyze(doc).devices
    amp = next(d for d in devices if d.name == "Amp")
    doc.uncomment_lines(amp.start, amp.end, amp.base)
    assert doc.text() == RIG


def test_comment_round_trip_keeps_blank_and_whitespace_lines():
    text = "A:\n    driver: 'X'\n\n    y: 2\n        \n    z: 3\n"
    doc = ConfigDocument(text)
    doc.comment_block(doc.node("A"))
    device = analyze(doc).devices[0]
    doc.uncomment_lines(device.start, device.end, device.base)
    assert doc.text() == text


def test_failed_uncomment_leaves_the_file_alone():
    text = "A: 1\n# B:\n#   x: (\n"
    doc = ConfigDocument(text)
    with pytest.raises(ConfigError):
        doc.uncomment_lines(1, 3)
    assert doc.text() == text


def test_insert_block_goes_after_the_last_key():
    doc = ConfigDocument("A:\n    x: 1\n# trailing\n")
    doc.insert_block("B:\n    y: 2")
    assert doc.text() == "A:\n    x: 1\n\nB:\n    y: 2\n# trailing\n"
    assert doc.value(doc.node("B", "y")) == 2


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "terminal,name",
    [(Terminal("Dev1", "ai", 3), "/Dev1/ai3"), (Terminal("Dev2", "ao", 1), "/Dev2/ao1"),
     (Terminal("Dev1", "p0", 7), "/Dev1/port0/line7"), (Terminal("Dev1", "pfi", 2), "/Dev1/PFI2")],
)
def test_channel_names(terminal, name):
    assert channel_name(terminal) == name


def test_examples_cover_the_acq4_template():
    examples = device_examples()
    assert len(examples) == 50
    pvcam = next(e for e in examples if e.driver == "PVCam")
    text = pvcam.text_named("MyCam")
    assert text.startswith("MyCam:")
    assert parse_text(text)["MyCam"]["driver"] == "PVCam"


def test_rename_follows_every_reference():
    text = (
        "DAQ:\n    driver: 'NiDAQ'\n"
        "A:\n    driver: 'X'\n    channels:\n        c:\n            device: 'DAQ'\n"
        "            channel: '/Dev1/ai0'\n            type: 'ai'\n"
        "T:\n    driver: 'Trigger'\n    channels:\n        DAQ: '/Dev1/PFI1'\n"
    )
    doc = ConfigDocument(text)
    write_boards(doc, {"DAQ": BOARD_MODELS["6259"]})
    write_alternates(doc, [{"DAQ", "T"}])
    rename_device(doc, doc.node("DAQ"), "Board")
    doc.check()
    assert doc.value(doc.node("A", "channels", "c", "device")) == "Board"
    assert doc.value(doc.node("T", "channels", "Board")) == "/Dev1/PFI1"
    assert list(read_boards(doc)) == ["Board"]
    assert read_alternates(doc) == [{"Board", "T"}]


def test_rename_updates_parents_and_lists():
    text = (
        "S:\n    driver: 'X'\n"
        "M:\n    driver: 'X'\n    parentDevice: 'S'\n"
        "P:\n    driver: 'X'\n    recordingChambers: ['S', 'Z']\n"
        "Q:\n    driver: 'X'\n    objectiveSwitch: 'S', 'objective'\n"
    )
    doc = ConfigDocument(text)
    rename_device(doc, doc.node("S"), "Stage2")
    assert doc.value(doc.node("M", "parentDevice")) == "Stage2"
    assert doc.value(doc.node("P", "recordingChambers")) == ["Stage2", "Z"]
    assert doc.value(doc.node("Q", "objectiveSwitch")) == ("Stage2", "objective")


# ------------------------------------------------------------------
# the form
# ------------------------------------------------------------------
def test_opening_and_browsing_changes_nothing(rig):
    window, editor = rig
    for name in ("DAQ", "Stage", "Scope", "Amp"):
        select(editor, name)
    select(editor, "Camera", active=False)
    assert not window.is_dirty


def test_form_shows_the_settings(rig):
    _, editor = rig
    select(editor, "Amp")
    assert row_for(editor, "mock") is not None
    assert row_for(editor, "channels", "Cmd", "channel") is not None
    combo = editor.tree.itemWidget(row_for(editor, "channels", "Cmd", "type"), 1)
    assert combo.currentText() == "ao"


def test_editing_a_value_changes_one_line_and_keeps_its_comment(rig):
    window, editor = rig
    select(editor, "Stage")
    row_for(editor, "scale").setText(1, "2, 2, 2")
    assert window.doc.text() == RIG.replace("scale: 1.0, 1.0, 1.0", "scale: 2, 2, 2")
    assert window.is_dirty


def test_bare_text_is_quoted(rig):
    window, editor = rig
    select(editor, "Amp")
    item = row_for(editor, "mock")
    window.doc.set_value(window.doc.node("Amp", "mock"), 0)
    window.device_structure_changed()
    item = row_for(editor, "mock")
    item.setText(1, "/some/where")
    assert values(window, "Amp", "mock") == "/some/where"
    assert "stored as text" in window.statusBar().currentMessage()


def test_bool_setting_uses_a_choice(rig):
    window, editor = rig
    select(editor, "Amp")
    choose(editor, "mock", text="False")
    assert values(window, "Amp", "mock") is False


def test_parent_is_chosen_from_active_devices(rig):
    window, editor = rig
    select(editor, "Scope")
    combo = editor.tree.itemWidget(row_for(editor, "parentDevice"), 1)
    names = [combo.itemText(i) for i in range(combo.count())]
    assert "Amp" in names and "Scope" not in names and "Camera" not in names
    choose(editor, "parentDevice", text="Amp")
    assert values(window, "Scope", "parentDevice") == "Amp"


def test_parent_can_be_cleared_and_comes_back(rig):
    window, editor = rig
    select(editor, "Scope")
    choose(editor, "parentDevice", text="(none)")
    assert window.doc.node("Scope", "parentDevice") is None
    assert "# parentDevice: 'Stage'" in window.doc.text()


def test_channel_lines_offer_only_free_lines_of_the_right_kind(rig):
    window, editor = rig
    write_boards(window.doc, {"DAQ": BOARD_MODELS["6221"]})
    window.device_structure_changed()
    select(editor, "Amp")
    combo = editor.tree.itemWidget(row_for(editor, "channels", "Cmd", "channel"), 1)
    names = [combo.itemText(i) for i in range(combo.count())]
    assert names == ["/Dev1/ao0", "/Dev1/ao1"]
    choose(editor, "channels", "Cmd", "channel", text="/Dev1/ao1")
    assert values(window, "Amp", "channels", "Cmd", "channel") == "/Dev1/ao1"


def test_changing_type_updates_the_lines_offered(rig):
    window, editor = rig
    write_boards(window.doc, {"DAQ": BOARD_MODELS["6221"]})
    window.device_structure_changed()
    select(editor, "Amp")
    choose(editor, "channels", "Cmd", "type", text="ai")
    combo = editor.tree.itemWidget(row_for(editor, "channels", "Cmd", "channel"), 1)
    assert combo.itemText(1) == "/Dev1/ai0"
    assert combo.count() == 17


def test_edit_updates_the_checks(rig):
    window, editor = rig
    select(editor, "Scope")
    choose(editor, "parentDevice", text="Amp")
    found = [window.checks.item(i).text() for i in range(window.checks.count())]
    assert any("Scope is defined before its parent Amp" in line for line in found)


def test_rename_setting_refuses_a_duplicate(rig):
    window, editor = rig
    select(editor, "Amp")
    row_for(editor, "mock").setText(0, "channels")
    assert row_for(editor, "mock") is not None
    assert window.doc.text() == RIG


def test_add_and_remove_setting(rig):
    window, editor = rig
    select(editor, "Stage")
    assert editor.add_setting("fastSpeed")
    row_for(editor, "fastSpeed").setText(1, "3*mm/s")
    assert values(window, "Stage", "fastSpeed") == pytest.approx(3e-3)
    window.doc.check()
    editor.tree.setCurrentItem(row_for(editor, "fastSpeed"))
    editor.remove_setting()
    assert window.doc.node("Stage", "fastSpeed") is None
    assert window.doc.text() == RIG


def test_add_setting_goes_in_the_selected_section(rig):
    window, editor = rig
    select(editor, "Amp")
    editor.tree.setCurrentItem(row_for(editor, "channels", "Cmd"))
    assert editor.add_setting("units")
    assert window.doc.node("Amp", "channels", "Cmd", "units") is not None


def test_add_channel_uses_the_next_free_line(rig):
    window, editor = rig
    write_boards(window.doc, {"DAQ": BOARD_MODELS["6221"]})
    window.device_structure_changed()
    select(editor, "Amp")
    assert editor.add_channel("Signal")
    assert values(window, "Amp", "channels", "Signal") == {
        "device": "DAQ", "channel": "/Dev1/ai0", "type": "ai",
    }
    assert editor.add_channel("Signal2")
    assert values(window, "Amp", "channels", "Signal2", "channel") == "/Dev1/ai1"
    window.doc.check()


def test_add_channel_needs_a_daq(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "d.cfg"
    path.write_text("A:\n    driver: 'DAQGeneric'\n", encoding="utf-8")
    window = RigConfigWindow()
    qtbot.addWidget(window)
    window.open_file(str(path))
    assert not window.device_editor.add_channel("x")
    assert "active DAQ" in window.statusBar().currentMessage()


# ------------------------------------------------------------------
# devices
# ------------------------------------------------------------------
def test_commented_device_is_read_only_until_enabled(rig):
    _, editor = rig
    select(editor, "Camera", active=False)
    assert not editor.add_setting_button.isEnabled()
    assert editor.toggle_button.text() == "Enable"
    assert row_for(editor, "parentDevice").text(1) == "'Scope'"


def test_disable_and_enable_restore_the_text(rig):
    window, editor = rig
    select(editor, "Amp")
    editor.toggle_enabled()
    assert window.doc.node("Amp") is None
    assert editor.current_device().name == "Amp" and not editor.current_device().active
    editor.toggle_enabled()
    assert window.doc.text() == RIG
    assert editor.current_device().active


def test_enabling_uncomments_and_keeps_inner_comments(rig):
    window, editor = rig
    select(editor, "Camera", active=False)
    editor.toggle_enabled()
    assert values(window, "Camera", "driver") == "PVCam"
    assert "    #comment: inside" in window.doc.text()
    window.doc.check()


def answering(monkeypatch, button):
    asked = []

    def answer(box):
        asked.append(box.text())
        return button

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", answer)
    return asked


SWAP = RIG + """
# Stage:
#     driver: 'Scientifica'
#     port: 'com3'
"""


def swap_window(qtbot, tmp_path):
    path = tmp_path / "devices.cfg"
    path.write_text(SWAP, encoding="utf-8")
    window = RigConfigWindow()
    window.open_file(str(path))
    return window, window.device_editor


def close_quietly(window):
    window.saved_text = window.doc.text()
    window.close()
    window.deleteLater()


def test_enabling_a_device_with_an_active_name_swaps_after_asking(qtbot, tmp_path, monkeypatch):
    window, editor = swap_window(qtbot, tmp_path)
    asked = answering(monkeypatch, StandardButton.Ok)
    select(editor, "Stage", active=False)
    editor.toggle_enabled()
    assert len(asked) == 1
    assert values(window, "Stage", "driver") == "Scientifica"
    assert "# Stage:\n#     driver: 'MockStage'" in window.doc.text()
    window.doc.check()
    close_quietly(window)


def test_swap_can_be_cancelled(qtbot, tmp_path, monkeypatch):
    window, editor = swap_window(qtbot, tmp_path)
    answering(monkeypatch, StandardButton.Cancel)
    select(editor, "Stage", active=False)
    editor.toggle_enabled()
    assert window.doc.text() == SWAP
    close_quietly(window)


def test_rename_device_from_the_form(rig):
    window, editor = rig
    select(editor, "Stage")
    editor.name_edit.setText("XY")
    editor.name_edit.editingFinished.emit()
    assert values(window, "Scope", "parentDevice") == "XY"
    assert editor.current_device().name == "XY"
    assert "default.cfg" in window.statusBar().currentMessage()


def test_duplicate_device_name_is_refused(rig):
    window, editor = rig
    select(editor, "Stage")
    editor.name_edit.setText("DAQ")
    editor.name_edit.editingFinished.emit()
    assert editor.name_edit.text() == "Stage"
    assert window.doc.text() == RIG


def test_move_device_changes_the_file_order(rig):
    window, editor = rig
    select(editor, "Scope")
    editor.move_device(-1)
    assert [n.key for n in window.doc.root.children] == ["DAQ", "Scope", "Stage", "Amp"]
    found = [window.checks.item(i).text() for i in range(window.checks.count())]
    assert any("Scope is defined before its parent" in line for line in found)
    assert editor.current_device().name == "Scope"
    window.doc.check()


def test_add_blank_device(rig):
    window, editor = rig
    assert editor.add_device("Cam2", "MockCamera", None)
    assert values(window, "Cam2", "driver") == "MockCamera"
    assert editor.current_device().name == "Cam2"
    assert [n.key for n in window.doc.root.children][-1] == "Cam2"
    assert window.doc.text().index("Cam2") < window.doc.text().index("# An older camera")
    window.doc.check()


def test_add_device_from_an_example(rig):
    window, editor = rig
    example = next(e for e in device_examples() if e.driver == "PVCam")
    assert editor.add_device("Cam2", "PVCam", example)
    assert values(window, "Cam2", "exposeChannel", "type") == "di"
    window.doc.check()


@pytest.mark.parametrize("name", ["", "DAQ", "a:b"])
def test_add_device_refuses_a_bad_name(rig, name):
    window, editor = rig
    assert not editor.add_device(name, "X", None)
    assert window.doc.text() == RIG


def test_add_dialog_lists_examples_for_the_driver(qtbot):
    dialog = AddDeviceDialog(None, ["PVCam", "NoExample"], device_examples())
    qtbot.addWidget(dialog)
    dialog.driver.setCurrentText("PVCam")
    assert dialog.example.currentData().driver == "PVCam"
    dialog.driver.setCurrentText("NoExample")
    assert dialog.example.count() == 1 and dialog.example.currentData() is None


def test_remove_asks_first(rig, monkeypatch):
    window, editor = rig
    asked = answering(monkeypatch, StandardButton.Cancel)
    select(editor, "Amp")
    editor.remove_device()
    assert len(asked) == 1 and window.doc.node("Amp") is not None
    answering(monkeypatch, StandardButton.Ok)
    editor.remove_device()
    assert window.doc.node("Amp") is None
    window.doc.check()


def test_remove_commented_device_takes_only_its_lines(rig, monkeypatch):
    window, editor = rig
    answering(monkeypatch, StandardButton.Ok)
    select(editor, "Camera", active=False)
    editor.remove_device()
    assert "PVCam" not in window.doc.text()
    assert "# An older camera" in window.doc.text()
    assert "'Laser'" in window.doc.text()


def test_edits_save_and_reopen(rig):
    window, editor = rig
    select(editor, "Camera", active=False)
    editor.toggle_enabled()
    assert window.save()
    assert window.open_file(str(window.path))
    assert any(d.name == "Camera" and d.active for d in window.analysis.devices)


def test_revert_undoes_device_edits(rig):
    window, editor = rig
    select(editor, "Amp")
    editor.toggle_enabled()
    window.revert()
    assert window.doc.text() == RIG
    assert any(d.name == "Amp" and d.active for d in window.analysis.devices)
