# Day/Slice Archive

Make a tar file of the day and slice levels of acq4 data, without the cells.
It holds the slice images and the `.index` files that describe the
experiment, at a small fraction of the size of the full data. Tar files of
individual cells can later be unpacked into the directory structure it creates.

The tool only reads the data, and writes one new tar file.

## What goes in the archive

For each day directory:

- the day directory and its `.index`;
- each `slice…` directory, the files directly in it (images, videos, `.index`);
- the slice's label directories (FITC, TRITC…) and their contents.

Cell directories and everything below them are left out, along with
`.DS_Store`, `Thumbs.db` and `._` files. Names in the archive start at the
directory you chose.

## Using it

1. **Directory to archive**: a day directory, or a folder holding days (at
   any depth).
2. Press **Make tar file…** and choose where to save it.
3. The status bar shows progress. **Cancel** stops, and no tar file is left
   behind.
4. When it finishes, the window lists every item in the archive with its
   size, read back from the finished file. Warnings at the top name any day
   or slice without a `.index`.

## Caveats

- The tar file is not compressed. Images rarely compress well.
- The file is written as `<name>.partial` and renamed when complete, so a
  file with the final name is always complete.
- Saving the archive inside the directory being archived is allowed. The
  archive leaves itself out.
