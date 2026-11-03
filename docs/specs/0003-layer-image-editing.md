# Layer-based image editing

Status: implemented

## Goal

Change the material or shape of selected parts in a view's photographic image while leaving every other pixel exactly as it was, and only change the design when the user accepts the result.

## Layers and masks

- R1. Each render of a view produces an instance image, a list of instances, an albedo image and a manifest with the render key.
- R2. A layer is a part, or a group: all front sections of a module, all parts of a module or molding, or all parts of one role.
- R3. The mask of a layer is the set of pixels whose instance belongs to it. Two doors of one module give two separate masks.
- R4. Handles are real parts, so they appear in lines, depth, mask and instance images; their material is set in the common settings and applies to every handle.

## Jobs

- R5. A job targets one view and carries one to eight tasks; two tasks may not touch the same part, and the error names the part.
- R6. A job is created against a base revision and the view's render key; a mismatch is rejected clearly.
- R7. Job kinds are `gen0`, `edit` and `geometry_edit`. Modes for `edit` are `quick` (image only) and `design` (also changes the design).
- R8. In `design` mode the design operation is applied only on accept, never at creation. If the design has changed since the job was created, accept reports a conflict.
- R9. A backend failure or a rejected result leaves the design unchanged.
- R10. When a job with several design changes is accepted, all of them become one revision.
- R11. Job statuses follow: created, `awaiting-send` or `running`, `awaiting-result`, `needs-review`, then `accepted` or `rejected`; failures are `error:<code>`.

## Compositing and checks

- R12. The model receives the mask dilated by 12 px. The composite uses the target mask only, with a 2 px soft edge inside it, except for thin parts such as handles which use a hard edge.
- R13. Every pixel outside the mask in the final image equals the base image, and the job report states this.
- R14. The report records, for each task, whether the pixels inside the mask changed; if some tasks changed and some did not, the job still reaches `needs-review` with a warning.
- R15. A job request that Gemini or a package will receive passes the request check (truncated file, broken base64, missing image, non-breaking space) before it can be sent.

## Backends

- R16. `recolor` changes the colour inside the mask while keeping light and dark, with no AI.
- R17. `gemini` is called once per job with the marked base image, the mask (a colour mask for several tasks), and instructions that name each region and its position.
- R18. `comfyui` runs tasks one after another with the workflow chosen by the job; `job-package` exports files for running elsewhere.
- R19. The marked base image has numbered coloured outlines 14 px from each region that never overlap a region; the instruction asks for them to be removed from the result.

## Geometry edit

- R20. A geometry edit applies one or more of: remove module, add module, door style, handle style, any operation, to a copy of the design.
- R21. It renders again with the same camera as the base image; if the default view would move, the old camera is pinned in the design by a `set-views` operation.
- R22. Its mask is where the instance, albedo or lines differ between the old and new render.
- R23. Accepting writes a new revision, and the accepted image becomes the base image of that revision.

## Known limits

- Door style is not drawn in the raster render, so the front of the module is always redrawn.
- Hand-drawn masks for objects not in the model are not supported.
