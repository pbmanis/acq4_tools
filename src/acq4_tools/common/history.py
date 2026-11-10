"""Persistent history of file and directory names, plus small app settings.

Everything is kept in one JSON file so the tools share a single history. The
file is re-read before each change, which keeps two running copies of the suite
from discarding each other's entries.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional, Union

from acq4_tools.common.paths import config_dir

DEFAULT_MAX_ENTRIES = 15


class HistoryStore:
    def __init__(self, path: Union[str, Path, None] = None):
        self.path = Path(path) if path is not None else config_dir() / "history.json"

    def _read(self) -> dict:
        """Read the store. A missing or corrupt file gives an empty store; a
        corrupt file is set aside rather than overwritten."""
        empty = {"history": {}, "settings": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return empty
        except (OSError, ValueError) as exc:
            print(f"history: could not read {self.path}: {exc}")
            try:
                os.replace(self.path, self.path.with_suffix(".corrupt"))
            except OSError:
                pass
            return empty
        if not isinstance(data, dict):
            return empty
        return {
            "history": data.get("history") if isinstance(data.get("history"), dict) else {},
            "settings": data.get("settings") if isinstance(data.get("settings"), dict) else {},
        }

    def _write(self, data: dict) -> None:
        """Replace the store atomically so a crash cannot truncate it."""
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            print(f"history: could not write {self.path}: {exc}")

    def get(self, key: str) -> list:
        """Return the entries for ``key``, newest first."""
        return list(self._read()["history"].get(key, []))

    def add(self, key: str, value: Union[str, Path], max_entries: int = DEFAULT_MAX_ENTRIES) -> list:
        """Move ``value`` to the top of ``key``'s history and return the list."""
        value = str(value)
        data = self._read()
        entries = [e for e in data["history"].get(key, []) if e != value]
        entries.insert(0, value)
        data["history"][key] = entries[:max_entries]
        self._write(data)
        return list(data["history"][key])

    def remove(self, key: str, value: Union[str, Path]) -> list:
        """Remove ``value`` from ``key``'s history and return the list."""
        value = str(value)
        data = self._read()
        entries = [e for e in data["history"].get(key, []) if e != value]
        data["history"][key] = entries
        self._write(data)
        return entries

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._read()["settings"].get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        data = self._read()
        data["settings"][key] = value
        self._write(data)


_store: Optional[HistoryStore] = None


def history_store() -> HistoryStore:
    """Return the store shared by the toolbar and all of the tools."""
    global _store
    if _store is None:
        _store = HistoryStore()
    return _store


def reset_history_store() -> None:
    """Forget the shared store so the next use re-resolves its location."""
    global _store
    _store = None
