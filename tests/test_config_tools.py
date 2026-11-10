import pytest
from pyqtgraph.Qt import QtWidgets

from acq4_tools.common.config_document import ConfigDocument, IncludedFile, parse_text
from acq4_tools.common.history import history_store
from acq4_tools.common.paths import acq4_config_dir, acq4_devices_dir
from acq4_tools.tools.rig_config import RigConfigWindow
from acq4_tools.tools.default_cfg import (
    DefaultConfigWindow,
    check_default_config,
    set_option,
    shortcut_is_valid,
    UNSET,
)
from acq4_tools.tools.folder_types import FieldSpec, FolderTypesWindow, check_folder_types

DEFAULT = """# my lab
devices: readConfigFile('devices.cfg')

modules:
    Data Manager:
        module: 'DataManager'
        shortcut: 'F2'
    Task Runner:
        module: 'TaskRunner'
        shortcut: 'F6'
    Console:
        module: 'Console'
        config: None

misc:
    ## compression comment
    defaultCompression: None
    # storageDir: '/home/user/data'

configurations:
    User_1:
        storageDir: '/data/one'
"""

FOLDERS = """Day:
    name: "%Y.%m.%d"
    experimentalUnit: True   ## one log per day
    info:
        description: "text", 6
        species: "list", ["Mouse", "Rat"]
        age: "string"
Cell:
    name: "cell"
    info:
        notes: "text", 10
"""


@pytest.fixture
def no_dialogs(monkeypatch):
    def fail(box):
        pytest.fail(f"unexpected dialog: {box.text()}")

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fail)


def discard_and_close(window):
    # Not registered with qtbot: it would close the window first, and the
    # question about unsaved changes would wait forever.
    window.saved_text = window.doc.text()
    window.close()
    window.deleteLater()


@pytest.fixture
def default_window(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "default.cfg"
    path.write_text(DEFAULT, encoding="utf-8")
    window = DefaultConfigWindow()
    assert window.open_file(str(path))
    yield window, path
    discard_and_close(window)


@pytest.fixture
def folder_window(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "folderTypes.cfg"
    path.write_text(FOLDERS, encoding="utf-8")
    window = FolderTypesWindow()
    assert window.open_file(str(path))
    yield window, path
    discard_and_close(window)


def checks(doc, config_dir=None, exists=lambda _path: True):
    return check_default_config(doc, config_dir, exists)


def edit_line(edit, text):
    edit.setText(text)
    edit.editingFinished.emit()


# ------------------------------------------------------------------
# default.cfg
# ------------------------------------------------------------------
def test_form_shows_the_file(default_window):
    window, _ = default_window
    table = window.modules_table
    assert [table.item(r, 0).text() for r in range(table.rowCount())] == [
        "Data Manager", "Task Runner", "Console",
    ]
    assert table.cellWidget(1, 1).currentText() == "TaskRunner"
    assert table.item(1, 2).text() == "F6"
    assert window.devices_edit.text() == "devices.cfg"
    assert window.configurations_table.item(0, 1).text() == "/data/one"
    assert window.option_combos["defaultCompression"].currentText() == "No compression"
    assert window.option_combos["useOpenGL"].currentText() == "(not set)"
    assert not window.is_dirty


def test_changing_a_shortcut_touches_only_that_line(default_window):
    window, path = default_window
    window.modules_table.item(0, 2).setText("F9")
    assert window.doc.text() == DEFAULT.replace("'F2'", "'F9'")
    assert window.is_dirty
    assert window.windowTitle().endswith("*")
    assert window.save()
    assert path.read_text(encoding="utf-8") == DEFAULT.replace("'F2'", "'F9'")
    assert (tmp := path.with_name("default.cfg.bak")).read_text(encoding="utf-8") == DEFAULT
    assert tmp.exists() and not window.is_dirty


def test_shortcut_added_after_module_and_comments_out_when_cleared(default_window):
    window, _ = default_window
    window.modules_table.item(2, 2).setText("F4")
    console = window.doc.node("modules", "Console")
    assert [c.key for c in console.children] == ["module", "shortcut", "config"]
    window.modules_table.item(2, 2).setText("")
    assert console.child("shortcut") is None
    assert "# shortcut: 'F4'" in window.doc.text()
    window.doc.check()


def test_module_class_change(default_window):
    window, _ = default_window
    combo = window.modules_table.cellWidget(2, 1)
    combo.setEditText("Camera")
    combo.lineEdit().editingFinished.emit()
    assert window.doc.value(window.doc.node("modules", "Console", "module")) == "Camera"


def test_duplicate_module_name_is_refused(default_window):
    window, _ = default_window
    window.modules_table.item(0, 0).setText("Console")
    assert window.modules_table.item(0, 0).text() == "Data Manager"
    assert window.doc.text() == DEFAULT


def test_add_move_remove_module(default_window):
    window, _ = default_window
    window.add_module()
    assert window.selected_module().key == "New Module 1"
    window.move_module(-1)
    assert list(window.doc.value(window.doc.node("modules"))) == [
        "Data Manager", "Task Runner", "New Module 1", "Console",
    ]
    window.remove_module()
    assert window.doc.text() == DEFAULT
    window.doc.check()


def test_module_setting_replaces_config_none(default_window):
    window, _ = default_window
    console = window.doc.node("modules", "Console")
    window.add_setting_named(console, "history")
    window.modules_table.selectRow(2)
    item = window.settings_table.item(0, 1)
    item.setText("/some/path")
    assert window.doc.value(console.child("config")) == {"history": "/some/path"}
    assert item.text() == "'/some/path'"
    item.setText("3 + 4")
    assert window.doc.value(console.child("config", )) == {"history": 7}
    window.doc.check()


def test_storage_directory_uses_the_commented_line_and_goes_back(default_window):
    window, _ = default_window
    edit_line(window.storage_edit, "/my/data")
    assert window.doc.text() == DEFAULT.replace(
        "# storageDir: '/home/user/data'", "storageDir: '/my/data'"
    )
    edit_line(window.storage_edit, "")
    assert "# storageDir: '/my/data'" in window.doc.text()
    assert window.doc.value(window.doc.root)["misc"].keys() == {"defaultCompression"}


def test_task_directory_is_added_to_the_task_runner(default_window):
    window, _ = default_window
    edit_line(window.task_dir_edit, "/tasks")
    config = window.doc.node("modules", "Task Runner", "config")
    assert window.doc.value(config) == {"taskDir": "/tasks"}
    window.doc.check()


def test_include_is_written_as_read_config_file(default_window):
    window, _ = default_window
    edit_line(window.devices_edit, "rig2.cfg")
    assert "devices: readConfigFile('rig2.cfg')" in window.doc.text()


def test_inline_devices_are_not_offered_as_a_file(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "d.cfg"
    path.write_text("devices:\n    Cam:\n        driver: 'X'\n", encoding="utf-8")
    window = DefaultConfigWindow()
    qtbot.addWidget(window)
    window.open_file(str(path))
    assert not window.devices_edit.isEnabled()
    window.devices_edit.editingFinished.emit()
    assert not window.is_dirty


def test_configurations_table(default_window):
    window, _ = default_window
    window.configurations_table.item(0, 1).setText("/data/new")
    window.configurations_table.item(0, 0).setText("Paul")
    window.add_configuration()
    section = window.doc.value(window.doc.node("configurations"))
    assert section == {"Paul": {"storageDir": "/data/new"}, "User_1": {"storageDir": ""}}
    assert any("empty storage" in w for w in checks(window.doc))


def test_options_write_and_clear(default_window):
    window, _ = default_window
    combo = window.option_combos["defaultCompression"]
    combo.setCurrentIndex(combo.findText("gzip, level 5"))
    combo.activated.emit(combo.currentIndex())
    assert window.doc.value(window.doc.node("misc", "defaultCompression")) == ("gzip", 5)
    assert "defaultCompression: 'gzip', 5" in window.doc.text()

    combo = window.option_combos["useOpenGL"]
    combo.setCurrentIndex(combo.findText("True"))
    combo.activated.emit(combo.currentIndex())
    assert window.doc.value(window.doc.node("misc", "useOpenGL")) is True
    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert window.doc.node("misc", "useOpenGL") is None


def test_unknown_option_value_is_kept_in_the_list(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "d.cfg"
    path.write_text("misc:\n    defaultCompression: 'gzip', 3\n", encoding="utf-8")
    window = DefaultConfigWindow()
    qtbot.addWidget(window)
    window.open_file(str(path))
    assert window.option_combos["defaultCompression"].currentData() == ("gzip", 3)
    assert not window.is_dirty


def test_option_at_the_top_level_is_left_there():
    doc = ConfigDocument("useOpenGL: True\nmisc:\n    a: 1\n")
    set_option(doc, "useOpenGL", False)
    assert doc.text() == "useOpenGL: False\nmisc:\n    a: 1\n"
    set_option(doc, "useOpenGL", UNSET)
    assert doc.text() == "# useOpenGL: False\nmisc:\n    a: 1\n"


@pytest.mark.parametrize("text,valid", [("F2", True), ("Ctrl+Shift+A", True),
                                        ("notakey", False), ("F99", False)])
def test_shortcut_validity(text, valid):
    assert shortcut_is_valid(text) is valid


@pytest.mark.parametrize(
    "text,expected",
    [
        ("bogus: 1\n", "top-level key 'bogus'"),
        ("misc:\n    bogus: 1\n", "'bogus' under misc"),
        ("modules:\n    A:\n        shortcut: 'F2'\n", "no 'module' class"),
        ("modules:\n    A:\n        module: 'Nope'\n", "no module class named 'Nope'"),
        ("modules:\n    A:\n        module: 'Camera'\n        junk: 1\n", "ignores the key 'junk'"),
        ("modules:\n    A:\n        module: 'Camera'\n        shortcut: 'zzz'\n",
         "not a valid shortcut"),
        ("modules:\n    A:\n        module: 'Camera'\n        shortcut: 'F2'\n"
         "    B:\n        module: 'Patch'\n        shortcut: 'F2'\n", "Shortcut F2 is used by: A, B"),
        ("modules:\n    A:\n        module: 'Imager'\n        config:\n"
         "            cameraModule: 'Cam'\n", "cameraModule 'Cam'"),
        ("misc:\n    defaultCompression: 'zip'\n", "will be rejected"),
        ("storageDir: '/x'\n", "/x was not found"),
        ("configurations:\n    U:\n        storageDir: '/y'\n", "/y was not found"),
    ],
)
def test_checks_find(text, expected):
    found = checks(ConfigDocument(text), exists=lambda _path: False)
    assert any(expected in w for w in found), found


def test_checks_accept_a_good_file_and_a_custom_module():
    text = DEFAULT + "    \nimports: 'x'\n"
    assert checks(ConfigDocument(text)) == []
    assert checks(ConfigDocument("modules:\n    A:\n        module: 'my.pkg.Mod'\n")) == []


def test_checks_look_for_includes_beside_the_file(tmp_path):
    doc = ConfigDocument("devices: readConfigFile('d.cfg')\nstylesheet: 's.css'\n")
    found = checks(doc, tmp_path, lambda p: not p.endswith("d.cfg"))
    assert len(found) == 1 and "d.cfg" in found[0]
    assert doc.value(doc.node("devices")) == IncludedFile("d.cfg")


# ------------------------------------------------------------------
# the shared window
# ------------------------------------------------------------------
def test_file_with_an_error_is_reported_and_not_loaded(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "bad.cfg"
    path.write_text("a: (\n", encoding="utf-8")
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", lambda box: shown.append(box.text()))
    window = DefaultConfigWindow()
    qtbot.addWidget(window)
    assert not window.open_file(str(path))
    assert window.doc is None and len(shown) == 1


def test_template_is_unsaved_until_saved_as(qtbot, tmp_path, monkeypatch, no_dialogs):
    window = DefaultConfigWindow()
    qtbot.addWidget(window)
    window.new_from_template()
    assert window.path is None and window.doc.node("modules") is not None
    target = tmp_path / "new.cfg"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(target), ""))
    assert window.save()
    assert window.path == target
    assert target.read_text(encoding="utf-8") == window.doc.text()
    assert parse_text(target.read_text(encoding="utf-8"))["modules"]


def test_revert(default_window):
    window, _ = default_window
    window.modules_table.item(0, 2).setText("F9")
    window.revert()
    assert window.doc.text() == DEFAULT
    assert window.modules_table.item(0, 2).text() == "F2"


def answering(monkeypatch, button):
    asked = []

    def answer(box):
        asked.append(box.text())
        return button

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", answer)
    return asked


StandardButton = QtWidgets.QMessageBox.StandardButton


def test_close_with_changes_can_be_cancelled(default_window, monkeypatch):
    window, path = default_window
    window.show()
    window.modules_table.item(0, 2).setText("F9")
    asked = answering(monkeypatch, StandardButton.Cancel)
    assert not window.close()
    assert len(asked) == 1 and window.isVisible()
    assert path.read_text(encoding="utf-8") == DEFAULT


def test_close_with_changes_can_save(default_window, monkeypatch):
    window, path = default_window
    window.show()
    window.modules_table.item(0, 2).setText("F9")
    answering(monkeypatch, StandardButton.Save)
    assert window.close()
    assert "'F9'" in path.read_text(encoding="utf-8")


def test_opening_another_file_can_discard(default_window, monkeypatch, tmp_path):
    window, _ = default_window
    other = tmp_path / "o.cfg"
    other.write_text("a: 1\n", encoding="utf-8")
    window.modules_table.item(0, 2).setText("F9")
    answering(monkeypatch, StandardButton.Discard)
    assert window.open_file(str(other))
    assert window.path == other


def test_change_on_disk_is_not_silently_overwritten(default_window, monkeypatch):
    window, path = default_window
    window.modules_table.item(0, 2).setText("F9")
    path.write_text("edited: 1\n", encoding="utf-8")
    asked = answering(monkeypatch, StandardButton.Cancel)
    assert not window.save()
    assert len(asked) == 1
    assert path.read_text(encoding="utf-8") == "edited: 1\n"


def test_saving_commits_a_field_still_being_edited(default_window, monkeypatch):
    window, path = default_window
    window.show()
    window.tabs.setCurrentIndex(1)
    window.storage_edit.setFocus()
    window.storage_edit.setText("/typed/not/finished")
    monkeypatch.setattr(QtWidgets.QApplication, "focusWidget",
                        staticmethod(lambda: window.storage_edit))
    monkeypatch.setattr(window.storage_edit, "clearFocus", window.storage_edit.editingFinished.emit)
    assert window.save()
    assert "/typed/not/finished" in path.read_text(encoding="utf-8")


@pytest.fixture
def acq4_top(tmp_path):
    top = tmp_path / "acq4"
    (top / "config").mkdir(parents=True)
    return top


def browse_start(monkeypatch, window):
    """The folder that the file chooser opens at."""
    seen = []

    def choose(_parent, _title, start):
        seen.append(start)
        return "", ""

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", choose)
    window.file_combo.browse()
    return seen[0]


@pytest.mark.parametrize("cls", [DefaultConfigWindow, FolderTypesWindow])
def test_browse_opens_the_config_folder_of_the_acq4_directory(qtbot, monkeypatch, acq4_top, cls):
    window = cls()
    qtbot.addWidget(window)
    window.acq4_dir.setText(str(acq4_top))
    assert browse_start(monkeypatch, window) == str(acq4_top / "config")


def test_config_folder_wins_over_the_last_file(default_window, monkeypatch, acq4_top):
    window, path = default_window
    assert window.file_combo.text() == str(path)
    window.acq4_dir.setText(str(acq4_top))
    assert browse_start(monkeypatch, window) == str(acq4_top / "config")


def test_config_folder_of_an_installation_is_found(tmp_path):
    (tmp_path / "acq4" / "config").mkdir(parents=True)
    (tmp_path / "acq4" / "acq4" / "devices").mkdir(parents=True)
    assert acq4_config_dir(str(tmp_path)) == tmp_path / "acq4" / "config"
    assert acq4_devices_dir(str(tmp_path)) == tmp_path / "acq4" / "acq4" / "devices"


def test_config_folder_of_a_checkout_comes_first(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "acq4" / "devices").mkdir(parents=True)
    (tmp_path / "acq4" / "config").mkdir()
    assert acq4_config_dir(str(tmp_path)) == tmp_path / "config"
    assert acq4_devices_dir(str(tmp_path)) == tmp_path / "acq4" / "devices"


def test_every_config_tool_browses_where_the_others_have_been(qtbot, monkeypatch, tmp_path):
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    history_store().add("default_cfg.files", str(folder / "default.cfg"))
    for cls in (DefaultConfigWindow, FolderTypesWindow, RigConfigWindow):
        window = cls()
        qtbot.addWidget(window)
        assert browse_start(monkeypatch, window) == str(folder)


def test_window_already_open_uses_a_directory_chosen_in_another(qtbot, monkeypatch, acq4_top):
    waiting = RigConfigWindow()
    qtbot.addWidget(waiting)
    assert waiting.acq4_dir.text() == ""
    chooser = DefaultConfigWindow()
    qtbot.addWidget(chooser)
    chooser.acq4_dir.setText(str(acq4_top))
    chooser.acq4_dir.activated.emit(str(acq4_top))
    assert browse_start(monkeypatch, waiting) == str(acq4_top / "config")


@pytest.mark.parametrize("top", ["", "does/not/exist"])
def test_no_config_folder(top):
    assert acq4_config_dir(top) is None
    assert acq4_devices_dir(top) is None


def test_browse_falls_back_when_the_directory_has_no_config(default_window, monkeypatch, tmp_path):
    window, path = default_window
    window.acq4_dir.setText(str(tmp_path / "empty"))
    assert browse_start(monkeypatch, window) == str(path.parent)


def test_acq4_directory_is_remembered_and_shared(qtbot, acq4_top):
    window = DefaultConfigWindow()
    qtbot.addWidget(window)
    window.acq4_dir.setText(str(acq4_top))
    window.acq4_dir.activated.emit(str(acq4_top))
    assert "Browse will open" in window.statusBar().currentMessage()
    other = FolderTypesWindow()
    qtbot.addWidget(other)
    assert other.acq4_dir.text() == str(acq4_top)


def test_typed_acq4_directory_is_remembered_when_a_file_is_opened(default_window, acq4_top):
    window, path = default_window
    window.acq4_dir.setText(str(acq4_top))
    assert window.open_file(str(path))
    assert history_store().get("acq4.top_dirs") == [str(acq4_top)]


def test_directory_without_config_is_reported_and_not_remembered(qtbot, tmp_path):
    window = DefaultConfigWindow()
    qtbot.addWidget(window)
    top = tmp_path / "not_acq4"
    top.mkdir()
    window.acq4_dir.setText(str(top))
    window.acq4_dir.activated.emit(str(top))
    assert "No config folder" in window.statusBar().currentMessage()
    assert history_store().get("acq4.top_dirs") == []


def test_save_as_of_a_new_file_starts_in_the_config_folder(qtbot, monkeypatch, acq4_top, no_dialogs):
    seen = []
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda _p, _t, start, _f: seen.append(start) or ("", ""))
    window = DefaultConfigWindow()
    qtbot.addWidget(window)
    window.acq4_dir.setText(str(acq4_top))
    window.new_from_template()
    assert not window.save_as()
    assert seen == [str(acq4_top / "config" / "default.cfg")]


def test_file_history_is_remembered(default_window):
    window, path = default_window
    assert str(path) in [window.file_combo.combo.itemText(i)
                         for i in range(window.file_combo.combo.count())]


# ------------------------------------------------------------------
# folderTypes.cfg
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["string", "bool", ("bool", True), ("string", "x"), ("text", 6), ("text", 6, "d"),
     ("list", ["a", "b"]), ("list", ["a"], "a")],
)
def test_field_spec_round_trip(value):
    assert FieldSpec.from_value(value).to_value() == value


@pytest.mark.parametrize("value", ["number", ("list", "a"), ("list",), ("text", "x"), 3, ()])
def test_field_spec_declines_other_forms(value):
    assert FieldSpec.from_value(value) is None


def test_text_default_without_lines_gets_a_line_count():
    assert FieldSpec("text", default="d").to_value() == ("text", 4, "d")


def test_folder_form_shows_the_file(folder_window):
    window, _ = folder_window
    assert [window.type_list.item(i).text() for i in range(window.type_list.count())] == [
        "Day", "Cell",
    ]
    assert window.name_edit.text() == "%Y.%m.%d"
    assert window.experimental_unit.isChecked()
    table = window.fields_table
    assert table.cellWidget(0, 1).currentText() == "text"
    assert table.item(0, 2).text() == "6"
    assert table.item(1, 4).text() == "Mouse, Rat"
    assert not window.is_dirty


def test_selecting_a_type_does_not_mark_changes(folder_window):
    window, _ = folder_window
    window.type_list.setCurrentRow(1)
    assert window.name_edit.text() == "cell"
    assert not window.experimental_unit.isChecked()
    assert not window.is_dirty


def test_name_edit_keeps_the_comment_on_other_lines(folder_window):
    window, _ = folder_window
    edit_line(window.name_edit, "%Y-%m-%d")
    assert window.doc.text() == FOLDERS.replace('"%Y.%m.%d"', "'%Y-%m-%d'")
    assert "## one log per day" in window.doc.text()


def test_experimental_unit(folder_window):
    window, _ = folder_window
    window.experimental_unit.setChecked(False)
    window._on_experimental_unit(False)
    assert "experimentalUnit: False   ## one log per day" in window.doc.text()
    window.type_list.setCurrentRow(1)
    window._on_experimental_unit(True)
    cell = window.doc.node("Cell")
    assert [c.key for c in cell.children] == ["name", "experimentalUnit", "info"]
    window.doc.check()


def test_list_values_can_be_edited(folder_window):
    window, _ = folder_window
    window.fields_table.selectRow(1)
    assert not window.values_group.isHidden()
    window.values_list.setCurrentRow(1)
    window.values_list.currentItem().setText("Guinea Pig")
    window.move_value(-1)
    window.add_value()
    window.values_list.setCurrentRow(0)
    window.remove_value()
    node = window.doc.node("Day", "info", "species")
    assert window.doc.value(node) == ("list", ["Mouse", "new value"])
    assert window.fields_table.item(1, 4).text() == "Mouse, new value"


def test_values_are_hidden_for_other_types(folder_window):
    window, _ = folder_window
    window.fields_table.selectRow(2)
    assert window.values_group.isHidden()


def test_field_type_change(folder_window):
    window, _ = folder_window
    node = window.doc.node("Day", "info", "age")
    window._on_field_type(node, "list")
    assert window.doc.value(node) == ("list", [])
    assert any("no list values" in w for w in check_folder_types(window.doc))
    window._on_field_type(node, "text")
    assert window.doc.value(node) == "text"
    window._on_field_type(node, "bool")
    assert window.doc.value(node) == "bool"
    window.doc.check()


def test_lines_and_default_cells(folder_window):
    window, _ = folder_window
    node = window.doc.node("Day", "info", "description")
    window.fields_table.item(0, 2).setText("3")
    assert window.doc.value(node) == ("text", 3)
    window.fields_table.item(0, 3).setText("hello")
    assert window.doc.value(node) == ("text", 3, "hello")
    window.fields_table.item(0, 2).setText("many")
    assert window.doc.value(node) == ("text", 3, "hello")
    assert window.fields_table.item(0, 2).text() == "3"


def test_add_field_and_type_then_parse(folder_window):
    window, _ = folder_window
    window.add_type()
    assert window.selected_type().key == "NewType"
    window.add_field()
    window.fields_table.item(0, 0).setText("region")
    assert parse_text(window.doc.text())["NewType"] == {
        "name": "newtype", "info": {"region": "string"},
    }
    assert check_folder_types(window.doc) == []


def test_remove_and_reorder_fields_and_types(folder_window):
    window, _ = folder_window
    window.fields_table.selectRow(0)
    window.move_field(1)
    assert list(window.doc.value(window.doc.node("Day", "info"))) == [
        "species", "description", "age",
    ]
    window.remove_field()
    assert list(window.doc.value(window.doc.node("Day", "info"))) == ["species", "age"]
    window.move_type(1)
    assert [n.key for n in window.doc.root.children] == ["Cell", "Day"]
    window.doc.check()
    window.remove_type()
    assert [n.key for n in window.doc.root.children] == ["Cell"]


def test_type_rename_warns_about_existing_data(folder_window):
    window, _ = folder_window
    window.type_list.item(1).setText("Neuron")
    assert window.doc.node("Neuron") is not None
    assert "keep the old type name" in window.statusBar().currentMessage()
    window.type_list.item(1).setText("Day")
    assert window.type_list.item(1).text() == "Neuron"


def test_folder_save(folder_window):
    window, path = folder_window
    window.type_list.setCurrentRow(1)
    window.fields_table.item(0, 2).setText("12")
    assert window.save()
    assert path.read_text(encoding="utf-8") == FOLDERS.replace('"text", 10', "'text', 12")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Day:\n    name: 'd'\n", "no info section"),
        ("Day:\n    info: {}\n", "no name format"),
        ("Day:\n    name: ''\n    info: {}\n", "empty name format"),
        ("Day:\n    name: 'a/b'\n    info: {}\n", "cannot be used for a directory"),
        ("Folder:\n    name: 'f'\n    info: {}\n", "already uses this name"),
        ("Day:\n    name: 'd'\n    info:\n    extra: 1\n", "ignores the key 'extra'"),
        ("Day: 3\n", "not a section"),
        ("Day:\n    name: 'd'\n    info:\n        x: 'number'\n", "no built-in field"),
        ("Day:\n    name: 'd'\n    info:\n        x: 'list', []\n", "no list values"),
        ("Day:\n    name: 'd'\n    info:\n        x: 'list', [1]\n", "must be text"),
    ],
)
def test_folder_checks_find(text, expected):
    found = check_folder_types(ConfigDocument(text))
    assert any(expected in w for w in found), found


def test_unusual_field_is_shown_read_only_and_kept(qtbot, tmp_path, no_dialogs):
    path = tmp_path / "f.cfg"
    text = "Day:\n    name: 'd'\n    info:\n        x: 'custom', 1, 2\n"
    path.write_text(text, encoding="utf-8")
    window = FolderTypesWindow()
    qtbot.addWidget(window)
    window.open_file(str(path))
    assert window.fields_table.item(0, 4).text() == "'custom', 1, 2"
    assert window.doc.text() == text
