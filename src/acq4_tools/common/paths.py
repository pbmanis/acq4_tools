"""Locations of the per-user configuration directory and the packaged data."""

import os
from pathlib import Path
from typing import Optional

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


def _acq4_root(top: str) -> Optional[Path]:
    """The folder holding acq4's config folder: the top directory itself for a
    source checkout, or its acq4 subdirectory for an installation."""
    if not top:
        return None
    for root in (Path(top), Path(top, "acq4")):
        try:
            if (root / "config").is_dir():
                return root
        except OSError:
            continue
    return None


def acq4_config_dir(top: str) -> Optional[Path]:
    """The config folder of an acq4 installation, given its top directory."""
    root = _acq4_root(top)
    return None if root is None else root / "config"


def acq4_devices_dir(top: str) -> Optional[Path]:
    """The folder of device drivers in an acq4 source tree, given its top directory."""
    root = _acq4_root(top)
    if root is None:
        return None
    candidate = root / "acq4" / "devices"
    try:
        return candidate if candidate.is_dir() else None
    except OSError:
        return None


def packaged_data(name: str) -> Path:
    """Return the path of a file shipped in the package's data directory."""
    return Path(__file__).resolve().parent.parent / "data" / name
