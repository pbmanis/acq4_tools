import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from acq4_tools.common.history import reset_history_store


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep every test away from the user's real history and settings."""
    config = tmp_path / "config"
    monkeypatch.setenv("ACQ4_TOOLS_CONFIG_DIR", str(config))
    reset_history_store()
    yield config
    reset_history_store()


def write_index(directory, timestamp=1_600_000_000.0, extra=""):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".index").write_text(
        f".:\n    __timestamp__: {timestamp}\n    dirType: 'Folder'\n{extra}", encoding="utf-8"
    )


@pytest.fixture
def day_tree(tmp_path):
    """A small well-formed acq4 day: day/slice_000/cell_000/CCIV_000/000."""
    day = tmp_path / "data" / "2024.03.05_000"
    write_index(day, 1000.0)
    slice_dir = day / "slice_000"
    write_index(slice_dir, 1100.0)
    cell = slice_dir / "cell_000"
    write_index(cell, 1200.0)
    protocol = cell / "CCIV_000"
    write_index(protocol, 1300.0)
    write_index(protocol / "000", 1301.0)
    (protocol / "000" / "data.ma").write_bytes(b"x" * 16)
    return day
