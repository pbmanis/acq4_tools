# Acq4 Config

Edit acq4's `default.cfg`, the main configuration file: which modules acq4
offers and their keyboard shortcuts, where data and tasks are stored, which
devices and folder-type files to load, and general options.

Opening, saving and the Checks list work as described in
[Working with config files](config_files.md).

## Modules tab

The table lists each module entry: its **Name** (as shown in acq4's Manager
window), its **Module** class, and its **Shortcut**.

- Edit a name or shortcut in the table. Shortcuts use Qt's form, e.g. `F1` or
  `Ctrl+Shift+D`.
- The Module drop-down lists acq4's module classes. Type a dotted name to use
  a custom class.
- **Add** adds an entry named "New Module". Rename it and choose its class.
- **Remove** deletes the selected entry and its settings.
- **Up / Down** move the entry, which sets its place in acq4's module list.

**Module settings** shows the `config` section of the selected module.
**Add Setting** offers the settings that module reads (for example `taskDir` for
the Task Runner, or `cameraModule` for the Imager). **Remove Setting** deletes
the selected setting. **Choose Directory…** sets the selected setting to a
directory picked from a dialog. Nested settings are shown as text only; edit
those in the file.

## Directories tab

| Field | Meaning |
| --- | --- |
| Storage directory | Where acq4 saves data. |
| Task directory | Where the Task Runner keeps saved tasks. When empty, acq4 uses the `protocols` folder beside this file. |
| Devices file | Usually `devices.cfg`, named relative to this file. |
| Folder types file | Usually `folderTypes.cfg`, named relative to this file. |
| Stylesheet | An optional Qt stylesheet, named relative to this file. |

If one of these is written out in full inside `default.cfg` rather than read
from another file, its field shows "(defined inside this file)" and cannot be
changed here.

**Configurations** are named sets, such as one for each user, that acq4 offers
at start-up. Each has its own storage directory. **Add**, **Remove** and
**Choose Directory…** manage them.

## Options tab

| Option | Meaning |
| --- | --- |
| CUDA image processing | Process camera images on a CUDA-capable GPU. |
| HDF5 compression | How data files are compressed. gzip is slow. lzf and szip are not available in every HDF5 installation. |
| Disable error popups | Do not open the log window when an error occurs. |
| Plot mouse mode | How the mouse drags pyqtgraph plots (one or three buttons). |
| Use OpenGL | Draw plots with OpenGL. |

## What the checks report

- Module entries with no class, an unknown class, an invalid shortcut, or a
  shortcut used twice.
- Keys acq4 ignores, at the top level, under `misc`, or in a module entry.
- Directories that are missing on this computer. This is expected when you
  edit a file meant for another computer.
- Devices, folder-types or stylesheet files that are not in the config folder.

## Caveats

- Renaming a device in [Acq4 Rig Config](rig_config.md) does not update module
  settings here that name it (for example `clampDev` or `cameraModule`).
- Paths are checked on this computer. A rig's paths may not exist where you
  edit the file.
