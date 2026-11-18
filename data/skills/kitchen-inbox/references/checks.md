# Checks before saving

The numbers below are the defaults; the design's own values are in `spec.common` (read them with `get_design`).

## Levels (rule GEO-HEIGHTS)

| What | Bottom (`y`) | Top | Common field |
|---|---|---|---|
| base cabinet | 0 | 840 | `baseTop` |
| wall cabinet (`upper`, `upper-glass`) | 1530 | 2280 (height 750) | `upperBottom`, `upperTierSplit` |
| hood cabinet (`upper-hood`) | top − its height (485 → 1795) | 2280 | `upperTierSplit` |
| loft row | 2280 | 2610 | `upperTierSplit`, `cabinetTop` |
| tall cabinet (`tall`, `tall-fridge`) | 0 | 2610 | `cabinetTop` |

Generators already lay new cabinets on these levels. If a preview still shows a GEO-HEIGHTS warning on the new cabinets, fix it with one
`propose_change` of `update` operations and save both.

Open shelves and display cabinets of TV and wine units (`upper-open`, the unit's own heights) follow their layout, not these levels.

## Depths

- Base cabinets: 580–650 mm (rule KITCHEN-DEFAULT-001). A run laid on a floorplan object takes the object's depth; a shallower object
  gives a warning. Mention it in the answer, do not change the object.
- Fridge cabinet: at least the fridge's depth + 30 mm (a 620 mm fridge needs 650).
- Wall cabinets: 300–350 mm.

## Worth a line in the answer (info, not errors)

- Worktop beside the sink (NKBA-10) or the fridge (NKBA-14) narrower than advised.
- Door clear width under 750 mm, or under 850 mm for a wheelchair.
- A sink or hob within 50 mm of the end of the run: offer to swap it with its neighbour in `choices`.

## Not your call (ask)

- A door or window hole outside every size of the type the sentence names.
- A run that does not fit between walls, columns or openings.
- Two readings of the sentence that build different things.
