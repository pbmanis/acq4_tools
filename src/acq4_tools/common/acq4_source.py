"""Find out from the acq4 source which configuration keys its device drivers use.

The source is parsed but never imported or run, so the drivers' hardware
libraries are not needed. A driver can read a key indirectly (for example by
looping over a list of names), so a key written as a string anywhere in the
driver's folder counts as "named"; only a key that appears nowhere is reported.
"""

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

READ = "read by driver"
NAMED = "named in driver"
NOT_FOUND = "not found"

_CONFIG_NAMES = frozenset(("config", "conf", "cfg", "opts", "_config", "_DGConfig", "camConfig"))
_KEY_METHODS = frozenset(("get", "pop", "setdefault"))
_DEFAULT_TRANSFORM_KEYS = frozenset(("pos", "scale", "angle", "axis"))


@dataclass
class DriverClass:
    name: str
    bases: set = field(default_factory=set)
    read: set = field(default_factory=set)
    named: set = field(default_factory=set)


def _is_config(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _CONFIG_NAMES
    return isinstance(node, ast.Attribute) and node.attr in _CONFIG_NAMES


def _string(node: ast.AST) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _read_key(node: ast.AST) -> Optional[str]:
    """The key if this expression reads one from a config dict."""
    if isinstance(node, ast.Subscript) and _is_config(node.value):
        return _string(node.slice)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in _KEY_METHODS and _is_config(node.func.value) and node.args:
        return _string(node.args[0])
    if isinstance(node, ast.Compare) and len(node.ops) == 1 \
            and isinstance(node.ops[0], (ast.In, ast.NotIn)) and _is_config(node.comparators[0]):
        return _string(node.left)
    return None


def _base_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _strings_in(tree: ast.AST) -> set:
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def _transform_keys(tree: ast.AST) -> Optional[frozenset]:
    """The set literal of allowed keys in setDeviceTransform, if this file has it."""
    for function in ast.walk(tree):
        if isinstance(function, ast.FunctionDef) and function.name == "setDeviceTransform":
            for node in ast.walk(function):
                if isinstance(node, ast.Set):
                    return frozenset(filter(None, map(_string, node.elts)))
    return None


class SourceCatalog:
    def __init__(self, classes: dict, transform_keys: frozenset = _DEFAULT_TRANSFORM_KEYS):
        self.classes = classes
        self.transform_keys = transform_keys

    def _lineage(self, name: str) -> set:
        seen: set = set()
        pending = [name]
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                if current in self.classes:
                    pending.extend(self.classes[current].bases)
        return seen

    def descends(self, name: str, ancestor: str) -> bool:
        return ancestor in self._lineage(name)

    def is_driver(self, name: str) -> bool:
        return name in self.classes and self.descends(name, "Device")

    def driver_names(self) -> list:
        return sorted(n for n in self.classes
                      if self.is_driver(n) and n not in ("Device", "OptomechDevice"))

    def known_keys(self, driver: str) -> list:
        """The keys that the driver reads, for offering when adding a setting."""
        keys: set = set()
        for name in self._lineage(driver):
            if name in self.classes:
                keys |= self.classes[name].read
        return sorted(keys)

    def key_status(self, driver: str, key: str) -> str:
        lineage = [self.classes[n] for n in self._lineage(driver) if n in self.classes]
        if any(key in c.read for c in lineage):
            return READ
        return NAMED if any(key in c.named for c in lineage) else NOT_FOUND


def scan_acq4_devices(devices_dir: Path,
                      check: Optional[Callable[[], None]] = None) -> SourceCatalog:
    """Build a catalog from the driver source files under ``devices_dir``."""
    classes: dict = {}
    transform_keys = None
    folder_strings: dict = defaultdict(set)
    class_folders: dict = defaultdict(set)
    for path in sorted(devices_dir.rglob("*.py")):
        if "tests" in path.parts:
            continue
        if check is not None:
            check()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        transform_keys = transform_keys or _transform_keys(tree)
        file_strings = _strings_in(tree)
        if path.parent != devices_dir:
            folder_strings[path.parent] |= file_strings
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            entry = classes.setdefault(node.name, DriverClass(node.name))
            entry.bases |= set(filter(None, map(_base_name, node.bases)))
            entry.named |= file_strings
            entry.read |= set(filter(None, map(_read_key, ast.walk(node))))
            class_folders[node.name].add(path.parent)
    # A driver's folder also holds its GUI classes, which read keys of their own.
    for name, folders in class_folders.items():
        for folder in folders:
            classes[name].named |= folder_strings.get(folder, set())
    return SourceCatalog(classes, transform_keys or _DEFAULT_TRANSFORM_KEYS)
