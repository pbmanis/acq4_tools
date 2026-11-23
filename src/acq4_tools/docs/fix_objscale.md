# Objective Scale

Correct the objective recorded for an image or video when acq4 was told the
wrong objective at the time. acq4 sets the image scale (meters per pixel) from
the objective, so a wrong objective gives every measurement in that image the
wrong size. This tool rewrites the objective and the scale in the `.index` file.

**This tool changes data.** Apply changes only when you are sure of the
objective that was used, and keep a backup of the directory.

## Window layout

- **Params** (left): the controls, and below them a browser for the whole
  day directory showing only the branches that hold images or videos.
- **Image + Spectrum**: the image on a grid in µm or mm, its intensity
  histogram (drag the handles to set the levels), and its 2-D amplitude
  spectrum. A video has a frame slider below.
- **Reporting (.index)**: the `.index` entries for every image and video in
  the directory, with the file shown highlighted.
- **Changes**: the result of a preview or of applying changes.
- **Help**: this page.

## Correcting a file

1. **Set Directory/Protocol**: choose the directory holding the images
   (`image_NNN.tif`) or videos (`video_NNN.ma`) and their `.index`, usually a
   slice or a label directory. **Recent** and **Reload Last Protocol** reopen
   earlier directories.
2. Choose the image or video in **File**, or click it in the day browser.
   The banner above the image shows its recorded objective, binning and scale.
3. Check **Camera**. Its pixel size is used to calculate the scale. **Cine Scale** is
   the camera coupler (1×, 0.5×…).
4. **Original Objective** shows the recorded objective. Set **New Objective**
   to the objective actually used.
5. Press **View proposed changes**. The Changes tab shows the old and new
   scale, and the image is redrawn at the new scale. The grid should now
   match a known feature size. Nothing is written yet.
6. Press **Apply changes** to write the new objective and scale into the
   `.index`. A note is added to the entry recording the change, the date, and
   your user name.

The new scale is *binning × camera pixel size ÷ cine scale ÷ magnification*,
in both the `transform` and `deviceTransform` of the entry.

## The objective and camera table

Objectives, cameras (pixel sizes) and cine scales come from
`fix_objective_data.cfg` in your settings folder (see
[Where settings are kept](index.md)). It is copied from the packaged defaults
the first time the tool opens. Edit that copy to match your rig, then reopen
the tool.

## Caveats

- **Changes apply to one file at a time**: the one shown in File. The Images
  and Videos fields are left over from an older version and are not used.
- **A preview changes the scale held in memory** for the file shown. If you
  preview a file and decide not to change it, click a file of that directory
  in the day browser before applying a change to another file. This reads the
  `.index` again. Otherwise the previewed scale is written too.
- There is no undo. To reverse a change, apply the original objective again.
  The scale is recalculated, but the note records the second change.
- Cine Scale is currently fixed at its first value in the table.
- Only the first 100 frames of a video are loaded for display. Videos are
  rotated on screen to match the still images. The file is not changed.
- **Reload** does nothing yet.
- The scale depends on the camera. Choose the camera the data were taken with.
