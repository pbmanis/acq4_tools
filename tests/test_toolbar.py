import re
from pathlib import Path

import pytest
from pyqtgraph.Qt import QtCore, QtWidgets

import acq4_tools
from acq4_tools.app import ToolbarWindow, create_application
from acq4_tools.common.history import history_store
from acq4_tools.registry import TOOLS, ToolSpec

PACKAGE = Path(acq4_tools.__file__).parent


@pytest.fixture
def toolbar(qtbot):
    # Not registered with qtbot: it would close the toolbar while tools are
    # still open, and the confirmation dialog would wait forever.
    create_application()
    window = ToolbarWindow()
    yield window
    window.close_all_tools()
    window.hide()
    window.deleteLater()


def make_toolbar(count):
    create_application()
    return ToolbarWindow([ToolSpec(f"t{i}", f"Tool {i}", "", "unused") for i in range(count)])


def cell(window, widget):
    row, column, _rows, _columns = window.grid.getItemPosition(window.grid.indexOf(widget))
    return row, column


def test_controls_have_their_own_row_below_the_tools(toolbar):
    row_numbers = {cell(toolbar, b)[0] for b in toolbar.buttons.values()}
    assert row_numbers == {0}
    assert cell(toolbar, toolbar.status) == (1, 0)
    assert cell(toolbar, toolbar.keep_on_top) == (1, 1)
    assert cell(toolbar, toolbar.close_button) == (1, 2)


@pytest.mark.parametrize("count,rows", [(1, 1), (8, 1), (9, 2), (16, 2), (17, 3)])
def test_tools_wrap_after_eight(qtbot, count, rows):
    window = make_toolbar(count)
    qtbot.addWidget(window)
    cells = [cell(window, b) for b in window.buttons.values()]
    assert max(c[0] for c in cells) + 1 == rows
    assert max(c[1] for c in cells) <= 7
    assert cells[-1] == ((count - 1) // 8, (count - 1) % 8)
    assert cell(window, window.status) == (rows, 0)
    assert window.grid.columnCount() == max(min(count, 8), 3)


def test_items_are_equally_wide_and_stay_put_when_a_tool_opens(toolbar):
    toolbar.show()
    QtWidgets.QApplication.processEvents()
    tool_buttons = list(toolbar.buttons.values())
    items = [*tool_buttons, toolbar.status, toolbar.close_button]
    assert len({item.width() for item in items}) == 1
    lefts = [item.x() for item in items]
    tool_lefts = [button.x() for button in tool_buttons]
    assert len({b - a for a, b in zip(tool_lefts, tool_lefts[1:])}) == 1
    assert toolbar.status.x() == tool_lefts[0]
    assert toolbar.close_button.x() == tool_lefts[2]
    toolbar.open_tool(TOOLS[0])
    QtWidgets.QApplication.processEvents()
    assert [item.x() for item in items] == lefts


@pytest.mark.parametrize("spec", TOOLS, ids=lambda s: s.key)
def test_each_tool_opens_and_closes(toolbar, spec):
    window = toolbar.open_tool(spec)
    assert window is not None
    assert spec.key in toolbar.open_tools
    assert toolbar.buttons[spec.key].text().startswith("●")
    window.close()
    assert spec.key not in toolbar.open_tools
    assert toolbar.buttons[spec.key].text() == spec.title


def test_several_tools_open_at_once(toolbar):
    for spec in TOOLS:
        toolbar.open_tool(spec)
    assert len(toolbar.open_tools) == len(TOOLS)
    assert toolbar.close_all_tools()


def test_second_press_reuses_the_window(toolbar):
    first = toolbar.open_tool(TOOLS[0])
    assert toolbar.open_tool(TOOLS[0]) is first


def test_broken_tool_is_reported_and_toolbar_survives(toolbar, monkeypatch):
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", lambda self: shown.append(self.text()))
    spec = type(TOOLS[0])("fix_objscale", "Broken", "", "acq4_tools.no_such_module")
    assert toolbar.open_tool(spec) is None
    assert shown == ["Could not open Broken."]
    assert not toolbar.open_tools


def test_close_with_no_tools_does_not_ask(toolbar, monkeypatch):
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "exec", lambda self: pytest.fail("should not ask")
    )
    toolbar.show()
    assert toolbar.close()


def test_close_cancelled_keeps_tools_open(toolbar, monkeypatch):
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "exec", lambda self: QtWidgets.QMessageBox.StandardButton.Cancel
    )
    toolbar.show()
    toolbar.open_tool(TOOLS[0])
    assert not toolbar.close()
    assert toolbar.isVisible()
    assert TOOLS[0].key in toolbar.open_tools


def test_close_confirmed_closes_tools(toolbar, monkeypatch):
    asked = []

    def answer(box):
        asked.append(box.informativeText())
        return QtWidgets.QMessageBox.StandardButton.Close

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", answer)
    toolbar.show()
    window = toolbar.open_tool(TOOLS[0])
    assert toolbar.close()
    assert asked == [TOOLS[0].title]
    assert not toolbar.open_tools
    assert not window.isVisible()


def test_application_quit_asks_only_once(toolbar, monkeypatch):
    """Cmd-Q arrives as a Quit event rather than a close of the toolbar."""
    asked = []

    def answer(box):
        asked.append(box.text())
        return QtWidgets.QMessageBox.StandardButton.Close

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", answer)
    app = QtWidgets.QApplication.instance()
    monkeypatch.setattr(app, "quit", lambda: None)
    toolbar.show()
    toolbar.open_tool(TOOLS[0])
    event = QtCore.QEvent(QtCore.QEvent.Type.Quit)
    assert toolbar.eventFilter(app, event) is True
    assert len(asked) == 1
    assert not toolbar.open_tools
    assert not toolbar.isVisible()


def test_keep_on_top_is_remembered(toolbar):
    toolbar.keep_on_top.setChecked(False)
    assert history_store().get_setting("toolbar.keep_on_top") is False
    assert not (toolbar.windowFlags() & QtCore.Qt.WindowType.WindowStaysOnTopHint)


def test_package_has_no_hard_coded_locations_or_credentials():
    pattern = re.compile(
        r"/Volumes/|/cygdrive/|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?!na)"
        r"|password\s*=\s*[\"'][^\"']+[\"']"
    )
    offenders = []
    for path in PACKAGE.rglob("*"):
        if path.suffix in (".py", ".cfg"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{number}")
    assert offenders == []
