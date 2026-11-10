"""Base window for the tools, and background work for long-running scans.

Each tool runs in the toolbar's process, so a tool closes its window rather
than exiting, and long scans (often over network volumes) run on a worker
thread so that the toolbar and the other tools stay responsive.
"""

import traceback
from typing import Callable, Optional

from pyqtgraph.Qt import QtCore, QtWidgets

# Workers that did not stop when their window closed (for example, blocked on an
# unresponsive network volume). Destroying a running QThread aborts the process,
# so they are kept referenced until they finish.
_orphaned_workers: list = []


class Cancelled(Exception):
    """Raised inside a worker function to stop after a cancel request."""


class FunctionWorker(QtCore.QThread):
    """Run ``fn(worker)`` on a thread.

    ``fn`` can report through ``worker.progress.emit(...)`` and should call
    ``worker.check_cancelled()`` regularly. Only connect these signals to
    methods of QObjects (such as a ToolWindow) so the slots run on the GUI thread.
    """

    progress = QtCore.Signal(object)
    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def check_cancelled(self) -> None:
        if self._cancel_requested:
            raise Cancelled()

    def run(self) -> None:
        try:
            result = self.fn(self)
        except Cancelled:
            return
        except Exception:  # noqa: BLE001 - reported to the user by the tool
            self.failed.emit(traceback.format_exc())
        else:
            self.succeeded.emit(result)


class ToolWindow(QtWidgets.QMainWindow):
    """Top-level window of a tool.

    ``closed`` tells the toolbar that the tool has gone. ``controller`` keeps a
    non-window object that drives the tool alive for as long as the window.
    """

    closed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.controller = None
        self._workers: list = []

    def start_worker(self, fn: Callable, progress: Optional[Callable] = None,
                     succeeded: Optional[Callable] = None,
                     failed: Optional[Callable] = None,
                     finished: Optional[Callable] = None) -> FunctionWorker:
        """Start ``fn`` on a thread. The callbacks must be methods of this window."""
        worker = FunctionWorker(fn)
        self._workers.append(worker)
        if progress is not None:
            worker.progress.connect(progress)
        if succeeded is not None:
            worker.succeeded.connect(succeeded)
        if failed is not None:
            worker.failed.connect(failed)
        if finished is not None:
            worker.finished.connect(finished)
        worker.finished.connect(self._reap_workers)
        worker.start()
        return worker

    def _reap_workers(self) -> None:
        self._workers = [w for w in self._workers if not w.isFinished()]

    def stop_workers(self, timeout_ms: int = 3000) -> None:
        """Ask running workers to stop and wait briefly for them."""
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            if not worker.wait(timeout_ms):
                _orphaned_workers.append(worker)
        self._workers = []

    def closeEvent(self, event):  # noqa: N802 - Qt override name
        super().closeEvent(event)
        if event.isAccepted():
            self.stop_workers()
            self.closed.emit()


def workers_still_running() -> bool:
    """True if a worker outlived its window and is still running."""
    return any(worker.isRunning() for worker in _orphaned_workers)
