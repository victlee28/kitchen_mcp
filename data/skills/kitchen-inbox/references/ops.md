# Operations you may write yourself (`propose_change`)

Every operation is previewed, then saved with `apply_change` exactly as previewed. Several go together in
`{"op": "multi", "ops": [...]}` (one revision). Sizes are millimetres.

## Cabinets

```json
{"op": "update", "id": "TT12", "changes": {"y": 1530, "height": 750}}
{"op": "update", "id": "TC3", "changes": {"depth": 650}}
{"op": "remove", "id": "TD5", "closeGap": false}
{"op": "add", "closeGap": false, "module": {"type": "base", "wall": "island", "run": "R2", "fromCorner": 700, "width": 300,
 "y": 0, "height": 840, "depth": 594, "doors": [300]}}
```

- `closeGap: false` keeps the other cabinets where they are; `true` slides them to close the gap.
- A cabinet of a run: `wall: "island"`, `run` = the run id, `fromCorner` = its start along the run.
- Ids are given by the design (`TD`, `TT`, `TC`, `TB`…); never invent one in `update` / `remove`.

## Runs

```json
{"op": "stretch-run", "id": "R2", "end": "end", "delta": 300}
{"op": "move-run", "id": "R2", "changes": {"x": 4590, "z": -125, "yaw": 0}}
{"op": "remove-run", "id": "R4"}
```

## Common levels, materials, handles

```json
{"op": "common", "changes": {"material": {"base": "Laminate vân gỗ sồi sáng", "countertop": "Đá trắng"}}}
```

Material and finish names are the catalog's Vietnamese names; `interpret_edit` finds them from a sentence, prefer it.

## Wall faces

```json
{"op": "surface-material", "surfaces": ["wall_h02#side-b"], "material": "Sơn đỏ"}
```

`material: null` gives the faces back the wall's own finish.

## A material taken from a reference picture

```json
{"op": "multi", "ops": [
 {"op": "material-sample", "name": "Đá marble trắng vân xám", "sample": "smp-0123456789abcdef", "color": "#d9d6d0"},
 {"op": "surface-material", "surfaces": ["wall_011#inside"], "material": "Đá marble trắng vân xám"}]}
```

`sample` and `color` come from `material_sample`. The same name on cabinets: `{"op": "update", "id": "TD1", "changes": {"material": "..."}}`.

## Openings (prefer `opening_command`, which fills the hole, the type and the sill)

```json
{"op": "update-opening", "id": "OP3", "changes": {"width": 900, "height": 2200}}
{"op": "remove-opening", "id": "OP3"}
```

## Templates (`propose_template`)

```json
{"kind": "run-i", "structureId": "STRUCT-furniture_017", "point": {"x": 10872.2, "z": 594.7}, "prompt": "tạo hệ tủ bếp có tủ lạnh"}
{"kind": "replace-system", "system": "furniture_017", "prompt": "thay thế bằng tủ bếp chữ I có tủ lạnh"}
{"kind": "run-line", "a": {"x": 0, "z": 0}, "b": {"x": 2400, "z": 0}, "front": {"x": 1200, "z": 600}, "prompt": "tủ dưới"}
{"kind": "corner", "runA": "R1", "runB": "R2", "width": 900}
```
