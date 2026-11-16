# Workshop guide: the catalog

The catalog is the data the kitchen designer works from: cabinet types, layout templates, appliances, materials, rules. Open it from the
editor with **📚 Catalog** (`catalog.html`). Pick your role at the top (**workshop** or **user**); the server may fix the role
(`KITCHEN_FIXED_ROLE`).

## What you can change

| Kind | What it decides | Who edits |
|---|---|---|
| Cabinet types | storey, size formulas, front sections (doors, drawers, glass), prompt words | workshop |
| Kitchen layout templates | I / L / U and your own: walls, the steps that fill them (corner base, base run, corner shelf, upper run) | workshop, user |
| Layout rules | how a run is split (sink near the fridge, hood above the cooktop, widths) | workshop |
| TV unit layouts | panels and formulas of a TV wall | workshop, user |
| Default sizes and finishes | sizes of a new design; finish names drawn where a design names none | workshop |
| Command dictionary | the words the editor understands ("make it wider", colours, tile patterns) | workshop |
| Appliances, materials, styles, palettes, regions, knowledge… | as named | see the page |

Locked kinds (developer rules) are shown but not editable.

## Editing an item

1. Pick a kind, then an item, then **Edit** (or **New**). Formulas use the variables listed beside the field (`width`, `height`, `depth`…);
   a mistake is shown under the field with its position.
2. **Preview** draws the item (cabinet type, layout template) without saving.
3. **Save**. The server checks the item can be compiled; if it cannot, nothing is saved and the error says why.
4. **History** lists earlier versions of the item; **Compare** shows the fields that differ from the builtin item.

## Saving a kitchen as a layout template

In the editor, select a cabinet of the system to keep and press **💾 Save system as template**, then give it a name. The system goes into
the catalog as a layout template of your layer: its corner cabinet, its base and tall cabinets in order (a `cabinets` step), its wall
cabinets and its corner shelf. The run with most corners becomes the back wall, runs square to it the side walls. Plain base cabinets
stretch (`fill`) so the same kitchen fits other wall lengths; sinks, cooktops, fridges and other cabinets keep their widths. Use it from
**New design → Shape**, or type "… theo mẫu <name>" when you replace a system (a one-wall template is laid along the run). Cabinets the
template cannot hold (an island, a run at an angle) are listed when it is saved.

## Room door and window types

Kind `opening-type` (workshop and users) decides how a room opening looks and is measured. A design places an opening by **axes**: its
centre on a wall axis (the centreline of a whole straight wall), its width the **hole in the wall**, vertical / horizontal axes dividing the
hole into bays, each leaf covering a block of bays (see `docs/adr/0005-opening-contract.md`).

| Field | Meaning |
|---|---|
| `kind`, `operation` | door / window / passage; the main way it opens |
| `axesRatio` | middle vertical axes as fractions of the hole width (`[0.5]` an even pair, `[0.75]` a 900 + 300 pair in a 1200 hole) |
| `hAxesFromSill`, `hAxesRatio` | horizontal axes (transom, fixed top light): mm above the sill, or fractions of the height |
| `leaves` | the leaves: from which axis to which (`cols`, `rows`; negative counts from the last), how it opens, the axis its hinge sits on, in / out seen from the kitchen, the main leaf |
| `frameFace`, `frameDepth`, `casing`, `transom`, `threshold`, `stop` | frame: face width, depth (empty = the wall's thickness), casing, transom bar, threshold, stop |
| `leafThickness`, `gap`, `minLeaf`, `openingAngle` | leaves: thickness, gap, narrowest leaf, opening angle (the sweep) |
| `defaultHeight`, `defaultSill` | hole height and sill when none is given (also the height an imported floorplan opening gets when the drawing has none) |
| `defaultWidth`, `minWidth`, `maxWidth` | hole width of a new opening when the command gives none; the type's range: a width outside it is asked about before the opening is made ("keep the size" sets `oversize` on the opening, "use the type's size" brings it into the range) |
| `sizes` | standard **wall-hole** sizes per country (`widths`, `heights`): a size recognized from a photo snaps to the nearest one within 30 mm |
| `sources` | where each country's sizes come from (kind of source, link, note) |

The clear width is worked out: the main leaf's bay less the frame at the hole's edges less (leaf thickness + stop) for a turning leaf.
**Preview** draws the type's front view at each standard size of the country (the page's `?country=` parameter) with its clear width, or
says why the leaves do not tile the bays. Countries that size doors by the leaf (US, GB, AU) are converted to hole sizes as `sources` says.

## Handles and hinges

Kinds `handle` and `hinge` (workshop and users) list the hardware a workshop offers: name, brand, product code, sizes, finish and price
(`price.amount` + `price.currency`, e.g. `VND`). A handle named in a command ("đổi tay nắm thành tay thanh inox 320") brings its kind,
length and finish to the cabinets, and the design records which catalog handle it is (`handle.item`); changing the handle by hand
afterwards forgets the item. Hinges are listed only for now; designs do not use them yet.

## What happens to existing designs

A design keeps the catalog it was saved with. When the catalog changes, the editor shows a notice (**Catalog updated**) on designs that
use a changed item; **Update** applies the new catalog as a new revision (undo with revert). Nothing changes silently.

## Moving a catalog between machines

**Export** saves one kind; **Export everything** saves the whole workshop catalog as one file (`kitchen-catalog-bundle/1`). **Import**
accepts either; every item is checked as if it were saved by hand.
