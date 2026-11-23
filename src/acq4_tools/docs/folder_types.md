# Acq4 Folders

Edit acq4's `folderTypes.cfg`. It defines the folder types the Data Manager
offers in its **New** menu (Day, Slice, Cell and so on), how new folders are
named, and the metadata fields shown for each type.

Opening, saving and the Checks list work as described in
[Working with config files](config_files.md).

## Folder types

The list on the left holds the folder types in menu order. Double-click a type
to rename it. **Add**, **Remove**, **Up** and **Down** manage the list.

For the selected type:

- **Name format**: the name given to a new folder. Date codes such as
  `%Y.%m.%d` are filled in, and acq4 adds a number. **A new folder today**
  previews the name, for example `2026.11.21_000`.
- **Experimental unit**: acq4 keeps a separate log for each folder of this
  type. Cells are usually experimental units.

## Fields

The table lists the metadata fields of the selected type, in the order the
Data Manager shows them.

| Column | Meaning |
| --- | --- |
| Field | The field's name. |
| Type | `string` (one line), `text` (several lines), `list` (a choice) or `bool`. |
| Lines | For `text`: the height of the box. |
| Default | The value given to a new folder. |
| Values | For `list`: the choices. Edit them below. |

**Add**, **Remove**, **Up** and **Down** manage the fields. For a `list` field,
**List values** holds its choices. Double-click a choice to edit it.

acq4 adds `notes` and `important` fields to every type that lacks them, so you
do not need to add those.

## What the checks report

- Types without a name format or an `info` section. acq4 fails when you
  create or select a folder of that type.
- Type names that clash with the Data Manager's own menu items ("Folder",
  "New...").
- Name formats that produce characters not allowed in directory names.
- Fields of a form acq4 has no widget for, and list fields without values.

## Caveats

- Changing a type here does not change folders that already exist. Their
  `.index` files keep the fields they were created with.
- Restart acq4 to see the changes in the Data Manager.
