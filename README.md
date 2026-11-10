# acq4 Tools

Tools to use alongside the [acq4](https://acq4.readthedocs.io) acquisition
program. A small floating toolbar launches each tool in its own window, and
several tools can be open at once.

| Tool | Purpose |
| --- | --- |
| Fix Objective Scale | Correct the objective and scale recorded in `.index` files for images and videos. |
| Fix Directory Order | Diagnose the structure of a day directory and show the corrections to make in the Data Manager. Never changes data. |
| Directory Check | Check the day/slice/cell/protocol hierarchy and produce a report (text, LaTeX, or PDF). |
| Empty Index Files | Find `.index` files that are empty or nearly empty. |
| Day/Slice Archive | Make a tar file of the day and slice levels of the data, including each day's `.index` and the slices' label directories, without the cells. |
| Index File Transfer | Upload `.index` files that are missing from a remote system over SFTP. Never overwrites. |

## Running from source

```
uv sync
uv run acq4-tools
```

## Tests

```
uv run pytest
```

The tests run headless, using Qt's offscreen platform.

## Building the application

PyInstaller cannot cross-compile, so build on the platform you are targeting:

| Platform | Command | Result |
| --- | --- | --- |
| macOS | `packaging/build_macos.sh` | `dist/acq4 Tools.app` |
| Linux | `packaging/build_linux.sh` | `dist/acq4-tools/acq4-tools` |
| Windows | `packaging\build_windows.ps1` | `dist\acq4-tools\acq4-tools.exe` |

Each script finishes by running the built program's `--self-test`, which opens
and closes every tool.

## Where settings are kept

File and directory history and the toolbar settings are in `history.json`, and
the objective and camera table is in `fix_objective_data.cfg` (copied from the
packaged defaults on first use, so edit this copy for your rig). Both are in an
`acq4_tools` folder in the platform's user configuration directory:

- macOS: `~/Library/Preferences/acq4_tools`
- Linux: `~/.config/acq4_tools`
- Windows: `%LOCALAPPDATA%\acq4_tools`

Set the `ACQ4_TOOLS_CONFIG_DIR` environment variable to use another location.
Passwords are never saved.

## SFTP host keys

Index File Transfer only connects to hosts already in your `known_hosts` file.
Connect once with `ssh user@host` and accept the key before using it.

## Adding a tool

Write a module in `src/acq4_tools/tools/` with a `create_tool()` function that
returns a `ToolWindow`, then add a `ToolSpec` entry to
`src/acq4_tools/registry.py`.
