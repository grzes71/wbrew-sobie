# Specification: Room Editor for an Atari 8-bit Game (PySide6)

Document version: 1.0

## 1. Purpose and scope

A desktop application written in Python with a PySide6 GUI, used to:

1. design the game's rooms ("komnaty") and the connections between them,
2. define object groups (charset + palette) and objects ("stamps" made of characters),
3. place objects in rooms (each room is 40×20 characters in ANTIC 4 text mode),
4. save and load the whole project to a `.yaml` file with compact compression of repeated patterns.

**Out of scope:** export to a binary / MADS format (done by separate game scripts), the game's status panel, game emulation, a charset editor (`.fnt` files are only loaded).

## 2. Glossary

| Term | Meaning |
|---|---|
| Room | A rectangle of fixed size 40×20 characters (ANTIC 4 mode). Has a name and an ID (1–255). Knows only where objects are placed, not characters. |
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
- **F-4.** **Passage condition:** the hero can cross an edge only where there is free space both in the room he leaves and in the room he enters. **Free space = a cell in which there is no object** (see F-21), except for objects marked with the `non-blockable` flag (see F-13), which do not block passage. One-way passages do not exist: if a room has an "exit" but no room is attached on the other side, the game will not let the hero leave. The editor only **visualizes** potential passages (see 3.6); the game implements the logic.
- **F-5.** **Room groups** are computed automatically from adjacency (connected components). There may be any number of groups on the canvas, including single-room groups. Groups are not stored in the file (they are computed on load). The editor highlights them visually (e.g. with a frame color) and allows moving a whole group together.
- **F-6.** **Teleports:** a bidirectional link between two endpoints. Each endpoint = (room ID, x, y) within the 40×20 room. Endpoints may lie in rooms of different groups, in rooms of the same group, or in the same room (a teleport from a room to itself). Visualization: a line with arrows at both ends between rooms on the canvas. Creation: an "add teleport" mode (click room A, click room B, choose endpoint positions); editing and deleting from a teleport list.
- **F-7.** **Start room and hero start position:** exactly one per project (room ID + x, y). Marked on the canvas with an icon.

### 3.2 Charsets and palettes

- **F-8.** Loading a `.fnt` file for an object group. Validation: size exactly 1024 bytes (128 characters × 8 bytes). In memory the first 128 characters are codes 0–127, and codes 128–255 are the same shapes with COLPF2 swapped for COLPF3 (an ANTIC 4 specific).
- **F-9.** Character rendering mode: **ANTIC 4**. A character has 8 rows of 4 pixels, each 2 bits wide (pixels are 2:1 wide). Pixel value mapping: `00` → COLBK, `01` → COLPF0, `10` → COLPF1, `11` → COLPF2 (codes 0–127) or COLPF3 (codes 128–255). The preview must reproduce the pixel proportions (each ANTIC 4 pixel is twice as wide as it is tall; a full room is 160×160 logical pixels).
- **F-10.** Each object group has a **palette**: COLBK (default 0), COLPF0, COLPF1, COLPF2, COLPF3. Default values are set **globally in the application settings** and copied to new groups.
- **F-11.** Colors are chosen from the **Atari PAL palette** (256 values; the color byte = hue in the high 4 bits and luminance in the low 4 bits, luminance bit 0 ignored). The tool ships an RGB table for PAL (a data file in the repository, easy to replace) and a color picker shown as a palette grid.

### 3.3 Objects, object groups and tags

- **F-12.** **Object group:** a name (unique), one charset, one palette. Many groups per project. Each group's charset is loaded individually.
- **F-13.** **Object:** a name, an ID 1–255 (unique in the project, lowest free by default), assignment to exactly one group, a grid of characters of arbitrary size w×h (codes 0–255 from the group's charset) where the number of cells is between 1 and 255 (w×h ≤ 255), zero or more tags, and a `non-blockable` flag (off by default; an object with the flag does not block passage in the visualization from F-4). Total limit: 255 objects per project.
- **F-14.** **Object editor:** a grid in which a character is picked from the group's charset palette and placed in any cell. The grid size is adjustable. An empty object cell (a "transparent" character) is allowed: code 0 in an object cell means "empty cell", it is not drawn and does not count as occupied by the object (so it does not block passage, see F-4, and does not take part in overlap checks, see F-21).
- **F-15.** **Tags:** a global tag list managed in the application (add, rename, delete). An object can have any number of tags. Tags replace per-character attributes. Deleting a tag removes it from objects (after confirmation).

### 3.4 Room layout

- **F-16.** A room is a grid of **40×20 cells** (size in ANTIC 4 characters). A room **does not store characters**: it stores only a list of **object instances** (object ID, x, y). Only the object itself knows which characters it consists of. A single character placed anywhere in a room is an object of size 1×1 (created in the object editor like any other). The room's appearance is composed from its object instances each time.
- **F-17.** **Object group per row:** each of the 20 rows has an assigned object group (which provides the charset and palette used in that row thanks to DLI). By default all 20 rows share one group (set for the whole room), but the group can be changed individually for each row. Assigning a group to a row has no cost limits (20 DLIs).
- **F-18.** **Faithful rendering:** each character of an object is rendered with the charset and palette of the group of the room row it lies in (not the object's own group). The same code therefore looks different in rows with different groups, and the editor shows this.
- **F-19.** Editing tools: object stamp (the primary tool), eraser (removes an instance), fill, line and rectangle (replicate the selected object along a line or within a rectangle), selection with copy/cut/paste of instances, undo/redo (unlimited within reason, at least 100 steps), grid and zoom toggles.
- **F-20.** Selection panel: a list of objects with previews, filterable by group and tag. Choosing the group for a row: a drop-down or selecting a range of rows.
- **F-21.** **Object instances:** placing an object adds an instance (object ID, x, y) to the room; the object's characters are not copied into the room. Instances in one room **do not overlap** (only object cells with a code other than 0 count) and cannot extend beyond 40×20; the editor does not allow placing an object on an occupied spot. Changing an object's appearance in the object editor immediately changes it in all rooms. Deleting an object used in rooms requires confirmation and removes its instances.

### 3.5 Saving and loading the project (YAML)

- **F-22.** The whole project is saved in a single `.yaml` file with a `version` field (an integer, starting at 1). Loading an unknown version ends with a clear error.
- **F-23.** Charsets are **only linked**, as **paths relative** to the project file (they are not embedded). If a `.fnt` file is missing, the application shows a warning and lets the user point to a replacement file.
- **F-24.** Saved data: global settings (default palette, tag list), object groups (name, `.fnt` path, palette), objects (ID, name, group, tags, `non-blockable` flag, grid), rooms (ID, name, canvas grid position, row-to-group assignment, object instances), teleports, start room and position. Room groups are not saved.
- **F-25.** **Instance list compression** (on save, automatic, lossless). Repeated instances of the same object, placed side by side without gaps (step equal to the object's size), are written with keywords:
  - `repeat-x: N`: N instances horizontally,
  - `repeat-y: N`: N instances vertically,
  - `repeat-xy: [W, H]`: a W×H rectangle of instances.
  The algorithm is **deterministic**: greedy selection of the largest rectangles of identical instances (largest area; ties broken by smallest y first, then smallest x, then greater width). Every instance is covered by exactly one entry. Single instances are written without a keyword. Because instances do not overlap, the order of entries does not affect the appearance, but the output has a deterministic order (sorted by y, then x).
- **F-26.** Loading: entries are expanded into the 40×20 grid. Round-trip requirement: save → load → save yields an identical model and an identical file (byte for byte).

Example file fragment (indicative format; the agent may refine key names):

```yaml
version: 1
settings:
  default_palette: {colbk: 0, colpf0: 40, colpf1: 202, colpf2: 148, colpf3: 15}
tags: [ladder, teleport, wall]
object_groups:
  - name: walls
    charset: fonts/walls.fnt
    palette: {colbk: 0, colpf0: 40, colpf1: 202, colpf2: 148, colpf3: 15}
objects:
  - {id: 1, name: ladder, group: walls, tags: [ladder], non-blockable: true, w: 1, h: 3, chars: [[34], [34], [34]]}
rooms:
  - id: 1
    name: K1
    pos: [0, 0]            # position on the canvas grid
    row_groups: [walls]    # one value = all rows; or a list of 20 elements
    placed:                # object instances only; the room does not know characters
      - {object: 2, x: 0, y: 0, repeat-x: 40}          # object 2 (1×1) 40 times horizontally
      - {object: 3, x: 0, y: 18, repeat-xy: [40, 2]}   # object 3 (1×1) in a 40×2 rectangle
      - {object: 1, x: 20, y: 10}                      # ladder (object 1, 1×3)
teleports:
  - {a: {room: 1, x: 5, y: 10}, b: {room: 3, x: 30, y: 10}}
start: {room: 1, x: 3, y: 17}
```

### 3.6 Validation (reasonable)

Validation runs on demand and on save. The result is shown in a problem list window (levels: error / warning), where clicking an entry jumps to the problem location.

- **Errors:** no start room; overlapping object instances or an instance extending beyond 40×20; an object with more than 255 cells; duplicate names or IDs; a teleport pointing to a non-existent room or a position outside 40×20; start position outside any room; an object without a group; a group without a loaded charset; exceeding the limits of 255 rooms / 255 objects.
- **Warnings:** an unreachable room (not in the start room's group and not the target of any teleport); an object used in a row whose group differs from the object's group (the characters look different than in the object editor); adjacent edges with no common free space (informational); unused objects and groups.
- **Passage visualization:** on the edges of adjacent rooms the editor marks segments where, in both neighbouring cells at the edge, there is no blocking object (an object without the `non-blockable` flag, see F-4). This is only a hint.

## 4. User interface

- Main window with tabs or docks: **Room canvas**, **Room editor**, **Objects and groups**, **Settings** (global palette, tag list).
- Double-clicking a room on the canvas opens its editor.
- Status bar: cursor position (x, y), character code, active group.
- Keyboard shortcuts (basic): Ctrl+N/O/S/Shift+S (project), Ctrl+Z/Y (undo/redo), Ctrl+C/X/V, Delete, Ctrl+mouse wheel (zoom), G (grid), S/E/F/L/R/V (tools: stamp/eraser/fill/line/rectangle/select).
- A warning on closing with unsaved changes. A "modified" indicator in the window title.

## 5. Technical requirements

- Python **≥ 3.14**, PySide6 in the **latest version** supporting Python 3.14, a YAML library (e.g. `ruamel.yaml` or `PyYAML`; the agent's choice, but the output must be deterministic and keep a stable key order).
- **Model separated from view:** the `model` package (rooms, grid, groups, objects, tags, teleports, room-group algorithm, compression, validation, YAML serialization) **does not import PySide6**. Views (`views`/`ui`) only present the model and invoke commands. Model changes go through the command pattern (the basis for undo/redo).
- Project structure: `model/`, `ui/`, `io/` (YAML, `.fnt`), `data/` (PAL palette), `tests/`. Dependencies in `pyproject.toml`.
- Type hints, dataclasses for the model, PEP 8 formatting.

## 6. Tests and acceptance criteria

Unit tests (pytest), without the GUI, for the `model` and `io` layers. At least:

- **T-1.** Loading `.fnt`: a valid 1024-byte file; rejection of other sizes; codes 128–255 have COLPF2 swapped for COLPF3.
- **T-2.** Grid snapping and adjacency detection: two rooms side by side are connected; no multiple neighbours on one edge; overlap forbidden.
- **T-3.** Room group computation: several disjoint groups, single-room groups, group change after moving a room.
- **T-4.** Teleports: bidirectionality, an endpoint pair within the same group and within the same room, deleting a room removes its teleports (after confirmation).
- **T-5.** Instance compression: correct `repeat-x`, `repeat-y`, `repeat-xy`; determinism (the same model always yields the same text); every instance covered exactly once; edge cases (empty room, a room completely filled with a 1×1 object, a checkerboard, objects larger than 1×1).
- **T-6.** **Round-trip:** save → load yields a model identical to the original; save → load → save yields an identical file.
- **T-7.** Validation: each error and warning from 3.6 has a positive and a negative test.
- **T-8.** Versioning: an unknown file version is rejected with a clear message; `.fnt` paths are relative and keep working after moving the project together with its directory.
- **T-9.** Row-to-group assignment: one group for all 20 rows by default; individual change of a single row; correct behaviour when deleting a group used in rows.
- **T-10.** Passage visualization: a blocking object closes the passage on an edge, an object with the `non-blockable` flag does not, no object means free space; the w×h ≤ 255 limit is enforced.

**Acceptance criteria (manual):** it is possible to build a project with at least 3 room groups and 2 teleports; draw a room with two object groups in different rows and correct PAL colors; save, close, load and see an identical result; the YAML file contains the keywords `repeat-x`, `repeat-y`, `repeat-xy` wherever repetitions occur.

## 7. Out of scope (again)

Binary export, editing `.fnt` files, the status panel, gameplay and collision logic, DLI emulation beyond the color preview.

## 8. Decisions and assumptions

- **Z-1 (confirmed).** "Free space" = no object in the given cell (except objects with the `non-blockable` flag, see Z-8).
- **Z-2 (confirmed).** Code 0 in an object cell means "empty / do not overwrite the cell" when placing.
- **Z-3 (confirmed).** A room stores only object instances (ID, x, y), without characters; a single character is a 1×1 object. The object knows which characters it consists of.
- **Z-4 (confirmed).** A teleport may link two different rooms or two positions in the same room.
- **Z-5 (confirmed).** The name of a room group is not stored (groups are computed).
- **Z-6 (confirmed).** Instances in a room cannot overlap (cells with code 0 do not count). As a result there is no overlay order and compression is simple.
- **Z-7 (confirmed).** The limit is 255 objects per project, and each object may consist of 1 to 255 characters (cells). The object limit is considered sufficient.
- **Z-8 (confirmed).** Since "free" = no object, objects (including 1×1 decorations) block passage in the visualization by default. Selected objects marked with the `non-blockable` flag (F-13) do not.
