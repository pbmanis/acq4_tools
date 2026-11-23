# Working with config files

[Acq4 Rig Config](rig_config.md), [Acq4 Config](default_cfg.md) and
[Acq4 Folders](folder_types.md) edit acq4's configuration files, and they share
one window layout.

## Opening a file

1. **acq4 directory**: choose the top directory of your acq4 installation or
   source checkout. **Browse…** on the file line then opens acq4's `config`
   folder. Acq4 Rig Config also uses this directory to read the acq4 source.
2. **Config file**: choose the file, then press **Open**.
3. Or press **New from Template** to start an untitled file from the template
   shipped with acq4 Tools. Nothing is written until you save.

## Editing

The tabs show the file as fields and tables. Each edit changes the file text
straight away. The **File Text** tab shows the exact text that will be saved.

Values are pyqtgraph config expressions, the same as in the file: numbers,
`'quoted text'`, `True`/`False`, lists, and expressions such as `5*um`.

Only the lines you edit change. Comments, commented-out options and
`readConfigFile(...)` includes are kept as they were.

## Checks

The **Checks** list below the tabs updates after each edit. It reports
settings that acq4 would reject or ignore, names that do not match, and files
or directories that are missing on this computer. A check does not stop you
saving.

## Saving

- **Save** writes the file. The previous version is kept beside it as
  `<name>.bak`, so one level of undo survives on disk.
- **Save As…** writes to a new file.
- **Revert** discards every change since the file was opened or last saved.
- If the file changed on disk since you opened it (for example, edited by
  hand), Save asks before replacing it.
- Closing the window or opening another file with unsaved changes asks whether
  to save. The title bar shows `*` while there are unsaved changes.

## Caveats

- acq4 reads its config files only when it starts. Restart acq4 after saving.
- pyqtgraph cannot read an empty section at the end of a file, so the editors
  write `{}` in a section until it has keys.
- Keep a copy of a working configuration before large changes. The `.bak` file
  holds only the version before the last save.
