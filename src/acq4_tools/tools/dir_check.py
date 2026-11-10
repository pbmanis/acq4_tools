"""Check an acq4 directory structure to be sure that the hierarchy is correct.

Produces a report of the data that are actually under a directory, which can be
saved as text or LaTeX (and turned into a PDF when pdflatex is available).

day
    slice
        cell
            protocols
        pair
            cells
                protocols

The slice may have images and videos, but no protocols. Its images and videos
may be grouped in label directories (FITC, TRITC, ...).
The cells and pairs may have both.
Pairs should have cells and protocols under cells.

Any other organization is flagged.
"""

import datetime
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import dateutil.parser as DUP
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from acq4_tools.common.acq4_index import DAY_DIR_RE, index_text, is_label_dir, read_dir_index
from acq4_tools.common.history import history_store
from acq4_tools.common.tool_window import ToolWindow
from acq4_tools.common.widgets import HistoryCombo, existing_dir_from

_IGNORED_NAMES = {".index", ".DS_Store", "log.txt"}
_IGNORED_EXTENSIONS = (
    ".p", ".pkl", ".sql", ".txt", ".doc", ".docx", ".xlsx", ".py", ".tex", ".cfg", ".ini",
    ".tif", ".tiff", ".jpg", ".jpeg", ".gif", ".png", ".pdf", ".ma", ".mosaic", ".db",
)
_TIMESTAMP_RE = re.compile(r"\s*(__timestamp__: )([\d.\d]*)")
_FMT = "{0:>15s} {1:<10s} {2:<10s} {3:<40} {4:>20}"
_FMT2 = "{0:>15s} {1:<10s} {2:<40s} {3:<10} {4:>20}"

# pdflatex is often not on the PATH given to a packaged application.
_PDFLATEX_LOCATIONS = ("/Library/TeX/texbin/pdflatex", "/usr/texbin/pdflatex",
                       "/opt/homebrew/bin/pdflatex", "/usr/local/bin/pdflatex")

_GUI_COLORS = {"red": "#d1242f", "blue": "#1f6feb", "teal": "#0a7f7f",
               "violet": "#8250df", "cyan": "#0a7f7f"}


@dataclass(frozen=True)
class ReportLine:
    text: str = ""
    color: Optional[str] = None
    page_break: bool = False


class DirCheck:
    """Walk a directory and describe it through ``sink``, one ReportLine at a time."""

    def __init__(self, topdir: Path, sink: Callable[[ReportLine], None],
                 show_protocol: bool = False,
                 after: str = "1970.1.1", before: str = "2266.1.1",
                 check: Optional[Callable[[], None]] = None):
        self.topdir = Path(topdir)
        if not self.topdir.is_dir():
            raise ValueError(f"Top directory not found: {self.topdir}")
        self.sink = sink
        self.show_protocol = show_protocol
        self.after = DUP.parse(after)
        self.before = DUP.parse(before)
        self.check = check
        self.flagged = 0

    def run(self) -> int:
        """Run the check and return the number of problems flagged."""
        if DAY_DIR_RE.match(self.topdir.name):
            self.do_dirs([self.topdir], self.topdir.parent)
        else:
            self.do_dirs(self._listdir(self.topdir), self.topdir)
        self.print_line("-" * 100, color="blue")
        return self.flagged

    # ------------------------------------------------------------------
    # output
    # ------------------------------------------------------------------
    def print_line(self, text: str, color: Optional[str] = None) -> None:
        self.sink(ReportLine(text, color))

    def flag(self, text: str, color: str = "red") -> None:
        self.flagged += 1
        self.print_line(text, color)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _listdir(self, path: Path) -> list:
        try:
            return sorted(path.iterdir())
        except OSError as exc:
            self.flag(f"   cannot read {path}: {exc}")
            return []

    @staticmethod
    def is_ignored(path: Path) -> bool:
        """Housekeeping names and files with extensions that are not hierarchy."""
        return (
            path.name in _IGNORED_NAMES
            or path.name.startswith(".")
            or path.name.endswith(_IGNORED_EXTENSIONS)
        )

    @staticmethod
    def gettimestamp(path: Path) -> str:
        """Get the timestamp of a directory from its .index file."""
        tstamp = "None"
        indexfile = path / ".index"
        if not indexfile.is_file():
            return tstamp
        with open(indexfile, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                match = _TIMESTAMP_RE.match(line)
                if match is not None:
                    try:
                        value = float(match.group(2))
                    except ValueError:
                        continue
                    tstamp = datetime.datetime.fromtimestamp(value).strftime(
                        "%Y-%m-%d  %H:%M:%S %z"
                    )
        return tstamp

    def _print_index(self, path: Path, color: Optional[str] = None) -> bool:
        """Print a directory's index. False (and flagged) if it is absent or broken."""
        tstamp = self.gettimestamp(path)
        try:
            index = read_dir_index(path)
        except FileNotFoundError:
            self.flag(_FMT2.format("", "", path.name, "", tstamp) + "  *** No .index file")
            return False
        except Exception:  # noqa: BLE001 - any parse failure means a damaged file
            self.flag(_FMT2.format("", "", path.name, "", tstamp) + "  *** Broken Index file")
            self.print_line(_FMT2.format("", "", str(path), "", "") + "File: ")
            return False
        self.print_line(index_text(index), color=color)
        return True

    # ------------------------------------------------------------------
    # hierarchy
    # ------------------------------------------------------------------
    def do_dirs(self, entries: list, current_top_dir: Path) -> int:
        """Check ``entries``, descending through directories above the day level.
        Returns the number of day directories found."""
        days_found = 0
        for ndir, entry in enumerate(sorted(entries)):
            if self.check is not None:
                self.check()
            if self.is_ignored(entry):
                continue
            path = Path(current_top_dir, entry.name)
            if not DAY_DIR_RE.match(path.name):
                if path.is_dir():
                    found = self.do_dirs(
                        [c for c in self._listdir(path) if c.is_dir()], path
                    )
                    days_found += found
                    if found == 0:
                        self.flag(
                            _FMT.format(path.name, "", "", "", self.gettimestamp(path))
                            + " is not a DAY directory"
                        )
                else:
                    self.flag(_FMT.format(path.name, "", "", "", "") + " unexpected file")
                continue
            try:
                thisday = datetime.datetime.strptime(path.name[:10], "%Y.%m.%d")
            except ValueError:
                self.flag(_FMT.format(path.name, "", "", "", "") + " has an invalid date")
                continue
            if thisday < self.after or thisday > self.before:
                continue
            days_found += 1
            self._check_day(path, new_page=ndir > 1)
        return days_found

    def _check_day(self, day: Path, new_page: bool) -> None:
        self.print_line(" ")
        if new_page:
            self.print_line("+" * 80)
            self.sink(ReportLine(page_break=True))
        self.print_line(_FMT.format(str(day), "", "", "", self.gettimestamp(day)))
        if self._print_index(day, color="blue"):
            self.print_line("            {0:16s} : {1:20s}".format("-" * 16, "-" * 20))
        for slicedir in self._listdir(day):
            if self.is_ignored(slicedir):
                continue
            if self.check is not None:
                self.check()
            tstamp = self.gettimestamp(slicedir) if slicedir.is_dir() else ""
            if not (slicedir.is_dir() and slicedir.name.startswith("slice_")):
                self.flag(
                    _FMT.format("", slicedir.name, "", "", tstamp) + "   is not a SLICE directory"
                )
                continue
            self.print_line(_FMT.format("", slicedir.name, "", "", tstamp), "teal")
            self._print_index(slicedir)
            self._check_slice(slicedir)

    def _check_slice(self, slicepath: Path) -> None:
        for celldir in self._listdir(slicepath):
            if self.is_ignored(celldir):
                continue
            tstamp = self.gettimestamp(celldir) if celldir.is_dir() else ""
            if celldir.is_dir() and is_label_dir(celldir.name):
                self.print_line(_FMT.format("", celldir.name, "", "", tstamp), "teal")
                self._check_label_dir(celldir)
                continue
            if not (celldir.is_dir() and celldir.name.startswith("cell_")):
                self.flag(
                    _FMT2.format("", "", celldir.name, "", tstamp) + "is not a CELL directory"
                )
                continue
            self.print_line(_FMT.format("", celldir.name, "", "", tstamp), "violet")
            if self._print_index(celldir):
                self._check_cell(celldir)

    def _check_label_dir(self, label: Path) -> None:
        """A label directory holds only images and videos."""
        for entry in self._listdir(label):
            if entry.is_dir() and not self.is_ignored(entry):
                self.flag(
                    _FMT2.format("", "", f"{label.name}/{entry.name}", "", "")
                    + "is a directory inside a label directory"
                )

    def _check_cell(self, cellpath: Path) -> None:
        index_file = cellpath / ".index"
        if index_file.stat().st_size == 0:
            self.flag(f"   {index_file} is empty")
        for protocol in self._listdir(cellpath):
            if protocol.name in _IGNORED_NAMES or self.is_ignored(protocol):
                continue
            if self.check is not None:
                self.check()
            if not protocol.is_dir():
                self.flag(_FMT.format("", "", "", protocol.name, "") + " unexpected file")
                continue
            self.print_line(
                _FMT.format("", "", "", protocol.name, self.gettimestamp(protocol))
            )
            if self.show_protocol and self._print_index(protocol):
                self.print_line("              -----------------------")
            self._check_protocol_files(protocol)

    def _check_protocol_files(self, protocol: Path) -> None:
        """Flag zero-length files in a protocol and its run directories."""
        for entry in self._listdir(protocol):
            if entry.name in (".DS_Store", "log.txt"):
                continue
            if entry.is_dir():
                for sub in self._listdir(entry):
                    if sub.name not in (".DS_Store", "log.txt") and sub.stat().st_size == 0:
                        self.flag(f"   {sub} is empty", color="cyan")
            elif entry.is_file() and entry.stat().st_size == 0:
                self.flag(f"   {entry} is empty")


# ----------------------------------------------------------------------
# reports
# ----------------------------------------------------------------------
_LATEX_HEADER = r"""\documentclass[8pt, letterpaper, oneside]{article}
\usepackage[utf8]{inputenc}
\usepackage{fancyvrb}
\usepackage{geometry}
\usepackage[dvipsnames]{xcolor}
\geometry{
 landscape,
 left=0.5in,
 top=0.5in,
 }

\begin{document}
"""

_LATEX_FOOTER = "\n\\end{document}\n"
_LATEX_SPECIALS = str.maketrans({
    "\\": r"\textbackslash{}", "_": r"\_", "%": r"\%", "&": r"\&", "#": r"\#",
    "$": r"\$", "{": r"\{", "}": r"\}", "^": r"\^{}", "~": r"\~{}",
})


def report_text(lines: list) -> str:
    return "".join(line.text + "\n" for line in lines if not line.page_break)


def report_latex(lines: list, title: str, topdir: str, now: str) -> str:
    """Build a LaTeX report. Text is set in Verbatim blocks, so that names and
    index contents need no escaping; flagged lines are framed in red."""
    out = [_LATEX_HEADER]
    for size, text in (("large", "Directory Check/Protocol Listing"), ("huge", title),
                       ("large", topdir), ("LARGE", "Run Date:"), ("huge", now)):
        out.append(
            f"\\vspace{{1cm}}\\begin{{center}}\\textbf{{\\{size}{{"
            f"{text.translate(_LATEX_SPECIALS)}}}}}\\end{{center}}\n"
        )
    out.append("\\newpage\n")
    for line in lines:
        if line.page_break:
            out.append("\\newpage\n")
            continue
        if not line.text.strip():
            continue
        if line.color == "red":
            options = "[frame=single,rulecolor=\\color{red},formatcom=\\color{red}]"
        elif line.color is not None:
            options = f"[formatcom=\\color{{{line.color}}}]"
        else:
            options = ""
        out.append(f"\\begin{{Verbatim}}{options}\n{line.text.rstrip()}\n\\end{{Verbatim}}\n")
    out.append(_LATEX_FOOTER)
    return "".join(out)


def find_pdflatex() -> Optional[str]:
    found = shutil.which("pdflatex")
    if found:
        return found
    return next((p for p in _PDFLATEX_LOCATIONS if Path(p).exists()), None)


def build_pdf(tex_file: Path, pdflatex: str) -> Path:
    """Run pdflatex beside ``tex_file``, remove its intermediates, and return the PDF."""
    subprocess.run(
        [pdflatex, "-interaction=nonstopmode", tex_file.name],
        cwd=tex_file.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=600,
        check=False,
    )
    for ext in (".aux", ".log", ".dvi", ".ps"):
        tex_file.with_suffix(ext).unlink(missing_ok=True)
    pdf = tex_file.with_suffix(".pdf")
    if not pdf.is_file():
        raise RuntimeError(f"pdflatex did not produce {pdf}")
    return pdf


class DirCheckWindow(ToolWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Directory Check")
        self.resize(1100, 800)
        self.lines: list = []
        self.worker = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QFormLayout()
        self.top_dir = HistoryCombo("dir_check.top_dir", title="Directory to check")
        form.addRow("Directory to check:", self.top_dir)
        self.after = QtWidgets.QLineEdit("1970.1.1")
        form.addRow("On or after:", self.after)
        self.before = QtWidgets.QLineEdit("2266.1.1")
        form.addRow("On or before:", self.before)
        self.show_protocol = QtWidgets.QCheckBox(
            "Include protocol information (very verbose)"
        )
        form.addRow("", self.show_protocol)
        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        self.run_button = QtWidgets.QPushButton("Run check")
        self.run_button.clicked.connect(self.start_check)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_check)
        self.save_button = QtWidgets.QPushButton("Save report…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_report)
        for button in (self.run_button, self.cancel_button, self.save_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(
            QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        )
        layout.addWidget(self.output, stretch=1)
        self.statusBar().showMessage("Choose a directory and press Run check.")

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.save_button.setEnabled(not running and bool(self.lines))

    def start_check(self) -> None:
        top = self.top_dir.text()
        if not top or not Path(top).is_dir():
            self.statusBar().showMessage(f"Not a directory: {top}")
            return
        after, before = self.after.text().strip(), self.before.text().strip()
        try:
            DUP.parse(after)
            DUP.parse(before)
        except (ValueError, OverflowError) as exc:
            self.statusBar().showMessage(f"Invalid date: {exc}")
            return
        self.top_dir.remember()
        show_protocol = self.show_protocol.isChecked()
        self.lines = []
        self.output.clear()
        self._set_running(True)
        self.statusBar().showMessage("Checking…")

        def scan(worker):
            # Send lines in batches so a large tree does not flood the event loop.
            batch: list = []
            last = time.monotonic()

            def sink(line: ReportLine) -> None:
                nonlocal batch, last
                batch.append(line)
                if len(batch) >= 200 or time.monotonic() - last > 0.1:
                    worker.progress.emit(batch)
                    batch, last = [], time.monotonic()

            checker = DirCheck(
                Path(top), sink, show_protocol, after, before, check=worker.check_cancelled
            )
            flagged = checker.run()
            worker.progress.emit(batch)
            return flagged

        self.worker = self.start_worker(
            scan,
            progress=self._on_lines,
            succeeded=self._on_done,
            failed=self._on_failed,
            finished=self._on_finished,
        )

    def cancel_check(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.statusBar().showMessage("Cancelled.")

    def _on_lines(self, lines: list) -> None:
        self.lines.extend(lines)
        cursor = self.output.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        for line in lines:
            if line.page_break:
                continue
            fmt = QtGui.QTextCharFormat()
            if line.color is not None:
                fmt.setForeground(QtGui.QColor(_GUI_COLORS.get(line.color, line.color)))
            cursor.insertText(line.text.rstrip("\n") + "\n", fmt)

    def _on_done(self, flagged: int) -> None:
        self.statusBar().showMessage(f"Check complete: {flagged} problem(s) flagged.")

    def _on_failed(self, detail: str) -> None:
        self.statusBar().showMessage("Check failed.")
        QtWidgets.QMessageBox.warning(self, "Directory Check", detail)

    def _on_finished(self) -> None:
        self._set_running(False)

    # ------------------------------------------------------------------
    # saving
    # ------------------------------------------------------------------
    def save_report(self) -> None:
        store = history_store()
        rundate = datetime.datetime.now().strftime("%Y.%m.%d")
        start_dir = existing_dir_from(store.get("dir_check.report"))
        stem = Path(self.top_dir.text()).name
        name, selected = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save report",
            str(Path(start_dir, f"{stem}_{rundate}_dircheck.txt")),
            "Text (*.txt);;LaTeX and PDF (*.tex)",
        )
        if not name:
            return
        path = Path(name)
        if "*.tex" in selected:
            path = path.with_suffix(".tex")
        store.add("dir_check.report", str(path))
        if path.suffix != ".tex":
            path.write_text(report_text(self.lines), encoding="utf-8")
            self.statusBar().showMessage(f"Saved {path}")
            return
        now = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S %z")
        path.write_text(
            report_latex(self.lines, path.name, self.top_dir.text(), now), encoding="utf-8"
        )
        pdflatex = find_pdflatex()
        if pdflatex is None:
            self.statusBar().showMessage(f"Saved {path} (pdflatex was not found, so no PDF)")
            return
        self.statusBar().showMessage(f"Saved {path}. Building PDF…")
        self.start_worker(
            lambda worker: build_pdf(path, pdflatex),
            succeeded=self._on_pdf_built,
            failed=self._on_failed,
        )

    def _on_pdf_built(self, pdf: Path) -> None:
        self.statusBar().showMessage(f"Saved {pdf}")
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(pdf)))


def create_tool() -> ToolWindow:
    return DirCheckWindow()
