"""Edit a pyqtgraph config file, changing only the lines that are edited.

pyqtgraph's own writer would discard the comments, the commented-out options
and expressions such as ``readConfigFile('devices.cfg')``, so the tools keep the
text of the file and make targeted changes to it. pyqtgraph's parser remains the
judge of whether a file is valid.
"""

import os
import re
import shutil
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from pyqtgraph import configfile

SECTION = object()  # value of a key that has nested keys below it
_COMMENT_LINE = re.compile(r"\s*#")
_COMMENTED_KEY = re.compile(r"\s*#+\s*[^\s#:][^:]*:")


class ConfigError(Exception):
    """The text is not a valid config file, or an edit cannot be made."""


@dataclass(frozen=True)
class IncludedFile:
    """The value of a ``readConfigFile('name')`` expression."""

    name: str


def _scope() -> dict:
    """The names available to expressions in a config file, as in readConfigFile."""
    scope = {
        **configfile.units.allUnits,
        "OrderedDict": OrderedDict,
        "readConfigFile": lambda name, **_kwargs: IncludedFile(name),
        "Point": configfile.Point,
        "QtCore": configfile.QtCore,
        "ColorMap": configfile.ColorMap,
        "datetime": configfile.datetime,
        "array": configfile.numpy.array,
    }
    for dtype in ("int8", "uint8", "int16", "uint16", "float16", "int32", "uint32",
                  "float32", "int64", "uint64", "float64"):
        scope[dtype] = getattr(configfile.numpy, dtype)
    return scope


def parse_text(text: str) -> dict:
    """Parse with pyqtgraph, reporting a problem as a ConfigError."""
    try:
        return configfile.parseString(text, **_scope())[1]
    except configfile.ParseError as exc:
        raise ConfigError(str(exc)) from exc


def split_comment(text: str) -> tuple:
    """Split ``value  # comment`` into the value and the rest, respecting quotes."""
    quote = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            value = text[:index].rstrip()
            return value, text[len(value):]
        index += 1
    value = text.rstrip()
    return value, text[len(value):]


def format_value(value: Any) -> str:
    """The text of a value, in the style of the acq4 config files."""
    if isinstance(value, IncludedFile):
        return f"readConfigFile({value.name!r})"
    if isinstance(value, tuple) and len(value) > 1:
        return ", ".join(repr(item) for item in value)
    return repr(value)


def _measure_indent(text: str) -> int:
    return len(text) - len(text.lstrip(" "))


class _Line:
    """One logical line; backslash continuations stay in ``text``."""

    def __init__(self, text: str):
        self.text = text

    @property
    def logical(self) -> str:
        return self.text.replace("\\\n", "")

    @property
    def is_real(self) -> bool:
        return not _COMMENT_LINE.match(self.logical) and bool(self.logical.strip())

    @property
    def is_comment(self) -> bool:
        return bool(_COMMENT_LINE.match(self.logical))


class Node:
    """A key in the file."""

    def __init__(self, key: str, indent: int, line: Optional[_Line], parent: Optional["Node"]):
        self.key = key
        self.indent = indent
        self.line = line
        self.parent = parent
        self.children: list = []

    @property
    def raw(self) -> str:
        """The text of the value, without any trailing comment."""
        if self.line is None:
            return ""
        return split_comment(self.line.logical.partition(":")[2])[0].strip()

    @property
    def is_section(self) -> bool:
        return not self.raw

    def child(self, key: str) -> Optional["Node"]:
        return next((c for c in self.children if c.key == key), None)


class ConfigDocument:
    def __init__(self, text: str):
        parse_text(text)
        self.lines = [_Line(t) for t in self._logical_lines(text)]
        self.root = Node("", -1, None, None)
        stack = [self.root]
        for line in self.lines:
            if not line.is_real:
                continue
            indent = _measure_indent(line.logical)
            while stack[-1].indent >= indent:
                stack.pop()
            node = Node(line.logical.partition(":")[0].strip(), indent, line, stack[-1])
            stack[-1].children.append(node)
            stack.append(node)

    @staticmethod
    def _logical_lines(text: str) -> list:
        lines = []
        pending = ""
        for physical in text.split("\n"):
            if physical.endswith("\\"):
                pending += physical + "\n"
            else:
                lines.append(pending + physical)
                pending = ""
        if pending:
            lines.append(pending[:-1])
        return lines

    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def check(self) -> None:
        """Raise ConfigError unless the text is still a valid config file."""
        parse_text(self.text())

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------
    def node(self, *path: str) -> Optional[Node]:
        current = self.root
        for key in path:
            current = current.child(key)
            if current is None:
                return None
        return current

    def value(self, node: Optional[Node], default: Any = None) -> Any:
        if node is None:
            return default
        if node.is_section:
            return {child.key: self.value(child) for child in node.children}
        return self.evaluate(node.raw)

    @staticmethod
    def evaluate(expression: str) -> Any:
        try:
            return eval(expression, _scope())  # noqa: S307 - pyqtgraph evaluates these too
        except Exception as exc:  # noqa: BLE001 - any expression can fail in any way
            raise ConfigError(f"Cannot evaluate '{expression}': {exc}") from exc

    # ------------------------------------------------------------------
    # changing values
    # ------------------------------------------------------------------
    def _write_value(self, node: Node, raw: str) -> None:
        before, _, after = node.line.logical.partition(":")
        comment = split_comment(after)[1]
        gap = after[:len(after) - len(after.lstrip())] or " "
        node.line.text = f"{before}:{gap}{raw}{comment}"

    def _drop_children(self, node: Node) -> None:
        for child in list(node.children):
            self._delete_lines(child, with_comments=False)
        node.children.clear()

    def set_value(self, node: Node, value: Any) -> bool:
        """Set a value. The line is left alone if the value would not change."""
        if not node.is_section:
            try:
                if self.evaluate(node.raw) == value:
                    return False
            except (ConfigError, ValueError):  # ValueError: comparing numpy arrays
                pass
        self._drop_children(node)
        self._write_value(node, format_value(value))
        return True

    def set_raw(self, node: Node, expression: str) -> bool:
        """Set a value from the text of a Python expression."""
        expression = expression.strip()
        if not expression or "\n" in expression:
            raise ConfigError("A value must be a single expression.")
        if expression == node.raw:
            return False
        self.evaluate(expression)
        self._drop_children(node)
        self._write_value(node, expression)
        return True

    def annotations(self, prefix: str) -> list:
        """The text after ``prefix`` of each comment line that starts with it."""
        return [line.logical[len(prefix):].strip() for line in self.lines
                if line.logical.startswith(prefix)]

    def set_annotations(self, prefix: str, values: list) -> bool:
        """Replace the comment lines starting with ``prefix``, kept at the end of the file."""
        if self.annotations(prefix) == list(values):
            return False
        self.lines = [line for line in self.lines if not line.logical.startswith(prefix)]
        index = len(self.lines)
        while index > 0 and not self.lines[index - 1].logical.strip():
            index -= 1
        self.lines[index:index] = [_Line(f"{prefix} {value}") for value in values]
        return True

    def set_typed(self, node: Node, text: str) -> bool:
        """Keep a Python value as typed. Anything else, such as a bare path, is
        stored as text, in which case True is returned."""
        try:
            self.set_raw(node, text)
        except ConfigError:
            self.set_value(node, text.strip())
            return True
        return False

    def make_section(self, node: Node) -> None:
        """Turn ``key: value`` into ``key:``, ready for nested keys."""
        before, _, after = node.line.logical.partition(":")
        node.line.text = f"{before}:{split_comment(after)[1]}"

    # ------------------------------------------------------------------
    # adding, removing, renaming and moving keys
    # ------------------------------------------------------------------
    def _check_key(self, parent: Node, key: str, ignore: Optional[Node] = None) -> None:
        if not key or key != key.strip() or ":" in key or key.startswith("#"):
            raise ConfigError(f"'{key}' cannot be used as a name.")
        existing = parent.child(key)
        if existing is not None and existing is not ignore:
            raise ConfigError(f"'{key}' already exists here.")

    def _index(self, line: _Line) -> int:
        return next(i for i, candidate in enumerate(self.lines) if candidate is line)

    @staticmethod
    def _last_line(node: Node) -> Optional[_Line]:
        while node.children:
            node = node.children[-1]
        return node.line

    def _commented_out(self, parent: Node, key: str, indent: int) -> Optional[_Line]:
        """A commented-out ``# key: value`` at the level of parent's children."""
        pattern = re.compile(rf"\s*#+\s*{re.escape(key)}\s*:")
        start = 0 if parent.line is None else self._index(parent.line) + 1
        for index in range(start, len(self.lines)):
            line = self.lines[index]
            if line.is_real and _measure_indent(line.logical) <= parent.indent:
                return None
            if line.is_comment and _measure_indent(line.logical) == indent \
                    and pattern.match(line.logical):
                following = next((c for c in self.lines[index + 1:] if c.is_real), None)
                if following is None or _measure_indent(following.logical) <= indent:
                    return line
        return None

    def add(self, parent: Node, key: str, value: Any = SECTION,
            after: Optional[Node] = None) -> Node:
        """Add a key. A commented-out line for the same key is reused, so that
        the comments explaining it stay with it."""
        self._check_key(parent, key)
        if parent is not self.root and not parent.is_section:
            self.make_section(parent)
        if parent.children:
            indent = parent.children[0].indent
        else:
            indent = 0 if parent is self.root else parent.indent + 4
        line = None
        if value is SECTION:
            # Written as {} until it has keys: pyqtgraph cannot read an empty
            # section at the end of a file.
            text = " " * indent + f"{key}: {{}}"
        else:
            text = " " * indent + f"{key}: {format_value(value)}"
            line = self._commented_out(parent, key, indent)
        if line is not None:
            line.text = text
        else:
            line = _Line(text)
            anchor = self._last_line(after if after is not None else parent)
            self.lines.insert(0 if anchor is None else self._index(anchor) + 1, line)
        node = Node(key, indent, line, parent)
        parent.children.append(node)
        parent.children.sort(key=lambda child: self._index(child.line))
        return node

    def comment_out(self, node: Node) -> None:
        """Turn a single-line key into a comment, so that it can come back."""
        if node.is_section:
            raise ConfigError(f"'{node.key}' has nested settings and cannot be commented out.")
        logical = node.line.logical
        node.line.text = " " * node.indent + "# " + logical.lstrip(" ")
        self._forget(node)

    def _forget(self, node: Node) -> None:
        parent = node.parent
        parent.children.remove(node)
        if parent is not self.root and not parent.children:
            self._write_value(parent, "{}")

    def _block(self, node: Node, with_comments: bool = True) -> tuple:
        """Line range of a key, with the description directly above it. A
        commented-out key directly above is left out, as it is not a description."""
        start = self._index(node.line)
        if with_comments:
            while start > 0:
                above = self.lines[start - 1]
                if not above.is_comment or _measure_indent(above.logical) != node.indent \
                        or _COMMENTED_KEY.match(above.logical):
                    break
                start -= 1
        return start, self._index(self._last_line(node)) + 1

    def _delete_lines(self, node: Node, with_comments: bool) -> None:
        start, end = self._block(node, with_comments)
        del self.lines[start:end]

    def _reparse(self) -> None:
        """Rebuild the tree after lines have become, or stopped being, keys."""
        self.__init__(self.text())

    def comment_block(self, node: Node) -> None:
        """Comment out a key and everything nested in it."""
        start, end = self._block(node, with_comments=False)
        for line in self.lines[start:end]:
            line.text = f"# {line.logical}" if line.logical else "#"
        self._reparse()

    def uncomment_lines(self, start: int, end: int, base: int = 0) -> None:
        """Bring back a commented-out block, removing ``base`` columns of indent."""
        saved = [line.text for line in self.lines[start:end]]
        for line in self.lines[start:end]:
            text = line.logical
            line.text = (text[2:] if text[1:2] == " " else text[1:])[base:]
        try:
            self._reparse()
        except ConfigError:
            for line, text in zip(self.lines[start:end], saved):
                line.text = text
            raise

    def delete_lines(self, start: int, end: int) -> None:
        del self.lines[start:end]
        self._reparse()

    def insert_block(self, text: str) -> None:
        """Add a new top-level entry after the last key in the file."""
        anchor = self._last_line(self.root)
        index = 0 if anchor is None else self._index(anchor) + 1
        self.lines[index:index] = [_Line(""), *(_Line(t) for t in text.rstrip("\n").split("\n"))]
        self._reparse()

    def block_text(self, node: Node) -> str:
        start, end = self._block(node, with_comments=False)
        return "\n".join(line.logical for line in self.lines[start:end])

    def remove(self, node: Node) -> None:
        self._delete_lines(node, with_comments=True)
        self._forget(node)

    def rename(self, node: Node, new_key: str) -> bool:
        new_key = new_key.strip()
        if new_key == node.key:
            return False
        self._check_key(node.parent, new_key, ignore=node)
        after = node.line.logical.partition(":")[2]
        node.line.text = " " * node.indent + f"{new_key}:{after}"
        node.key = new_key
        return True

    def move(self, node: Node, delta: int) -> bool:
        """Move a key up (-1) or down (+1) among its siblings."""
        siblings = node.parent.children
        position = siblings.index(node)
        other_position = position + delta
        if not 0 <= other_position < len(siblings):
            return False
        first, second = sorted((node, siblings[other_position]),
                               key=lambda n: self._index(n.line))
        first_start, first_end = self._block(first)
        second_start, second_end = self._block(second)
        self.lines[first_start:second_end] = (
            self.lines[second_start:second_end]
            + self.lines[first_end:second_start]
            + self.lines[first_start:first_end]
        )
        siblings[position], siblings[other_position] = siblings[other_position], node
        return True


def read_config_text(path: Union[str, Path]) -> str:
    """Read a config file, with line endings normalized as pyqtgraph does."""
    text = Path(path).read_bytes().decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_config_text(path: Union[str, Path], text: str) -> Optional[Path]:
    """Replace a config file in one step, keeping its line endings and leaving
    the previous version beside it as ``<name>.bak``, whose path is returned."""
    path = Path(path)
    backup = None
    newline = "\n"
    if path.exists():
        if b"\r\n" in path.read_bytes():
            newline = "\r\n"
        backup = path.with_name(path.name + ".bak")
        shutil.copy2(path, backup)
    partial = path.with_name(path.name + ".partial")
    try:
        partial.write_bytes(text.replace("\n", newline).encode("utf-8"))
        if backup is not None:
            shutil.copymode(path, partial)
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return backup
