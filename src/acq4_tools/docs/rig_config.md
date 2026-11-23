# Acq4 Rig Config

Edit and check acq4's `devices.cfg`, the file that describes the hardware of a
rig. The tool shows the devices as forms, draws the DAQ wiring, lists every DAQ
line, shows the optomechanical tree, and compares each setting name with the
acq4 source.

Opening, saving and the Checks list work as described in
[Working with config files](config_files.md).

## Before you start

- Choose the **acq4 directory**. The tool reads the device drivers in
  `acq4/devices` to learn which drivers exist and which keys each one reads. It
  reads the source without running it, so the hardware libraries are not
  needed. Without the directory the tool still works, but it cannot check names.
- Open `devices.cfg`, usually in acq4's `config` folder.

## Devices tab

The list on the left shows every device in file order. Commented-out devices
are gray. The **Lines** column counts the DAQ lines each device uses.

| Button | What it does |
| --- | --- |
| **Disable / Enable** | Disable comments the device out of the file, so acq4 skips it but it stays for later. Enable brings a commented-out device back. If a device of the same name is active, Enable offers to swap them. |
| **Add…** | Add a device. Choose the driver, then start blank or from one of acq4's example devices, and give it a name. |
| **Remove** | Delete the device from the file. Use Disable to keep it. Revert undoes a removal until you save. |
| **Up / Down** | Move the device in the file. acq4 creates devices in file order, so a device must come after its parent and its DAQ. |

The form on the right edits the selected active device:

- **Device name**: rename the device. References to it elsewhere in this file
  (parentDevice, DAQ names and similar) are renamed too.
- The settings tree has drop-downs where the choices are known: driver,
  parent device, DAQ, channel type (ai, ao, di, do), mode (rse, nrse, diff),
  free DAQ lines, and True/False. Other values are typed as expressions.
- **In acq4 source** shows whether the driver reads each key.
- **Add Setting…** adds a key to the device, or to the selected section. The
  list offers the keys the driver reads.
- **Add DAQ Channel…** adds an analog-input channel on the first DAQ's first
  free line. Change its type and line afterwards.
- **Remove Setting** removes the selected setting or section.

## DAQ Boards tab

Choose the National Instruments board model for each DAQ. This tells the
tool which lines exist. Choose **Custom** to enter the counts yourself.
Where one DAQ device has several boards, each appears as `DAQ/Dev2`.

The choice is stored as a comment line at the end of `devices.cfg`, which acq4
ignores:

```
## acq4_tools board DAQ: 6259 ai=32 ao=4 port0=32 pfi=16
```

> **Check the counts.** The line counts for the listed models were entered
> from memory, not from datasheets. Compare them with your board's
> datasheet, and use Custom if they differ.

## Line Map tab

Every line on each board, with its status:

| Status | Meaning |
| --- | --- |
| free | No device uses it. |
| in use | One active device uses it. |
| shared | Two or more active devices use it at once (red). |
| alternates | Several devices use it, but they are marked as never used together. |
| not on board | A device names a line the chosen board does not have (red). |

Commented-out devices are taken as alternates and never conflict. Two active
devices on one line are reported until you select the line and press
**Mark as Alternates**. **Clear Mark** removes the mark. Marks are stored as a
comment line:

```
## acq4_tools alternates: Shutter | LED
```

Terminal names are resolved: `/Dev1/line30`, `/Dev1/port0/line30` and the
corresponding PFI name all refer to one physical terminal. A differential
input also uses its negative partner line.

## Wiring Diagram tab

Shows each board, with every device wired to the terminals it uses. Lines are
colored by signal type. The colors avoid green and stay distinguishable for
common forms of color blindness:

| Signal | Color |
| --- | --- |
| Analog in (ai) | dark blue |
| Analog out (ao) | teal |
| Digital in (di) | purple |
| Digital out (do) | magenta |
| Trigger | near black |
| Problem | red |

Where several devices share a terminal, each gets its own line style. Each
port is labeled with its DAQ terminal.

- **Include commented-out devices** also draws the alternates, in gray.
- **Fit** zooms to the whole diagram. Drag to pan and scroll to zoom.
- **Export…** saves the diagram as a one-page PDF or a PNG image.

## Optomechanics tab

The tree of parent devices, starting from global coordinates. Each row shows
the device's driver, its position in the file, and its transform. Microscope
objectives are listed under their scope.

acq4 accepts only the transform keys `pos`, `scale`, `angle` and `axis`.
The acq4 documentation mentions `position`, but acq4 rejects it with an error.

## Parameters tab

Every key of every device, and whether the driver reads it in the acq4
source. A key counts as read if its name appears as text anywhere in the
driver's folder, so the check is lenient. Only keys found nowhere are reported.

## What the checks report

- Lines that are not on the chosen board, and channel types that do not fit
  their terminal.
- Lines shared by active devices, including through terminal aliases and
  differential pairs.
- A device that comes before its parent or its DAQ in the file. acq4 leaves
  such a device unconnected and prints only a message.
- Loops of parent devices, and parents that are not optomechanical.
- Transform keys acq4 rejects.
- Unknown drivers and keys the driver never reads.

## Caveats

- Renaming a device does not change `default.cfg` or references inside
  commented-out devices. Check `default.cfg` for modules that name the device.
- The checks compare the file with the acq4 source. They cannot check
  the hardware itself. Load the saved file in acq4 and test the rig before an
  experiment.
- acq4 only finds a line conflict when a task runs. These checks find it when
  you edit.
