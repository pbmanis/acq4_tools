import pytest
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from acq4_tools.common.acq4_source import NAMED, NOT_FOUND, READ, scan_acq4_devices
from acq4_tools.common.config_document import ConfigDocument, read_config_text
from acq4_tools.common.paths import packaged_data
from acq4_tools.tools.rig_analysis import (
    BOARD_MODELS,
    Board,
    Terminal,
    analyze,
    find_commented_devices,
    parse_terminal,
    read_alternates,
    read_boards,
    write_alternates,
    write_boards,
)
from acq4_tools.tools.rig_config import RigConfigWindow
from acq4_tools.tools.wiring_diagram import (
    KIND_COLORS,
    LINE_PATTERNS,
    PROBLEM,
    terminal_order,
)

BOARD = BOARD_MODELS["6259"]

DAQ = "DAQ:\n    driver: 'NiDAQ'\n    defaultAIMode: 'NRSE'\n"


def channel(name, line, kind, indent=8, **extra):
    pad = " " * indent
    text = f"{pad}{name}:\n{pad}    device: 'DAQ'\n{pad}    channel: '{line}'\n"
    text += f"{pad}    type: '{kind}'\n"
    return text + "".join(f"{pad}    {k}: {v!r}\n" for k, v in extra.items())


def generic(name, *channels):
    return f"{name}:\n    driver: 'DAQGeneric'\n    channels:\n" + "".join(channels)


SOURCE = {
    "Device.py": "class Device:\n    pass\n",
    "OptomechDevice.py": (
        "from Device import Device\n"
        "class OptomechDevice(Device):\n"
        "    def __init__(self, config):\n"
        "        config['parentDevice']\n"
        "        config.get('transform')\n"
        "    def setDeviceTransform(self, tr):\n"
        "        allowed = {'pos', 'scale', 'angle', 'axis'}\n"
    ),
    "NiDAQ/nidaq.py": (
        "class NiDAQ(Device):\n"
        "    def __init__(self, dm, config, name):\n"
        "        config.get('defaultAIMode')\n"
        "        config.get('mock')\n"
    ),
    "DAQGeneric/DAQGeneric.py": (
        "class DAQGeneric(Device):\n"
        "    def __init__(self, dm, config, name):\n"
        "        config.get('channels', config)\n"
    ),
    "Stage/Stage.py": (
        "class Stage(OptomechDevice):\n"
        "    def __init__(self, dm, config, name):\n"
        "        self.scale = config.get('scale')\n"
    ),
    "Camera/camera.py": (
        "AXES = ['exposeChannel']\n"
        "class Camera(DAQGeneric, OptomechDevice):\n"
        "    def __init__(self, dm, config, name):\n"
        "        if 'triggerInChannel' in config:\n"
        "            pass\n"
    ),
    "Camera/gui.py": "class CamGui:\n    def f(self):\n        self.dev.config.get('fromGui')\n",
    "Trigger/Trigger.py": "class Trigger(Device):\n    pass\n",
    "helper.py": "class Helper:\n    def f(self, config):\n        config['nope']\n",
}


@pytest.fixture
def acq4_top(tmp_path):
    top = tmp_path / "acq4_install"
    devices = top / "acq4" / "devices"
    for name, text in SOURCE.items():
        path = devices / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (top / "config").mkdir()
    return top


@pytest.fixture
def catalog(acq4_top):
    return scan_acq4_devices(acq4_top / "acq4" / "devices")


def findings(text, catalog=None):
    return analyze(ConfigDocument(text), catalog).findings


def has(found, *parts):
    return any(all(part in line for part in parts) for line in found)


# ------------------------------------------------------------------
# reading the acq4 source
# ------------------------------------------------------------------
def test_scan_separates_read_named_and_unknown_keys(catalog):
    assert catalog.key_status("Camera", "triggerInChannel") == READ
    assert catalog.key_status("Camera", "exposeChannel") == NAMED
    assert catalog.key_status("Camera", "madeUp") == NOT_FOUND


def test_scan_counts_keys_used_elsewhere_in_the_driver_folder(catalog):
    assert catalog.key_status("Camera", "fromGui") == NAMED
    assert catalog.key_status("Stage", "fromGui") == NOT_FOUND


def test_scan_inherits_keys_and_knows_the_family(catalog):
    assert catalog.key_status("Camera", "parentDevice") == READ
    assert catalog.key_status("Camera", "channels") == READ
    assert catalog.descends("Camera", "OptomechDevice")
    assert catalog.is_driver("Stage")
    assert not catalog.is_driver("Helper")
    assert catalog.key_status("Stage", "nope") == NOT_FOUND


def test_scan_reads_transform_keys_from_the_source(catalog):
    assert catalog.transform_keys == {"pos", "scale", "angle", "axis"}


def test_scan_survives_a_file_with_a_syntax_error(acq4_top):
    (acq4_top / "acq4" / "devices" / "broken.py").write_text("def (:\n", encoding="utf-8")
    assert scan_acq4_devices(acq4_top / "acq4" / "devices").is_driver("Stage")


# ------------------------------------------------------------------
# terminals
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,board,label",
    [
        ("/Dev1/ai5", None, "ai5"),
        ("/Dev1/AO1", None, "ao1"),
        ("/Dev1/port0/line3", None, "P0.3"),
        ("/Dev1/line30", BOARD, "P0.30"),
        ("/Dev1/line33", BOARD, "PFI1"),
        ("/Dev1/PFI5", None, "PFI5"),
        ("/Dev1/port1/line5", None, "PFI5"),
        ("/Dev1/port2/line1", None, "PFI9"),
        ("garbage", None, "garbage"),
    ],
)
def test_terminal_names(name, board, label):
    assert parse_terminal(name, board).label == label


def test_different_names_for_one_terminal_are_equal():
    assert parse_terminal("/Dev1/line7") == parse_terminal("/Dev1/port0/line7")
    assert parse_terminal("/Dev1/PFI2") == parse_terminal("/Dev1/port1/line2")


# ------------------------------------------------------------------
# commented-out devices
# ------------------------------------------------------------------
def test_commented_devices_are_found():
    text = (
        "# Prose: not a device\n"
        "# Clamp1:\n"
        "#     driver: 'MultiClamp'\n"
        "#     #dllPath: 'x'\n"
        "#     commandChannel:\n"
        "#         device: 'DAQ'\n"
        "#         channel: '/Dev1/ao0'\n"
        "#         type: 'ao'\n"
        "\n"
        "#Switch:\n"
        "#    driver: 'DIOSwitch'\n"
        "#    interval: 300e-3\n"
        "# Some words afterwards:\n"
        "# Second:\n"
        "#     driver: 'X'\n"
    )
    devices, unreadable = find_commented_devices(text)
    assert [(d.name, d.driver) for d in devices] == [
        ("Clamp1", "MultiClamp"), ("Switch", "DIOSwitch"), ("Second", "X"),
    ]
    assert unreadable == 0
    assert not devices[0].active
    assert devices[0].config["commandChannel"]["channel"] == "/Dev1/ao0"


def test_unreadable_block_is_counted():
    devices, unreadable = find_commented_devices("# A:\n#     driver: 'X'\n#     bad: (\n")
    assert devices == [] and unreadable == 1


def test_packaged_template_reads_every_example_device():
    doc = ConfigDocument(read_config_text(packaged_data("devices_template.cfg")))
    analysis = analyze(doc)
    assert sum(d.active for d in analysis.devices) == 15
    assert sum(not d.active for d in analysis.devices) >= 30
    assert analysis.unreadable_blocks == 0


# ------------------------------------------------------------------
# connections and sharing
# ------------------------------------------------------------------
def test_connections_of_all_forms():
    text = DAQ + (
        "Cam:\n    driver: 'MockCamera'\n"
        "    exposeChannel:\n        device: 'DAQ'\n        channel: '/Dev1/port0/line0'\n"
        "        type: 'di'\n"
        "    triggerOutChannel:\n        device: 'DAQ'\n        channel: '/Dev1/PFI5'\n"
        "Foot:\n    driver: 'Trigger'\n    channels:\n        DAQ: '/Dev1/PFI6'\n"
        "Old:\n    driver: 'MockCamera'\n    triggerOutChannel: 'DAQ', '/Dev1/PFI7'\n"
    )
    analysis = analyze(ConfigDocument(text))
    found = {(c.device, c.port): (c.terminal.label, c.kind) for c in analysis.connections}
    assert found == {
        ("Cam", "exposeChannel"): ("P0.0", "di"),
        ("Cam", "triggerOutChannel"): ("PFI5", "trigger"),
        ("Foot", "trigger"): ("PFI6", "trigger"),
        ("Old", "triggerOutChannel"): ("PFI7", "trigger"),
    }
    assert has(analysis.findings, "Warning: Old", "out of date")


def test_shared_line_warns_until_marked():
    text = DAQ + generic("A", channel("x", "/Dev1/ao2", "ao")) + generic(
        "B", channel("y", "/Dev1/ao2", "ao"))
    doc = ConfigDocument(text)
    assert has(analyze(doc).findings, "Warning", "DAQ ao2 is shared", "A (x)", "B (y)")
    write_alternates(doc, [{"A", "B"}])
    doc.check()
    analysis = analyze(doc)
    assert not has(analysis.findings, "is shared")
    assert analysis.shared[0].marked
    assert ConfigDocument(doc.text()).annotations("## acq4_tools alternates:") == ["A | B"]
    assert read_alternates(ConfigDocument(doc.text())) == [{"A", "B"}]


def test_commented_out_device_never_conflicts():
    text = DAQ + generic("A", channel("x", "/Dev1/ao2", "ao")) + (
        "# B:\n#     driver: 'DAQGeneric'\n#     channels:\n#         y:\n"
        "#             device: 'DAQ'\n#             channel: '/Dev1/ao2'\n"
        "#             type: 'ao'\n"
    )
    analysis = analyze(ConfigDocument(text))
    assert not has(analysis.findings, "is shared")
    assert analysis.shared == []
    row = next(r for r in analysis.line_rows if r.terminal.label == "ao2")
    assert row.active == ["A (x)"] and row.alternates == ["B (y)"]


def test_alias_names_are_detected_as_sharing():
    text = DAQ + generic("A", channel("x", "/Dev1/line7", "do")) + generic(
        "B", channel("y", "/Dev1/port0/line7", "di"))
    assert has(findings(text), "P0.7 is shared")


def test_differential_channel_occupies_its_pair():
    text = DAQ + generic("A", channel("x", "/Dev1/ai0", "ai", mode="diff")) + generic(
        "B", channel("y", "/Dev1/ai8", "ai"))
    assert has(findings(text), "ai8 is shared", "A (x)", "B (y)")


def test_default_differential_mode_applies():
    daq = "DAQ:\n    driver: 'NiDAQ'\n    defaultAIMode: 'DIFF'\n"
    text = daq + generic("A", channel("x", "/Dev1/ai1", "ai")) + generic(
        "B", channel("y", "/Dev1/ai9", "ai", mode="rse"))
    assert has(findings(text), "ai9 is shared")


def test_negative_side_cannot_be_differential():
    text = DAQ + generic("A", channel("x", "/Dev1/ai8", "ai", mode="diff"))
    assert has(findings(text), "Error", "negative side")


def test_two_channels_of_one_device_cannot_be_marked():
    text = DAQ + generic("A", channel("x", "/Dev1/ao0", "ao"), channel("y", "/Dev1/ao0", "ao"))
    assert has(findings(text), "ao0 is shared")


# ------------------------------------------------------------------
# channel checks
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "chan,expected",
    [
        (channel("x", "/Dev1/ai0", "ao"), "does not fit terminal ai0"),
        (channel("x", "/Dev1/ao0", "do"), "does not fit terminal ao0"),
        (channel("x", "/Dev1/ai0", "xx"), "is not ai, ao, di or do"),
        (channel("x", "/Dev1/ai0", "ai", mode="odd"), "mode 'odd'"),
        (channel("x", "/Dev1/line0", "do", scale=2), "only allowed on analog"),
        (channel("x", "/Dev1/ao0", "ao", invert=True), "only allowed on digital"),
        (channel("x", "/Dev1/nonsense", "ai"), "cannot interpret"),
        ("        x:\n            device: 'DAQ'\n            channel: '/Dev1/ai0'\n",
         "no type is given"),
    ],
)
def test_channel_problems(chan, expected):
    assert has(findings(DAQ + generic("A", chan)), expected)


def test_channel_with_a_missing_daq_is_an_error():
    assert has(findings(generic("A", channel("x", "/Dev1/ai0", "ai"))),
               "Error", "no active DAQ named 'DAQ'")


def test_channel_on_a_device_that_is_not_a_daq():
    text = "DAQ:\n    driver: 'MockStage'\n" + generic("A", channel("x", "/Dev1/ai0", "ai"))
    assert has(findings(text), "Error", "'DAQ' is not a DAQ device")


def test_device_before_its_daq_is_reported():
    text = generic("A", channel("x", "/Dev1/ai0", "ai")) + DAQ
    assert has(findings(text), "Warning: A is defined before its DAQ")


def boarded(text, board=BOARD):
    doc = ConfigDocument(text)
    write_boards(doc, {"DAQ": board})
    doc.check()
    return ConfigDocument(doc.text())


@pytest.mark.parametrize(
    "line,kind,label",
    [("/Dev1/ai32", "ai", "ai32"), ("/Dev1/ao4", "ao", "ao4"),
     ("/Dev1/PFI16", "di", "PFI16"), ("/Dev1/port0/line32", "do", "P0.32")],
)
def test_lines_not_on_the_board_are_errors(line, kind, label):
    doc = boarded(DAQ + generic("A", channel("x", line, kind)))
    found = analyze(doc).findings
    assert has(found, "Error", f"{label} does not exist on 6259")


def test_board_round_trip_keeps_custom_counts():
    doc = boarded(DAQ, Board("Custom", 8, 2, 4, 3))
    assert read_boards(doc) == {"DAQ": Board("Custom", 8, 2, 4, 3)}
    assert write_boards(doc, {}) and "acq4_tools" not in doc.text()
    doc.check()


def test_annotations_stay_before_the_final_newline():
    doc = ConfigDocument(DAQ)
    write_boards(doc, {"DAQ": BOARD})
    assert doc.text().endswith("pfi=16\n")


def test_note_until_a_board_is_chosen():
    assert has(findings(DAQ), "Note", "choose a board for DAQ")
    assert not has(analyze(boarded(DAQ)).findings, "choose a board")


def test_line_map_lists_free_lines_when_the_board_is_known():
    doc = boarded(DAQ + generic("A", channel("x", "/Dev1/ai3", "ai")))
    rows = analyze(doc).line_rows
    assert len(rows) == BOARD.ai + BOARD.ao + BOARD.port0 + BOARD.pfi
    statuses = {r.terminal.label: r.status for r in rows}
    assert statuses["ai3"] == "in use" and statuses["ai4"] == "free"


def test_line_outside_the_board_appears_in_the_map():
    doc = boarded(DAQ + generic("A", channel("x", "/Dev1/ai40", "ai")))
    assert any(r.status == "not on board" and r.active == ["A (x)"]
               for r in analyze(doc).line_rows)


# ------------------------------------------------------------------
# optomechanical tree
# ------------------------------------------------------------------
STAGE = "Stage:\n    driver: 'Stage'\n    transform:\n        pos: 0, 0, 0\n"
SCOPE = "Scope:\n    driver: 'Microscope'\n    parentDevice: 'Stage'\n"
CAMERA = (
    "Cam:\n    driver: 'Camera'\n    parentDevice: 'Scope'\n    transform:\n"
    "        scale: (1, -1)\n        angle: 0\n"
)


def test_tree_follows_parents():
    roots = analyze(ConfigDocument(STAGE + SCOPE + CAMERA)).opto_roots
    assert [r.device.name for r in roots] == ["Stage"]
    scope = roots[0].children[0]
    assert scope.device.name == "Scope"
    assert scope.children[0].device.name == "Cam"
    assert scope.children[0].transform == "scale (1, -1); angle 0"


def test_child_before_parent_is_an_error():
    assert has(findings(SCOPE + STAGE), "Error: Scope is defined before its parent Stage")


def test_missing_parent_is_an_error():
    assert has(findings(SCOPE), "Error: Scope: parent 'Stage' is not an active device")


def test_commented_out_parent_is_an_error():
    assert has(findings("# Stage:\n#     driver: 'Stage'\n\n" + SCOPE),
               "Error: Scope: parent 'Stage' is not an active device")


def test_parent_loop_is_an_error():
    text = "A:\n    driver: 'X'\n    parentDevice: 'B'\nB:\n    driver: 'X'\n    parentDevice: 'A'\n"
    found = findings(text)
    assert has(found, "Error: A is part of a loop") and has(found, "Error: B is part of a loop")


def test_parent_given_as_a_dict():
    text = STAGE + "Scope:\n    driver: 'X'\n    parentDevice:\n        name: 'Stage'\n"
    roots = analyze(ConfigDocument(text)).opto_roots
    assert roots[0].children[0].device.name == "Scope"


def test_bad_transform_key_is_an_error():
    text = "Cam:\n    driver: 'Camera'\n    transform:\n        position: 0, 0\n"
    assert has(findings(text), "Error: Cam: transform key 'position' is not allowed")


def test_zero_transform_scale_is_a_warning():
    text = "Cam:\n    driver: 'Camera'\n    transform:\n        scale: 0, 1\n"
    assert has(findings(text), "Warning: Cam", "scale of 0")


def test_parent_that_is_not_optomechanical(catalog):
    text = DAQ + "Cam:\n    driver: 'Camera'\n    parentDevice: 'DAQ'\n"
    assert has(findings(text, catalog), "Warning: Cam: parent DAQ", "not an optomechanical")


def test_reference_to_a_missing_device():
    text = "P:\n    driver: 'PatchPipette'\n    clampDevice: 'C'\n"
    assert has(findings(text), "Warning: P: clampDevice 'C' is not an active device")


# ------------------------------------------------------------------
# names against the source
# ------------------------------------------------------------------
def test_unknown_driver_is_an_error(catalog):
    assert has(findings("A:\n    driver: 'Nope'\n", catalog), "Error: A: acq4 has no driver")


def test_custom_dotted_driver_is_accepted(catalog):
    assert not has(findings("A:\n    driver: 'my.pkg.Thing'\n", catalog), "no driver")


def test_missing_driver_is_an_error():
    assert has(findings("A:\n    x: 1\n"), "Error: A has no driver")


def test_key_not_in_the_source_is_a_warning(catalog):
    text = "S:\n    driver: 'Stage'\n    scale: 1, 1, 1\n    bogus: 1\n"
    found = findings(text, catalog)
    assert has(found, "Warning: S: the Stage driver does not use the key 'bogus'")
    assert not has(found, "'scale'")


def test_nested_config_section_is_used_like_the_manager(catalog):
    text = "S:\n    driver: 'Stage'\n    config:\n        scale: 1, 1, 1\n"
    analysis = analyze(ConfigDocument(text), catalog)
    assert [r.key for r in analysis.key_rows] == ["scale"]
    assert not has(analysis.findings, "does not use")


def test_arbitrary_channel_names_of_generic_devices_are_accepted(catalog):
    text = DAQ + (
        "Old:\n    driver: 'DAQGeneric'\n"
        "    Command:\n        device: 'DAQ'\n        channel: '/Dev1/ao0'\n        type: 'ao'\n"
    )
    assert not has(findings(text, catalog), "does not use")


def test_commented_devices_are_listed_but_not_warned_about(catalog):
    text = "# S:\n#     driver: 'Stage'\n#     bogus: 1\n"
    analysis = analyze(ConfigDocument(text), catalog)
    assert [(r.key, r.status, r.active) for r in analysis.key_rows] == [
        ("bogus", NOT_FOUND, False)
    ]
    assert not has(analysis.findings, "bogus")


def test_note_until_the_source_is_chosen():
    assert has(findings(DAQ), "Note", "choose the acq4 directory")


def test_errors_come_first():
    found = findings(DAQ + "A:\n    x: 1\n")
    assert found[0].startswith("Error")
    assert found[-1].startswith("Note")


# ------------------------------------------------------------------
# the window
# ------------------------------------------------------------------
RIG = DAQ + generic("A", channel("x", "/Dev1/ao2", "ao")) + generic(
    "B", channel("y", "/Dev1/ao2", "ao")) + STAGE + SCOPE + CAMERA + (
    "# C:\n#     driver: 'DAQGeneric'\n#     channels:\n#         z:\n"
    "#             device: 'DAQ'\n#             channel: '/Dev1/ai1'\n"
    "#             type: 'ai'\n"
)


@pytest.fixture
def no_dialogs(monkeypatch):
    def fail(box):
        pytest.fail(f"unexpected dialog: {box.text()}")

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fail)


@pytest.fixture
def rig_window(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "devices.cfg"
    path.write_text(RIG, encoding="utf-8")
    window = RigConfigWindow()
    assert window.open_file(str(path))
    yield window, path
    # Not registered with qtbot: it would close the window first, and the
    # question about unsaved changes would wait forever.
    window.saved_text = window.doc.text()
    window.close()
    window.deleteLater()


def texts(table, column):
    return [table.item(r, column).text() for r in range(table.rowCount())]


def checks_text(window):
    return [window.checks.item(i).text() for i in range(window.checks.count())]


def test_opening_changes_nothing(rig_window):
    window, _ = rig_window
    assert not window.is_dirty
    assert window.doc.text() == RIG


def test_window_shows_every_view(rig_window):
    window, _ = rig_window
    assert texts(window.devices_table, 0) == ["DAQ", "A", "B", "Stage", "Scope", "Cam", "C"]
    assert texts(window.devices_table, 2)[-1] == "Commented out"
    assert texts(window.lines_table, 1) == ["ai1", "ao2"]
    top = window.tree.topLevelItem(0)
    assert top.text(0) == "Global coordinates"
    assert top.child(0).text(0) == "Stage"
    assert top.child(0).child(0).child(0).text(0) == "Cam"
    assert has(checks_text(window), "ao2 is shared")


def test_choosing_a_board_writes_a_comment_only(rig_window):
    window, path = rig_window
    combo, spins = window.board_rows["DAQ"]
    combo.setCurrentText("6259")
    combo.activated.emit(combo.currentIndex())
    assert [s.value() for s in spins] == [32, 4, 32, 16]
    assert window.doc.text() == RIG + "## acq4_tools board DAQ: 6259 ai=32 ao=4 port0=32 pfi=16\n"
    assert window.is_dirty
    assert not has(checks_text(window), "choose a board")
    assert window.lines_table.rowCount() == 84
    assert window.save()
    assert "acq4_tools board" in path.read_text(encoding="utf-8")


def test_changing_a_count_makes_the_board_custom(rig_window):
    window, _ = rig_window
    combo, spins = window.board_rows["DAQ"]
    combo.setCurrentText("6221")
    combo.activated.emit(combo.currentIndex())
    spins[0].setValue(8)
    spins[0].editingFinished.emit()
    assert combo.currentText() == "Custom"
    assert "DAQ: Custom ai=8 ao=2 port0=8 pfi=16" in window.doc.text()


def test_board_is_restored_on_open(rig_window, tmp_path):
    window, _ = rig_window
    combo, _spins = window.board_rows["DAQ"]
    combo.setCurrentText("6259")
    combo.activated.emit(combo.currentIndex())
    window.save()
    window.open_file(str(window.path))
    combo, spins = window.board_rows["DAQ"]
    assert combo.currentText() == "6259" and spins[3].value() == 16


def select_terminal(window, label):
    window.lines_table.selectRow(texts(window.lines_table, 1).index(label))


def test_mark_and_clear_alternates(rig_window):
    window, _ = rig_window
    select_terminal(window, "ao2")
    window.mark_alternates()
    assert "## acq4_tools alternates: A | B\n" in window.doc.text()
    assert not has(checks_text(window), "is shared")
    assert texts(window.lines_table, 2)[texts(window.lines_table, 1).index("ao2")] == "alternates"
    select_terminal(window, "ao2")
    window.clear_alternates()
    assert window.doc.text() == RIG
    assert has(checks_text(window), "is shared")


def test_marking_a_line_that_is_not_shared_does_nothing(rig_window):
    window, _ = rig_window
    select_terminal(window, "ai1")
    window.mark_alternates()
    assert "not shared" in window.statusBar().currentMessage()
    assert window.doc.text() == RIG


def test_diagram_draws_and_can_include_commented_devices(rig_window):
    window, _ = rig_window
    active = len(window.diagram.items)
    assert active > 5
    window.include_commented.setChecked(True)
    assert len(window.diagram.items) > active


@pytest.mark.parametrize("name", ["wiring.png", "wiring.pdf"])
def test_diagram_export(rig_window, tmp_path, name):
    window, _ = rig_window
    target = tmp_path / name
    assert window.write_diagram(str(target))
    assert target.stat().st_size > 500


def test_source_scan_updates_the_checks(rig_window, qtbot, acq4_top):
    window, _ = rig_window
    assert has(checks_text(window), "choose the acq4 directory")
    window.acq4_dir.setText(str(acq4_top))
    window.acq4_dir.activated.emit(str(acq4_top))
    qtbot.waitUntil(lambda: window.catalog is not None, timeout=5000)
    assert not has(checks_text(window), "choose the acq4 directory")
    assert window.keys_table.rowCount() > 0


def labels_named(window, text):
    return [i for i in window.diagram.items
            if isinstance(i, QtWidgets.QGraphicsSimpleTextItem) and i.text() == text]


def label_color(item):
    return item.brush().color().name().upper()


def wire_patterns(window):
    return [tuple(i.pen().dashPattern()) if i.pen().style() != QtCore.Qt.PenStyle.SolidLine else ()
            for i in window.diagram.items if isinstance(i, QtWidgets.QGraphicsPathItem)]


def test_devices_sharing_a_terminal_get_different_line_styles(rig_window):
    window, _ = rig_window
    assert sorted(wire_patterns(window)) == sorted([(), LINE_PATTERNS[1]])
    assert all(0 < min(p) >= 2 for p in LINE_PATTERNS if p)


def test_four_devices_on_one_terminal_use_all_four_styles(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "devices.cfg"
    path.write_text(DAQ + "".join(generic(n, channel("x", "/Dev1/ao0", "ao")) for n in "ABCD"),
                    encoding="utf-8")
    window = RigConfigWindow()
    qtbot.addWidget(window)
    window.open_file(str(path))
    assert sorted(wire_patterns(window)) == sorted(LINE_PATTERNS)


def test_daq_labels_show_the_type_and_ports_show_problems(rig_window):
    window, _ = rig_window
    assert label_color(labels_named(window, "ao2")[0]) == KIND_COLORS["ao"]
    assert label_color(labels_named(window, "x")[0]) == PROBLEM
    assert label_color(labels_named(window, "y")[0]) == PROBLEM
    select_terminal(window, "ao2")
    window.mark_alternates()
    assert label_color(labels_named(window, "x")[0]) == KIND_COLORS["ao"]


def test_each_port_names_its_daq_terminal_in_the_daq_color(rig_window):
    window, _ = rig_window
    daq_label, *device_labels = labels_named(window, "ao2")
    assert len(device_labels) == 2
    assert all(label_color(i) == label_color(daq_label) == KIND_COLORS["ao"]
               for i in device_labels)
    assert all(i.x() > daq_label.x() and not i.font().bold() for i in device_labels)


def test_terminal_column_is_on_the_wire_side_of_the_port(qtbot, tmp_path, no_dialogs):
    window = open_rig(qtbot, tmp_path, crowded_rig())
    right_source = labels_named(window, "ao0")[1]
    right_port = labels_named(window, "x")[0]
    assert right_source.x() < right_port.x()
    left_source = labels_named(window, "ai0")[1]
    left_port = labels_named(window, "a")[0]
    assert left_source.x() > left_port.x()
    assert left_port.x() + left_port.boundingRect().width() < left_source.x()


def test_port_color_follows_its_own_connection(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "devices.cfg"
    path.write_text(DAQ + generic("A", channel("out", "/Dev1/ao0", "ao"),
                                  channel("in", "/Dev1/ai0", "ai")), encoding="utf-8")
    window = RigConfigWindow()
    qtbot.addWidget(window)
    window.open_file(str(path))
    assert label_color(labels_named(window, "out")[0]) == KIND_COLORS["ao"]
    assert label_color(labels_named(window, "in")[0]) == KIND_COLORS["ai"]
    assert KIND_COLORS["ao"] != KIND_COLORS["ai"]


def crowded_rig():
    """Fourteen unshared two-channel devices whose terminals interleave, and one shared line."""
    text = DAQ
    for n in range(14):
        text += generic(f"Dev{n:02d}", channel("a", f"/Dev1/ai{n}", "ai"),
                        channel("b", f"/Dev1/port0/line{n}", "do"))
    return text + generic("S1", channel("x", "/Dev1/ao0", "ao")) + generic(
        "S2", channel("y", "/Dev1/ao0", "ao"))


def open_rig(qtbot, tmp_path, text):
    path = tmp_path / "devices.cfg"
    path.write_text(text, encoding="utf-8")
    window = RigConfigWindow()
    qtbot.addWidget(window)
    assert window.open_file(str(path))
    return window


def test_short_diagram_keeps_every_device_on_one_side(rig_window):
    window, _ = rig_window
    daq_x = labels_named(window, "ao2")[0].x()
    assert all(labels_named(window, name)[0].x() > daq_x for name in "AB")


def test_crowded_diagram_puts_unshared_devices_on_the_left(qtbot, tmp_path, no_dialogs):
    window = open_rig(qtbot, tmp_path, crowded_rig())
    daq_x = labels_named(window, "ao0")[0].x()
    assert labels_named(window, "Dev00")[0].x() < daq_x
    assert labels_named(window, "S1")[0].x() > daq_x
    assert labels_named(window, "S2")[0].x() > daq_x


def test_left_side_wires_do_not_cross(qtbot, tmp_path, no_dialogs):
    window = open_rig(qtbot, tmp_path, crowded_rig())
    daq_x = labels_named(window, "ao0")[0].x()
    ends = sorted(
        (i.path().elementAt(0).y, i.path().elementAt(i.path().elementCount() - 1).y)
        for i in window.diagram.items
        if isinstance(i, QtWidgets.QGraphicsPathItem) and i.path().elementAt(3).x < daq_x
    )
    assert len(ends) == 28
    assert [end for _start, end in ends] == sorted(end for _start, end in ends)


def test_terminal_order_keeps_each_devices_lines_together():
    a0, a1 = Terminal("D", "ai", 0), Terminal("D", "ai", 1)
    p0, p1 = Terminal("D", "p0", 0), Terminal("D", "p0", 1)
    owners = {a0: "A", p0: "A", a1: "B", p1: "B"}
    assert terminal_order([p1, a1, p0, a0], owners) == [a0, p0, a1, p1]
    assert terminal_order([p0, a0], {}) == [a0, p0]


def test_device_with_a_shared_line_stays_on_the_right(qtbot, tmp_path, no_dialogs):
    text = crowded_rig() + generic("Mixed", channel("p", "/Dev1/ao0", "ao"),
                                   channel("q", "/Dev1/ai20", "ai"))
    window = open_rig(qtbot, tmp_path, text)
    assert labels_named(window, "Mixed")[0].x() > labels_named(window, "ao0")[0].x()


TWO_BOARDS = DAQ + generic("A", channel("x", "/Dev1/ai0", "ai")) + generic(
    "B", channel("y", "/Dev2/ai0", "ai"))


def test_two_boards_get_separate_labelled_boxes(qtbot, tmp_path, no_dialogs):
    window = open_rig(qtbot, tmp_path, TWO_BOARDS)
    assert labels_named(window, "DAQ  Dev1") and labels_named(window, "DAQ  Dev2")
    assert labels_named(window, "x") and labels_named(window, "y")
    assert labels_named(window, "Dev1/ai0") and labels_named(window, "Dev2/ai0")
    bodies = [i for i in window.diagram.items if isinstance(i, QtWidgets.QGraphicsRectItem)
              and i.pen().widthF() == 2.5]
    assert len({i.brush().color().name() for i in bodies}) >= 3


def test_same_line_on_two_boards_is_not_shared():
    analysis = analyze(ConfigDocument(TWO_BOARDS))
    assert analysis.shared == []
    assert [r.place for r in analysis.line_rows] == ["Dev1/ai0", "Dev2/ai0"]


def test_each_board_can_have_its_own_model(qtbot, tmp_path, no_dialogs):
    window = open_rig(qtbot, tmp_path, TWO_BOARDS)
    assert set(window.board_rows) == {"DAQ/Dev1", "DAQ/Dev2"}
    for key, model in (("DAQ/Dev1", "6259"), ("DAQ/Dev2", "6221")):
        combo, _spins = window.board_rows[key]
        combo.setCurrentText(model)
        combo.activated.emit(combo.currentIndex())
    boards = read_boards(window.doc)
    assert boards["DAQ/Dev2"].ai == 16 and boards["DAQ/Dev1"].ai == 32
    assert labels_named(window, "DAQ  Dev2  (6221)")
    assert window.lines_table.rowCount() == 84 + 42
    window.saved_text = window.doc.text()


def test_line_that_exists_on_only_one_board(qtbot):
    doc = ConfigDocument(DAQ + generic("A", channel("x", "/Dev1/ai20", "ai")) + generic(
        "B", channel("y", "/Dev2/ai20", "ai")))
    write_boards(doc, {"DAQ/Dev1": BOARD_MODELS["6259"], "DAQ/Dev2": BOARD_MODELS["6221"]})
    found = analyze(doc).findings
    assert has(found, "Error: B, y: Dev2/ai20 does not exist on 6221")
    assert not has(found, "A, x")


def test_long_transforms_wrap_and_rewrap_when_the_column_changes(qtbot, tmp_path, no_dialogs):
    text = ("Long:\n    driver: 'Camera'\n    transform:\n"
            "        pos: (1.5, 2.5, 3.5)\n        scale: (1.25, -1.25, 1.25)\n"
            "        angle: 12.5\n        axis: (0, 0, 1)\n"
            "Short:\n    driver: 'Camera'\n    transform:\n        angle: 0\n")
    window = open_rig(qtbot, tmp_path, text)
    window.show()
    window.tabs.setCurrentWidget(window.tree)
    top = window.tree.topLevelItem(0)
    long_item, short_item = top.child(0), top.child(1)
    assert "axis" in long_item.text(3)
    window.tree.setColumnWidth(0, window.tree.viewport().width() - 130)
    window.tree.setColumnWidth(1, 10)
    window.tree.setColumnWidth(2, 10)
    QtWidgets.QApplication.processEvents()
    narrow = window.tree.visualItemRect(long_item).height()
    assert narrow > 2 * window.tree.visualItemRect(short_item).height()
    window.tree.setColumnWidth(0, 40)
    QtWidgets.QApplication.processEvents()
    assert window.tree.visualItemRect(long_item).height() < narrow


def test_optomechanics_rows_are_shaded_padded_and_top_aligned(rig_window):
    window, _ = rig_window
    window.show()
    window.tabs.setCurrentWidget(window.tree)
    QtWidgets.QApplication.processEvents()
    tree = window.tree
    assert tree.alternatingRowColors()
    palette = tree.palette()
    assert palette.color(QtGui.QPalette.ColorRole.AlternateBase) != palette.color(
        QtGui.QPalette.ColorRole.Base
    )
    item = tree.topLevelItem(0)
    assert tree.visualItemRect(item).height() > tree.fontMetrics().height() + 4
    option = QtWidgets.QStyleOptionViewItem()
    tree.itemDelegate().initStyleOption(option, tree.indexFromItem(item, 3))
    assert option.displayAlignment & QtCore.Qt.AlignmentFlag.AlignTop


def test_template_opens(qtbot, no_dialogs):
    window = RigConfigWindow()
    qtbot.addWidget(window)
    window.new_from_template()
    assert window.devices_table.rowCount() >= 45
    assert window.path is None
    assert Terminal("Dev1", "ai", 0).label == "ai0"
