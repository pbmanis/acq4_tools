"""The window shared by the tools that edit an acq4 config file."""

from pathlib import Path
from typing import Optional

from pyqtgraph.Qt import QtWidgets

from acq4_tools.common.config_document import (
    ConfigDocument,
    ConfigError,
    read_config_text,
    write_config_text,
)
from acq4_tools.common.history import history_store
from acq4_tools.common.paths import acq4_config_dir, packaged_data
from acq4_tools.common.tool_window import ToolWindow
from acq4_tools.common.widgets import HistoryCombo, existing_dir_from

_ACQ4_DIR_KEY = "acq4.top_dirs"
CONFIG_HISTORY_KEYS = ("default_cfg.files", "folder_types.files", "rig_config.files")
_FILE_FILTER = "Config files (*.cfg);;All files (*)"
StandardButton = QtWidgets.QMessageBox.StandardButton


class ConfigEditorWindow(ToolWindow):
    """Open, check and save a config file. Subclasses provide the fields; each
    edit changes ``self.doc`` at once and is followed by a call to ``edited()``."""

    tool_title = ""
    file_label = "Config file:"
    history_key = ""
    template_name = ""
    suggested_name = ""

    def __init__(self):
        super().__init__()
        self.doc: Optional[ConfigDocument] = None
        self.path: Optional[Path] = None
        self.saved_text = ""
        self.loading = False
        self._exists: dict = {}  # a slow volume should not delay every keystroke
        self.resize(980, 760)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        file_grid = QtWidgets.QGridLayout()
        file_grid.setColumnStretch(1, 1)
        file_grid.addWidget(QtWidgets.QLabel("acq4 directory:"), 0, 0)
        self.acq4_dir = HistoryCombo(_ACQ4_DIR_KEY, "dir", "Select the top acq4 directory")
        self.acq4_dir.setToolTip("The top directory of acq4. Browse opens its config folder.")
        self.acq4_dir.activated.connect(self._on_acq4_dir_chosen)
        file_grid.addWidget(self.acq4_dir, 0, 1)
        file_grid.addWidget(QtWidgets.QLabel(self.file_label), 1, 0)
        self.file_combo = HistoryCombo(self.history_key, "file", "Select config file",
                                       start_dir=self._browse_folder)
        self.file_combo.activated.connect(lambda _text: self.open_file())
        file_grid.addWidget(self.file_combo, 1, 1)
        self.open_button = QtWidgets.QPushButton("Open")
        self.open_button.clicked.connect(lambda: self.open_file())
        self.template_button = QtWidgets.QPushButton("New from Template")
        self.template_button.clicked.connect(lambda: self.new_from_template())
        file_grid.addWidget(self.open_button, 1, 2)
        file_grid.addWidget(self.template_button, 1, 3)
        layout.addLayout(file_grid)

        self.tabs = QtWidgets.QTabWidget()
        self.build_tabs()
        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.tabs.addTab(self.preview, "File Text")
        layout.addWidget(self.tabs, stretch=1)

        layout.addWidget(QtWidgets.QLabel("Checks:"))
        self.checks = QtWidgets.QListWidget()
        self.checks.setMaximumHeight(110)
        layout.addWidget(self.checks)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.revert_button = QtWidgets.QPushButton("Revert")
        self.revert_button.clicked.connect(self.revert)
        self.save_as_button = QtWidgets.QPushButton("Save As…")
        self.save_as_button.clicked.connect(lambda: self.save_as())
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(lambda: self.save())
        for button in (self.revert_button, self.save_as_button, self.save_button):
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self._update_state()
        self.statusBar().showMessage("Open a file, or start a new one from the template.")

    # ------------------------------------------------------------------
    # supplied by the tools
    # ------------------------------------------------------------------
    def build_tabs(self) -> None:
        raise NotImplementedError

    def load_form(self) -> None:
        """Show the contents of ``self.doc`` in the fields."""
        raise NotImplementedError

    def run_checks(self) -> list:
        """Warnings about the contents of ``self.doc``."""
        return []

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    @property
    def is_dirty(self) -> bool:
        return self.doc is not None and self.doc.text() != self.saved_text

    @property
    def config_dir(self) -> Optional[Path]:
        """Where acq4 would look for files named relative to this one."""
        return None if self.path is None else self.path.parent

    def path_exists(self, path: str) -> bool:
        if path not in self._exists:
            try:
                self._exists[path] = Path(path).exists()
            except OSError:
                self._exists[path] = False
        return self._exists[path]

    def edited(self) -> None:
        if not self.loading:
            self._update_state()

    def _update_state(self) -> None:
        has_document = self.doc is not None
        for widget in (self.tabs, self.save_button, self.save_as_button):
            widget.setEnabled(has_document)
        self.revert_button.setEnabled(self.is_dirty)
        name = "" if not has_document else (self.path.name if self.path else "Untitled")
        marker = " *" if self.is_dirty else ""
        self.setWindowTitle(f"{self.tool_title} - {name}{marker}" if name else self.tool_title)
        if has_document:
            self.preview.setPlainText(self.doc.text())
            warnings = self.run_checks()
            self.checks.clear()
            self.checks.addItems(warnings or ["No problems found."])

    def _show_document(self, doc: ConfigDocument, path: Optional[Path], saved_text: str) -> None:
        self.doc = doc
        self.path = path
        self.saved_text = saved_text
        self._exists = {}
        self.loading = True
        try:
            self.load_form()
        finally:
            self.loading = False
        self._update_state()

    def _show_error(self, text: str, detail: str) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle(self.tool_title)
        box.setText(text)
        box.setInformativeText(detail)
        box.exec()

    # ------------------------------------------------------------------
    # opening
    # ------------------------------------------------------------------
    def _acq4_config_folder(self) -> Optional[str]:
        if not self.acq4_dir.text():
            self.acq4_dir.refresh()  # it may have been chosen since this window opened
        folder = acq4_config_dir(self.acq4_dir.text())
        return None if folder is None else str(folder)

    def _browse_folder(self) -> str:
        """Every config tool looks in the same places: the acq4 config folder,
        then the folder of the file most recently used by this tool or another."""
        folder = self._acq4_config_folder()
        if folder is not None:
            return folder
        recent = [self.file_combo.text()]
        for key in (self.history_key, *CONFIG_HISTORY_KEYS):
            recent += history_store().get(key)
        return existing_dir_from(recent)

    def _on_acq4_dir_chosen(self, top: str) -> None:
        folder = self._acq4_config_folder()
        if folder is None:
            self.statusBar().showMessage(f"No config folder found in {top}.")
            return
        self.acq4_dir.remember()
        self.statusBar().showMessage(f"Browse will open {folder}")
        self.acq4_dir_changed()

    def acq4_dir_changed(self) -> None:
        """Called when a valid acq4 directory has been chosen."""

    def open_file(self, path: Optional[str] = None) -> bool:
        path = path or self.file_combo.text()
        if not path:
            self.statusBar().showMessage("Choose a file to open.")
            return False
        if not self.confirm_discard():
            return False
        try:
            text = read_config_text(path)
            doc = ConfigDocument(text)
        except (OSError, UnicodeDecodeError, ConfigError) as exc:
            self._show_error(f"Could not open {path}.", str(exc))
            return False
        self.file_combo.setText(path)
        self.file_combo.remember()
        if self._acq4_config_folder() is not None:
            self.acq4_dir.remember()  # it may have been typed in rather than chosen
        self._show_document(doc, Path(path), text)
        self.statusBar().showMessage(f"Opened {path}")
        return True

    def new_from_template(self) -> bool:
        if not self.confirm_discard():
            return False
        text = read_config_text(packaged_data(self.template_name))
        self._show_document(ConfigDocument(text), None, text)
        self.statusBar().showMessage("New file from the template. Nothing is written until Save.")
        return True

    def revert(self) -> None:
        self._show_document(ConfigDocument(self.saved_text), self.path, self.saved_text)
        self.statusBar().showMessage("Changes discarded.")

    # ------------------------------------------------------------------
    # saving
    # ------------------------------------------------------------------
    @staticmethod
    def _commit_pending_edit() -> None:
        """A field or table cell still being typed in applies its text on losing focus."""
        focused = QtWidgets.QApplication.focusWidget()
        if focused is not None:
            focused.clearFocus()

    def save(self) -> bool:
        self._commit_pending_edit()
        return self.save_as() if self.path is None else self._write(self.path)

    def save_as(self) -> bool:
        self._commit_pending_edit()
        start = self.path or Path(self.file_combo.starting_dir()) / self.suggested_name
        chosen, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save config file", str(start), _FILE_FILTER
        )
        return self._write(Path(chosen)) if chosen else False

    def _changed_on_disk(self, path: Path) -> bool:
        return path == self.path and path.exists() and read_config_text(path) != self.saved_text

    def _confirm_overwrite_changed_file(self, path: Path) -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle(self.tool_title)
        box.setText(f"{path.name} has changed on disk since it was opened.")
        box.setInformativeText("Replace it with this version?")
        box.setStandardButtons(StandardButton.Save | StandardButton.Cancel)
        box.setDefaultButton(StandardButton.Cancel)
        return box.exec() == StandardButton.Save

    def _write(self, path: Path) -> bool:
        try:
            self.doc.check()
            if self._changed_on_disk(path) and not self._confirm_overwrite_changed_file(path):
                return False
            backup = write_config_text(path, self.doc.text())
        except (OSError, UnicodeDecodeError, ConfigError) as exc:
            self._show_error(f"Could not save {path}.", str(exc))
            return False
        self.path = path
        self.saved_text = self.doc.text()
        self._exists = {}
        self.file_combo.setText(str(path))
        self.file_combo.remember()
        self._update_state()
        kept = f"; the previous version is {backup.name}" if backup else ""
        self.statusBar().showMessage(f"Saved {path}{kept}")
        return True

    def confirm_discard(self) -> bool:
        """Offer to save unsaved changes. False means stay where we are."""
        self._commit_pending_edit()
        if not self.is_dirty:
            return True
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setWindowTitle(self.tool_title)
        box.setText("Save your changes to this file?")
        box.setStandardButtons(
            StandardButton.Save | StandardButton.Discard | StandardButton.Cancel
        )
        box.setDefaultButton(StandardButton.Save)
        answer = box.exec()
        if answer == StandardButton.Save:
            return self.save()
        return answer == StandardButton.Discard

    def closeEvent(self, event):  # noqa: N802 - Qt override name
        if not self.confirm_discard():
            event.ignore()
            return
        super().closeEvent(event)
