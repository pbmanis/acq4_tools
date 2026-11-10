"""Widgets shared by the tools."""

from pathlib import Path
from typing import Callable, Optional

from pyqtgraph.Qt import QtCore, QtWidgets

from acq4_tools.common.history import DEFAULT_MAX_ENTRIES, history_store


class HistoryCombo(QtWidgets.QWidget):
    """An editable drop-down backed by the persistent history.

    ``mode`` is "dir" or "file" to add a Browse button, or "text" for plain
    values such as host names. Entries are only added by ``remember()``, so a
    tool can record a value once it has been used successfully. ``start_dir``
    can name the folder that Browse should open, or return None to use the history.
    """

    activated = QtCore.Signal(str)

    def __init__(self, key: str, mode: str = "dir", title: str = "", parent=None,
                 max_entries: int = DEFAULT_MAX_ENTRIES,
                 start_dir: Optional[Callable[[], Optional[str]]] = None):
        super().__init__(parent)
        self.key = key
        self.mode = mode
        self.title = title
        self.max_entries = max_entries
        self.start_dir = start_dir

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QtWidgets.QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self.combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.combo.setMinimumContentsLength(30)
        self.combo.activated.connect(self._on_activated)
        layout.addWidget(self.combo, stretch=1)
        if mode in ("dir", "file"):
            browse = QtWidgets.QPushButton("Browse…")
            browse.clicked.connect(self.browse)
            layout.addWidget(browse)
        self.refresh()

    def refresh(self) -> None:
        """Reload the drop-down from the history, keeping the current text."""
        text = self.combo.currentText()
        entries = history_store().get(self.key)
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(entries)
        self.combo.setEditText(text or (entries[0] if entries else ""))
        self.combo.blockSignals(False)

    def text(self) -> str:
        return self.combo.currentText().strip()

    def setText(self, value: str) -> None:  # noqa: N802 - matches Qt naming
        self.combo.setEditText(value)

    def remember(self) -> None:
        """Add the current value to the top of the history."""
        value = self.text()
        if value:
            history_store().add(self.key, value, self.max_entries)
            self.refresh()

    def starting_dir(self) -> str:
        """The folder to browse from: ``start_dir`` if it names one, otherwise
        the closest existing directory to the current value."""
        chosen = self.start_dir() if self.start_dir is not None else None
        return chosen or existing_dir_from([self.text(), *history_store().get(self.key)])

    def browse(self) -> None:
        if self.mode == "dir":
            chosen = QtWidgets.QFileDialog.getExistingDirectory(
                self, self.title or "Select directory", self.starting_dir()
            )
        else:
            chosen, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, self.title or "Select file", self.starting_dir()
            )
        if chosen:
            self.setText(chosen)
            self.activated.emit(chosen)

    def _on_activated(self, _index: int) -> None:
        self.activated.emit(self.text())


def existing_dir_from(candidates: list) -> str:
    """First candidate that exists (or the parent of one that is a file), else
    the user's home directory. History can name a volume that is unmounted."""
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        try:
            if path.is_dir():
                return str(path)
            if path.parent.is_dir():
                return str(path.parent)
        except OSError:
            continue
    return str(Path.home())


def pick_directory(parent, title: str, start: str) -> Optional[str]:
    """Show a directory chooser. Returns None if it is cancelled."""
    chosen = QtWidgets.QFileDialog.getExistingDirectory(parent, title, start)
    return chosen or None
