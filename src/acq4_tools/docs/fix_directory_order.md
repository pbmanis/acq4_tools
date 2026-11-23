# Data Order

Diagnose the structure of one acq4 day directory and show how it should be
arranged: slices, cells and protocols in the order they were recorded, and
directories at the right level.

**This tool never moves, renames or deletes anything.** acq4 data must be
rearranged with acq4's Data Manager so the `.index` files stay correct. Use
this tool to see what to change, make the changes in the Data Manager, then
press **Reload current structure** to confirm.

## Choosing a day

| Control | What it does |
| --- | --- |
| **Browse…** | Choose a day directory. A directory inside a day selects that day. A folder of days selects the earliest. |
| **Previous day / Next day** | Step to the neighboring day in the same folder. |
| **Reload current structure** | Read the day again, for example after making changes in the Data Manager. |
| **Recent day directories** | Days shown before. Click one to show it again. |
| **Flag protocol order (name vs time)** | Also flag a cell's protocols whose numbering differs from the order they were recorded in. This is off by default, because it is usually harmless. |

## Reading the display

The banner says either **No reordering required** (green) or
**Suggested reordering** with the number of flagged items (amber).

- **Current structure** (left) is the day as it is on disk, with the time
  each directory was made.
- **Suggested reordering** (right) is the day as it should be.
- Arrows join each item that would move to its new place. The two trees
  scroll together. Arrows are drawn only for items visible in both trees.

Colors in the right-hand tree (hover over an item for the reason):

| Color | Meaning |
| --- | --- |
| Blue | Out of recording order; its position changes. |
| Orange | A cell that is not directly under a slice, to be moved under the last slice recorded before it. Or a label directory (FITC, TRITC…) inside another, to be moved up beside it. |
| Red | A conflict. The move would clash with a directory of the same name, or no slice exists to hold the cell. |

Each directory also shows how many images and videos it holds.

## Timestamps

Times come from the `__timestamp__` in each directory's `.index`. When that is
missing, the tool uses the parent's time or the directory's modification time,
and marks it `(parent)` or `(mtime)`. Treat orders based on those with care.
Modification times change when files are copied.

## Caveats

- `pair_` directories are treated as cells. They are usually made by
  accident in acq4.
- Protocol run directories (`000`, `000_001`, …) are not examined.
- The suggestion is only advice. Check it against your notes before making
  changes in the Data Manager.
