"""Edit acq4's default.cfg: modules and their shortcuts, directories and options."""

from pathlib import Path
from typing import Optional

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from acq4_tools.common.config_document import (
    ConfigDocument,
    ConfigError,
    IncludedFile,
    Node,
)
from acq4_tools.common.config_editor import ConfigEditorWindow

UNSET = object()
ItemFlag = QtCore.Qt.ItemFlag

# Names acq4 accepts for the "module" key: the Module subclasses in acq4.modules.
# A dotted name imports a custom class.
KNOWN_MODULES = (
    "DataManager", "TaskRunner", "Camera", "Patch", "MultiPatch", "Imager", "Console",
    "TaskMonitor", "MosaicEditorModule", "Manager", "NoiseMonitor", "SolutionEditor",
    "Tasker", "CCFViewer", "FixObjective",
)
MODULE_KEYS = ("module", "shortcut", "config", "exec", "import")
MODULE_SETTINGS = {
    "TaskRunner": ("taskDir", "reduceMemoryUsage"),
    "Tasker": ("taskDir", "taskerDir"),
    "Patch": ("clampDev", "sampleRate", "downsample"),
    "MultiPatch": ("enableMockPatch", "patchProfiles", "xkeysDevice",
                   "coarseSearchDistance", "fineSearchDistance"),
    "Imager": ("cameraModule", "scanner", "laser", "detector", "detectors",
               "powerCheckInterval"),
    "SolutionEditor": ("recipeFile",),
    "CCFViewer": ("resolution",),
}

# Keys that Manager._loadConfig acts on, at the top level or under "misc", and
# those that are read elsewhere in acq4.
LOADED_KEYS = frozenset((
    "imports", "execFiles", "devices", "modules", "storageDir", "defaultCompression",
    "folderTypes", "stylesheet", "disableErrorPopups", "defaultMouseMode", "useOpenGL",
    "misc", "cudaImageProcessing",
))
TOP_LEVEL_ONLY_KEYS = frozenset(("configurations", "drivers"))
COMPRESSION_FILTERS = (None, "gzip", "szip", "lzf")

_BOOLEAN = (("True", True), ("False", False))
OPTIONS = (
    ("cudaImageProcessing", "CUDA image processing",
     "Use a CUDA-enabled GPU to process camera images.", _BOOLEAN),
    ("defaultCompression", "HDF5 compression",
     "Compression used when writing data files. 'gzip' is slow; 'lzf' and 'szip' "
     "are not available on all HDF5 installations.",
     (("No compression", None), ("gzip", "gzip"), ("gzip, level 1", ("gzip", 1)),
      ("gzip, level 5", ("gzip", 5)), ("gzip, level 9", ("gzip", 9)),
      ("lzf", "lzf"), ("szip", "szip"))),
    ("disableErrorPopups", "Disable error popups",
     "Do not pop up the log window when an error occurs.", _BOOLEAN),
    ("defaultMouseMode", "Plot mouse mode",
     "How the mouse drags pyqtgraph plots.",
     (("One button", "oneButton"), ("Three button", "threeButton"))),
    ("useOpenGL", "Use OpenGL", "Draw plots with OpenGL.", _BOOLEAN),
)


def option_node(doc: ConfigDocument, key: str) -> Optional[Node]:
    """acq4 reads these keys either under "misc" or at the top level."""
    misc = doc.node("misc")
    node = misc.child(key) if misc is not None else None
    return node if node is not None else doc.node(key)


def set_option(doc: ConfigDocument, key: str, value) -> None:
    node = option_node(doc, key)
    if value is UNSET:
        if node is not None:
            doc.comment_out(node)
    elif node is not None:
        doc.set_value(node, value)
    else:
        misc = doc.node("misc")
        doc.add(misc if misc is not None and misc.is_section else doc.root, key, value)


def shortcut_is_valid(text: str) -> bool:
    sequence = QtGui.QKeySequence.fromString(text, QtGui.QKeySequence.SequenceFormat.PortableText)
    return bool(sequence.toString())


def module_entries(doc: ConfigDocument) -> list:
    section = doc.node("modules")
    return [] if section is None else [n for n in section.children if n.is_section]


def _check_modules(doc: ConfigDocument, path_exists) -> list:
    warnings = []
    shortcuts: dict = {}
    entries = module_entries(doc)
    names = {node.key for node in entries}
    for node in entries:
        label = f"Module '{node.key}'"
        for child in node.children:
            if child.key not in MODULE_KEYS:
                warnings.append(f"{label}: acq4 ignores the key '{child.key}'.")
        module_class = doc.value(node.child("module"))
        if module_class is None:
            warnings.append(f"{label} has no 'module' class and will fail to load.")
        elif module_class not in KNOWN_MODULES and "." not in str(module_class):
            warnings.append(f"{label}: acq4 has no module class named '{module_class}'.")
        shortcut = doc.value(node.child("shortcut"))
        if shortcut is not None:
            if not shortcut_is_valid(str(shortcut)):
                warnings.append(f"{label}: '{shortcut}' is not a valid shortcut.")
            shortcuts.setdefault(str(shortcut), []).append(node.key)
        config = node.child("config")
        if config is None:
            continue
        task_dir = doc.value(config.child("taskDir"))
        if isinstance(task_dir, str) and not path_exists(task_dir):
            warnings.append(f"{label}: taskDir {task_dir} was not found on this computer.")
        if module_class == "Imager":
            camera = doc.value(config.child("cameraModule"))
            if camera is not None and camera not in names:
                warnings.append(f"{label}: cameraModule '{camera}' is not a defined module.")
    for shortcut, users in shortcuts.items():
        if len(users) > 1:
            warnings.append(f"Shortcut {shortcut} is used by: {', '.join(users)}.")
    return warnings


def _check_includes(doc: ConfigDocument, config_dir: Optional[Path], path_exists) -> list:
    warnings = []
    if config_dir is None:
        return warnings
    for key in ("devices", "folderTypes"):
        value = doc.value(option_node(doc, key))
        if isinstance(value, IncludedFile) and not path_exists(str(config_dir / value.name)):
            warnings.append(f"{value.name} ('{key}') is not in {config_dir}.")
    stylesheet = doc.value(option_node(doc, "stylesheet"))
    if isinstance(stylesheet, str) and not path_exists(str(config_dir / stylesheet)):
        warnings.append(f"Stylesheet {stylesheet} is not in {config_dir}.")
    return warnings


def _check_compression(doc: ConfigDocument) -> list:
    node = option_node(doc, "defaultCompression")
    if node is None:
        return []
    value = doc.value(node)
    name = value[0] if isinstance(value, tuple) else value
    valid = name in COMPRESSION_FILTERS and (
        not isinstance(value, tuple) or isinstance(value[1], int)
    )
    return [] if valid else [f"defaultCompression {value!r} will be rejected by acq4."]


def check_default_config(doc: ConfigDocument, config_dir: Optional[Path], path_exists) -> list:
    """Problems acq4 would have with this file."""
    warnings = []
    for node in doc.root.children:
        if node.key not in LOADED_KEYS | TOP_LEVEL_ONLY_KEYS:
            warnings.append(f"acq4 does not use the top-level key '{node.key}'.")
    misc = doc.node("misc")
    if misc is not None:
        for node in misc.children:
            if node.key not in LOADED_KEYS:
                warnings.append(f"acq4 does not use the key '{node.key}' under misc.")
    warnings += _check_modules(doc, path_exists)
    warnings += _check_includes(doc, config_dir, path_exists)
    warnings += _check_compression(doc)

    storage = doc.value(option_node(doc, "storageDir"))
    if isinstance(storage, str) and not path_exists(storage):
        warnings.append(f"Storage directory {storage} was not found on this computer.")
    configurations = doc.node("configurations")
    if configurations is not None:
        for node in configurations.children:
            directory = doc.value(node.child("storageDir"))
            if isinstance(directory, str) and not directory:
                warnings.append(f"Configuration '{node.key}' has an empty storage directory.")
            elif isinstance(directory, str) and not path_exists(directory):
                warnings.append(
                    f"Configuration '{node.key}': {directory} was not found on this computer."
                )
    return warnings


def _read_only_item(text: str) -> QtWidgets.QTableWidgetItem:
    item = QtWidgets.QTableWidgetItem(text)
    item.setFlags(item.flags() & ~ItemFlag.ItemIsEditable)
    return item


def _button_column(*buttons) -> QtWidgets.QVBoxLayout:
    column = QtWidgets.QVBoxLayout()
    for button in buttons:
        column.addWidget(button)
    column.addStretch(1)
    return column


class DefaultConfigWindow(ConfigEditorWindow):
    tool_title = "Default Config"
    file_label = "default.cfg file:"
    history_key = "default_cfg.files"
    template_name = "default_template.cfg"
    suggested_name = "default.cfg"

    def build_tabs(self) -> None:
        self.module_nodes: list = []
        self.setting_nodes: list = []
        self.configuration_nodes: list = []
        self.tabs.addTab(self._build_modules_tab(), "Modules")
        self.tabs.addTab(self._build_directories_tab(), "Directories")
        self.tabs.addTab(self._build_options_tab(), "Options")

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _build_modules_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)

        row = QtWidgets.QHBoxLayout()
        self.modules_table = QtWidgets.QTableWidget(0, 3)
        self.modules_table.setHorizontalHeaderLabels(["Name", "Module", "Shortcut"])
        self.modules_table.horizontalHeader().setStretchLastSection(True)
        self.modules_table.setColumnWidth(0, 200)
        self.modules_table.setColumnWidth(1, 220)
        self.modules_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.modules_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.modules_table.itemChanged.connect(self._on_module_item_changed)
        self.modules_table.itemSelectionChanged.connect(self._fill_settings)
        row.addWidget(self.modules_table, stretch=1)
        add, remove, up, down = (QtWidgets.QPushButton(t) for t in ("Add", "Remove", "Up", "Down"))
        add.clicked.connect(self.add_module)
        remove.clicked.connect(self.remove_module)
        up.clicked.connect(lambda: self.move_module(-1))
        down.clicked.connect(lambda: self.move_module(1))
        row.addLayout(_button_column(add, remove, up, down))
        layout.addLayout(row, stretch=3)

        self.settings_group = QtWidgets.QGroupBox("Module settings")
        row = QtWidgets.QHBoxLayout(self.settings_group)
        self.settings_table = QtWidgets.QTableWidget(0, 2)
        self.settings_table.setHorizontalHeaderLabels(["Setting", "Value"])
        self.settings_table.horizontalHeader().setStretchLastSection(True)
        self.settings_table.setColumnWidth(0, 200)
        self.settings_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.settings_table.itemChanged.connect(self._on_setting_item_changed)
        row.addWidget(self.settings_table, stretch=1)
        add = QtWidgets.QPushButton("Add Setting")
        add.clicked.connect(self.add_setting)
        remove = QtWidgets.QPushButton("Remove Setting")
        remove.clicked.connect(self.remove_setting)
        browse = QtWidgets.QPushButton("Choose Directory…")
        browse.clicked.connect(self.choose_setting_directory)
        row.addLayout(_button_column(add, remove, browse))
        layout.addWidget(self.settings_group, stretch=2)
        return tab

    def _path_row(self, form, label: str, tooltip: str, on_finished,
                  browse: Optional[str] = None) -> QtWidgets.QLineEdit:
        edit = QtWidgets.QLineEdit()
        edit.setToolTip(tooltip)
        edit.editingFinished.connect(on_finished)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(edit, stretch=1)
        if browse == "dir":
            button = QtWidgets.QPushButton("Browse…")
            button.clicked.connect(lambda: self._browse_into(edit))
            row.addWidget(button)
        form.addRow(label, row)
        return edit

    def _browse_into(self, edit: QtWidgets.QLineEdit) -> None:
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, "Select directory", edit.text())
        if chosen:
            edit.setText(chosen)
            edit.editingFinished.emit()

    def _build_directories_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        form = QtWidgets.QFormLayout()
        self.storage_edit = self._path_row(
            form, "Storage directory:", "Base directory where acq4 keeps acquired data.",
            self._on_storage_finished, browse="dir",
        )
        self.task_dir_edit = self._path_row(
            form, "Task directory:", "Where the Task Runner keeps saved tasks. When empty, "
            "acq4 uses the protocols directory beside this file.",
            self._on_task_dir_finished, browse="dir",
        )
        self.devices_edit = self._path_row(
            form, "Devices file:", "Named relative to this file.",
            lambda: self._on_include_finished("devices", self.devices_edit),
        )
        self.folder_types_edit = self._path_row(
            form, "Folder types file:", "Named relative to this file.",
            lambda: self._on_include_finished("folderTypes", self.folder_types_edit),
        )
        self.stylesheet_edit = self._path_row(
            form, "Stylesheet:", "Named relative to this file.", self._on_stylesheet_finished,
        )
        layout.addLayout(form)

        group = QtWidgets.QGroupBox("Configurations (named sets, such as one for each user)")
        row = QtWidgets.QHBoxLayout(group)
        self.configurations_table = QtWidgets.QTableWidget(0, 2)
        self.configurations_table.setHorizontalHeaderLabels(["Name", "Storage directory"])
        self.configurations_table.horizontalHeader().setStretchLastSection(True)
        self.configurations_table.setColumnWidth(0, 200)
        self.configurations_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.configurations_table.itemChanged.connect(self._on_configuration_item_changed)
        row.addWidget(self.configurations_table, stretch=1)
        add = QtWidgets.QPushButton("Add")
        add.clicked.connect(self.add_configuration)
        remove = QtWidgets.QPushButton("Remove")
        remove.clicked.connect(self.remove_configuration)
        browse = QtWidgets.QPushButton("Choose Directory…")
        browse.clicked.connect(self.choose_configuration_directory)
        row.addLayout(_button_column(add, remove, browse))
        layout.addWidget(group, stretch=1)
        return tab

    def _build_options_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        self.option_combos: dict = {}
        for key, label, tooltip, _choices in OPTIONS:
            combo = QtWidgets.QComboBox()
            combo.setToolTip(tooltip)
            combo.activated.connect(self._make_option_handler(key))
            form.addRow(f"{label}:", combo)
            self.option_combos[key] = combo
        return tab

    def _make_option_handler(self, key: str):
        return lambda _index: self._on_option_chosen(key)

    # ------------------------------------------------------------------
    # filling the fields
    # ------------------------------------------------------------------
    def load_form(self) -> None:
        self._fill_modules()
        self._fill_directories()
        self._fill_configurations()
        self._fill_options()

    def _fill_modules(self, select: Optional[Node] = None) -> None:
        table = self.modules_table
        self.module_nodes = module_entries(self.doc)
        with QtCore.QSignalBlocker(table):
            table.setRowCount(len(self.module_nodes))
            for row, node in enumerate(self.module_nodes):
                table.setItem(row, 0, QtWidgets.QTableWidgetItem(node.key))
                table.setCellWidget(row, 1, self._module_combo(node))
                shortcut = self.doc.value(node.child("shortcut"))
                table.setItem(row, 2, QtWidgets.QTableWidgetItem(
                    "" if shortcut is None else str(shortcut)
                ))
        if self.module_nodes:
            node = select if select in self.module_nodes else self.module_nodes[0]
            table.selectRow(self.module_nodes.index(node))
        self._fill_settings()

    def _module_combo(self, node: Node) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        combo.addItems(KNOWN_MODULES)
        combo.setEditText(str(self.doc.value(node.child("module"), "")))
        combo.lineEdit().editingFinished.connect(lambda: self._on_module_class(node, combo))
        combo.activated.connect(lambda _index: self._on_module_class(node, combo))
        return combo

    def selected_module(self) -> Optional[Node]:
        rows = self.modules_table.selectionModel().selectedRows()
        return self.module_nodes[rows[0].row()] if rows else None

    def _fill_settings(self) -> None:
        table = self.settings_table
        node = self.selected_module()
        self.settings_group.setTitle(
            "Module settings" if node is None else f"Settings for {node.key}"
        )
        self.settings_group.setEnabled(node is not None)
        config = None if node is None else node.child("config")
        self.setting_nodes = [] if config is None else list(config.children)
        with QtCore.QSignalBlocker(table):
            table.setRowCount(len(self.setting_nodes))
            for row, setting in enumerate(self.setting_nodes):
                table.setItem(row, 0, QtWidgets.QTableWidgetItem(setting.key))
                if setting.is_section:
                    table.setItem(row, 1, _read_only_item("(nested settings, see File Text)"))
                else:
                    table.setItem(row, 1, QtWidgets.QTableWidgetItem(setting.raw))

    def _include_text(self, edit: QtWidgets.QLineEdit, key: str) -> None:
        node = option_node(self.doc, key)
        value = self.doc.value(node)
        inline = node is not None and not isinstance(value, IncludedFile)
        edit.setEnabled(not inline)
        if inline:
            edit.setText("(defined inside this file)")
        else:
            edit.setText("" if value is None else value.name)

    def _fill_directories(self) -> None:
        storage = self.doc.value(option_node(self.doc, "storageDir"), "")
        self.storage_edit.setText(str(storage))
        runner = self._task_runner()
        self.task_dir_edit.setEnabled(runner is not None)
        config = None if runner is None else runner.child("config")
        task_dir = None if config is None else self.doc.value(config.child("taskDir"))
        self.task_dir_edit.setText("" if task_dir is None else str(task_dir))
        self._include_text(self.devices_edit, "devices")
        self._include_text(self.folder_types_edit, "folderTypes")
        self.stylesheet_edit.setText(str(self.doc.value(option_node(self.doc, "stylesheet"), "")))

    def _fill_configurations(self) -> None:
        table = self.configurations_table
        section = self.doc.node("configurations")
        self.configuration_nodes = [] if section is None else list(section.children)
        with QtCore.QSignalBlocker(table):
            table.setRowCount(len(self.configuration_nodes))
            for row, node in enumerate(self.configuration_nodes):
                directory = self.doc.value(node.child("storageDir"), "")
                table.setItem(row, 0, QtWidgets.QTableWidgetItem(node.key))
                table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(directory)))

    def _fill_options(self) -> None:
        for key, _label, _tooltip, choices in OPTIONS:
            combo = self.option_combos[key]
            node = option_node(self.doc, key)
            combo.clear()
            combo.addItem("(not set)", UNSET)
            for text, value in choices:
                combo.addItem(text, value)
            if node is None:
                combo.setCurrentIndex(0)
                continue
            value = self.doc.value(node)
            index = next((i for i in range(1, combo.count()) if combo.itemData(i) == value), -1)
            if index < 0:
                combo.addItem(f"{value!r}", value)
                index = combo.count() - 1
            combo.setCurrentIndex(index)

    def _task_runner(self) -> Optional[Node]:
        return next(
            (n for n in module_entries(self.doc)
             if self.doc.value(n.child("module")) == "TaskRunner"),
            None,
        )

    def run_checks(self) -> list:
        return check_default_config(self.doc, self.config_dir, self.path_exists)

    # ------------------------------------------------------------------
    # modules
    # ------------------------------------------------------------------
    def _on_module_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        node = self.module_nodes[item.row()]
        text = item.text().strip()
        if item.column() == 0:
            self._rename(node, text, item)
        elif item.column() == 2:
            self._set_shortcut(node, text)
        self.edited()

    def _rename(self, node: Node, text: str, item: QtWidgets.QTableWidgetItem) -> None:
        try:
            self.doc.rename(node, text)
        except ConfigError as exc:
            self.statusBar().showMessage(str(exc))
            with QtCore.QSignalBlocker(item.tableWidget()):
                item.setText(node.key)

    def _set_shortcut(self, node: Node, text: str) -> None:
        existing = node.child("shortcut")
        if existing is not None and not text:
            self.doc.comment_out(existing)
        elif existing is not None:
            self.doc.set_value(existing, text)
        elif text:
            self.doc.add(node, "shortcut", text, after=node.child("module"))

    def _on_module_class(self, node: Node, combo: QtWidgets.QComboBox) -> None:
        if node not in self.module_nodes:
            return
        text = combo.currentText().strip()
        existing = node.child("module")
        if existing is not None:
            changed = self.doc.set_value(existing, text)
        else:
            self.doc.add(node, "module", text)
            changed = True
        if changed:
            self.edited()

    def _unique_name(self, parent: Optional[Node], stem: str) -> str:
        number = 1
        while parent is not None and parent.child(f"{stem} {number}") is not None:
            number += 1
        return f"{stem} {number}"

    def add_module(self) -> None:
        section = self.doc.node("modules")
        if section is None:
            section = self.doc.add(self.doc.root, "modules")
        node = self.doc.add(section, self._unique_name(section, "New Module"))
        self.doc.add(node, "module", KNOWN_MODULES[0])
        self._fill_modules(select=node)
        self.edited()

    def remove_module(self) -> None:
        node = self.selected_module()
        if node is not None:
            self.doc.remove(node)
            self._fill_modules()
            self.edited()

    def move_module(self, delta: int) -> None:
        node = self.selected_module()
        if node is not None and self.doc.move(node, delta):
            self._fill_modules(select=node)
            self.edited()

    # ------------------------------------------------------------------
    # module settings
    # ------------------------------------------------------------------
    def _on_setting_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        node = self.setting_nodes[item.row()]
        if item.column() == 0:
            self._rename(node, item.text().strip(), item)
        else:
            self.store_expression(node, item)
        self.edited()

    def store_expression(self, node: Node, item: QtWidgets.QTableWidgetItem) -> None:
        """Keep a Python value as typed; anything else, such as a bare path, is text."""
        if self.doc.set_typed(node, item.text()):
            self.statusBar().showMessage(f"{node.key} stored as text.")
        with QtCore.QSignalBlocker(item.tableWidget()):
            item.setText(node.raw)

    def _setting_names(self, module: Node) -> list:
        known = MODULE_SETTINGS.get(self.doc.value(module.child("module")), ())
        config = module.child("config")
        present = set() if config is None else {c.key for c in config.children}
        return [name for name in known if name not in present]

    def add_setting(self) -> None:
        module = self.selected_module()
        if module is None:
            return
        name, accepted = QtWidgets.QInputDialog.getItem(
            self, "Add setting", "Setting name:", self._setting_names(module), 0, True
        )
        if accepted:
            self.add_setting_named(module, name.strip())

    def add_setting_named(self, module: Node, name: str) -> None:
        config = module.child("config")
        try:
            if config is None:
                config = self.doc.add(module, "config")
            self.doc.add(config, name, None)
        except ConfigError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._fill_settings()
        self.edited()

    def selected_setting(self) -> Optional[Node]:
        rows = self.settings_table.selectionModel().selectedRows()
        return self.setting_nodes[rows[0].row()] if rows else None

    def remove_setting(self) -> None:
        node = self.selected_setting()
        if node is not None:
            self.doc.remove(node)
            self._fill_settings()
            self.edited()

    def choose_setting_directory(self) -> None:
        node = self.selected_setting()
        if node is None or node.is_section:
            return
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, "Select directory")
        if chosen:
            self.doc.set_value(node, chosen)
            self._fill_settings()
            self.edited()

    # ------------------------------------------------------------------
    # directories
    # ------------------------------------------------------------------
    def _on_storage_finished(self) -> None:
        if self.doc is None:
            return
        text = self.storage_edit.text().strip()
        set_option(self.doc, "storageDir", text or UNSET)
        self.edited()

    def _on_task_dir_finished(self) -> None:
        runner = self._task_runner() if self.doc is not None else None
        if runner is None:
            return
        text = self.task_dir_edit.text().strip()
        config = runner.child("config")
        existing = None if config is None else config.child("taskDir")
        if existing is not None and not text:
            self.doc.comment_out(existing)
        elif existing is not None:
            self.doc.set_value(existing, text)
        elif text:
            if config is None:
                config = self.doc.add(runner, "config")
            self.doc.add(config, "taskDir", text)
        self._fill_settings()
        self.edited()

    def _on_include_finished(self, key: str, edit: QtWidgets.QLineEdit) -> None:
        if self.doc is None or not edit.isEnabled():
            return
        text = edit.text().strip()
        set_option(self.doc, key, IncludedFile(text) if text else UNSET)
        self.edited()

    def _on_stylesheet_finished(self) -> None:
        if self.doc is None:
            return
        text = self.stylesheet_edit.text().strip()
        set_option(self.doc, "stylesheet", text or UNSET)
        self.edited()

    # ------------------------------------------------------------------
    # configurations
    # ------------------------------------------------------------------
    def _on_configuration_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        node = self.configuration_nodes[item.row()]
        if item.column() == 0:
            self._rename(node, item.text().strip(), item)
        else:
            self._set_configuration_directory(node, item.text().strip())
        self.edited()

    def _set_configuration_directory(self, node: Node, text: str) -> None:
        existing = node.child("storageDir")
        if existing is not None and not text:
            self.doc.comment_out(existing)
        elif existing is not None:
            self.doc.set_value(existing, text)
        elif text:
            self.doc.add(node, "storageDir", text)

    def add_configuration(self) -> None:
        section = self.doc.node("configurations")
        if section is None:
            section = self.doc.add(self.doc.root, "configurations")
        node = self.doc.add(section, self._unique_name(section, "User").replace(" ", "_"))
        self.doc.add(node, "storageDir", "")
        self._fill_configurations()
        self.edited()

    def selected_configuration(self) -> Optional[Node]:
        rows = self.configurations_table.selectionModel().selectedRows()
        return self.configuration_nodes[rows[0].row()] if rows else None

    def remove_configuration(self) -> None:
        node = self.selected_configuration()
        if node is not None:
            self.doc.remove(node)
            self._fill_configurations()
            self.edited()

    def choose_configuration_directory(self) -> None:
        node = self.selected_configuration()
        if node is None:
            return
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, "Select directory")
        if chosen:
            self._set_configuration_directory(node, chosen)
            self._fill_configurations()
            self.edited()

    # ------------------------------------------------------------------
    # options
    # ------------------------------------------------------------------
    def _on_option_chosen(self, key: str) -> None:
        if self.doc is None:
            return
        set_option(self.doc, key, self.option_combos[key].currentData())
        self.edited()


def create_tool() -> DefaultConfigWindow:
    return DefaultConfigWindow()
