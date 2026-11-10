"""The floating toolbar that launches the tools."""

import os
import sys
import traceback
from typing import Optional, Sequence

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

from acq4_tools.common.history import history_store
from acq4_tools.common.tool_window import ToolWindow, workers_still_running
from acq4_tools.registry import TOOLS, ToolSpec

APP_NAME = "acq4 Tools"
_KEEP_ON_TOP = "toolbar.keep_on_top"
_GEOMETRY = "toolbar.horizontal_geometry"
_MAX_TOOLS_PER_ROW = 6
_FONT_SCALE = 0.85  # the toolbar's text, relative to the application font


class ToolbarWindow(QtWidgets.QWidget):
    def __init__(self, tools: Sequence[ToolSpec] = TOOLS):
        super().__init__()
        self.tools = tools
        self.open_tools: dict = {}  # tool key -> ToolWindow
        self.buttons: dict = {}  # tool key -> QPushButton
        self._quit_confirmed = False

        self.setWindowTitle(APP_NAME)
        font = self.font()
        font.setPointSizeF(font.pointSizeF() * _FONT_SCALE)
        self.setFont(font)
        self.setStyleSheet("QPushButton { padding: 2px 6px; }")
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.grid.setSpacing(4)
        # The window always fits the grid, whatever size was last saved.
        self.grid.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetFixedSize)

        for position, spec in enumerate(tools):
            button = QtWidgets.QPushButton(spec.title)
            button.setToolTip(spec.description)
            button.clicked.connect(self._make_launcher(spec))
            row, column = divmod(position, _MAX_TOOLS_PER_ROW)
            self.grid.addWidget(button, row, column)
            self.buttons[spec.key] = button

        keep_on_top = bool(history_store().get_setting(_KEEP_ON_TOP, True))
        self.keep_on_top = QtWidgets.QCheckBox("Keep on top")
        self.keep_on_top.setChecked(keep_on_top)
        self.keep_on_top.toggled.connect(self._on_keep_on_top)

        self.status = QtWidgets.QLabel()
        self.status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        # The controls have their own row below the tools.
        row = (len(tools) + _MAX_TOOLS_PER_ROW - 1) // _MAX_TOOLS_PER_ROW
        self.grid.addWidget(self.status, row, 0)
        self.grid.addWidget(self.keep_on_top, row, 1, QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.grid.addWidget(self.close_button, row, 2)
        self._equalize_columns()

        self._apply_on_top(keep_on_top)
        geometry = history_store().get_setting(_GEOMETRY)
        if geometry:
            self.restoreGeometry(QtCore.QByteArray.fromBase64(geometry.encode("ascii")))
        self._update_status()

    def _equalize_columns(self) -> None:
        """Make every cell as wide as the widest item needs, allowing for a tool
        button's bold open marker, so that opening a tool does not move anything."""
        widths = [
            self.keep_on_top.sizeHint().width(),
            self.close_button.sizeHint().width(),
            self.status.fontMetrics().horizontalAdvance("10 tool(s) open"),
        ]
        for spec in self.tools:
            self._set_open_marker(spec, True)
            widths.append(self.buttons[spec.key].sizeHint().width())
            self._set_open_marker(spec, False)
        width = max(widths)
        for column in range(self.grid.columnCount()):
            self.grid.setColumnMinimumWidth(column, width)
            self.grid.setColumnStretch(column, 1)

    # ------------------------------------------------------------------
    # launching
    # ------------------------------------------------------------------
    def _make_launcher(self, spec: ToolSpec):
        return lambda _checked=False: self.open_tool(spec)

    def open_tool(self, spec: ToolSpec) -> Optional[ToolWindow]:
        """Open a tool, or bring its window forward if it is already open."""
        window = self.open_tools.get(spec.key)
        if window is not None:
            window.showNormal()
            window.raise_()
            window.activateWindow()
            return window
        try:
            window = spec.create()
        except Exception:  # noqa: BLE001 - a broken tool must not stop the others
            detail = traceback.format_exc()
            print(detail, file=sys.stderr)
            box = QtWidgets.QMessageBox(self)
            box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
            box.setWindowTitle(APP_NAME)
            box.setText(f"Could not open {spec.title}.")
            box.setDetailedText(detail)
            box.exec()
            return None
        self.open_tools[spec.key] = window
        window.closed.connect(self._make_closed_handler(spec.key, window))
        self._set_open_marker(spec, True)
        self._update_status()
        window.show()
        window.raise_()
        return window

    def _make_closed_handler(self, key: str, window: ToolWindow):
        return lambda: self._on_tool_closed(key, window)

    def _on_tool_closed(self, key: str, window: ToolWindow) -> None:
        if self.open_tools.get(key) is window:
            del self.open_tools[key]
        spec = next(s for s in self.tools if s.key == key)
        self._set_open_marker(spec, False)
        self._update_status()
        window.deleteLater()

    def _set_open_marker(self, spec: ToolSpec, is_open: bool) -> None:
        button = self.buttons[spec.key]
        button.setText(f"● {spec.title}" if is_open else spec.title)
        font = button.font()
        font.setBold(is_open)
        button.setFont(font)

    def _update_status(self) -> None:
        count = len(self.open_tools)
        self.status.setText("No tools open" if count == 0 else f"{count} tool(s) open")

    # ------------------------------------------------------------------
    # floating behavior
    # ------------------------------------------------------------------
    def _apply_on_top(self, on_top: bool) -> None:
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, on_top)

    def _on_keep_on_top(self, on_top: bool) -> None:
        history_store().set_setting(_KEEP_ON_TOP, on_top)
        self._apply_on_top(on_top)
        self.show()  # changing window flags hides the window

    # ------------------------------------------------------------------
    # closing
    # ------------------------------------------------------------------
    def confirm_close_tools(self) -> bool:
        """Ask for permission to close any tools that are still open."""
        if not self.open_tools:
            return True
        titles = [s.title for s in self.tools if s.key in self.open_tools]
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setWindowTitle(f"Close {APP_NAME}")
        box.setText("These tools are still open. Close them and exit?")
        box.setInformativeText("\n".join(titles))
        box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Close
            | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        return box.exec() == QtWidgets.QMessageBox.StandardButton.Close

    def close_all_tools(self) -> bool:
        """Close every tool. False if a tool declined to close."""
        for window in list(self.open_tools.values()):
            window.close()
        return not self.open_tools

    def closeEvent(self, event):  # noqa: N802 - Qt override name
        if not (self._quit_confirmed or self.confirm_close_tools()) or not self.close_all_tools():
            self._quit_confirmed = False
            event.ignore()
            return
        self._quit_confirmed = True
        history_store().set_setting(
            _GEOMETRY, bytes(self.saveGeometry().toBase64()).decode("ascii")
        )
        event.accept()
        QtWidgets.QApplication.instance().quit()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override name
        """Handle application quit (Cmd-Q, the Dock) the same way as Close."""
        if event.type() == QtCore.QEvent.Type.Quit and watched is QtWidgets.QApplication.instance():
            if self.isVisible() and not self._quit_confirmed:
                if self.confirm_close_tools():
                    self._quit_confirmed = True
                    self.close()
                return True
        return super().eventFilter(watched, event)


def _show_unhandled_exception(exc_type, exc, tb) -> None:
    """Report an error in a tool. Without a handler, PyQt aborts the whole
    process on an unhandled exception in a slot, taking the other tools with it."""
    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    print(detail, file=sys.stderr)
    if QtWidgets.QApplication.instance() is None:
        return
    box = QtWidgets.QMessageBox()
    box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
    box.setWindowTitle(APP_NAME)
    box.setText(f"An error occurred: {exc}")
    box.setDetailedText(detail)
    box.exec()


def _filter_offscreen_messages(_mode, _context, message: str) -> None:
    """The build's self-test runs on Qt's offscreen platform, which prints a
    harmless complaint about propagateSizeHints for every window."""
    if "does not support propagateSizeHints" not in message:
        print(message, file=sys.stderr)


def self_test() -> int:
    """Open and close every tool. Used to check a packaged build."""
    QtCore.qInstallMessageHandler(_filter_offscreen_messages)
    status = 0
    for spec in TOOLS:
        try:
            window = spec.create()
            window.show()
            QtWidgets.QApplication.processEvents()
            window.close()
            print(f"ok      {spec.title}")
        except Exception:  # noqa: BLE001 - every tool should be reported
            status = 1
            print(f"FAILED  {spec.title}\n{traceback.format_exc()}")
    return status


def create_application() -> QtWidgets.QApplication:
    app = pg.mkQApp(APP_NAME)
    app.setStyle("fusion")
    # The tools index image arrays as [row, column].
    pg.setConfigOptions(imageAxisOrder="row-major")
    return app


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = create_application()
    if "--self-test" in argv:
        return self_test()

    sys.excepthook = _show_unhandled_exception
    toolbar = ToolbarWindow()
    app.installEventFilter(toolbar)
    toolbar.show()
    status = app.exec()
    if workers_still_running():
        # A thread is stuck on an unresponsive volume; it cannot be destroyed
        # safely, and normal interpreter shutdown would wait on or crash with it.
        sys.stdout.flush()
        os._exit(status)
    return status


if __name__ == "__main__":
    sys.exit(main())
