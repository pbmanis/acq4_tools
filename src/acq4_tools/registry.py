"""The tools the toolbar offers.

Each tool module is imported the first time its button is pressed, which keeps
the toolbar quick to start. To add a tool, add a ToolSpec here and give its
module a ``create_tool()`` function that returns a ToolWindow.
"""

import importlib
from dataclasses import dataclass

from acq4_tools.common.tool_window import ToolWindow


@dataclass(frozen=True)
class ToolSpec:
    key: str
    title: str
    description: str
    module: str

    def create(self) -> ToolWindow:
        return importlib.import_module(self.module).create_tool()


TOOLS = (
    ToolSpec(
        "fix_objscale",
        "Fix Objective Scale",
        "Correct the objective and scale recorded in .index files for images and videos.",
        "acq4_tools.tools.fix_objscale",
    ),
    ToolSpec(
        "fix_directory_order",
        "Fix Directory Order",
        "Diagnose a day directory's structure and show the corrections to make in the "
        "Data Manager.",
        "acq4_tools.tools.fix_directory_order",
    ),
    ToolSpec(
        "dir_check",
        "Directory Check",
        "Check the day/slice/cell/protocol hierarchy and produce a report.",
        "acq4_tools.tools.dir_check",
    ),
    ToolSpec(
        "empty_index",
        "Empty Index Files",
        "Find .index files that are empty or nearly empty.",
        "acq4_tools.tools.empty_index",
    ),
    ToolSpec(
        "day_slice_archive",
        "Day/Slice Archive",
        "Make a tar file of the day and slice levels of the data, without the cells.",
        "acq4_tools.tools.day_slice_archive",
    ),
    ToolSpec(
        "index_transfer",
        "Index File Transfer",
        "Upload .index files that are missing from a remote system.",
        "acq4_tools.tools.index_transfer",
    ),
)
