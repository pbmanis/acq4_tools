"""The help viewer and the Help menu each tool window carries.

The documentation is a set of Markdown pages in the package's docs directory,
one per tool (named by the tool's key) plus index.md. They are shown with
QTextBrowser, so no web engine is needed and they travel with a packaged build.
"""

from pathlib import Path
from typing import Optional

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from acq4_tools.common.paths import packaged_docs

INDEX_PAGE = "index.md"
_GEOMETRY = (820, 760)
_MARGIN = 14

_viewer: Optional["HelpWindow"] = None


def help_page(key: str) -> Path:
    """The documentation page for a tool key, or the overview."""
    return packaged_docs() / f"{key}.md"


class HelpWindow(QtWidgets.QMainWindow):
    """A small browser for the documentation pages. Links between pages are
    followed here; web links open in the system browser."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("acq4 Tools Help")
        self.resize(*_GEOMETRY)

        self.browser = QtWidgets.QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._follow_link)
        self.browser.setSearchPaths([str(packaged_docs())])
        self.browser.sourceChanged.connect(self._on_source_changed)
        self.browser.document().setDocumentMargin(_MARGIN)
        self.setCentralWidget(self.browser)

        bar = self.addToolBar("Navigation")
        bar.setMovable(False)
        self.back_action = bar.addAction("◀ Back", self.browser.backward)
        self.back_action.setToolTip("Go back to the previous page.")
        self.back_action.setShortcut(QtGui.QKeySequence.StandardKey.Back)
        self.forward_action = bar.addAction("Forward ▶", self.browser.forward)
        self.forward_action.setToolTip("Go forward again after going back.")
        self.forward_action.setShortcut(QtGui.QKeySequence.StandardKey.Forward)
        contents = bar.addAction("Contents", lambda: self.show_page(INDEX_PAGE))
        contents.setToolTip("Show the overview and the list of tools.")
        self.browser.backwardAvailable.connect(self.back_action.setEnabled)
        self.browser.forwardAvailable.connect(self.forward_action.setEnabled)
        self.back_action.setEnabled(False)
        self.forward_action.setEnabled(False)

        bar.addSeparator()
        self.find_edit = QtWidgets.QLineEdit()
        self.find_edit.setPlaceholderText("Find on this page")
        self.find_edit.setToolTip("Type text and press Return to find the next match.")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setMaximumWidth(260)
        self.find_edit.returnPressed.connect(self.find_next)
        bar.addWidget(self.find_edit)
        find_shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Find, self)
        find_shortcut.activated.connect(self.find_edit.setFocus)

    def show_page(self, name: str) -> bool:
        """Show a page by file name, e.g. "rig_config.md". False if it is missing."""
        path = packaged_docs() / name
        if not path.is_file():
            self.browser.setPlainText(
                f"The help page {name} was not found in {packaged_docs()}."
            )
            return False
        self.browser.setSource(
            QtCore.QUrl.fromLocalFile(str(path)), QtGui.QTextDocument.ResourceType.MarkdownResource
        )
        return True

    def find_next(self) -> None:
        text = self.find_edit.text()
        if not text:
            return
        if not self.browser.find(text):
            # Wrap around to the top of the page.
            self.browser.moveCursor(QtGui.QTextCursor.MoveOperation.Start)
            if not self.browser.find(text):
                self.statusBar().showMessage(f"'{text}' was not found on this page.", 4000)

    def _follow_link(self, url: QtCore.QUrl) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QtGui.QDesktopServices.openUrl(url)
            return
        if not url.isLocalFile() and url.isRelative() and not url.path():
            self.browser.scrollToAnchor(url.fragment())  # a link within the page
            return
        target = self.browser.source().resolved(url)
        if Path(target.toLocalFile()).suffix == ".md":
            self.browser.setSource(target, QtGui.QTextDocument.ResourceType.MarkdownResource)
        else:
            QtGui.QDesktopServices.openUrl(target)

    def _on_source_changed(self, url: QtCore.QUrl) -> None:
        title = page_title(Path(url.toLocalFile()))
        self.setWindowTitle(f"acq4 Tools Help - {title}" if title else "acq4 Tools Help")


def page_title(path: Path) -> str:
    """The first top-level heading of a page (Markdown sets no document title)."""
    try:
        with open(path, encoding="utf-8") as page:
            for line in page:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return ""


def show_help(key: str = "index") -> HelpWindow:
    """Open the shared help window at a tool's page (or the overview) and bring
    it forward. One window serves every tool, so it keeps its history."""
    global _viewer
    if _viewer is None:
        _viewer = HelpWindow()
        _viewer.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
    _viewer.show_page(f"{key}.md")
    _viewer.showNormal()
    _viewer.raise_()
    _viewer.activateWindow()
    return _viewer


def close_help() -> None:
    """Close the help window, if it was ever opened."""
    if _viewer is not None:
        _viewer.close()


def add_help_menu(window: QtWidgets.QMainWindow, key: str, title: str) -> QtWidgets.QMenu:
    """Give a tool window a Help menu with its own page and the overview."""
    menu = window.menuBar().addMenu("&Help")
    tool_help = menu.addAction(f"{title} Help", lambda: show_help(key))
    tool_help.setShortcut(QtGui.QKeySequence.StandardKey.HelpContents)
    tool_help.setToolTip(f"Instructions and caveats for {title}.")
    overview = menu.addAction("acq4 Tools Overview", lambda: show_help("index"))
    overview.setToolTip("What each tool does, and where settings are kept.")
    menu.setToolTipsVisible(True)
    return menu
