# 0005. Room openings are located by their own axes

Status: accepted (13/11/2026). Replaces the first version of this record (12/11/2026: `host` + `offset`, `hinge: start|end`,
`swing: in|out`).

## Context

Room doors, windows and passages come from three places: an audited floorplan, a recognition draft from a photo, and the user. Each
measured them its own way (an offset along one wall face, a distance from the image's left edge, a click), so the same door ended up
with different numbers and the checks, the drawing and the editor disagreed. Drawings in Vietnam place openings on the wall's
centreline, from grid axes, and recognition sees the edges and middles of an opening, not one offset.

## Decision

- **Wall axis.** Every opening sits on a wall axis: the centreline of a whole straight wall (collinear segments joined). An end that
  meets another wall is the crossing of the two centrelines; the axis runs towards +x (or +z) so its start never depends on how the
  outline was drawn. A wall that runs on straight past the room's corner, into another room, carries the axis with it (the
  floorplan's collinear wall elements: touching, or apart by at most 2400 mm with an opening in the gap or the same thickness).
  Floorplan axes are kept in the room frame with a fingerprint (start, direction, length): a later floorplan change marks the
  opening (`opening-orphaned`) instead of moving it, except when the axis only grew along the same centreline (the old axis lies
  within the new one): then the stored centre moves with the start and the opening keeps its place (`opening-axis-extended`).
  Distances "from the corner" are from the room's inner corners, wherever the axis starts. Without a floorplan the back, right and
  left walls start at the back-right corner, because their lengths may follow the cabinets.
- **Walls of other rooms.** The floorplan's wall elements that no room axis holds get axes of their own (after the room's, id
  `WA-<first element>`, no kitchen side), so a door can be put in the wall of a neighbouring room, or in the hole a floorplan
  opening element leaves there. The three.js export carries such openings on a hidden wall record of their own (`WALL-<axis id>`).
- **Commands.** A right-click sentence ("tạo cửa đi ở vị trí này", "thay bằng cửa sổ 1200x1400", "đặt cửa nhôm đen") places the type
  it names (the catalog's, the user's saved ones included) or the kind's default type, at the type's `defaultWidth` /
  `defaultHeight`; on an opening it changes that one, in a floorplan opening element's hole it takes the hole's place and width
  (`kitchen/openings/command.py`). "lưu vào database" saves the clicked opening as an `opening-type` item (its sizes as the
  defaults) or the clicked cabinet system as a `layout-template`.
- **Own axes.** An opening's main axis is its centre (`center`, mm along the wall axis). `width` is always the hole in the wall,
  `clearWidth` always the clear passage. The outer vertical axes are the hole's edges, the outer horizontal ones the sill and head;
  `axes` / `hAxes` hold the middle ones (`null`: the type's template, rescaled with the hole).
- **Leaves.** Leaves tile the bays between the axes. A hinge sits on one axis of the leaf's edge; `side` (`+` / `-` of the axis
  normal) says where it opens. In / out is derived, never stored, so rebinding the kitchen to another room cannot flip a door.
- **Heights** are above the finished floor of the building level (`spec.level`); absolute heights appear only in exports.
- **Types** (catalog kind `opening-type`) hold the template (axis ratios, horizontal axes, leaves), the frame, casing, stop, transom,
  leaf thickness, gap, minimum leaf, opening angle and the standard hole sizes per country. Sizes are always hole sizes.
- **One normalization** (`kitchen/openings/normalize.py`) for the three sources. Only recognition sizes snap to the country's
  standard holes (tolerance `defaults.openings.snapTolerance`, the centre kept); recognized edges are trim edges unless said
  otherwise; unseen hinges and sides go to `unsure`.
- **Storage.** The design's own openings, and records that override or remove (`removed: true`) a floorplan opening
  (`sourceElement`), live in `KitchenSpec.openings`, stored normalized. Floorplan data is never changed. `openings.effective` is the
  only reader. Frames, leaves and sweeps are derived (`openings.shape`), never stored.
- A floorplan opening the design leaves alone keeps its drawn shape and its checks (the images already approved stay valid).
- Records saved in the first form are read and upgraded on reading; saved revisions are not rewritten.
- No separate process: the core package `kitchen/openings/` holds the contract, wall axes, frame changes, types, normalization,
  floorplan reading, the effective list, shapes and operations; recognition stays an adapter that returns drafts in this contract.

## Consequences

- `schemas/opening.schema.json` is generated from `kitchen.spec.Opening`; a test checks it against the core dataclass.
- Operations: `add-opening`, `update-opening`, `move-opening`, `remove-opening`, `reset-opening`, `rehost-opening`.
- The three.js export carries, for each opening the design places, its frame and leaves as boxes the browser draws.
- Later: the "Doors & windows" panel, materials and masks for frames and leaves, recognition of openings (plan, slices 2-4).
