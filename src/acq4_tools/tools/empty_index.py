"""Find acq4 .index files that are empty or nearly empty.

A zero-length .index usually means a data transfer failed part way through.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

from pyqtgraph.Qt import QtCore, QtWidgets

from acq4_tools.common.acq4_index import DAY_DIR_RE
from acq4_tools.common.tool_window import ToolWindow
from acq4_tools.common.widgets import HistoryCombo

DEFAULT_THRESHOLD = 10  # bytes; a usable .index is always larger than this
_RUN_DIR_RE = re.compile(r"\d{3}(_\d{3})*$")


@dataclass(frozen=True)
class IndexFinding:
    path: Path
    size: int
    level: str


def directory_level(name: str) -> str:
    """Name the place of a directory in the acq4 hierarchy, from its name."""
    if DAY_DIR_RE.fullmatch(name):
        return "day"
    if name.startswith("slice_"):
        return "slice"
    if name.startswith(("cell_", "pair_")):
        return "cell"
    if _RUN_DIR_RE.fullmatch(name):
        return "protocol run"
    return "protocol/other"


def find_small_index_files(
    top: Union[str, Path],
    threshold: int = DEFAULT_THRESHOLD,
    check: Optional[Callable[[], None]] = None,
    report: Optional[Callable[[int], None]] = None,
) -> list:
    """Walk ``top`` and return an IndexFinding for each .index smaller than
    ``threshold`` bytes. ``check`` is called per directory and can raise to stop
    the walk; ``report`` receives the number of directories visited so far."""
    findings = []
    visited = 0
    for dirpath, dirnames, filenames in os.walk(top):
        if check is not None:
            check()
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        visited += 1
        if report is not None and visited % 50 == 0:
            report(visited)
        if ".index" not in filenames:
            continue
        path = Path(dirpath, ".index")
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < threshold:
            findings.append(IndexFinding(path, size, directory_level(Path(dirpath).name)))
    return findings


class EmptyIndexWindow(ToolWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Empty Index Files")
        self.resize(900, 600)
        self.findings: list = []
        self.worker = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QFormLayout()
        self.top_dir = HistoryCombo("empty_index.top_dir", title="Directory to scan")
        form.addRow("Directory to scan:", self.top_dir)
        self.threshold = QtWidgets.QSpinBox()
        self.threshold.setRange(1, 1_000_000)
        self.threshold.setValue(DEFAULT_THRESHOLD)
        self.threshold.setSuffix(" bytes")
        form.addRow("Report files smaller than:", self.threshold)
        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        self.scan_button = QtWidgets.QPushButton("Scan")
        self.scan_button.clicked.connect(self.start_scan)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.save_button = QtWidgets.QPushButton("Save list…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_list)
        for button in (self.scan_button, self.cancel_button, self.save_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File", "Size (bytes)", "Level"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table, stretch=1)

        self.statusBar().showMessage("Choose a directory and press Scan.")

    def _set_running(self, running: bool) -> None:
        self.scan_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def start_scan(self) -> None:
        top = self.top_dir.text()
        if not top or not Path(top).is_dir():
            self.statusBar().showMessage(f"Not a directory: {top}")
            return
        self.top_dir.remember()
        threshold = self.threshold.value()
        self.findings = []
        self.table.setRowCount(0)
        self.save_button.setEnabled(False)
        self._set_running(True)
        self.statusBar().showMessage("Scanning…")

        def scan(worker):
            return find_small_index_files(
                top, threshold, check=worker.check_cancelled, report=worker.progress.emit
            )

        self.worker = self.start_worker(
            scan,
            progress=self._on_progress,
            succeeded=self._on_results,
            failed=self._on_failed,
            finished=self._on_finished,
        )

    def cancel_scan(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.statusBar().showMessage("Cancelled.")

    def _on_progress(self, visited: int) -> None:
        self.statusBar().showMessage(f"Scanning… {visited} directories")

    def _on_results(self, findings: list) -> None:
        self.findings = findings
        self.table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            for col, value in enumerate((str(finding.path), str(finding.size), finding.level)):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        self.save_button.setEnabled(bool(findings))
        self.statusBar().showMessage(f"Scan complete: {len(findings)} small .index file(s) found.")

    def _on_failed(self, detail: str) -> None:
        self.statusBar().showMessage("Scan failed.")
        QtWidgets.QMessageBox.warning(self, "Empty Index Files", detail)

    def _on_finished(self) -> None:
        self._set_running(False)

    def save_list(self) -> None:
        start = str(Path(self.top_dir.text(), "empty_index_files.txt"))
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save list", start, "Text (*.txt)")
        if not name:
            return
        lines = [f"{f.path}\t{f.size}\t{f.level}\n" for f in self.findings]
        Path(name).write_text("".join(lines), encoding="utf-8")
        self.statusBar().showMessage(f"Saved {name}")


def create_tool() -> ToolWindow:
    return EmptyIndexWindow()
