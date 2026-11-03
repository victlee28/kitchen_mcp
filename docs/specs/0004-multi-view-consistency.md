# Consistent images across views

Status: planned

## Goal

After the user accepts a change in one view, the other views do not silently keep an image of the old design.

## Problem

The render key ignores materials, so after accepting a material change in view A at revision 2, view B at revision 2 can still use an image accepted at revision 1 as its base image.

## Requirements

- R1. An image has an appearance key made of materials and geometry; a base image is usable only when its appearance key equals that of the design revision.
- R2. When a view's accepted change alters the appearance key, every other view's accepted image is marked stale.
- R3. A stale view offers an action that applies the same changes to the remaining views as jobs.
- R4. A first photographic image (`gen0`) of a view can take an accepted image from another view as a style reference.
- R5. Staleness is shown in the web editor and returned by the API.
- R6. Existing renders and jobs keep working; stale marking never deletes files.

## Out of scope

- Recognising a design from a photo.
