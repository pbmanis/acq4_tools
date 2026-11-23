# Find Empty .index

Find `.index` files that are empty or nearly empty. A zero-length `.index`
usually means a copy or transfer stopped part way. acq4 cannot read the
directory it describes, and the directory's times and metadata are lost.

The tool only reads the data.

## Using it

1. **Directory to scan**: any directory. Everything below it is searched.
2. **Report files smaller than**: the size limit in bytes. The default, 10,
   catches empty files. A usable `.index` is always larger.
3. Press **Scan**. The status bar counts directories as it goes. **Cancel**
   stops it.
4. The table lists each small file, its size, and the directory's level
   (day, slice, cell, protocol run, or protocol/other), judged from its name.
5. **Save list…** writes the list as a tab-separated text file.

## What to do with the results

- Look for a good copy of the same `.index` elsewhere, such as the
  acquisition computer or a backup. [Retrieve .index Files](index_transfer.md)
  can upload missing `.index` files from a local copy to a server.
- Do not delete an empty `.index` before you have a replacement.

## Caveats

- Hidden directories (names starting with `.`) are skipped.
- Large network volumes can take a long time. Scan one year or one day at a
  time if needed.
