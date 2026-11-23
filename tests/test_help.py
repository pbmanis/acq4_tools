import re

import pytest
from pyqtgraph.Qt import QtCore, QtWidgets

from acq4_tools.app import ToolbarWindow, create_application
from acq4_tools.common import help as help_module
from acq4_tools.common.help import HelpWindow, help_page, page_title, show_help
from acq4_tools.common.paths import packaged_docs
from acq4_tools.registry import TOOLS

_LINK_RE = re.compile(r"\]\(([^)#]+)(#[^)]*)?\)")


@pytest.fixture
def viewer(qtbot):
    create_application()
    yield
    if help_module._viewer is not None:
        help_module._viewer.close()
        help_module._viewer.deleteLater()
        help_module._viewer = None


@pytest.mark.parametrize("spec", TOOLS, ids=lambda s: s.key)
def test_every_tool_has_a_help_page_titled_like_its_button(spec):
    page = help_page(spec.key)
    assert page.is_file()
    assert page_title(page) == spec.title


def test_links_between_pages_lead_somewhere():
    for page in packaged_docs().glob("*.md"):
        for target, _anchor in _LINK_RE.findall(page.read_text(encoding="utf-8")):
            if not target.startswith(("http://", "https://", "mailto:")):
                assert (page.parent / target).is_file(), f"{page.name} links to {target}"


@pytest.mark.parametrize("spec", TOOLS, ids=lambda s: s.key)
def test_each_tool_window_has_a_help_menu_that_opens_its_page(viewer, spec):
    window = spec.create()
    try:
        menus = [a for a in window.menuBar().actions() if a.text() == "&Help"]
        assert len(menus) == 1
        tool_help = menus[0].menu().actions()[0]
        assert tool_help.text() == f"{spec.title} Help"
        tool_help.trigger()
        shown = help_module._viewer.browser.source().toLocalFile()
        assert shown == str(help_page(spec.key))
        assert spec.title in help_module._viewer.windowTitle()
        assert "not found" not in help_module._viewer.browser.toPlainText()
    finally:
        window.close()


def test_one_help_window_serves_every_tool(viewer):
    first = show_help("rig_config")
    second = show_help("dir_check")
    assert first is second
    assert first.browser.source().toLocalFile().endswith("dir_check.md")
    assert first.back_action.isEnabled()
    first.browser.backward()
    assert first.browser.source().toLocalFile().endswith("rig_config.md")


def test_following_a_link_opens_the_page_in_the_viewer(viewer):
    window = show_help("index")
    window._follow_link(QtCore.QUrl("rig_config.md"))
    assert window.browser.source().toLocalFile() == str(help_page("rig_config"))
    assert "DAQ Boards" in window.browser.toPlainText()


def test_a_missing_page_says_so(viewer):
    window = HelpWindow()
    assert not window.show_page("no_such_page.md")
    assert "not found" in window.browser.toPlainText()
    window.deleteLater()


def test_find_wraps_to_the_top(viewer):
    window = show_help("rig_config")
    window.find_edit.setText("Optomechanics")
    window.find_next()
    first = window.browser.textCursor().position()
    for _ in range(20):
        window.find_next()
        if window.browser.textCursor().position() == first:
            break
    assert window.browser.textCursor().position() == first


def test_the_toolbar_help_button_opens_the_overview(viewer):
    toolbar = ToolbarWindow()
    try:
        toolbar.help_button.click()
        assert help_module._viewer.browser.source().toLocalFile() == str(help_page("index"))
    finally:
        toolbar.hide()
        toolbar.deleteLater()


def _untipped_buttons(window: QtWidgets.QWidget) -> list:
    """Buttons with no tooltip of their own. Qt's internal buttons (the menu bar
    overflow, a table's corner, a tab bar's scroll arrows) and the buttons of a
    standard dialog button box are left out."""
    missing = []
    for button in window.findChildren(QtWidgets.QAbstractButton):
        parent = button.parentWidget()
        if (button.toolTip() or button.objectName().startswith("qt_")
                or isinstance(parent, (QtWidgets.QTabBar, QtWidgets.QDialogButtonBox))):
            continue
        missing.append(button.text() or type(button).__name__)
    return missing


@pytest.mark.parametrize("spec", TOOLS, ids=lambda s: s.key)
def test_every_button_has_a_tooltip(viewer, spec):
    window = spec.create()
    try:
        window.show()
        QtWidgets.QApplication.processEvents()
        assert _untipped_buttons(window) == []
    finally:
        window.close()


def test_every_toolbar_button_has_a_tooltip(viewer):
    toolbar = ToolbarWindow()
    try:
        assert _untipped_buttons(toolbar) == []
    finally:
        toolbar.hide()
        toolbar.deleteLater()


def test_every_objective_scale_command_has_a_tip(viewer):
    from acq4_tools.tools.fix_objscale import FixObjective, load_objective_data

    tool = FixObjective(load_objective_data())
    tool.build_ptree()
    assert [p["name"] for p in tool.params if not p.get("tip")] == []
