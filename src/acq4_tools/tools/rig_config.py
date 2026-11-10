"""Check a devices.cfg: wiring, optomechanical tree, and names against the acq4 source."""

from typing import Optional

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from acq4_tools.common.acq4_source import SourceCatalog, scan_acq4_devices
from acq4_tools.common.config_editor import ConfigEditorWindow
from acq4_tools.common.paths import acq4_devices_dir
from acq4_tools.tools.device_editor import DeviceEditor
from acq4_tools.tools.rig_analysis import (
    BOARD_MODELS,
    CUSTOM_MODEL,
    Board,
    OptoNode,
    RigAnalysis,
    _format_vector,
    analyze,
    write_alternates,
    write_boards,
)
from acq4_tools.tools.wiring_diagram import MUTED, PROBLEM, WiringDiagram

_NOT_SET = "Not set"
_TRANSFORM_COLUMN = 3
_ROW_PADDING = 3

def _read_only_table(headers: list) -> QtWidgets.QTableWidget:
    table = QtWidgets.QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
    return table


def _fill_table(table: QtWidgets.QTableWidget, rows: list, muted: Optional[list] = None) -> None:
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(str(value))
            if muted is not None and muted[row]:
                item.setForeground(QtGui.QBrush(QtGui.QColor(MUTED)))
            table.setItem(row, column, item)


class _OptomechanicsDelegate(QtWidgets.QStyledItemDelegate):
    """Top-aligns every cell, pads each row, and wraps the transform column. A tree
    asks for row heights as if columns were unlimited in width, so the wrapped
    text is measured here at the column's real width."""

    def __init__(self, tree: QtWidgets.QTreeWidget):
        super().__init__(tree)
        self.tree = tree

    def initStyleOption(self, option, index):  # noqa: N802 - Qt override name
        super().initStyleOption(option, index)
        option.displayAlignment = (
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
        )

    def paint(self, painter, option, index):
        padded = QtWidgets.QStyleOptionViewItem(option)
        padded.rect = option.rect.adjusted(0, _ROW_PADDING, 0, -_ROW_PADDING)
        super().paint(painter, padded, index)

    def sizeHint(self, option, index):  # noqa: N802 - Qt override name
        hint = super().sizeHint(option, index)
        height = hint.height()
        text = index.data()
        if index.column() == _TRANSFORM_COLUMN and text:
            style = self.tree.style()
            margin = style.pixelMetric(QtWidgets.QStyle.PixelMetric.PM_FocusFrameHMargin) + 1
            width = max(self.tree.columnWidth(index.column()) - 2 * margin, 1)
            area = QtCore.QRect(0, 0, width, 100000)
            flags = QtCore.Qt.TextFlag.TextWordWrap
            height = max(height, option.fontMetrics.boundingRect(area, flags, text).height() + 2)
        hint.setHeight(height + 2 * _ROW_PADDING)
        return hint


class _OptomechanicsTree(QtWidgets.QTreeWidget):
    """Shaded alternate rows and a thin line under each, so a row reads across."""

    def __init__(self):
        super().__init__()
        self.setAlternatingRowColors(True)
        palette = self.palette()
        base = palette.color(QtGui.QPalette.ColorRole.Base)
        shaded = base.darker(104) if base.lightness() > 127 else base.lighter(135)
        palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, shaded)
        self.setPalette(palette)

    def drawRow(self, painter, option, index):  # noqa: N802 - Qt override name
        super().drawRow(painter, option, index)
        painter.save()
        line = self.palette().color(QtGui.QPalette.ColorRole.Text)
        line.setAlpha(150)  # a mid gray whether the window is light or dark
        painter.setPen(line)
        y = option.rect.bottom()
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.restore()


class RigConfigWindow(ConfigEditorWindow):
    tool_title = "Rig Configuration"
    file_label = "devices.cfg file:"
    history_key = "rig_config.files"
    template_name = "devices_template.cfg"
    suggested_name = "devices.cfg"

    def build_tabs(self) -> None:
        self.analysis: Optional[RigAnalysis] = None
        self.catalog: Optional[SourceCatalog] = None
        self._catalog_top = ""
        self._scanning_top = ""
        self.board_rows: dict = {}
        self.resize(1120, 800)

        self.device_editor = DeviceEditor(self)
        self.devices_table = self.device_editor.table
        self.tabs.addTab(self.device_editor, "Devices")
        self.tabs.addTab(self._build_boards_tab(), "DAQ Boards")
        self.tabs.addTab(self._build_lines_tab(), "Line Map")
        self.tabs.addTab(self._build_diagram_tab(), "Wiring Diagram")
        self.tree = _OptomechanicsTree()
        self.tree.setHeaderLabels(["Device", "Driver", "File order", "Transform"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setWordWrap(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setItemDelegate(_OptomechanicsDelegate(self.tree))
        # Row heights follow the column width, but Qt only measures them on a layout.
        self.tree.header().sectionResized.connect(lambda *_args: self.tree.doItemsLayout())
        self.tabs.addTab(self.tree, "Optomechanics")
        self.keys_table = _read_only_table(["Device", "Driver", "Key", "In acq4 source"])
        self.tabs.addTab(self.keys_table, "Parameters")

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _build_boards_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(QtWidgets.QLabel(
            "The board tells the tool which lines exist. It is kept as a comment in devices.cfg."
        ))
        self.boards_table = QtWidgets.QTableWidget(0, 6)
        self.boards_table.setHorizontalHeaderLabels(
            ["DAQ", "Board", "AI", "AO", "Port 0 lines", "PFI"]
        )
        self.boards_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.boards_table, stretch=1)
        return tab

    def _build_lines_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        self.lines_table = _read_only_table(
            ["DAQ", "Terminal", "Status", "Active devices", "Commented-out devices"]
        )
        self.lines_table.setColumnWidth(3, 300)
        layout.addWidget(self.lines_table, stretch=1)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(
            "Devices that share a line but are never used together can be marked as alternates."
        ), stretch=1)
        self.mark_button = QtWidgets.QPushButton("Mark as Alternates")
        self.mark_button.clicked.connect(self.mark_alternates)
        self.unmark_button = QtWidgets.QPushButton("Clear Mark")
        self.unmark_button.clicked.connect(self.clear_alternates)
        row.addWidget(self.mark_button)
        row.addWidget(self.unmark_button)
        layout.addLayout(row)
        return tab

    def _build_diagram_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        self.diagram_view = pg.GraphicsView(background="w")
        self.diagram_view.enableMouse(True)
        self.diagram_view.setAspectLocked(True)
        self.diagram = WiringDiagram(self.diagram_view.scene())
        layout.addWidget(self.diagram_view, stretch=1)
        row = QtWidgets.QHBoxLayout()
        self.include_commented = QtWidgets.QCheckBox("Include commented-out devices")
        self.include_commented.toggled.connect(lambda _on: self._draw_diagram())
        row.addWidget(self.include_commented)
        row.addStretch(1)
        fit = QtWidgets.QPushButton("Fit")
        fit.clicked.connect(self._fit_diagram)
        export = QtWidgets.QPushButton("Export…")
        export.clicked.connect(lambda: self.export_diagram())
        row.addWidget(fit)
        row.addWidget(export)
        layout.addLayout(row)
        return tab

    # ------------------------------------------------------------------
    # source catalog
    # ------------------------------------------------------------------
    def acq4_dir_changed(self) -> None:
        self._ensure_catalog()

    def _ensure_catalog(self) -> None:
        top = self.acq4_dir.text()
        if top in (self._catalog_top, self._scanning_top):
            return
        devices_dir = acq4_devices_dir(top)
        if devices_dir is None:
            if self.catalog is not None:
                self.catalog = None
                self._catalog_top = ""
                self._refresh_views()
            return
        self._scanning_top = top
        self.statusBar().showMessage(f"Reading the acq4 source in {devices_dir}…")
        self.start_worker(
            lambda worker: (top, scan_acq4_devices(devices_dir, worker.check_cancelled)),
            succeeded=self._on_catalog_ready,
            failed=self._on_catalog_failed,
        )

    def _on_catalog_ready(self, result: tuple) -> None:
        top, catalog = result
        self._scanning_top = ""
        self.catalog = catalog
        self._catalog_top = top
        self.statusBar().showMessage(f"Checked against the acq4 source in {top}")
        self._refresh_views()
        self._ensure_catalog()  # the directory may have changed during the scan

    def _on_catalog_failed(self, detail: str) -> None:
        self._scanning_top = ""
        self.statusBar().showMessage("Could not read the acq4 source.")
        print(detail)

    # ------------------------------------------------------------------
    # showing the file
    # ------------------------------------------------------------------
    def load_form(self) -> None:
        self._refresh_views()
        self._fill_boards()
        self._ensure_catalog()

    def run_checks(self) -> list:
        return [] if self.analysis is None else self.analysis.findings

    def device_value_changed(self) -> None:
        """A value changed, and the settings shown in the form are still right."""
        self._refresh_views(rebuild_form=False)

    def device_structure_changed(self) -> None:
        self._refresh_views()

    def _refresh_views(self, rebuild_form: bool = True) -> None:
        if self.doc is None:
            return
        self.analysis = analyze(self.doc, self.catalog)
        if self.board_rows and self.analysis.board_keys != list(self.board_rows):
            self._fill_boards()
        self.device_editor.show_devices(rebuild_form)
        self._fill_lines()
        self._fill_tree()
        self._fill_keys()
        self._draw_diagram()
        self.edited()

    def _fill_lines(self) -> None:
        rows = self.analysis.line_rows
        _fill_table(self.lines_table, [
            [r.daq, r.place, r.status, ", ".join(r.active), ", ".join(r.alternates)]
            for r in rows
        ], [r.status == "free" for r in rows])
        for row, entry in enumerate(rows):
            if entry.status in ("shared", "not on board"):
                self.lines_table.item(row, 2).setForeground(QtGui.QBrush(QtGui.QColor(PROBLEM)))

    def _tree_item(self, node: OptoNode) -> QtWidgets.QTreeWidgetItem:
        device = node.device
        item = QtWidgets.QTreeWidgetItem(
            [device.name, device.driver or "", str(device.order + 1), node.transform]
        )
        settings = device.config.get("config", device.config)
        objectives = settings.get("objectives") if isinstance(settings, dict) else None
        if isinstance(objectives, dict):
            for slot, choices in objectives.items():
                for key, objective in (choices.items() if isinstance(choices, dict) else ()):
                    if isinstance(objective, dict):
                        detail = "; ".join(f"{k} {_format_vector(v)}"
                                           for k, v in objective.items() if k != "name")
                        item.addChild(QtWidgets.QTreeWidgetItem(
                            [f"slot {slot}: {objective.get('name', key)}", "objective", "", detail]
                        ))
        for child in node.children:
            item.addChild(self._tree_item(child))
        return item

    def _fill_tree(self) -> None:
        self.tree.clear()
        top = QtWidgets.QTreeWidgetItem(["Global coordinates", "", "", ""])
        for root in self.analysis.opto_roots:
            top.addChild(self._tree_item(root))
        self.tree.addTopLevelItem(top)
        self.tree.expandAll()

    def _fill_keys(self) -> None:
        rows = self.analysis.key_rows
        _fill_table(self.keys_table, [[r.device, r.driver, r.key, r.status] for r in rows],
                    [not r.active for r in rows])

    def _draw_diagram(self) -> None:
        if self.analysis is not None:
            self.diagram.draw(self.analysis, self.include_commented.isChecked())
            self._fit_diagram()

    def _fit_diagram(self) -> None:
        if not self.diagram.bounds.isEmpty():
            self.diagram_view.setRange(self.diagram.bounds, padding=0.02)

    # ------------------------------------------------------------------
    # boards
    # ------------------------------------------------------------------
    def _fill_boards(self) -> None:
        table = self.boards_table
        keys = self.analysis.board_keys
        boards = self.analysis.boards
        table.setRowCount(len(keys))
        self.board_rows = {}
        for row, daq in enumerate(keys):
            board = boards.get(daq) or boards.get(daq.partition("/")[0])
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(daq))
            combo = QtWidgets.QComboBox()
            combo.addItems([_NOT_SET, *BOARD_MODELS, CUSTOM_MODEL])
            if board is not None:
                known = board == BOARD_MODELS.get(board.model)
                combo.setCurrentText(board.model if known else CUSTOM_MODEL)
            combo.activated.connect(self._make_model_handler(daq))
            table.setCellWidget(row, 1, combo)
            spins = []
            for column, value in zip(range(2, 6), self._counts(board)):
                spin = QtWidgets.QSpinBox()
                spin.setRange(0, 256)
                spin.setValue(value)
                spin.setEnabled(board is not None)
                spin.editingFinished.connect(self._make_count_handler(daq))
                table.setCellWidget(row, column, spin)
                spins.append(spin)
            self.board_rows[daq] = (combo, spins)

    @staticmethod
    def _counts(board: Optional[Board]) -> tuple:
        return (0, 0, 0, 0) if board is None else (board.ai, board.ao, board.port0, board.pfi)

    def _make_model_handler(self, daq: str):
        return lambda _index: self._on_model_chosen(daq)

    def _make_count_handler(self, daq: str):
        return lambda: self._on_count_changed(daq)

    def _on_model_chosen(self, daq: str) -> None:
        combo, spins = self.board_rows[daq]
        model = combo.currentText()
        board = BOARD_MODELS.get(model)
        if board is not None:
            for spin, value in zip(spins, self._counts(board)):
                with QtCore.QSignalBlocker(spin):
                    spin.setValue(value)
        for spin in spins:
            spin.setEnabled(model != _NOT_SET)
        self._store_boards()

    def _on_count_changed(self, daq: str) -> None:
        combo, spins = self.board_rows[daq]
        current = BOARD_MODELS.get(combo.currentText())
        if current is not None and self._counts(current) != tuple(s.value() for s in spins):
            combo.setCurrentText(CUSTOM_MODEL)
        self._store_boards()

    def _store_boards(self) -> None:
        boards = {}
        for daq, (combo, spins) in self.board_rows.items():
            if combo.currentText() != _NOT_SET:
                boards[daq] = Board(combo.currentText(), *(s.value() for s in spins))
        if write_boards(self.doc, boards):
            self._refresh_views()

    # ------------------------------------------------------------------
    # alternates
    # ------------------------------------------------------------------
    def _selected_shared(self):
        rows = self.lines_table.selectionModel().selectedRows()
        if not rows:
            self.statusBar().showMessage("Select a line first.")
            return None
        entry = self.analysis.line_rows[rows[0].row()].shared
        if entry is None:
            self.statusBar().showMessage("That line is not shared.")
        return entry

    def mark_alternates(self) -> None:
        entry = self._selected_shared()
        if entry is None:
            return
        if len(entry.devices) < 2:
            self.statusBar().showMessage("Those are two channels of the same device.")
            return
        names = set(entry.devices)
        groups = [g for g in self.analysis.alternates if not g <= names]
        write_alternates(self.doc, [*groups, names])
        self._refresh_views()

    def clear_alternates(self) -> None:
        entry = self._selected_shared()
        if entry is None:
            return
        names = set(entry.devices)
        groups = [g for g in self.analysis.alternates if len(g & names) < 2]
        if write_alternates(self.doc, groups):
            self._refresh_views()

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------
    def export_diagram(self) -> bool:
        chosen, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export wiring diagram", "wiring.pdf", "PDF (*.pdf);;PNG image (*.png)"
        )
        if not chosen:
            return False
        return self.write_diagram(chosen)

    def write_diagram(self, path: str) -> bool:
        source = self.diagram.bounds.adjusted(-20, -20, 20, 20)
        scene = self.diagram.scene
        if path.lower().endswith(".pdf"):
            writer = QtGui.QPdfWriter(path)
            writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.Letter))
            orientation = QtGui.QPageLayout.Orientation
            writer.setPageOrientation(
                orientation.Portrait if source.height() > source.width() else orientation.Landscape
            )
            painter = QtGui.QPainter(writer)
            scene.render(painter, QtCore.QRectF(painter.viewport()), source)
            painter.end()
            saved = True
        else:
            image = QtGui.QImage(int(source.width() * 2), int(source.height() * 2),
                                 QtGui.QImage.Format.Format_RGB32)
            image.fill(QtGui.QColor("white"))
            painter = QtGui.QPainter(image)
            scene.render(painter, QtCore.QRectF(image.rect()), source)
            painter.end()
            saved = image.save(path)
        self.statusBar().showMessage(f"Saved {path}" if saved else f"Could not save {path}")
        return saved


def create_tool() -> RigConfigWindow:
    return RigConfigWindow()
