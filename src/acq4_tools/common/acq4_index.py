"""Reading acq4 .index files and acq4 directory naming conventions."""

import collections
import datetime
import re
import textwrap
from pathlib import Path
from typing import Union

import numpy as np
from pyqtgraph import configfile

# acq4 "day" directory names look like 2025.01.10_000.
DAY_DIR_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}_\d{3}")
# Label (fluorophore) directories hold images and videos inside a slice.
LABEL_DIRS = ("FITC", "TRITC", "DAPI", "GFP", "CY3", "CY5", "ALEXA")


def is_label_dir(name: str) -> bool:
    return name.upper() in LABEL_DIRS


def read_dir_index(directory: Union[str, Path]) -> dict:
    """Read a directory's .index file. Raises FileNotFoundError if it has none,
    and the parser's exception if the file is damaged."""
    index_file = Path(directory, ".index")
    if not index_file.is_file():
        raise FileNotFoundError(f"No .index file in {directory}")
    return configfile.readConfigFile(str(index_file))


def format_timestamp(value: float) -> str:
    return datetime.datetime.fromtimestamp(value).strftime("%Y-%m-%d  %H:%M:%S %z")


def index_text(index, line_end: str = "\n") -> str:
    """Return a readable listing of an index, as far down as it goes."""
    lines: list = []
    _format_index(index, 0, lines, line_end)
    return "".join(lines)


def _format_index(index, indent: int, out: list, lb: str) -> None:
    indent += 1
    pad = " " * (indent * 4)
    if isinstance(index, list):
        for item in index:
            _format_index(item, indent, out, lb)
            if isinstance(item, list):
                out.append(f"{pad}  list, len={len(item):d}{lb}")
            elif not isinstance(item, tuple):
                out.append(f"{pad}  {item}{lb}")
    elif isinstance(index, tuple):
        out.append(f"{pad} Device, Sequence : {index[0]!s}, {index[1]!s}{lb}")
    elif isinstance(index, dict):
        for key, value in index.items():
            key = str(key)
            if key.endswith((".ma", ".tif")) or key == "splitter":
                continue
            _format_index(value, indent, out, lb)
            if isinstance(value, (list, np.ndarray)):
                out.append(f"{pad} {key:3s} : list/array, len= {len(value):4d}{lb}")
            elif key == "__timestamp__":
                out.append(f"{pad} {'timestamp':>20s} : {format_timestamp(value)}{lb}")
            elif key == ".":
                continue
            elif key in ("description", "notes"):
                header = f"{pad} {key:>20s} : "
                wrapper = textwrap.TextWrapper(
                    initial_indent="", subsequent_indent=len(header) * " ", width=100
                )
                out.extend(line + lb for line in wrapper.wrap(header + str(value)))
            elif isinstance(value, collections.OrderedDict):
                # A nested entry ends the listing at this level.
                break
            else:
                out.append(f"{pad} {key:>20s} : {value!s}{lb}")
