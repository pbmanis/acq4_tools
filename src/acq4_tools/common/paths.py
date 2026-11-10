"""Locations of the per-user configuration directory and the packaged data."""

import os
from pathlib import Path

from pyqtgraph.Qt import QtCore


def config_dir() -> Path:
    """Return the per-user settings directory, creating it if needed."""
    override = os.environ.get("ACQ4_TOOLS_CONFIG_DIR")
    if override:
        path = Path(override)
    else:
        base = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.GenericConfigLocation
        )
        path = Path(base, "acq4_tools")
    path.mkdir(parents=True, exist_ok=True)
    return path


def packaged_data(name: str) -> Path:
    """Return the path of a file shipped in the package's data directory."""
    return Path(__file__).resolve().parent.parent / "data" / name
