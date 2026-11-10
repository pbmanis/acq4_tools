"""The Devices tab of Rig Configuration: a list of devices and a form for each."""

from typing import Callable, Optional

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from acq4_tools.common.acq4_source import NOT_FOUND
from acq4_tools.common.config_document import ConfigError, Node
from acq4_tools.tools.rig_analysis import (
    AI_MODES,
    ANALOG_TYPES,
    DIGITAL_TYPES,
    REFERENCE_KEYS,
    DeviceExample,
    RigDevice,
    _descends,
    _type_fits_terminal,
    channel_name,
    device_examples,
    rename_device,
)

_NODE_ROLE = QtCore.Qt.ItemDataRole.UserRole
_NO_DEVICE = "(none)"
_BLANK_EXAMPLE = "Blank"
_MUTED = "#999999"
_PROBLEM = "#C00000"
StandardButton = QtWidgets.QMessageBox.StandardButton
ItemFlag = QtCore.Qt.ItemFlag


def _button_row(*buttons) -> QtWidgets.QHBoxLayout:
    row = QtWidgets.QHBoxLayout()
    for button in buttons:
        row.addWidget(button)
    return row


def _is_channel(section: Optional[Node]) -> bool:
    return section is not None and section.child("channel") is not None \
        and section.child("device") is not None


class AddDeviceDialog(QtWidgets.QDialog):
    def __init__(self, parent, drivers: list, examples: list):
        super().__init__(parent)
        self.setWindowTitle("Add device")
        self.examples = examples
        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit()
        self.driver = QtWidgets.QComboBox()
        self.driver.setEditable(True)
        self.driver.addItems(drivers)
        self.driver.currentTextChanged.connect(self._fill_examples)
        self.example = QtWidgets.QComboBox()
        form.addRow("Driver:", self.driver)
        form.addRow("Start from:", self.example)
        form.addRow("Device name:", self.name)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._fill_examples(self.driver.currentText())

    def _fill_examples(self, driver: str) -> None:
        self.example.clear()
        self.example.addItem(_BLANK_EXAMPLE, None)
        for example in self.examples:
            if example.driver == driver:
                self.example.addItem(f"acq4 example: {example.name}", example)
        if self.example.count() > 1:
            self.example.setCurrentIndex(1)


class DeviceEditor(QtWidgets.QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self._current: Optional[tuple] = None  # name, active, position of a commented block
        self._filling = False

        layout = QtWidgets.QHBoxLayout(self)
        splitter = QtWidgets.QSplitter()
        layout.addWidget(splitter)
        splitter.addWidget(self._build_list())
        splitter.addWidget(self._build_form())
        splitter.setSizes([420, 540])

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _build_list(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Device", "Driver", "State", "Lines", "Parent"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 48)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, stretch=1)

        self.toggle_button = QtWidgets.QPushButton("Disable")
        self.toggle_button.setToolTip("Comment the device out of the file, or bring it back.")
        self.toggle_button.clicked.connect(self.toggle_enabled)
        add = QtWidgets.QPushButton("Add…")
        add.clicked.connect(self.add_device_from_dialog)
        self.remove_button = QtWidgets.QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_device)
        self.up_button = QtWidgets.QPushButton("Up")
        self.up_button.clicked.connect(lambda: self.move_device(-1))
        self.down_button = QtWidgets.QPushButton("Down")
        self.down_button.clicked.connect(lambda: self.move_device(1))
        layout.addLayout(_button_row(self.toggle_button, add, self.remove_button,
                                     self.up_button, self.down_button))
        return panel

    def _build_form(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.editingFinished.connect(self._on_name_finished)
        form.addRow("Device name:", self.name_edit)
        layout.addLayout(form)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Setting", "Value", "In acq4 source"])
        self.tree.setColumnWidth(0, 170)
        self.tree.setColumnWidth(1, 240)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, stretch=1)
        self.note = QtWidgets.QLabel()
        layout.addWidget(self.note)
        self.add_setting_button = QtWidgets.QPushButton("Add Setting…")
        self.add_setting_button.clicked.connect(self.add_setting_from_dialog)
        self.add_channel_button = QtWidgets.QPushButton("Add DAQ Channel…")
        self.add_channel_button.clicked.connect(self.add_channel_from_dialog)
        self.remove_setting_button = QtWidgets.QPushButton("Remove Setting")
        self.remove_setting_button.clicked.connect(self.remove_setting)
        layout.addLayout(_button_row(self.add_setting_button, self.add_channel_button,
                                     self.remove_setting_button))
        return panel

    # ------------------------------------------------------------------
    # the list
    # ------------------------------------------------------------------
    @property
    def doc(self):
        return self.host.doc

    @property
    def analysis(self):
        return self.host.analysis

    def show_devices(self, rebuild_form: bool) -> None:
        counts: dict = {}
        for connection in self.analysis.connections:
            key = connection.device, connection.active
            counts[key] = counts.get(key, 0) + 1
        with QtCore.QSignalBlocker(self.table):
            self.table.setRowCount(len(self.analysis.devices))
            for row, device in enumerate(self.analysis.devices):
                config = device.config.get("config", device.config)
                parent = config.get("parentDevice", "") if isinstance(config, dict) else ""
                if isinstance(parent, dict):
                    parent = parent.get("name", "")
                values = (device.name, device.driver or "(none)",
                          "Active" if device.active else "Commented out",
                          counts.get((device.name, device.active), 0) or "", parent)
                for column, value in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(str(value))
                    if not device.active:
                        item.setForeground(QtGui.QBrush(QtGui.QColor(_MUTED)))
                    self.table.setItem(row, column, item)
            self.table.selectRow(self._row_to_select())
        self._remember_selection()
        if rebuild_form:
            self.fill_form()

    def _row_to_select(self) -> int:
        if self._current is None:
            return 0
        name, active, start = self._current
        matches = [row for row, d in enumerate(self.analysis.devices)
                   if d.name == name and d.active == active]
        if not matches:
            return 0
        return min(matches, key=lambda row: abs(self.analysis.devices[row].start - start))

    def current_device(self) -> Optional[RigDevice]:
        rows = self.table.selectionModel().selectedRows()
        return self.analysis.devices[rows[0].row()] if rows else None

    def _remember_selection(self) -> None:
        device = self.current_device()
        self._current = None if device is None else (device.name, device.active, device.start)

    def _on_selection_changed(self) -> None:
        self._remember_selection()
        self.fill_form()

    def select_device(self, name: str, active: bool = True, start: int = -1) -> None:
        self._current = (name, active, start)
        self.host.device_structure_changed()

    # ------------------------------------------------------------------
    # the form
    # ------------------------------------------------------------------
    def fill_form(self) -> None:
        device = self.current_device()
        self._filling = True
        self.tree.clear()
        self.name_edit.setText("" if device is None else device.name)
        editable = device is not None and device.active
        for widget in (self.name_edit, self.add_setting_button, self.add_channel_button,
                       self.remove_setting_button, self.up_button, self.down_button):
            widget.setEnabled(editable)
        self.toggle_button.setEnabled(device is not None)
        self.remove_button.setEnabled(device is not None)
        self.toggle_button.setText("Disable" if device is None or device.active else "Enable")
        if device is None:
            self.note.setText("")
        elif device.active:
            self.note.setText("Values can be numbers, text or expressions such as 5*um.")
            for child in self.doc.node(device.name).children:
                self._add_row(self.tree.invisibleRootItem(), child, device)
        else:
            self.note.setText("Commented out. Enable this device to edit it.")
            self._add_read_only(self.tree.invisibleRootItem(), device.config)
        self.tree.expandAll()
        self._filling = False

    def _add_read_only(self, parent, mapping: dict) -> None:
        for key, value in mapping.items():
            item = QtWidgets.QTreeWidgetItem([str(key), "" if isinstance(value, dict) else
                                              repr(value), ""])
            parent.addChild(item)
            if isinstance(value, dict):
                self._add_read_only(item, value)

    def _status(self, node: Node, device: RigDevice) -> str:
        catalog = self.host.catalog
        if catalog is None or node.parent.parent is not self.doc.root or node.key == "driver" \
                or not device.driver or not catalog.is_driver(device.driver):
            return ""
        if _is_channel(node) or node.key == "config":
            return "DAQ channel" if _is_channel(node) else ""
        return catalog.key_status(device.driver, node.key)

    def _add_row(self, parent, node: Node, device: RigDevice) -> None:
        status = self._status(node, device)
        item = QtWidgets.QTreeWidgetItem([node.key, "", status])
        item.setData(0, _NODE_ROLE, node)
        if status == NOT_FOUND:
            item.setForeground(2, QtGui.QBrush(QtGui.QColor(_PROBLEM)))
        item.setFlags(item.flags() | ItemFlag.ItemIsEditable)
        parent.addChild(item)
        if node.is_section:
            for child in node.children:
                self._add_row(item, child, device)
            return
        widget = self._value_widget(node, device)
        if widget is not None:
            self.tree.setItemWidget(item, 1, widget)
        else:
            item.setText(1, node.raw)

    def _combo(self, node: Node, values: list, editable: bool = False,
               convert: Callable = str, rebuild: bool = False) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setEditable(editable)
        current = str(self.doc.value(node))
        combo.addItems(list(dict.fromkeys([current, *values])))
        combo.setCurrentText(current)
        store = lambda *_args: self._store_choice(node, combo, convert, rebuild)  # noqa: E731
        combo.activated.connect(store)
        if editable:
            combo.lineEdit().editingFinished.connect(store)
        return combo

    def _active_names(self, excluding: str) -> list:
        return [c.key for c in self.doc.root.children if c.key != excluding]

    def _value_widget(self, node: Node, device: RigDevice) -> Optional[QtWidgets.QComboBox]:
        try:
            value = self.doc.value(node)
        except ConfigError:
            return None
        key, section = node.key, node.parent
        if key == "driver" and section.parent is self.doc.root:
            return self._combo(node, self.drivers(), editable=True, rebuild=True)
        if key == "parentDevice" or (key in REFERENCE_KEYS and isinstance(value, str)):
            names = [_NO_DEVICE, *self._active_names(device.name)]
            return self._combo(node, names, rebuild=True)
        if _is_channel(section):
            if key == "device" and isinstance(value, str):
                return self._combo(node, self.analysis.daqs, rebuild=True)
            if key == "type":
                return self._combo(node, [*ANALOG_TYPES, *DIGITAL_TYPES], rebuild=True)
            if key == "mode" and isinstance(value, str):
                return self._combo(node, list(AI_MODES))
            if key == "channel" and isinstance(value, str):
                return self._combo(node, self._line_choices(section), editable=True, rebuild=True)
        if isinstance(value, bool):
            return self._combo(node, ["True", "False"], convert=lambda text: text == "True")
        return None

    def _free_lines(self, daq: str, kind: Optional[str]) -> list:
        return [channel_name(row.terminal) for row in self.analysis.line_rows
                if row.daq == daq and row.status == "free"
                and _type_fits_terminal(kind, row.terminal)]

    def _line_choices(self, section: Node) -> list:
        daq = self.doc.value(section.child("device"))
        kind_node = section.child("type")
        return self._free_lines(daq, None if kind_node is None else self.doc.value(kind_node))

    def drivers(self) -> list:
        catalog = self.host.catalog
        if catalog is not None:
            return catalog.driver_names()
        return sorted({example.driver for example in device_examples()})

    def _store_choice(self, node: Node, combo: QtWidgets.QComboBox, convert: Callable,
                      rebuild: bool) -> None:
        text = combo.currentText().strip()
        if text == _NO_DEVICE:
            self.doc.comment_out(node)
            self.host.device_structure_changed()
            return
        if self.doc.set_value(node, convert(text)):
            if rebuild:
                self.host.device_structure_changed()
            else:
                self.host.device_value_changed()

    def _on_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        node = item.data(0, _NODE_ROLE)
        if self._filling or node is None:
            return
        if column == 0:
            self._rename_setting(item, node)
        elif column == 1:
            self._store_typed(item, node)

    def _rename_setting(self, item: QtWidgets.QTreeWidgetItem, node: Node) -> None:
        try:
            changed = self.doc.rename(node, item.text(0))
        except ConfigError as exc:
            self.host.statusBar().showMessage(str(exc))
            with QtCore.QSignalBlocker(self.tree):
                item.setText(0, node.key)
            return
        if changed:
            self.host.device_structure_changed()

    def _store_typed(self, item: QtWidgets.QTreeWidgetItem, node: Node) -> None:
        if node.is_section:
            with QtCore.QSignalBlocker(self.tree):
                item.setText(1, "")
            return
        if self.doc.set_typed(node, item.text(1)):
            self.host.statusBar().showMessage(f"{node.key} stored as text.")
        with QtCore.QSignalBlocker(self.tree):
            item.setText(1, node.raw)
        self.host.device_value_changed()

    # ------------------------------------------------------------------
    # changing a device's name and state
    # ------------------------------------------------------------------
    def _on_name_finished(self) -> None:
        device = self.current_device()
        if device is None or not device.active:
            return
        new_name = self.name_edit.text().strip()
        if new_name == device.name:
            return
        try:
            rename_device(self.doc, self.doc.node(device.name), new_name)
        except ConfigError as exc:
            self.host.statusBar().showMessage(str(exc))
            self.name_edit.setText(device.name)
            return
        self.select_device(new_name)
        self.host.statusBar().showMessage(
            f"Renamed in this file. Check default.cfg for modules that name {device.name}."
        )

    def _confirm(self, text: str, detail: str = "") -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setWindowTitle(self.host.tool_title)
        box.setText(text)
        box.setInformativeText(detail)
        box.setStandardButtons(StandardButton.Ok | StandardButton.Cancel)
        box.setDefaultButton(StandardButton.Cancel)
        return box.exec() == StandardButton.Ok

    def toggle_enabled(self) -> None:
        device = self.current_device()
        if device is None:
            return
        if device.active:
            self.doc.comment_block(self.doc.node(device.name))
            self._current = (device.name, False, -1)
            self.host.device_structure_changed()
            return
        existing = self.doc.node(device.name)
        if existing is not None:
            if not self._confirm(f"A device named {device.name} is already active.",
                                 "Comment that one out and use this one instead?"):
                return
            self.doc.comment_block(existing)
        try:
            self.doc.uncomment_lines(device.start, device.end, device.base)
        except ConfigError as exc:
            self.host.statusBar().showMessage(str(exc))
            return
        self.select_device(device.name)

    def remove_device(self) -> None:
        device = self.current_device()
        if device is None or not self._confirm(
            f"Remove {device.name} from this file?",
            "To keep it for later, use Disable instead. Revert undoes this until you save.",
        ):
            return
        if device.active:
            self.doc.remove(self.doc.node(device.name))
        else:
            self.doc.delete_lines(device.start, device.end)
        self._current = None
        self.host.device_structure_changed()

    def move_device(self, delta: int) -> None:
        device = self.current_device()
        if device is not None and device.active \
                and self.doc.move(self.doc.node(device.name), delta):
            self.select_device(device.name)

    def add_device_from_dialog(self) -> None:
        dialog = AddDeviceDialog(self, self.drivers(), device_examples())
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.add_device(dialog.name.text().strip(), dialog.driver.currentText().strip(),
                            dialog.example.currentData())

    def add_device(self, name: str, driver: str, example: Optional[DeviceExample]) -> bool:
        if not name or ":" in name or self.doc.node(name) is not None:
            self.host.statusBar().showMessage(f"'{name}' cannot be used as a device name.")
            return False
        self.doc.insert_block(f"{name}:\n    driver: {driver!r}" if example is None
                              else example.text_named(name))
        self.select_device(name)
        return True

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------
    def selected_node(self) -> Optional[Node]:
        items = self.tree.selectedItems()
        return items[0].data(0, _NODE_ROLE) if items else None

    def _target_section(self, device: RigDevice) -> Node:
        node = self.selected_node()
        if node is not None and (node.is_section or node.raw == "{}"):
            return node
        return self.doc.node(device.name)

    def add_setting_from_dialog(self) -> None:
        device = self.current_device()
        if device is None or not device.active:
            return
        catalog = self.host.catalog
        target = self._target_section(device)
        known = []
        if catalog is not None and device.driver and target is self.doc.node(device.name):
            present = {child.key for child in target.children}
            known = [k for k in catalog.known_keys(device.driver) if k not in present]
        name, accepted = QtWidgets.QInputDialog.getItem(
            self, "Add setting", "Setting name:", known, 0, True
        )
        if accepted:
            self.add_setting(name.strip())

    def add_setting(self, name: str) -> bool:
        device = self.current_device()
        try:
            self.doc.add(self._target_section(device), name, None)
        except ConfigError as exc:
            self.host.statusBar().showMessage(str(exc))
            return False
        self.host.device_structure_changed()
        return True

    def remove_setting(self) -> None:
        node = self.selected_node()
        if node is not None:
            self.doc.remove(node)
            self.host.device_structure_changed()

    def add_channel_from_dialog(self) -> None:
        name, accepted = QtWidgets.QInputDialog.getText(self, "Add DAQ channel", "Channel name:")
        if accepted:
            self.add_channel(name.strip())

    def add_channel(self, name: str, kind: str = "ai") -> bool:
        device = self.current_device()
        daqs = self.analysis.daqs
        if device is None or not device.active or not daqs:
            self.host.statusBar().showMessage("The file needs an active DAQ device first.")
            return False
        node = self.doc.node(device.name)
        target = node
        if _descends(self.host.catalog, device.driver, "DAQGeneric"):
            target = node.child("channels") or self.doc.add(node, "channels")
        free = self._free_lines(daqs[0], kind)
        try:
            section = self.doc.add(target, name)
        except ConfigError as exc:
            self.host.statusBar().showMessage(str(exc))
            return False
        self.doc.add(section, "device", daqs[0])
        self.doc.add(section, "channel", free[0] if free else "/Dev1/ai0")
        self.doc.add(section, "type", kind)
        self.host.device_structure_changed()
        return True
