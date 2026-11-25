# Specification: Room Editor for an Atari 8-bit Game (PySide6)

Document version: 4.0

## 1. Purpose and scope

A desktop application written in Python with a PySide6 GUI, used to:

1. design the game's rooms ("komnaty") and the connections between them,
2. define object groups (indexed PNG image + pixel mapping + one or more named ANTIC 4 palettes) and objects (rectangular stamp regions cut from the group's PNG),
3. place objects in rooms (each room is 40×24 characters in ANTIC 4 text mode, 160×192 logical pixels) with layered z-order support and per-row `(group, palette)` DLI assignment,
4. save and load the whole project to a `.yaml` (version 4) file with derived glyph tables and compact lossless compression of repeated patterns.

**Out of scope:** export to a binary / MADS `.fnt` format (done by separate game scripts from the YAML glyph tables), the game's status panel (handled independently in game code), game emulation, and pixel-level image painting inside the editor (indexed PNG files are loaded from disk).

## 2. Glossary

| Term | Meaning |
|---|---|
| Room | A rectangle of fixed size 40×24 characters (ANTIC 4 mode, 160×192 logical pixels, 320×192 at 2:1 aspect). Has a name and an ID (1–255). Stores an ordered list of object instances, not raw characters. |
| Room group | A set of rooms linked by adjacency on the canvas (computed automatically). |
| Source image (PNG) | An indexed (palette, mode `P`) PNG using only palette indexes `0–3`, with width a positive multiple of `4` and height a positive multiple of `8`. |
| Pixel mapping | A permutation mapping PNG palette indexes `0–3` to ANTIC 4 2-bit pixel values (`00`=COLBK, `01`=COLPF0, `10`=COLPF1, `11`=COLPF2/COLPF3). |
| Glyph | A `4×8`-pixel ANTIC 4 character cell (8 bytes, 2 bits per pixel). |
| Glyph table | Derived per-group table assigning deterministic codes `1..127` to unique non-empty glyphs used by objects in the group. Code `0` is reserved and always empty (`0000000000000000`). |
| Object group | A unique name + one linked indexed PNG + one pixel mapping + ordered list of named 5-color ANTIC 4 palettes (`>= 1`, unique names within the group; first palette is the default) + derived glyph table (`≤ 127` unique glyphs). |
| Named palette | A group palette entry (`name` + `COLBK, COLPF0..COLPF3` PAL colour bytes). Does not affect glyphs or the 127-glyph budget. |
| Row assignment | A per-row pair `(group, palette)` (`RowAssignment`) determining both the charset (`.fnt` / glyph table) and the 5 ANTIC 4 colours used to render that character row (`0..23`). |
| Object | A named rectangular stamp (`region`: `x, y, w, h` in glyph units) cut from one object group's PNG. Has an ID (1–255), zero or more tags, optional `non-blockable` flag, and optional `colpf3` flag. |
| Object instance | A placement of an object in a room: `(object ID, x, y)` where `x in 0..39`, `y in 0..23`. |
| Tag | A globally defined label (e.g. `ladder`, `teleport`) assigned to objects. |
| Teleport | A bidirectional link between two points in rooms, independent of adjacency. |

## 3. Functional requirements

### 3.1 Rooms and connections (canvas)

- **F-1.** A canvas with a grid. Each room occupies one grid cell (cell size proportional to the 40×24 ANTIC 4 display aspect `320:192` = `5:3`). Rooms can be freely added, moved and deleted. While dragging, a room **snaps to the grid**, and therefore to its neighbours.
- **F-2.** Each room has a **name** (unique in the project) and a **numeric ID 1–255** (unique, assigned automatically as the lowest free value; the user may change it). The project cannot exceed 255 rooms.
- **F-3.** Two rooms whose edges touch (left/right/top/bottom) are connected. Each room edge has **at most one neighbour**; two rooms cannot occupy the same grid cell.
- **F-4.** **Passage condition:** the hero can cross an edge only where there is free space both in the room he leaves and in the room he enters (left/right edges span `24` rows `0..23`; top/bottom edges span `40` columns `0..39`). **Free space = a cell with no blocking object** (i.e. only blockable objects — `non-blockable = false` — block on cells with code ≠ 0; `non-blockable` objects and code `0` cells never block, regardless of whether they overlap). One-way passages do not exist: if a room has an "exit" but no room is attached on the other side, the game will not let the hero leave. The editor only **visualizes** potential passages (see 3.6); the game implements the logic.
- **F-5.** **Room groups** are computed automatically from adjacency (connected components). There may be any number of groups on the canvas, including single-room groups. Groups are not stored in the file (they are computed on load). The editor highlights them visually (e.g. with a frame color) and allows moving a whole group together.
- **F-6.** **Teleports:** a bidirectional link between two endpoints. Each endpoint = `(room ID, x, y)` within the `40×24` room (`x in 0..39`, `y in 0..23`). Endpoints may lie in rooms of different groups, in rooms of the same group, or in the same room (a teleport from a room to itself). Visualization: a line with arrows at both ends between rooms on the canvas.
- **F-7.** **Start room and hero start position:** exactly one per project (`room ID` + `x in 0..39, y in 0..23`). Marked on the canvas with an icon.

### 3.2 Indexed PNG images, pixel mapping, and palettes

- **F-8.** **PNG requirements & loading:** Each object group links **one indexed PNG** (mode `P`). Validated on import and every reload:
  - Must be a valid indexed PNG using **only palette indexes `0–3`**.
  - Width must be a positive multiple of `4` pixels and height a positive multiple of `8` pixels.
  - Colours stored in the PNG file's palette are ignored by the game (only used in the optional *"As in file"* editor preview).
  - Reloading an updated PNG re-validates the PNG, all object regions, the 127-glyph limit, and the glyph table; objects whose region became invalid or that exceed the limit are flagged as errors without automatically deleting data.
- **F-9.** **Character rendering mode (ANTIC 4):** Each glyph is `8` rows × `4` pixels of `2` bits each (pixels are `2:1` wide; a full `40×24` room is `160×192` logical pixels / `320×192` at 2:1 display aspect). Pixel value mapping: `00` → `COLBK`, `01` → `COLPF0`, `10` → `COLPF1`, `11` → `COLPF2` (codes `0–127`) or `COLPF3` (codes `128–255`).
- **F-10.** Each object group owns an ordered list of **named palettes** (always at least 1, never 0; unique names within the group). Each palette defines `COLBK` (default 0), `COLPF0`, `COLPF1`, `COLPF2`, `COLPF3`.
  - The **first palette** of the group is its default palette.
  - A newly created group gets one palette named `"default"` initialized from global application settings (`Settings.default_palette`).
  - Palettes support **Add** (initialized as a copy of the currently selected palette, or global default if none, with a unique free name), **Duplicate**, **Rename** (updates all `(group, palette)` room row references; undoable), **Reorder** (move up/down; preserves explicit room row palette names), and **Delete** (refused on the last remaining palette; if used by room rows, lists affected rooms/rows for confirmation and falls back those rows to the group's first palette; undoable).
  - Palettes are purely visual: they never change the glyph table, 127-glyph limit, regions, `colpf3`, or pixel mapping.
- **F-11.** Colors are chosen from the **Atari PAL palette** (256 values; bit 0 ignored) backed by `room_editor/data/pal_palette.json`.
- **F-12.** **Pixel mapping (per group):** Maps each PNG palette index `0..3` to a distinct ANTIC 4 pixel value (`00`, `01`, `10`, `11`). Must be a permutation of `(0, 1, 2, 3)` (default identity `[0, 1, 2, 3]`). Configurable in the PNG import dialog and later via **Pixel Mapping...** with a live 2:1 preview (rendered using the group's currently selected preview palette).
  - Whichever PNG index maps to `00` (`COLBK`) defines **empty pixels**. Any `4×8` glyph containing only `00` pixels becomes character code `0` (reserved empty glyph) and does **not** count toward the 127 limit.
  - **Transparency consequence:** A cell of pure `COLBK` (`00`) is code `0` and is always **transparent** in rooms (under both `non-blockable` and blockable overlap/draw-order rules, never overwriting cells beneath it and never blocking hero passage).
  - Changing the mapping re-evaluates all objects in the group; if the new mapping would make an object all-empty, exceed 127 unique glyphs, or create blockable room overlaps, the editor refuses the change and lists the conflicting objects.

### 3.3 Objects, glyph tables, and tags

- **F-13.** **Object:** unique name, unique ID `1–255`, belongs to one group, defined by a rectangular **region** `(x, y, w, h)` in **glyph units** (`1` unit = `4×8` pixels; minimum `1×1`, `1 <= w * h <= 255`, lying inside the group's PNG), zero or more tags, a `non-blockable` flag (default off), a `pickable` flag (default off), and a `colpf3` flag (default off). Total limit: `255` objects per project.
  - **COLPF3 flag:** When `colpf3` is on, all non-empty cells of the object use codes `+128` (`129..255`), drawing the same glyph shapes with `COLPF3` instead of `COLPF2` for value `11`. Empty cells remain code `0` (never `128`). `colpf3` creates **no new glyphs** and has **no effect** on the 127-glyph limit.
- **F-14.** **Stamp Image window & 127-glyph budget:**
  - Displays the group's indexed PNG at 2:1 pixel aspect with zoom/scroll, a `4×8`-pixel grid overlay, snapped drag selection (in glyph units), an *"As in file"* palette toggle, a *"Preview with COLPF3"* toggle, live group counter (`used/127`), and live selection counter (`+N new`, free slots).
  - **Deterministic glyph table:** For each group, objects are iterated in **ascending object ID** and cells **row-major**. Every unique non-empty `4×8` mapped bitmap (exact 32-pixel comparison; mirrored/rotated glyphs are distinct) receives the next free code `1..127` on its first occurrence (`src: [gx, gy]`). Deleting or editing an object shifts subsequent codes automatically (rooms reference object IDs, not raw character codes).
  - An object consisting solely of empty (`00`) glyphs is invalid and rejected. Creating/updating an object that would exceed `127` unique glyphs is rejected with a message showing how many new glyphs it would add and how many slots remain free.
- **F-15.** **Tags:** global tag list (add, rename, delete with confirmation).

### 3.4 Room layout, draw order, and overlapping

- **F-16.** A room is a grid of **40×24 cells** (`x in 0..39`, `y in 0..23`) storing an **ordered list of object instances** `(object ID, x, y)`. For `non-blockable` instances, list order is their **z-order** (later in the list = drawn later = on top). Newly placed non-blockable instances are appended at the top of the z-order.
- **F-17.** **Object group and palette per row:** each of the **24** rows (`0..23`) has an assigned pair **`(group, palette)`** (`RowAssignment`, 24 DLIs — glyph table + palette). Default for a new room: one `(group, palette)` pair for all 24 rows, individually changeable per row or row range. Changing the group selector in the Room Editor preserves a same-named palette if present in the new group, or falls back to the new group's first (default) palette otherwise.
- **F-18.** **Faithful rendering & draw order:** the room is composed into a **40×24** grid of character codes (`0..255`, derived from each object's region, glyph table, and `colpf3` flag) in two layers before rendering each row `y` using its assigned `room.row_groups[y].group` glyph table and `room.row_groups[y].palette` colors:
  1. **Layer 1 (background / non-blockable):** all `non-blockable` instances drawn in z-order (earlier → later).
  2. **Layer 2 (foreground / blockable):** all blockable instances drawn after (on top of) Layer 1. Because blockable instances never overlap each other, their relative order does not affect appearance.
  3. **Transparency:** character code `0` (including any pure-`COLBK` cell in an object) is transparent and never overwrites a non-zero character underneath, in either layer.
  4. **Cross-group rows:** each cell `(x, y)` is rendered using the glyph table of `room.row_groups[y].group` and the palette of `room.row_groups[y].palette` (even if the placed object belongs to a different group; exposed in pure model form as `render_room_row_rgb`). If the cell's base code `(code & 0x7F)` is not present in that row group's glyph table, the cell is drawn as empty (and validation emits `OBJECT_ROW_GROUP_MISMATCH`).
- **F-19.** **Editing tools:** Stamp (`S`), Eraser (`E` — removes the topmost visible instance with a non-zero cell under the cursor), Fill (`F`), Line (`L`), Rectangle (`R`), Select (`V` — click selects topmost visible instance, drag marquee selects intersecting instances) with Copy/Cut/Paste/Delete, Undo/Redo, Grid (`G`), Zoom (`Ctrl+wheel`), and **Z-order arrangement** for non-blockable instances (Bring to Front `Ctrl+Shift+]`, Move Up `Ctrl+]`, Move Down `Ctrl+[`, Send to Back `Ctrl+Shift+[`, also available via right-click context menu).
- **F-20.** Selection panel: object list with previews (including COLPF3 colors and synchronized UI-only **Preview Palette** selector; does not alter project data), filterable by group and tag; 24-row gutter displaying a 5-color swatch chip + group/palette label per row and supporting single-row, Shift-range, and *"Set All 24 Rows"* `(group, palette)` assignment (all undoable).
- **F-21.** **Overlapping rules:**
  - **Blockable + blockable:** MUST NOT overlap on cells with code ≠ 0 and cannot extend beyond **40×24** (`x + w <= 40`, `y + h <= 24`). Touching or overlapping solely through code `0` cells is permitted.
  - **Non-blockable:** MAY overlap other non-blockable instances and MAY lie under/over blockable instances (checked only against **40×24** bounds).
  - Objects with validation errors (missing/invalid group PNG, region out of image, all-empty, or exceeding 127 glyphs) cannot be placed in rooms until fixed.
  - **Changing `non-blockable` from ON to OFF:** if existing room placements of that object would create blockable-vs-blockable overlaps on non-zero cells, the editor warns, lists the conflicting rooms and coordinates, and refuses the change until conflicts are resolved.
  - Deleting a used object requires confirmation and removes its instances.

### 3.5 Saving and loading the project (YAML v4)

- **F-22.** Single `.yaml` file with integer `version: 4`. Any other version (including versions 1, 2, and 3) or missing version fails with a clear `UnsupportedVersionError`.
- **F-23.** Group PNG images are **linked only**, as **POSIX paths relative** to the project `.yaml` file (never embedded). Missing PNG files trigger a warning and let the user point to a replacement PNG on load.
- **F-24.** Saved data: `settings`, `tags`, `object_groups` (each with `name`, `image`, `pixel_mapping`, ordered `palettes` list of `{name, colbk, colpf0, colpf1, colpf2, colpf3}`, and derived `glyphs` table), `objects` (each with `id`, `name`, `group`, `tags`, `non-blockable`, `pickable`, `colpf3`, `region`), `rooms` (`row_groups` as a 1-element list if all 24 rows share one `(group, palette)`, or a 24-element list where each entry is `"group"` when targeting the group's first palette or `{group: "...", palette: "..."}` otherwise), `teleports`, `start`. Room groups are computed on load and not saved.
  - On load, both shorthand string `"group"` (resolved to the group's first palette) and explicit `{group: "...", palette: "..."}` mappings are accepted; unknown group or palette names or list lengths other than `1` or `24` fail with `ProjectIOError`.
  - On every save, the editor regenerates each group's `glyphs` table deterministically from the PNG, `pixel_mapping`, and objects.
  - On load, after loading PNGs, the editor recomputes each group's glyph table and checks it against the stored `glyphs` list in the YAML file (warning if any mismatch is detected).
- **F-25.** **Two-layer instance compression (lossless, deterministic):**
  - **Blockable instances** are written **first**, compressed via the greedy largest-rectangle algorithm (`repeat-x`, `repeat-y`, `repeat-xy` with step `(w, h)` across the `40×24` grid; tie-break: largest area, smallest `y`, smallest `x`, greater width), sorted by `(y, x, object)`.
  - **Non-blockable instances** are written **after** blockable instances in exact **z-order**. Only consecutive runs in z-order of the same object forming a gapless row-major tiling (`repeat-x`, `repeat-y`, `repeat-xy`) are merged, preserving relative draw order verbatim.
- **F-26.** **Loading & round-trip:** entries in `placed` are expanded onto the `40×24` grid in file order without re-sorting non-blockable instances. `save → load → save` yields an identical model (including z-order, 24 `(group, palette)` row assignments, named group palettes, and glyph tables) and a byte-for-byte identical file.

Example YAML v4 fragment:

```yaml
version: 4
settings:
  default_palette: {colbk: 0, colpf0: 40, colpf1: 202, colpf2: 148, colpf3: 15}
tags: [ladder, teleport, wall]
object_groups:
  - name: walls
    image: images/walls.png
    pixel_mapping: [0, 1, 2, 3]
    palettes:
      - {name: day, colbk: 0, colpf0: 40, colpf1: 202, colpf2: 148, colpf3: 15}
      - {name: night, colbk: 0, colpf0: 116, colpf1: 136, colpf2: 146, colpf3: 10}
    glyphs:
      - {code: 1, data: "55AA55AA55AA55AA", src: [0, 0]}
      - {code: 2, data: "FF00FF00FF00FF00", src: [1, 0]}
objects:
  - {id: 1, name: ladder, group: walls, tags: [ladder], non-blockable: true, colpf3: true, region: {x: 0, y: 0, w: 1, h: 3}}
  - {id: 2, name: brick, group: walls, tags: [wall], non-blockable: false, colpf3: false, region: {x: 1, y: 0, w: 1, h: 1}}
rooms:
  - id: 1
    name: K1
    pos: [0, 0]
    row_groups:             # 1 entry (all 24 rows) or 24 entries ("group" = first palette, or {group, palette})
      - walls
      - {group: walls, palette: night}
      # ... total 24 entries when mixed, or [walls] when uniform
    placed:
      - {object: 2, x: 0, y: 0, repeat-x: 40}
      - {object: 3, x: 0, y: 22, repeat-xy: [40, 2]}
      - {object: 1, x: 20, y: 10}
teleports:
  - {a: {room: 1, x: 5, y: 10}, b: {room: 2, x: 30, y: 21}}
start: {room: 1, x: 3, y: 21}
```

#### Note for Game-Side Scripts: Glyph Table Format, `.fnt` Generation, and Room Composition

Game-side conversion/build scripts do **not** need to read PNG files; everything required to build `.fnt` charsets and room data is stored directly in the YAML v4 file:

1. **Generating the 1024-byte `.fnt` charset for each object group:**
   - Allocate `1024` zero bytes (`128` characters × `8` bytes).
   - **Code `0`** stays `8` zero bytes (`0000000000000000`) — reserved empty / transparent character.
   - For each entry `{code, data, src}` in `group.glyphs` (`1 <= code <= 127`):
     - Decode `data` (16 uppercase hex characters = 8 bytes, already mapped to ANTIC 4 bit pairs: bits `7..6` = pixel 0, `5..4` = pixel 1, `3..2` = pixel 2, `1..0` = pixel 3, row 0 first).
     - Write those 8 bytes at byte offset `code * 8`.
   - At runtime in ANTIC 4, **codes `128..255`** automatically use the exact same `8`-byte shapes as `0..127` (`offset = (code & 0x7F) * 8`) with pixel value `%11` displayed using `COLPF3` instead of `COLPF2`.
2. **Computing each object's character matrix:**
   - Each non-empty `4×8` cell in `object.region` matches one `data` entry in its group's `glyphs` table (`code` in `1..127`); an all-zero cell (`0000000000000000`) becomes code `0`.
   - If `object.colpf3` is `true`, add `128` to every non-zero cell (`code + 128` → `129..255`), leaving `0` cells as `0` (never `128`).
3. **Expanding and composing rooms (`40×24`):**
   - Each room's `placed` list contains **blockable entries first**, followed by **non-blockable entries in z-order**.
   - Expand `repeat-x: N`, `repeat-y: N`, and `repeat-xy: [W, H]` in row-major order (`for iy in 0..H-1: for ix in 0..W-1`) with step `(obj.region.w, obj.region.h)`.
   - Pass 1: draw all `non-blockable` instances in file order; Pass 2: draw all blockable instances on top. Skip code `0` cells. Render row `y` (`0..23`) with the `.fnt` of `row.group` and the `colbk, colpf0..colpf3` entry named `row.palette` (defaulting to `palettes[0].name` if shorthand string) in `group.palettes`.

### 3.6 Validation

- **Errors:**
  - project-level: no start room, start outside `40×24` (`x in 0..39`, `y in 0..23`), `> 255` rooms, `> 255` objects, duplicate names or IDs;
  - object groups: group without PNG image (`GROUP_NO_IMAGE`), group with invalid PNG format/mode/indexes/dimensions (`GROUP_INVALID_IMAGE`), invalid pixel mapping (`GROUP_INVALID_PIXEL_MAPPING`), group exceeding `127` unique glyphs (`GROUP_GLYPH_LIMIT_EXCEEDED`), group with empty palette list (`GROUP_NO_PALETTES`), empty palette name (`EMPTY_PALETTE_NAME`), duplicate palette name (`DUPLICATE_PALETTE_NAME`);
  - objects: missing/unknown group, `w * h > 255`, object region outside group's PNG (`OBJECT_REGION_OUT_OF_IMAGE`), object consisting only of empty `00` glyphs (`OBJECT_EMPTY`), object exceeding `127` glyph limit (`OBJECT_EXCEEDS_GLYPH_LIMIT`);
  - rooms & teleports: invalid/unassigned row group (`ROOM_INVALID_ROW_GROUP`), row palette not found in assigned group (`ROOM_INVALID_ROW_PALETTE`), overlapping **blockable** instances on non-zero cells, instance outside `40×24`, unknown object reference, invalid teleport room/bounds (`y in 0..23`).
- **Warnings:**
  - group PNG file missing on disk (`GROUP_IMAGE_MISSING`);
  - object with `colpf3` enabled whose glyphs contain no value-`11` pixels (`OBJECT_COLPF3_NO_EFFECT`);
  - unreachable room (`UNREACHABLE_ROOM`);
  - object used in a row whose group differs from the object's group (`OBJECT_ROW_GROUP_MISMATCH`);
  - adjacent edges with no common free space (`ADJACENT_NO_PASSAGE`, checked over all `24` rows on left/right edges and `40` columns on top/bottom edges);
  - unused objects (`UNUSED_OBJECT`), unused groups (`UNUSED_GROUP`), and unused group palettes (`UNUSED_PALETTE`);
  - non-blockable instance completely hidden by other instances (`HIDDEN_NON_BLOCKABLE_INSTANCE`).
- **Passage visualization:** green segments along shared edges (`24` rows left/right, `40` columns top/bottom) where neither room has a blockable non-zero cell.

## 4. User interface

- Main window tabs: **Room Canvas**, **Room Editor**, **Objects & Groups**, **Settings** (global default palette and tags).
- **Room Canvas:** proportional `5:3` (`320:192`) room cells with group borders, 24-row left/right and 40-column top/bottom passage markers, teleport arrows, and start position marker.
- **Room Editor:** `40×24` interactive canvas with `24`-row `(group, palette)` gutter (5-color swatch chip + group/palette label per row), paired **Row Group** + **Palette** selectors (preserving matching palette name or falling back to first palette on group switch; **Set Selected Rows** & **Set All 24 Rows** undoable), **Preview Palette** selector for the object palette list, and status bar displaying `Row: <group> / <palette>`.
- **Objects & Groups** tab:
  - Left column: group list (`[OK]` / `[NO PNG]` / `[MISSING]` / `[INVALID]` + `used/127`), relative PNG path, **Load PNG...**, **Reload Image**, **Pixel Mapping...**, unique glyphs counter, **Named Palettes** list (**+ Add**, **Duplicate**, **Rename**, **Delete** with room/row confirmation, **Move Up**, **Move Down**), and 5-register PAL palette editor for the selected palette.
  - Center column: object list with previews (`[NB]`, `[COLPF3]`, `[ERR]`) rendered in a selectable **Preview Palette** (UI-only), metadata (`ID`, `Name`, `Group`), glyph `Region (x, y, w, h)`, `Non-blockable` and `COLPF3` toggles, and `Tags`.
  - Right column (**Stamp Image** window): 2:1 PNG view with zoom/scroll, `4×8` grid overlay, snapped region drag selection, UI-only **Preview Palette** selector, *"Preview with COLPF3"* and *"As in file"* toggles, live `used/127` and `+N new` counters, and buttons to create an object or update the selected object's region.
- **PNG Import & Pixel Mapping** dialog (`PngImportDialog`): 4 PNG index swatches + permutation dropdowns with auto-swap, identity reset, live 2:1 preview (*"As in file"* / *"Preview with COLPF3"* using the active group palette), and validation against existing objects in the group.

## 5. Technical requirements

- Python **≥ 3.14**, `PySide6`, `PyYAML`, `Pillow` (dependencies declared in `pyproject.toml`).
- **Single source of truth for dimensions:** `ROOM_WIDTH = 40`, `ROOM_HEIGHT = 24`, and derived pixel constants (`ROOM_PIXEL_WIDTH = 160`, `ROOM_PIXEL_HEIGHT = 192`, `ROOM_DISPLAY_WIDTH = 320`, `ROOM_DISPLAY_HEIGHT = 192`) defined once in `room_editor/model/project.py` and used across model, IO, UI, and tests.
- **Strict layer separation:** `room_editor/model/` must never import `PySide6` or `PIL`/`Pillow`; `room_editor/io/` handles PNG loading (`io/png.py`) and YAML serialization (`io/yaml_io.py`) without importing `PySide6`; `room_editor/ui/` renders via `QtRenderer` and mutates the model via `Command`s on `UndoStack`.

## 6. Tests (`room_editor/tests/`, pytest without GUI + offscreen smoke)

- **Room size constants & PNG/glyph rules (`test_png_and_glyphs.py`):** `40×24` dimensions and `160×192` / `320×192` derived pixel sizes; valid indexed PNG & rejection of non-indexed modes, indexes `> 3`, non-multiples of `4×8`, missing files; pixel mapping permutations & empty semantics; glyph splitting, deduplication, mirror distinctness, deterministic codes `1..127`, `127`-glyph limit; `colpf3` (`+128` for non-empty only, `0` preserved, `COLPF3` rendering); region bounds & `w * h <= 255`.
- **Named palettes, per-row assignments, YAML v4 (`test_palettes_and_rows.py`):** add/edit/rename/reorder/delete palettes (last-palette refusal, room/row fallback & undo/redo); per-row & range `(group, palette)` assignment and group deletion fallback; YAML v4 shorthand vs `{group, palette}` normalization, rejection of versions `1`/`2`/`3`, unknown palette/group & wrong list lengths; pure model `render_room_row_rgb`; palette validation errors & `UNUSED_PALETTE`.
- **Canvas, groups, teleports, 24-cell passages (`test_canvas_and_graph.py`):** proportional grid snapping, adjacency, connected components, bidirectional teleports, 24-row left/right and 40-col top/bottom passage visualization, `w * h <= 255`.
- **Layering, z-order, compression (`test_layering_and_zorder.py`, `test_compression_and_yaml.py`):** blockable vs non-blockable overlap rules, two-layer composition, transparency of code `0`, z-order undo/redo, full `40×24` (`960`-cell) `repeat-xy: [40, 24]` and `repeat-y: 24` compression.
- **YAML v4 round-trip, versioning, row groups, consistency (`test_compression_and_yaml.py`):** save → load → save yields identical model, 24 `(group, palette)` row assignments, glyph tables, and file bytes; rejects versions `1`, `2`, `3`, `99`, and missing version; rejects `row_groups` lists of length `20` or `25`; relative PNG paths remain valid after moving project directory; glyph table mismatch detected and recomputed on load.
- **Validation (`test_validation.py`):** positive and negative tests for every error and warning in Section 3.6, including boundary checks at `y = 23` (valid) and `y = 24` (rejected) for instances, teleports, and start position.
- **Architecture & GUI (`test_architecture_and_gui.py`):** AST checks (no `PySide6` in `model`/`io`, no `PIL` in `model`), >120 undo/redo steps, tools, offscreen `MainWindow` smoke workflow asserting rendered room image size `320×192` (`160×192` at 2:1 aspect).

**Acceptance criteria:** build a project with multiple room groups, teleports, multi-palette object groups, and mixed 24-row `(group, palette)` DLI assignments; verify `160×192` logical (`320×192` 2:1) proportions on both the canvas and the room editor; verify `y = 23` boundary placements, `repeat-x`, `repeat-y: 24`, `repeat-xy: [40, 24]`, and deterministic `version: 4` round-trip.
