# Retrieve .index Files

Compare a local copy of acq4 data with the same data on a remote computer
(for example, a lab server) and upload the `.index` files missing there.
Use it when data reached the server without their `.index` files.

**Existing remote files are never overwritten.** Only missing files are sent,
and each is checked again just before it is uploaded.

## Before you start

The tool connects over SSH (SFTP) and accepts only hosts already in your
`known_hosts` file. Connect once from a terminal and accept the host key:

```
ssh username@server.example.edu
```

## Using it

1. **Local directory**: a day directory, or a folder holding day directories.
2. **Remote host**, **Port** (usually 22), **User name** and **Password**.
   The password is used only while connected and is never saved.
3. **Remote directory**: the directory on the remote computer that holds the
   same day directories. A local day `…/2024.03.05_000` is matched with
   `<remote directory>/2024.03.05_000`.
4. Press **List day directories**. Untick any days to leave out.
5. Press **Check remote**. Every `.index` in the ticked days is looked up on
   the remote computer and marked *present* or *missing*. Nothing is changed.
6. Press **Upload missing…** and confirm. The Status column shows *uploaded*,
   *present* (it appeared since the check) or *failed* for each file.

**Cancel** stops after the current file.

## Caveats

- Remote directories are not created. A `.index` whose directory does not
  exist on the remote computer fails to upload.
- Remote paths always use `/`, whatever the local system.
- Only password log-in is offered. Key-based log-in is not.
- If the host is not in `known_hosts`, the tool says so and does not connect.
