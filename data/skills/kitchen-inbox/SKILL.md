---
name: kitchen-inbox
description: Carry out the right-click commands of the kitchen design web app (the command inbox) through the kitchen-design tools. Use when asked to process, do or handle the inbox ("xử lý hộp thư", "thực hiện lệnh trong hộp thư"), or when given one inbox command to carry out.
---

# Kitchen design: the command inbox

The user right-clicks something in the web app (a cabinet, a countertop, a floorplan object, a wall face, a door) and types a sentence,
usually in Vietnamese. Each sentence is a command in the inbox. You carry it out with the kitchen-design tools and answer it; the web app
reloads the design and shows your answer to the user.

## Tool names

Chat agents use the MCP tools; the background worker of the server gets a short list of its own. Same service behind both.

| Step | MCP (chat) | Background worker |
|---|---|---|
| list the queue | `list_menu_commands` | (one command is given to you) |
| take a command | `start_menu_command` | (taken for you) |
| read the design | `get_design` | `get_design` |
| door / window / passage, "lưu vào database" | `opening_command` (pass `place`) | `opening_command` (place is filled in) |
| cabinet edit sentence | `interpret_edit` (`scope_modules`, `surfaces`) | `interpret_edit` (`surfaces` filled in) |
| your own operation | `propose_change` | `propose_change` |
| run of cabinets / replace a system | `propose_template` | `propose_template` |
| save a preview | `apply_change` (`op`, `base_rev`, `expect`) | `apply_change` (`expect`) |
| close the command | `answer_menu_command` | `answer` |
| look at the result | `render_views` | (not available) |
| build the whole floorplan | `auto_place` | (not available) |
| see the reference picture | `get_command_picture` | (in the first message) |
| keep it as a material sample | `material_sample` (design and command ids) | `material_sample` |

## The queue (chat agents)

1. `list_menu_commands` (pending). The answer carries this skill's `version`; read `get_inbox_skill` once per session if you have not.
2. Oldest first: `start_menu_command(id)`. Refused as taken (`command-taken`): skip it, the background worker has it.
3. Carry it out (below), close it, then take the next one. When the list is empty, list again: the user keeps sending while you work.
4. Each preview is made on the design as it is now. Never reuse the `baseRev` written in the command: the commands before it changed the
   design.

## One command

Read `text`, `lang` and `place` (`kind`, `id`, `part`, `point` {x, z} in the room frame, `structureId`, `module`, `modules`, `surfaces`,
`title`). A command with `replyTo` is the user's answer to your earlier question: `context` holds the first sentence and what you asked.

### Choose the tool

- **A floorplan object** (`structureId` = `furniture_*`) and "tạo hệ tủ bếp / tivi / rượu…": `propose_template`
  `{"kind": "run-i", "structureId": "STRUCT-<id>", "point": place.point, "prompt": <the sentence>}`. The object is replaced by the run.
- **A cabinet or countertop of an existing run** and "thay thế bằng… / đổi thành hệ…": the whole system is replaced:
  `propose_template {"kind": "replace-system", "system": <system>, "prompt": <the sentence>}`. The system id is the floorplan object the
  run replaced (`runs[].system`, e.g. `furniture_017`). Find the run from the clicked module (`module`, `modules`) or from
  `structureId`; do not compare `place.point` with `runs[].x/z` (room frame vs kitchen frame).
- **A door, window or passage** (a floorplan opening, a wall, an existing `OPn`), and "lưu vào database / lưu cửa này": `opening_command`
  with `place` = `{point, structureId, module}` of the command. A right click on a door or window the design placed gives
  `place.kind` = `opening`, `place.id` = `OPn` and a `point` inside it: a new type or size goes through `opening_command` with that point;
  a move or a removal through `propose_change` (`move-opening`, `update-opening`, `remove-opening` with `id` = `OPn`).
- **Cabinet changes** (width, doors, handles, colours, worktop, moldings, remove): `interpret_edit`, `scope_modules` = `place.modules`
  when it is there (every cabinet the user selected; change them all, not only `place.id`), else the clicked module. Check that the
  preview's `affectedModules` covers the whole selection; when a cabinet of it cannot take the change, say which in the answer.
- **An appliance** (`place.kind` = `appliance`, `place.id` = `TBn`): another model in its place. `propose_template`
  `{"kind": "replace-appliance", "id": <TBn>, "prompt": <the sentence>}` lists the models (`status: "choose-model"`, those that fit
  first); preview the best one with `{"kind": "replace-appliance", "id": <TBn>, "model": <id>}`. A TV and a wall painting
  ("thay bằng bức tranh") take each other's place.
- **Picked wall faces** (`place.surfaces`): `interpret_edit` with `surfaces` = `place.surfaces`, or `propose_change`
  `{"op": "surface-material", "surfaces": [...], "material": "..."}`. Never change the material of every wall when faces were picked.
  A face `<wall>#reveal-<opening>` is the inside of that opening's hole (jambs, head, sill): it takes its own finish like any face.
- **A reference picture sent with the sentence** (the record has `attachment`) and a sentence such as
  "ốp tường bằng vật liệu trong ảnh tham chiếu" (clad, paint, tile, a material or colour "in the picture"): take the material from it. Look at it (`get_command_picture`), keep it (`material_sample` → `sample`, `color`), name
  the material in the catalog's Vietnamese words for what you see (e.g. "Đá marble trắng vân xám", "Gỗ óc chó", "Gạch thẻ xanh rêu"), and
  preview one `{"op": "multi"}`: `{"op": "material-sample", "name", "sample", "color"}` + the operation that puts that name on the
  selection (`surface-material` for `place.surfaces`, `update` `material` for each of `place.modules` / the clicked cabinet, `common`
  for a whole tier or the worktop). The 3D view lays the picture on those surfaces. If the picture shows several materials, or it is not
  clear which surface the sentence means, ask (`question`) with the choices.
- **"Tự động đặt" / build what the floorplan draws**: `auto_place` (one revision; it reports what it skipped).
- Anything else you can write as an operation: `propose_change`. Operation shapes: `references/ops.md`.

### Check the preview before saving

Read `proposal.diff`, `proposal.validation.introduced` and the summary. The checklist with the numbers is `references/checks.md`.

- The change does only what the sentence asks: nothing removed, replaced or resized that it does not name.
- No new GEO-HEIGHTS warning: wall cabinets, hood cabinet and tall cabinets sit on the design's common levels.
- A fridge cabinet is deeper than its fridge; a sink or hob is not jammed against the end of the run.
- No error is introduced (`introducesErrors` is false).

Fix what you can with one more preview (`propose_change` with `update` operations) and save it in the same command. If the fix is a
choice the user must make, do not guess: ask (below).

### Save

`apply_change` with exactly the previewed operation, its `baseRev` and `expect` = its `opHash`. Anything else is refused. Several saves in
one command are fine; the menu's undo goes back to the revision before the first one.

### Answer

- **done**: `revision` = the revision after your last save, `from_rev` = the revision before your first save (MCP). `reply` = one line in
  the command's language: what was built or changed (run id, length, the main parts) and the one thing the user should know (a warning,
  a tight space). When you had to choose between reasonable ways, put the others in `choices` (2–4 short items).
- **question**: save nothing. `reply` = the question; `choices` = 2–4 short answers. Ask when a tool returns `ask` or `clarify` (a door
  wider than the type allows: offer the fitting types, e.g. sliding with 2 or 4 leaves), the space is too shallow, an appliance does not
  fit, the change brings an error, or the sentence does not say which cabinet or which size. Never invent sizes.
- **failed**: it cannot be done; `reply` = why, in the command's language.

### Look (chat agents)

After saving, `render_views` the run's view (`run-<id>`, `run-<id>-oblique`) or the opening's view, and the `plan`, and look at them before
you report.

## Never

- Touch a design the command is not about. Never edit the design `mau-du-lieu-4dec31`.
- Save an operation you did not preview, or one the preview showed to break something.
- Leave a command taken and unanswered.
