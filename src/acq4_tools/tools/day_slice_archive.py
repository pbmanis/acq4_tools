"""Make a tar file of the day and slice levels of acq4 data.

The archive holds each day's .index and, for each slice, its directory, the
files directly in it, and its label directories (FITC, TRITC, ...). Cell
directories are left out: tar files of the cells can be unpacked into the
directory structure made by unpacking this archive.
"""

import os
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

from pyqtgraph.Qt import QtGui, QtWidgets

from acq4_tools.common.acq4_index import DAY_DIR_RE, is_label_dir
from acq4_tools.common.history import history_store
from acq4_tools.common.tool_window import ToolWindow
from acq4_tools.common.widgets import HistoryCombo

_JUNK_NAMES = {".DS_Store", "Thumbs.db"}


@dataclass
class ArchivePlan:
    top: Path
    members: list = field(default_factory=list)  # directories come before their files
    missing_index: list = field(default_factory=list)  # day and slice directories

    def arcname(self, path: Path) -> str:
        """Names in the archive start at the directory that was chosen."""
        return path.relative_to(self.top.parent).as_posix()


def find_day_dirs(top: Path, check: Optional[Callable[[], None]] = None) -> list:
    """``top`` if it is a day directory, else every day directory below it."""
    if DAY_DIR_RE.fullmatch(top.name):
        return [top]
    days = []
    for dirpath, dirnames, _filenames in os.walk(top):
        if check is not None:
            check()
        days.extend(Path(dirpath, d) for d in dirnames if DAY_DIR_RE.fullmatch(d))
        dirnames[:] = sorted(
            d for d in dirnames if not DAY_DIR_RE.fullmatch(d) and not d.startswith(".")
        )
    return sorted(days)


def _files_in(directory: Path) -> list:
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.name not in _JUNK_NAMES and not p.name.startswith("._")
    )


def _add_label_dir(plan: ArchivePlan, label: Path) -> None:
    plan.members.append(label)
    plan.members.extend(_files_in(label))
    for child in sorted(label.iterdir()):
        if child.is_dir() and is_label_dir(child.name):
            _add_label_dir(plan, child)


def plan_archive(top: Union[str, Path], check: Optional[Callable[[], None]] = None) -> ArchivePlan:
    """Work out what goes in the archive, without writing anything."""
    plan = ArchivePlan(Path(top))
    for day in find_day_dirs(plan.top, check):
        if check is not None:
            check()
        plan.members.append(day)
        if (day / ".index").is_file():
            plan.members.append(day / ".index")
        else:
            plan.missing_index.append(day)
        for slice_dir in sorted(
            p for p in day.iterdir() if p.is_dir() and p.name.startswith("slice")
        ):
            plan.members.append(slice_dir)
            plan.members.extend(_files_in(slice_dir))
            if not (slice_dir / ".index").is_file():
                plan.missing_index.append(slice_dir)
            for child in sorted(slice_dir.iterdir()):
                if child.is_dir() and is_label_dir(child.name):
                    _add_label_dir(plan, child)
    return plan


def write_archive(
    plan: ArchivePlan,
    output: Union[str, Path],
    check: Optional[Callable[[], None]] = None,
    report: Optional[Callable[[tuple], None]] = None,
) -> list:
    """Write the archive and return its (name, size) contents, read back from
    the finished file. The output only appears once it is complete."""
    output = Path(output)
    partial = output.with_name(output.name + ".partial")
    members = [m for m in plan.members if m != output]
    try:
        with tarfile.open(partial, "w") as tar:
            for done, path in enumerate(members):
                if check is not None:
                    check()
                tar.add(path, arcname=plan.arcname(path), recursive=False)
                if report is not None:
                    report((done + 1, len(members)))
        with tarfile.open(partial, "r") as tar:
            contents = [(m.name, m.size) for m in tar.getmembers()]
        os.replace(partial, output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return contents


class DaySliceArchiveWindow(ToolWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Day/Slice Archive")
        self.resize(900, 600)
        self.worker = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QFormLayout()
        self.top_dir = HistoryCombo("day_slice_archive.top_dir", title="Directory to archive")
        form.addRow("Directory to archive:", self.top_dir)
        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        self.make_button = QtWidgets.QPushButton("Make tar file…")
        self.make_button.clicked.connect(self.start_archive)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_archive)
        buttons.addWidget(self.make_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(
            QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        )
        layout.addWidget(self.output, stretch=1)
        self.statusBar().showMessage("Choose a directory and press Make tar file.")

    def _set_running(self, running: bool) -> None:
        self.make_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def _choose_output(self, top: str) -> str:
        previous = history_store().get("day_slice_archive.output")
        start = Path(previous[0]).parent if previous else Path(top)
        name, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save tar file", str(start / "DaySlice.tar"), "Tar files (*.tar)"
        )
        return name

    def start_archive(self) -> None:
        top = self.top_dir.text()
        if not top or not Path(top).is_dir():
            self.statusBar().showMessage(f"Not a directory: {top}")
            return
        output = self._choose_output(top)
        if not output:
            return
        self.top_dir.remember()
        history_store().add("day_slice_archive.output", output)
        self.output.clear()
        self._set_running(True)
        self.statusBar().showMessage("Finding day and slice directories…")

        def run(worker):
            plan = plan_archive(top, check=worker.check_cancelled)
            contents = write_archive(
                plan, output, check=worker.check_cancelled, report=worker.progress.emit
            )
            return plan, contents, output

        self.worker = self.start_worker(
            run,
            progress=self._on_progress,
            succeeded=self._on_done,
            failed=self._on_failed,
            finished=self._on_finished,
        )

    def cancel_archive(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.statusBar().showMessage("Cancelled. No tar file was written.")

    def _on_progress(self, update: tuple) -> None:
        done, total = update
        self.statusBar().showMessage(f"Writing… {done} of {total}")

    def _on_done(self, result: tuple) -> None:
        plan, contents, output = result
        lines = [f"WARNING: no .index file in {path}" for path in plan.missing_index]
        lines.extend(f"{size:>12d}  {name}" for name, size in contents)
        self.output.setPlainText("\n".join(lines))
        warning = f", {len(plan.missing_index)} without .index" if plan.missing_index else ""
        self.statusBar().showMessage(f"Wrote {output}: {len(contents)} items{warning}.")

    def _on_failed(self, detail: str) -> None:
        self.statusBar().showMessage("Archive failed. No tar file was written.")
        QtWidgets.QMessageBox.warning(self, "Day/Slice Archive", detail)

    def _on_finished(self) -> None:
        self._set_running(False)


def create_tool() -> ToolWindow:
    return DaySliceArchiveWindow()
