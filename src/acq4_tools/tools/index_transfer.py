"""Upload acq4 .index files that are missing from a remote system.

The local tree is compared to the same tree on the remote system over SFTP, and
only .index files that are absent there are sent. Existing remote files are
never overwritten. Passwords are held only for the duration of an operation.
"""

import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Union

import paramiko
from pyqtgraph.Qt import QtCore, QtWidgets

from acq4_tools.common.acq4_index import DAY_DIR_RE
from acq4_tools.common.tool_window import ToolWindow
from acq4_tools.common.widgets import HistoryCombo

MISSING = "missing"
PRESENT = "present"


@dataclass
class TransferItem:
    local: Path
    remote: str
    status: str = ""


def discover_days(root: Union[str, Path]) -> list:
    """Day directories to consider: ``root`` itself, or the days directly in it."""
    root = Path(root)
    if DAY_DIR_RE.fullmatch(root.name):
        return [root]
    return sorted(c for c in root.iterdir() if c.is_dir() and DAY_DIR_RE.fullmatch(c.name))


def find_index_files(
    day: Path, check: Optional[Callable[[], None]] = None
) -> list:
    """All .index files under a day directory, including the day's own."""
    found = []
    for path in sorted(day.rglob(".index")):
        if check is not None:
            check()
        if path.is_file():
            found.append(path)
    return found


def remote_path_for(local: Path, day: Path, remote_root: str) -> str:
    """The remote location of ``local``: the day directory directly under
    ``remote_root``, with the same layout below it. Remote paths are always POSIX."""
    relative = local.relative_to(day.parent)
    return str(PurePosixPath(remote_root, *relative.parts))


def connect_sftp(host: str, port: int, username: str, password: str):
    """Open an SFTP session, returning (ssh_client, sftp). Only hosts already in
    the user's known_hosts are accepted."""
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(hostname=host, port=port, username=username, password=password)
    except paramiko.SSHException as exc:
        client.close()
        if "known_hosts" in str(exc):
            raise ConnectionError(
                f"{host} is not in your known_hosts file. Connect once with "
                f"'ssh {username}@{host}' and accept the host key, then try again."
            ) from exc
        raise
    except Exception:
        client.close()
        raise
    return client, client.open_sftp()


def remote_status(sftp, remote: str) -> str:
    """Return PRESENT or MISSING. Other failures, such as permissions, raise."""
    try:
        attrs = sftp.stat(remote)
    except FileNotFoundError:
        return MISSING
    if stat.S_ISDIR(attrs.st_mode or 0):
        raise IsADirectoryError(remote)
    return PRESENT


def check_items(sftp, items: list, check=None, report=None) -> None:
    """Fill in the remote status of each item."""
    for row, item in enumerate(items):
        if check is not None:
            check()
        try:
            item.status = remote_status(sftp, item.remote)
        except OSError as exc:
            item.status = f"error: {exc}"
        if report is not None:
            report((row, item.status))


def upload_missing(sftp, items: list, check=None, report=None) -> int:
    """Upload items currently marked MISSING and return how many were sent. The
    remote is checked again just before each upload so nothing is overwritten."""
    uploaded = 0
    for row, item in enumerate(items):
        if item.status != MISSING:
            continue
        if check is not None:
            check()
        try:
            if remote_status(sftp, item.remote) == PRESENT:
                item.status = PRESENT
            else:
                sftp.put(str(item.local), item.remote)
                item.status = "uploaded"
                uploaded += 1
        except OSError as exc:
            item.status = f"failed: {exc}"
        if report is not None:
            report((row, item.status))
    return uploaded


class IndexTransferWindow(ToolWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Index File Transfer")
        self.resize(1000, 700)
        self.items: list = []
        self.worker = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QFormLayout()
        self.local_root = HistoryCombo("index_transfer.local_root", title="Local data directory")
        form.addRow("Local directory:", self.local_root)
        self.host = HistoryCombo("index_transfer.host", mode="text")
        form.addRow("Remote host:", self.host)
        self.port = QtWidgets.QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(22)
        form.addRow("Port:", self.port)
        self.username = HistoryCombo("index_transfer.username", mode="text")
        form.addRow("User name:", self.username)
        self.password = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Not saved")
        form.addRow("Password:", self.password)
        self.remote_root = HistoryCombo("index_transfer.remote_root", mode="text")
        form.addRow("Remote directory:", self.remote_root)
        layout.addLayout(form)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.day_list = QtWidgets.QListWidget()
        split.addWidget(self.day_list)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Local file", "Remote file", "Status"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        split.addWidget(self.table)
        split.setSizes([220, 780])
        layout.addWidget(split, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        self.list_button = QtWidgets.QPushButton("List day directories")
        self.list_button.clicked.connect(self.list_days)
        self.check_button = QtWidgets.QPushButton("Check remote")
        self.check_button.clicked.connect(self.check_remote)
        self.upload_button = QtWidgets.QPushButton("Upload missing…")
        self.upload_button.setEnabled(False)
        self.upload_button.clicked.connect(self.upload)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        for button in (self.list_button, self.check_button, self.upload_button, self.cancel_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.statusBar().showMessage("Choose a local directory and list its day directories.")

    # ------------------------------------------------------------------
    # local side
    # ------------------------------------------------------------------
    def list_days(self) -> None:
        root = self.local_root.text()
        if not root or not Path(root).is_dir():
            self.statusBar().showMessage(f"Not a directory: {root}")
            return
        self.local_root.remember()
        days = discover_days(root)
        self.day_list.clear()
        for day in days:
            item = QtWidgets.QListWidgetItem(day.name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(day))
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked)
            self.day_list.addItem(item)
        self.statusBar().showMessage(f"{len(days)} day directories found.")

    def _selected_days(self) -> list:
        days = []
        for row in range(self.day_list.count()):
            item = self.day_list.item(row)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                days.append(Path(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        return days

    # ------------------------------------------------------------------
    # remote side
    # ------------------------------------------------------------------
    def _connection_settings(self) -> Optional[dict]:
        host, user, remote_root = self.host.text(), self.username.text(), self.remote_root.text()
        if not (host and user and remote_root):
            self.statusBar().showMessage("Enter the remote host, user name, and directory.")
            return None
        self.host.remember()
        self.username.remember()
        self.remote_root.remember()
        return {
            "host": host,
            "port": self.port.value(),
            "username": user,
            "password": self.password.text(),
        }

    def _set_running(self, running: bool) -> None:
        self.list_button.setEnabled(not running)
        self.check_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.upload_button.setEnabled(
            not running and any(item.status == MISSING for item in self.items)
        )

    def check_remote(self) -> None:
        days = self._selected_days()
        if not days:
            self.statusBar().showMessage("No day directories are selected.")
            return
        settings = self._connection_settings()
        if settings is None:
            return
        remote_root = self.remote_root.text()
        self.items = []
        self.table.setRowCount(0)
        self._set_running(True)
        self.statusBar().showMessage("Checking remote…")

        def run(worker):
            items = []
            for day in days:
                for path in find_index_files(day, worker.check_cancelled):
                    items.append(TransferItem(path, remote_path_for(path, day, remote_root)))
            client, sftp = connect_sftp(**settings)
            try:
                check_items(sftp, items, check=worker.check_cancelled)
            finally:
                sftp.close()
                client.close()
            return items

        self.worker = self.start_worker(
            run, succeeded=self._on_checked, failed=self._on_failed, finished=self._on_finished
        )

    def upload(self) -> None:
        missing = [item for item in self.items if item.status == MISSING]
        if not missing:
            return
        settings = self._connection_settings()
        if settings is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Upload .index files",
            f"Upload {len(missing)} .index file(s) to {settings['host']}?\n"
            "Existing remote files will not be changed.",
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._set_running(True)
        self.statusBar().showMessage("Uploading…")
        items = self.items

        def run(worker):
            client, sftp = connect_sftp(**settings)
            try:
                return upload_missing(
                    sftp, items, check=worker.check_cancelled, report=worker.progress.emit
                )
            finally:
                sftp.close()
                client.close()

        self.worker = self.start_worker(
            run,
            progress=self._on_upload_progress,
            succeeded=self._on_uploaded,
            failed=self._on_failed,
            finished=self._on_finished,
        )

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.statusBar().showMessage("Cancelled.")

    def _on_checked(self, items: list) -> None:
        self.items = items
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = (str(item.local), item.remote, item.status)
            for col, value in enumerate(values):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        count = sum(1 for item in items if item.status == MISSING)
        self.statusBar().showMessage(f"{len(items)} file(s) checked, {count} missing on remote.")

    def _on_upload_progress(self, update: tuple) -> None:
        row, status = update
        self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(status))

    def _on_uploaded(self, count: int) -> None:
        self.statusBar().showMessage(f"{count} file(s) uploaded.")

    def _on_failed(self, detail: str) -> None:
        self.statusBar().showMessage("Operation failed.")
        message = detail.strip().splitlines()[-1]
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("Index File Transfer")
        box.setText(message)
        box.setDetailedText(detail)
        box.exec()

    def _on_finished(self) -> None:
        self._set_running(False)


def create_tool() -> ToolWindow:
    return IndexTransferWindow()
