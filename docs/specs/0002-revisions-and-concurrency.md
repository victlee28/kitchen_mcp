# Design revisions and concurrent edits

Status: implemented

## Goal

A design's history is a trustworthy, append-only series of snapshots, and two clients can never silently overwrite each other.

## Requirements

- R1. Creating a design stores revision 1.
- R2. Every change to a design is an operation applied to the latest specification and saved as a new revision with the operation and its source.
- R3. A save names the revision it was based on (`base_rev`); if it is no longer the latest, the save fails with a conflict and nothing is written.
- R4. Revisions are never edited or deleted.
- R5. Reverting a design to an older revision creates a new revision holding the older specification.
- R6. An operation that would produce an invalid specification is rejected and no revision is created.
- R7. Generated metadata and render paths carry the same design id and revision number.
- R8. Both the MCP server and the HTTP server reach this behaviour through `KitchenService`; neither implements it separately.
