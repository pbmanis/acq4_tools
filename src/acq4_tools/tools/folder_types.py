"""Edit acq4's folderTypes.cfg: the folders offered by the Data Manager."""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from pyqtgraph.Qt import QtCore, QtWidgets

from acq4_tools.common.config_document import ConfigDocument, Node
from acq4_tools.common.config_editor import ConfigEditorWindow
from acq4_tools.tools.default_cfg import _button_column, _read_only_item

# The field types in acq4.modules.DataManager.FileInfoView.
FIELD_TYPES = ("string", "text", "list", "bool")
TYPE_KEYS = ("name", "experimentalUnit", "info")
RESERVED_TYPE_NAMES = ("Folder", "New...")
UNSAFE_NAME_CHARACTERS = '/\\:*?"<>|'
DEFAULT_TEXT_LINES = 4
ItemFlag = QtCore.Qt.ItemFlag


@dataclass
class FieldSpec:
    """A metadata field. In the file: (type, numLines, default) for text,
    (type, values, default) for list and (type, default) otherwise."""

    kind: str
    lines: Optional[int] = None
    values: list = field(default_factory=list)
    default: Any = None

    @classmethod
    def from_value(cls, value: Any) -> Optional["FieldSpec"]:
        """None if this is not a form of field that can be edited here."""
        if isinstance(value, str):
            value = (value,)
        if not isinstance(value, tuple) or not value or value[0] not in FIELD_TYPES:
            return None
        kind, rest = value[0], list(value[1:])
        if kind == "text":
            if rest and not isinstance(rest[0], int):
                return None
            return cls(kind, lines=rest[0] if rest else None,
                       default=rest[1] if len(rest) > 1 else None)
        if kind == "list":
            if not rest or not isinstance(rest[0], list):
                return None
            return cls(kind, values=rest[0], default=rest[1] if len(rest) > 1 else None)
        return cls(kind, default=rest[0] if rest else None)

    def to_value(self) -> Any:
        if self.kind == "text":
            parts = [self.kind]
            if self.lines is not None or self.default is not None:
                parts.append(DEFAULT_TEXT_LINES if self.lines is None else self.lines)
            if self.default is not None:
                parts.append(self.default)
        elif self.kind == "list":
            parts = [self.kind, self.values]
            if self.default is not None:
                parts.append(self.default)
        else:
            parts = [self.kind] if self.default is None else [self.kind, self.default]
        return parts[0] if len(parts) == 1 else tuple(parts)


def check_folder_types(doc: ConfigDocument) -> list:
    """Problems acq4 would have with this file."""
    warnings = []
    for node in doc.root.children:
        label = f"Folder type '{node.key}'"
        if not node.is_section:
            warnings.append(f"{label} is not a section with a name and info.")
            continue
        if node.key in RESERVED_TYPE_NAMES:
            warnings.append(f"{label}: the Data Manager already uses this name for its own menu.")
        for child in node.children:
            if child.key not in TYPE_KEYS:
                warnings.append(f"{label}: acq4 ignores the key '{child.key}'.")
        warnings += _check_name(doc, node, label)
        info = node.child("info")
        if info is None:
            warnings.append(f"{label} has no info section; selecting one will fail in acq4.")
            continue
        for item in info.children:
            warnings += _check_field(doc, item, label)
    return warnings


def _check_name(doc: ConfigDocument, node: Node, label: str) -> list:
    name_node = node.child("name")
    if name_node is None:
        return [f"{label} has no name format; creating one will fail in acq4."]
    name_format = doc.value(name_node)
    if not isinstance(name_format, str) or not name_format.strip():
        return [f"{label} has an empty name format."]
    name = time.strftime(name_format)
    if any(character in name for character in UNSAFE_NAME_CHARACTERS):
        return [f"{label}: the name '{name}' cannot be used for a directory."]
    return []


def _check_field(doc: ConfigDocument, item: Node, label: str) -> list:
    spec = None if item.is_section else FieldSpec.from_value(doc.value(item))
    if spec is None:
        return [f"{label}, field '{item.key}': acq4 has no built-in field of this form."]
    if spec.kind == "list":
        if not spec.values:
            return [f"{label}, field '{item.key}' has no list values."]
        if any(not isinstance(value, str) for value in spec.values):
            return [f"{label}, field '{item.key}': list values must be text."]
    return []


class FolderTypesWindow(ConfigEditorWindow):
    tool_title = "Folder Types"
    file_label = "folderTypes.cfg file:"
    history_key = "folder_types.files"
    template_name = "folderTypes_template.cfg"
    suggested_name = "folderTypes.cfg"

    def build_tabs(self) -> None:
        self.type_nodes: list = []
        self.field_nodes: list = []
        tab = QtWidgets.QWidget()
        outer = QtWidgets.QHBoxLayout(tab)
        outer.addWidget(self._build_type_list())
        outer.addWidget(self._build_type_details(), stretch=1)
        self.tabs.addTab(tab, "Folder Types")

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _build_type_list(self) -> QtWidgets.QWidget:
        group = QtWidgets.QGroupBox("Folder types")
        group.setMaximumWidth(260)
        layout = QtWidgets.QVBoxLayout(group)
        self.type_list = QtWidgets.QListWidget()
        self.type_list.currentRowChanged.connect(self._on_type_selected)
        self.type_list.itemChanged.connect(self._on_type_renamed)
        layout.addWidget(self.type_list, stretch=1)
        row = QtWidgets.QHBoxLayout()
        for text, handler in (
            ("Add", self.add_type), ("Remove", self.remove_type),
            ("Up", lambda: self.move_type(-1)), ("Down", lambda: self.move_type(1)),
        ):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        return group

    def _build_type_details(self) -> QtWidgets.QWidget:
        self.details = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.details)
        form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setToolTip(
            "Name given to new folders. Date codes such as %Y.%m.%d are filled in, "
            "and acq4 adds a number (_000)."
        )
        self.name_edit.textChanged.connect(self._update_name_preview)
        self.name_edit.editingFinished.connect(self._on_name_finished)
        self.name_preview = QtWidgets.QLabel()
        self.experimental_unit = QtWidgets.QCheckBox(
            "Experimental unit (one log file is kept for each folder)"
        )
        self.experimental_unit.clicked.connect(self._on_experimental_unit)
        form.addRow("Name format:", self.name_edit)
        form.addRow("A new folder today:", self.name_preview)
        form.addRow("", self.experimental_unit)
        layout.addLayout(form)

        row = QtWidgets.QHBoxLayout()
        self.fields_table = QtWidgets.QTableWidget(0, 5)
        self.fields_table.setHorizontalHeaderLabels(["Field", "Type", "Lines", "Default", "Values"])
        self.fields_table.horizontalHeader().setStretchLastSection(True)
        self.fields_table.setColumnWidth(0, 150)
        self.fields_table.setColumnWidth(2, 50)
        self.fields_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.fields_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.fields_table.itemChanged.connect(self._on_field_item_changed)
        self.fields_table.itemSelectionChanged.connect(self._fill_values)
        row.addWidget(self.fields_table, stretch=1)
        add, remove, up, down = (QtWidgets.QPushButton(t) for t in ("Add", "Remove", "Up", "Down"))
        add.clicked.connect(self.add_field)
        remove.clicked.connect(self.remove_field)
        up.clicked.connect(lambda: self.move_field(-1))
        down.clicked.connect(lambda: self.move_field(1))
        row.addLayout(_button_column(add, remove, up, down))
        layout.addLayout(row, stretch=3)
        layout.addWidget(QtWidgets.QLabel(
            "acq4 adds 'notes' and 'important' fields to every folder type that lacks them."
        ))

        self.values_group = QtWidgets.QGroupBox("List values")
        row = QtWidgets.QHBoxLayout(self.values_group)
        self.values_list = QtWidgets.QListWidget()
        self.values_list.itemChanged.connect(lambda _item: self._store_values())
        row.addWidget(self.values_list, stretch=1)
        add, remove, up, down = (QtWidgets.QPushButton(t) for t in ("Add", "Remove", "Up", "Down"))
        add.clicked.connect(self.add_value)
        remove.clicked.connect(self.remove_value)
        up.clicked.connect(lambda: self.move_value(-1))
        down.clicked.connect(lambda: self.move_value(1))
        row.addLayout(_button_column(add, remove, up, down))
        layout.addWidget(self.values_group, stretch=2)
        return self.details

    # ------------------------------------------------------------------
    # filling the fields
    # ------------------------------------------------------------------
    def load_form(self) -> None:
        self._fill_types()

    def run_checks(self) -> list:
        return check_folder_types(self.doc)

    def _fill_types(self, select: Optional[Node] = None) -> None:
        self.type_nodes = [n for n in self.doc.root.children if n.is_section]
        with QtCore.QSignalBlocker(self.type_list):
            self.type_list.clear()
            for node in self.type_nodes:
                item = QtWidgets.QListWidgetItem(node.key)
                item.setFlags(item.flags() | ItemFlag.ItemIsEditable)
                self.type_list.addItem(item)
            row = self.type_nodes.index(select) if select in self.type_nodes else 0
            self.type_list.setCurrentRow(row if self.type_nodes else -1)
        self._fill_type_details()

    def selected_type(self) -> Optional[Node]:
        row = self.type_list.currentRow()
        return self.type_nodes[row] if 0 <= row < len(self.type_nodes) else None

    def _on_type_selected(self, _row: int) -> None:
        self._fill_type_details()

    def _fill_type_details(self) -> None:
        node = self.selected_type()
        self.details.setEnabled(node is not None)
        name = "" if node is None else self.doc.value(node.child("name"), "")
        with QtCore.QSignalBlocker(self.name_edit):
            self.name_edit.setText(str(name))
        self._update_name_preview()
        unit = False if node is None else self.doc.value(node.child("experimentalUnit"), False)
        self.experimental_unit.setChecked(bool(unit))
        self._fill_fields()

    def _update_name_preview(self) -> None:
        name_format = self.name_edit.text().strip()
        self.name_preview.setText(f"{time.strftime(name_format)}_000" if name_format else "")

    def _fill_fields(self, select: Optional[Node] = None) -> None:
        table = self.fields_table
        node = self.selected_type()
        info = None if node is None else node.child("info")
        self.field_nodes = [] if info is None else list(info.children)
        with QtCore.QSignalBlocker(table):
            table.setRowCount(len(self.field_nodes))
            for row, item in enumerate(self.field_nodes):
                self._fill_field_row(row, item)
        if self.field_nodes:
            chosen = select if select in self.field_nodes else self.field_nodes[0]
            table.selectRow(self.field_nodes.index(chosen))
        self._fill_values()

    def _fill_field_row(self, row: int, item: Node) -> None:
        table = self.fields_table
        table.setItem(row, 0, QtWidgets.QTableWidgetItem(item.key))
        spec = None if item.is_section else FieldSpec.from_value(self.doc.value(item))
        if spec is None:
            table.removeCellWidget(row, 1)
            table.setItem(row, 1, _read_only_item("(other)"))
            for column, text in ((2, ""), (3, ""), (4, item.raw)):
                table.setItem(row, column, _read_only_item(text))
            return
        combo = QtWidgets.QComboBox()
        combo.addItems(FIELD_TYPES)
        combo.setCurrentText(spec.kind)
        combo.activated.connect(lambda _index: self._on_field_type(item, combo.currentText()))
        table.setCellWidget(row, 1, combo)
        lines = "" if spec.lines is None else str(spec.lines)
        table.setItem(row, 2, QtWidgets.QTableWidgetItem(lines) if spec.kind == "text"
                      else _read_only_item(""))
        default = "" if spec.default is None else str(spec.default)
        table.setItem(row, 3, QtWidgets.QTableWidgetItem(default))
        summary = ", ".join(str(v) for v in spec.values) if spec.kind == "list" else ""
        table.setItem(row, 4, _read_only_item(summary))

    def selected_field(self) -> Optional[Node]:
        rows = self.fields_table.selectionModel().selectedRows()
        return self.field_nodes[rows[0].row()] if rows else None

    def _selected_list_spec(self) -> Optional[FieldSpec]:
        item = self.selected_field()
        spec = None if item is None or item.is_section else FieldSpec.from_value(self.doc.value(item))
        return spec if spec is not None and spec.kind == "list" else None

    def _fill_values(self) -> None:
        spec = self._selected_list_spec()
        self.values_group.setVisible(spec is not None)
        with QtCore.QSignalBlocker(self.values_list):
            self.values_list.clear()
            if spec is not None:
                self.values_group.setTitle(f"List values for {self.selected_field().key}")
                for value in spec.values:
                    entry = QtWidgets.QListWidgetItem(str(value))
                    entry.setFlags(entry.flags() | ItemFlag.ItemIsEditable)
                    self.values_list.addItem(entry)

    # ------------------------------------------------------------------
    # folder types
    # ------------------------------------------------------------------
    def _on_type_renamed(self, item: QtWidgets.QListWidgetItem) -> None:
        node = self.type_nodes[self.type_list.row(item)]
        try:
            changed = self.doc.rename(node, item.text())
        except Exception as exc:  # noqa: BLE001 - shown to the user as a refused rename
            self.statusBar().showMessage(str(exc))
            with QtCore.QSignalBlocker(self.type_list):
                item.setText(node.key)
            return
        if changed:
            self.statusBar().showMessage(
                "Folders already created keep the old type name, and acq4 will not "
                "show this type's fields for them."
            )
            self.edited()

    def _unique(self, parent: Node, stem: str) -> str:
        number = 1
        name = stem
        while parent.child(name) is not None:
            number += 1
            name = f"{stem}{number}"
        return name

    def add_type(self) -> None:
        node = self.doc.add(self.doc.root, self._unique(self.doc.root, "NewType"))
        self.doc.add(node, "name", "newtype")
        self.doc.add(node, "info")
        self._fill_types(select=node)
        self.edited()

    def remove_type(self) -> None:
        node = self.selected_type()
        if node is not None:
            self.doc.remove(node)
            self._fill_types()
            self.edited()

    def move_type(self, delta: int) -> None:
        node = self.selected_type()
        if node is not None and self.doc.move(node, delta):
            self._fill_types(select=node)
            self.edited()

    def _on_name_finished(self) -> None:
        node = self.selected_type()
        if node is None:
            return
        text = self.name_edit.text().strip()
        existing = node.child("name")
        if existing is not None:
            self.doc.set_value(existing, text)
        else:
            self.doc.add(node, "name", text)
        self.edited()

    def _on_experimental_unit(self, checked: bool) -> None:
        node = self.selected_type()
        if node is None:
            return
        existing = node.child("experimentalUnit")
        if existing is not None:
            self.doc.set_value(existing, checked)
        elif checked:
            self.doc.add(node, "experimentalUnit", True, after=node.child("name"))
        self.edited()

    # ------------------------------------------------------------------
    # fields
    # ------------------------------------------------------------------
    def _on_field_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        node = self.field_nodes[item.row()]
        if item.column() == 0:
            self._rename_field(node, item)
        elif item.column() == 2:
            self._edit_spec(node, lines=item.text())
        elif item.column() == 3:
            self._edit_spec(node, default=item.text())
        self.edited()

    def _rename_field(self, node: Node, item: QtWidgets.QTableWidgetItem) -> None:
        try:
            self.doc.rename(node, item.text())
        except Exception as exc:  # noqa: BLE001 - shown to the user as a refused rename
            self.statusBar().showMessage(str(exc))
            with QtCore.QSignalBlocker(self.fields_table):
                item.setText(node.key)

    def _edit_spec(self, node: Node, lines: Optional[str] = None,
                   default: Optional[str] = None) -> None:
        spec = FieldSpec.from_value(self.doc.value(node))
        if spec is None:
            return
        if lines is not None:
            text = lines.strip()
            if text and not text.isdigit():
                self.statusBar().showMessage("Lines must be a whole number.")
            else:
                spec.lines = int(text) if text else None
        if default is not None:
            text = default.strip()
            if spec.kind == "bool" and text not in ("", "True", "False"):
                self.statusBar().showMessage("The default of a bool field is True or False.")
            elif spec.kind == "bool":
                spec.default = {"": None, "True": True, "False": False}[text]
            else:
                spec.default = text or None
        self.doc.set_value(node, spec.to_value())
        with QtCore.QSignalBlocker(self.fields_table):
            self._fill_field_row(self.field_nodes.index(node), node)

    def _on_field_type(self, node: Node, kind: str) -> None:
        old = FieldSpec.from_value(self.doc.value(node))
        if old is None or old.kind == kind:
            return
        self.doc.set_value(node, FieldSpec(kind, values=old.values).to_value() if kind == "list"
                           else FieldSpec(kind).to_value())
        if kind == "list" and not old.values:
            self.doc.set_raw(node, '"list", []')
        self._fill_fields(select=node)
        self.edited()

    def add_field(self) -> None:
        node = self.selected_type()
        if node is None:
            return
        info = node.child("info")
        if info is None:
            info = self.doc.add(node, "info")
        item = self.doc.add(info, self._unique(info, "new_field"), "string")
        self._fill_fields(select=item)
        self.edited()

    def remove_field(self) -> None:
        item = self.selected_field()
        if item is not None:
            self.doc.remove(item)
            self._fill_fields()
            self.edited()

    def move_field(self, delta: int) -> None:
        item = self.selected_field()
        if item is not None and self.doc.move(item, delta):
            self._fill_fields(select=item)
            self.edited()

    # ------------------------------------------------------------------
    # list values
    # ------------------------------------------------------------------
    def _store_values(self) -> None:
        item = self.selected_field()
        spec = self._selected_list_spec()
        if spec is None:
            return
        spec.values = [self.values_list.item(i).text().strip()
                       for i in range(self.values_list.count())]
        self.doc.set_value(item, spec.to_value())
        with QtCore.QSignalBlocker(self.fields_table):
            self._fill_field_row(self.field_nodes.index(item), item)
        self.edited()

    def add_value(self) -> None:
        if self._selected_list_spec() is None:
            return
        entry = QtWidgets.QListWidgetItem("new value")
        entry.setFlags(entry.flags() | ItemFlag.ItemIsEditable)
        with QtCore.QSignalBlocker(self.values_list):
            self.values_list.addItem(entry)
            self.values_list.setCurrentItem(entry)
        self._store_values()
        self.values_list.editItem(entry)

    def remove_value(self) -> None:
        row = self.values_list.currentRow()
        if row >= 0:
            with QtCore.QSignalBlocker(self.values_list):
                self.values_list.takeItem(row)
            self._store_values()

    def move_value(self, delta: int) -> None:
        row = self.values_list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.values_list.count():
            return
        with QtCore.QSignalBlocker(self.values_list):
            entry = self.values_list.takeItem(row)
            self.values_list.insertItem(target, entry)
            self.values_list.setCurrentRow(target)
        self._store_values()


def create_tool() -> FolderTypesWindow:
    return FolderTypesWindow()
