# acq4 Tools

acq4 Tools is a set of small programs for use alongside the
[acq4](https://acq4.readthedocs.io) acquisition program. Some tidy up and check
recorded data; others edit acq4's configuration files.

Each tool opens in its own window from the floating toolbar, and several can be
open at once. Every tool window has a **Help** menu. Its first item (also
**F1**, or **Cmd-?** on macOS) opens that tool's page here.

## The tools

### Configuration

| Tool | What it does |
| --- | --- |
| [Acq4 Rig Config](rig_config.md) | Edit and check `devices.cfg`: devices, DAQ wiring, line map, optomechanical tree, and parameter names compared with the acq4 source. |
| [Acq4 Config](default_cfg.md) | Edit `default.cfg`: modules and shortcuts, directories, configurations and options. |
| [Acq4 Folders](folder_types.md) | Edit `folderTypes.cfg`: the folder types and metadata fields offered by the Data Manager. |

These three share a window layout. See [Working with config files](config_files.md).

### Data

| Tool | What it does | Changes data? |
| --- | --- | --- |
| [Data Order](fix_directory_order.md) | Diagnose the structure of a day directory and show the corrections to make in the Data Manager. | Never |
| [Check Directories](dir_check.md) | Check the day/slice/cell/protocol hierarchy and produce a report. | Never |
| [Objective Scale](fix_objscale.md) | Correct the objective and scale recorded for an image or video. | **Yes**: rewrites `.index` |
| [Find Empty .index](empty_index.md) | Find `.index` files that are empty or nearly empty. | Never |
| [Retrieve .index Files](index_transfer.md) | Upload `.index` files that are missing on a remote computer, over SFTP. | Only adds missing remote files |
| [Day/Slice Archive](day_slice_archive.md) | Make a tar file of the day and slice levels of the data, without the cells. | Never (writes a new tar file) |

## The acq4 data hierarchy

The data tools expect the layout acq4's Data Manager creates:

```
2024.03.05_000            day      (YYYY.MM.DD_NNN)
    slice_000             slice    images and videos, label directories
        FITC              label    images and videos only
        cell_000          cell
            CCIV_000      protocol
                000       run      data files
```

Each directory has a hidden `.index` file that describes it and its contents.
The `.index` files record when each directory was made, so they matter as
much as the data. Move or rename acq4 data with the Data Manager, which keeps
the `.index` files correct, rather than with the Finder, Explorer or a shell.

## The toolbar

- Press a tool's button to open it. If it is already open, its window comes forward.
  An open tool is shown in bold with a ● marker.
- **Keep on top** keeps the toolbar above other windows.
- **Help** opens this page.
- **Close** closes every tool, asking first, and quits. Tools with unsaved
  changes ask whether to save them.

## Drop-down history

Directory and file fields remember the values you have used. Pick an earlier
value from the drop-down, type a new one, or press **Browse…**. A value is
added to the history once it has been used successfully.

## Where settings are kept

History, toolbar settings and the objective table (`fix_objective_data.cfg`)
are kept in an `acq4_tools` folder in your user settings directory:

| System | Location |
| --- | --- |
| macOS | `~/Library/Preferences/acq4_tools` |
| Linux | `~/.config/acq4_tools` |
| Windows | `%LOCALAPPDATA%\acq4_tools` |

Set the environment variable `ACQ4_TOOLS_CONFIG_DIR` to use another folder.
Passwords are never saved.

## Long-running work

Scans of large or network volumes run in the background, so the toolbar and
other tools stay usable. Use the tool's **Cancel** button to stop one. If a
network volume stops responding, closing the tool may not stop the scan at
once. It finishes on its own when the volume answers.
