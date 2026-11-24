# Specification: Room Editor for an Atari 8-bit Game (PySide6)

Document version: 1.1

## 1. Purpose and scope

A desktop application written in Python with a PySide6 GUI, used to:

1. design the game's rooms ("komnaty") and the connections between them,
2. define object groups (charset + palette) and objects ("stamps" made of characters),
3. place objects in rooms (each room is 40×20 characters in ANTIC 4 text mode) with layered z-order support,
4. save and load the whole project to a `.yaml` file with compact lossless compression of repeated patterns.

**Out of scope:** export to a binary / MADS format (done by separate game scripts), the game's status panel, game emulation, a charset editor (`.fnt` files are only loaded).

## 2. Glossary

| Term | Meaning |
|---|---|
| Room | A rectangle of fixed size 40×20 characters (ANTIC 4 mode). Has a name and an ID (1–255). Stores an ordered list of object instances, not raw characters. |
| Room group | A set of rooms linked by adjacency on the canvas (computed automatically). |
| Charset | A `.fnt` file, 1024 bytes. |
| Object group | A name + one charset + one palette. Contains objects. |
| Object | A named "stamp": a grid of one or more characters. Has an ID (1–255), belongs to one group, has zero or more tags and an optional `non-blockable` flag. |
| Object instance | A placement of an object in a room: (object ID, x, y). |
| Tag | A globally defined label (e.g. `ladder`, `teleport`) assigned to objects. |
| Teleport | A bidirectional link between two points in rooms, independent of adjacency. |

## 3. Functional requirements

### 3.1 Rooms and connections (canvas)

- **F-1.** A canvas with a grid. Each room occupies one grid cell (cell size = room size). Rooms can be freely added, moved and deleted. While dragging, a room **snaps to the grid**, and therefore to its neighbours.
- **F-2.** Each room has a **name** (unique in the project) and a **numeric ID 1–255** (unique, assigned automatically as the lowest free value; the user may change it). The project cannot exceed 255 rooms.
- **F-3.** Two rooms whose edges touch (left/right/top/bottom) are connected. Each room edge has **at most one neighbour**; two rooms cannot occupy the same grid cell.
- **F-4.** **Passage condition:** the hero can cross an edge only where there is free space both in the room he leaves and in the room he enters. **Free space = a cell with no blocking object** (i.e. only blockable objects — `non-blockable = false` — block on cells with code ≠ 0; `non-blockable` objects and code `0` cells never block, regardless of whether they overlap). One-way passages do not exist: if a room has an "exit" but no room is attached on the other side, the game will not let the hero leave. The editor only **visualizes** potential passages (see 3.6); the game implements the logic.
- **F-5.** **Room groups** are computed automatically from adjacency (connected components). There may be any number of groups on the canvas, including single-room groups. Groups are not stored in the file (they are computed on load). The editor highlights them visually (e.g. with a frame color) and allows moving a whole group together.
- **F-6.** **Teleports:** a bidirectional link between two endpoints. Each endpoint = (room ID, x, y) within the 40×20 room. Endpoints may lie in rooms of different groups, in rooms of the same group, or in the same room (a teleport from a room to itself). Visualization: a line with arrows at both ends between rooms on the canvas.
- **F-7.** **Start room and hero start position:** exactly one per project (room ID + x, y). Marked on the canvas with an icon.

### 3.2 Charsets and palettes

- **F-8.** Loading a `.fnt` file for an object group. Validation: size exactly 1024 bytes (128 characters × 8 bytes). Codes 0–127 use `COLPF2` for pixel pair `11`; codes 128–255 use the same glyph shapes with `COLPF2` swapped for `COLPF3`.
- **F-9.** Character rendering mode: **ANTIC 4** (8 rows × 4 pixels of 2 bits each, 2:1 pixel aspect ratio, full room 160×160 logical pixels). Mapping: `00` → `COLBK`, `01` → `COLPF0`, `10` → `COLPF1`, `11` → `COLPF2` (0–127) or `COLPF3` (128–255).
- **F-10.** Each object group has a **palette**: `COLBK` (default 0), `COLPF0`, `COLPF1`, `COLPF2`, `COLPF3`. Defaults are set globally in application settings and copied to new groups.
- **F-11.** Colors are chosen from the **Atari PAL palette** (256 values; bit 0 ignored) backed by `room_editor/data/pal_palette.json`.

### 3.3 Objects, object groups and tags

- **F-12.** **Object group:** a unique name, one `.fnt` charset, one palette.
- **F-13.** **Object:** unique name, unique ID 1–255, one group, grid `w × h` with `1 <= w * h <= 255`, zero or more tags, and a `non-blockable` flag (off by default). Total limit: 255 objects per project.
- **F-14.** **Object editor:** interactive `w × h` character grid + 256-entry charset picker. Code `0` in an object cell means "transparent / empty cell": it is not drawn, never covers characters beneath it, does not participate in overlap checks, and does not block passage.
- **F-15.** **Tags:** global tag list (add, rename, delete with confirmation).

### 3.4 Room layout, draw order, and overlapping

- **F-16.** A room is a grid of **40×20 cells** storing an **ordered list of object instances** `(object ID, x, y)`. For `non-blockable` instances, list order is their **z-order** (later in the list = drawn later = on top). Newly placed non-blockable instances are appended at the top of the z-order.
- **F-17.** **Object group per row:** each of the 20 rows has an assigned object group (DLI charset + palette).
- **F-18.** **Faithful rendering & draw order:** the room is composed into a 40×20 grid in two layers before rendering each cell with its row's charset and palette:
  1. **Layer 1 (background / non-blockable):** all `non-blockable` instances drawn in z-order (earlier → later).
  2. **Layer 2 (foreground / blockable):** all blockable instances drawn after (on top of) Layer 1. Because blockable instances never overlap each other, their relative order does not affect appearance.
  3. **Transparency:** character code `0` in any object cell is transparent and never overwrites a non-zero character underneath, in either layer.
- **F-19.** **Editing tools:** Stamp (`S`), Eraser (`E` — removes the topmost visible instance with a non-zero cell under the cursor), Fill (`F`), Line (`L`), Rectangle (`R`), Select (`V` — click selects topmost visible instance, drag marquee selects intersecting instances) with Copy/Cut/Paste/Delete, Undo/Redo, Grid (`G`), Zoom (`Ctrl+wheel`), and **Z-order arrangement** for non-blockable instances (Bring to Front `Ctrl+Shift+]`, Move Up `Ctrl+]`, Move Down `Ctrl+[`, Send to Back `Ctrl+Shift+[`, also available via right-click context menu).
- **F-20.** Selection panel: object list with previews, filterable by group and tag; row-group gutter supporting single-row and Shift-range assignment.
- **F-21.** **Overlapping rules:**
  - **Blockable + blockable:** MUST NOT overlap on cells with code ≠ 0 and cannot extend beyond 40×20. Touching or overlapping solely through code `0` cells is permitted.
  - **Non-blockable:** MAY overlap other non-blockable instances and MAY lie under/over blockable instances (checked only against 40×20 bounds).
  - **Changing `non-blockable` from ON to OFF:** if existing room placements of that object would create blockable-vs-blockable overlaps on non-zero cells, the editor warns, lists the conflicting rooms and coordinates, and refuses the flag change until conflicts are resolved.
  - Editing an object updates all rooms immediately; deleting a used object requires confirmation and removes its instances.

### 3.5 Saving and loading the project (YAML)

- **F-22.** Single `.yaml` file with integer `version: 1`. Unknown versions fail with a clear error.
- **F-23.** Charsets are linked by relative POSIX paths; missing `.fnt` files trigger a warning and replacement prompt on load.
- **F-24.** Saved data: `settings`, `tags`, `object_groups`, `objects`, `rooms`, `teleports`, `start`. Room groups are computed on load and not saved.
- **F-25.** **Two-layer instance compression (lossless, deterministic):**
  - **Blockable instances** are written **first**, compressed via the greedy largest-rectangle algorithm (`repeat-x`, `repeat-y`, `repeat-xy` with step `(w, h)`; tie-break: largest area, smallest `y`, smallest `x`, greater width), sorted by `(y, x, object)`.
  - **Non-blockable instances** are written **after** blockable instances in exact **z-order**. Only consecutive runs in z-order of the same object forming a gapless row-major tiling (`repeat-x`, `repeat-y`, `repeat-xy`) are merged, preserving relative draw order verbatim.
- **F-26.** **Loading & round-trip:** entries in `placed` are expanded in file order without re-sorting non-blockable instances. `save → load → save` yields an identical model (including z-order) and a byte-for-byte identical file.

#### Note on YAML File Format and Draw Order for Game-Side Scripts

Game-side conversion/build scripts consuming the project `.yaml` file should follow these rules:
1. Each room's `placed` list contains **blockable entries first**, followed by **non-blockable entries in z-order**.
2. Expand `repeat-x: N`, `repeat-y: N`, and `repeat-xy: [W, H]` in row-major order (`for iy in 0..H-1: for ix in 0..W-1`) with step `(obj.w, obj.h)`.
3. Compose the 40×20 screen buffer in two passes:
   - **Pass 1:** draw all `non-blockable` instances in the exact order they appear in `placed`.
   - **Pass 2:** draw all blockable instances on top of Pass 1.
   - In both passes, skip cells with character code `0` (transparent).
4. Render each cell `(x, y)` using the charset and palette of `room.row_groups[y]`.

### 3.6 Validation

- **Errors:** no start room; start outside 40×20; overlapping **blockable** instances on non-zero cells; instance outside 40×20; object with > 255 cells; duplicate names or IDs; invalid teleport room/bounds; object without group; group without loaded charset; > 255 rooms or > 255 objects.
- **Warnings:** unreachable room; object used in a row whose group differs from the object's group; adjacent edges with no common free space; unused objects/groups; non-blockable instance completely hidden by other instances.
- **Passage visualization:** green segments along shared edges where neither room has a blockable non-zero cell.

## 4. Decisions and assumptions (updated)

- **Z-1.** Free space for passage = no blockable object with code ≠ 0 in the cell (`non-blockable` objects and code `0` never block).
- **Z-2.** Code `0` in any object cell is transparent and never overwrites underlying characters.
- **Z-6 (revised).** Overlap rules depend on `non-blockable`: blockable instances cannot overlap each other on non-zero cells; `non-blockable` instances may overlap any instances freely and use explicit z-order (Layer 1 beneath Layer 2 blockable objects).
