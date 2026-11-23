# Check Directories

Walk a directory of acq4 data, list every day, slice, cell and protocol with
its time and `.index` contents, and flag anything outside the expected
hierarchy. The report can be saved as text, or as LaTeX that is made into a PDF.

The tool only reads the data.

## Using it

1. **Directory to check**: a day directory, or a folder holding days (at any
   depth).
2. **On or after / On or before**: limit the check to days in a date range,
   written `year.month.day`, for example `2024.3.5`. The defaults include
   every day.
3. **Include protocol information**: also print each protocol's `.index`. The
   report becomes very long.
4. Press **Run check**. The report fills in as it runs. **Cancel** stops it.
5. **Save report…** saves it. Choose *Text* for a plain `.txt`, or *LaTeX and
   PDF* for a `.tex` file. If `pdflatex` is installed, a landscape PDF is
   built beside it and opened.

## What is flagged (red)

- A directory with no day directories below it ("is not a DAY directory").
- Unexpected files where only directories belong.
- A day whose name is not a valid date.
- Anything in a day other than `slice_` directories.
- Anything in a slice other than `cell_` directories and label directories
  (FITC, TRITC…).
- Directories inside a label directory.
- Missing or damaged `.index` files, and empty `.index` files in cells.
- Empty data files in protocols and their run directories.

The status bar gives the total number of problems.

## The expected hierarchy

```
day
    slice          images and videos, label directories
        cell       protocols
```

Images, documents, spreadsheets and other non-data files (`.tif`, `.pdf`,
`.txt`, `.py` and so on) are ignored wherever they are.

## Caveats

- The PDF needs a TeX installation that includes `pdflatex`. The tool looks on
  the PATH and in the usual MacTeX and Homebrew locations. Without it, only
  the `.tex` file is saved.
- Pair directories (`pair_`) are flagged in slices. Use
  [Data Order](fix_directory_order.md) to see where their cells belong.
