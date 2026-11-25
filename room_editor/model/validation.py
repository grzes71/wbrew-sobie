"""Project validation returning structured errors and warnings (Section 3.6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from room_editor.model.glyphs import MAX_GLYPHS_PER_GROUP, is_valid_pixel_mapping
from room_editor.model.graph import (
    compute_edge_passages,
    compute_reachable_rooms,
    get_adjacent_rooms,
)
from room_editor.model.project import (
    MAX_OBJECT_CELLS,
    MAX_OBJECTS,
    MAX_ROOMS,
    ROOM_HEIGHT,
    ROOM_WIDTH,
    Project,
)

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation error or warning with navigation metadata."""

    severity: Severity
    code: str
    message: str
    target_type: str = "project"
    target_id: int | str | None = None
    x: int | None = None
    y: int | None = None


def validate_project(project: Project) -> list[ValidationIssue]:
    """Validate project integrity and return errors followed by warnings."""
    project.resolve_row_assignments()
    project.rebuild_glyph_tables()
    issues: list[ValidationIssue] = []

    # --- Project-level limits ---
    if len(project.rooms) > MAX_ROOMS:
        issues.append(
            ValidationIssue(
                severity="error",
                code="TOO_MANY_ROOMS",
                message=f"Project has {len(project.rooms)} rooms; maximum is {MAX_ROOMS}.",
                target_type="project",
            )
        )
    if len(project.objects) > MAX_OBJECTS:
        issues.append(
            ValidationIssue(
                severity="error",
                code="TOO_MANY_OBJECTS",
                message=f"Project has {len(project.objects)} objects; maximum is {MAX_OBJECTS}.",
                target_type="project",
            )
        )

    # --- Object groups ---
    seen_group_names: set[str] = set()
    groups_by_name = {}
    for grp in project.object_groups:
        if not grp.name.strip():
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="EMPTY_GROUP_NAME",
                    message="Object group has an empty name.",
                    target_type="group",
                    target_id=grp.name,
                )
            )
        elif grp.name in seen_group_names:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DUPLICATE_GROUP_NAME",
                    message=f"Duplicate object group name '{grp.name}'.",
                    target_type="group",
                    target_id=grp.name,
                )
            )
        else:
            seen_group_names.add(grp.name)
            groups_by_name[grp.name] = grp

        if not grp.palettes:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="GROUP_NO_PALETTES",
                    message=f"Object group '{grp.name}' must have at least one palette.",
                    target_type="group",
                    target_id=grp.name,
                )
            )
        else:
            seen_pal_names: set[str] = set()
            for pal in grp.palettes:
                if not pal.name.strip():
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="EMPTY_PALETTE_NAME",
                            message=f"Object group '{grp.name}' has a palette with an empty name.",
                            target_type="group",
                            target_id=grp.name,
                        )
                    )
                elif pal.name in seen_pal_names:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="DUPLICATE_PALETTE_NAME",
                            message=(
                                f"Object group '{grp.name}' has duplicate palette name '{pal.name}'."
                            ),
                            target_type="group",
                            target_id=grp.name,
                        )
                    )
                else:
                    seen_pal_names.add(pal.name)

        if not is_valid_pixel_mapping(grp.pixel_mapping):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="GROUP_INVALID_PIXEL_MAPPING",
                    message=(
                        f"Object group '{grp.name}' has invalid pixel mapping {grp.pixel_mapping!r}; "
                        "must be a permutation of (0, 1, 2, 3)."
                    ),
                    target_type="group",
                    target_id=grp.name,
                )
            )

        if grp.image is None:
            if grp.image_status == "invalid":
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="GROUP_INVALID_IMAGE",
                        message=(
                            f"Object group '{grp.name}' has invalid PNG '{grp.image_path}': "
                            f"{grp.image_error or 'validation failed'}."
                        ),
                        target_type="group",
                        target_id=grp.name,
                    )
                )
            elif grp.image_status == "missing":
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="GROUP_IMAGE_MISSING",
                        message=(
                            f"Object group '{grp.name}' PNG file is missing on disk: '{grp.image_path}'."
                        ),
                        target_type="group",
                        target_id=grp.name,
                    )
                )
            else:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="GROUP_NO_IMAGE",
                        message=f"Object group '{grp.name}' has no PNG image assigned.",
                        target_type="group",
                        target_id=grp.name,
                    )
                )
        elif (
            grp.glyph_analysis is not None
            and grp.glyph_analysis.total_unique_needed > MAX_GLYPHS_PER_GROUP
        ):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="GROUP_GLYPH_LIMIT_EXCEEDED",
                    message=(
                        f"Object group '{grp.name}' requires {grp.glyph_analysis.total_unique_needed} "
                        f"unique non-empty glyphs; maximum is {MAX_GLYPHS_PER_GROUP}."
                    ),
                    target_type="group",
                    target_id=grp.name,
                )
            )

    # --- Objects ---
    seen_obj_ids: set[int] = set()
    seen_obj_names: set[str] = set()
    objects_by_id = {}
    for obj in project.objects:
        if not (1 <= obj.id <= MAX_OBJECTS):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="INVALID_OBJECT_ID",
                    message=f"Object '{obj.name}' has invalid ID {obj.id} (must be 1..{MAX_OBJECTS}).",
                    target_type="object",
                    target_id=obj.id,
                )
            )
        elif obj.id in seen_obj_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DUPLICATE_OBJECT_ID",
                    message=f"Duplicate object ID {obj.id} ('{obj.name}').",
                    target_type="object",
                    target_id=obj.id,
                )
            )
        else:
            seen_obj_ids.add(obj.id)
            objects_by_id[obj.id] = obj

        if not obj.name.strip():
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="EMPTY_OBJECT_NAME",
                    message=f"Object ID {obj.id} has an empty name.",
                    target_type="object",
                    target_id=obj.id,
                )
            )
        elif obj.name in seen_obj_names:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DUPLICATE_OBJECT_NAME",
                    message=f"Duplicate object name '{obj.name}'.",
                    target_type="object",
                    target_id=obj.id,
                )
            )
        else:
            seen_obj_names.add(obj.name)

        if obj.w < 1 or obj.h < 1 or obj.w * obj.h > MAX_OBJECT_CELLS:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="OBJECT_TOO_MANY_CELLS",
                    message=(
                        f"Object '{obj.name}' (ID {obj.id}) has size {obj.w}x{obj.h} "
                        f"({obj.w * obj.h} cells); must be 1..{MAX_OBJECT_CELLS}."
                    ),
                    target_type="object",
                    target_id=obj.id,
                )
            )

        grp = groups_by_name.get(obj.group)
        if grp is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="OBJECT_MISSING_GROUP",
                    message=f"Object '{obj.name}' (ID {obj.id}) has missing or unknown group '{obj.group}'.",
                    target_type="object",
                    target_id=obj.id,
                )
            )
        elif grp.image is not None and grp.glyph_analysis is not None:
            analysis = grp.glyph_analysis
            if obj.id in analysis.invalid_region_object_ids and 1 <= obj.cell_count <= MAX_OBJECT_CELLS:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="OBJECT_REGION_OUT_OF_IMAGE",
                        message=(
                            f"Object '{obj.name}' (ID {obj.id}) region ({obj.region.x}, {obj.region.y}) "
                            f"{obj.w}x{obj.h} lies outside group '{grp.name}' image "
                            f"({grp.image.glyph_cols}x{grp.image.glyph_rows} glyphs)."
                        ),
                        target_type="object",
                        target_id=obj.id,
                    )
                )
            if obj.id in analysis.empty_object_ids:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="OBJECT_EMPTY",
                        message=f"Object '{obj.name}' (ID {obj.id}) contains only empty (00) glyphs.",
                        target_type="object",
                        target_id=obj.id,
                    )
                )
            if obj.id in analysis.overflow_object_ids:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="OBJECT_EXCEEDS_GLYPH_LIMIT",
                        message=(
                            f"Object '{obj.name}' (ID {obj.id}) exceeds the {MAX_GLYPHS_PER_GROUP}-glyph "
                            f"limit for group '{grp.name}'."
                        ),
                        target_type="object",
                        target_id=obj.id,
                    )
                )
            if obj.id in analysis.colpf3_no_effect_object_ids:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="OBJECT_COLPF3_NO_EFFECT",
                        message=(
                            f"Object '{obj.name}' (ID {obj.id}) has COLPF3 enabled, "
                            "but none of its glyphs use pixel value 11 (COLPF2/COLPF3)."
                        ),
                        target_type="object",
                        target_id=obj.id,
                    )
                )

    # --- Rooms ---
    seen_room_ids: set[int] = set()
    seen_room_names: set[str] = set()
    seen_room_pos: dict[tuple[int, int], int] = {}
    rooms_by_id = {}
    used_object_ids: set[int] = set()
    used_group_names: set[str] = {o.group for o in project.objects if o.group in groups_by_name}
    used_palettes: set[tuple[str, str]] = set()

    for room in project.rooms:
        if not (1 <= room.id <= MAX_ROOMS):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="INVALID_ROOM_ID",
                    message=f"Room '{room.name}' has invalid ID {room.id} (must be 1..{MAX_ROOMS}).",
                    target_type="room",
                    target_id=room.id,
                )
            )
        elif room.id in seen_room_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DUPLICATE_ROOM_ID",
                    message=f"Duplicate room ID {room.id} ('{room.name}').",
                    target_type="room",
                    target_id=room.id,
                )
            )
        else:
            seen_room_ids.add(room.id)
            rooms_by_id[room.id] = room

        if not room.name.strip():
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="EMPTY_ROOM_NAME",
                    message=f"Room ID {room.id} has an empty name.",
                    target_type="room",
                    target_id=room.id,
                )
            )
        elif room.name in seen_room_names:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DUPLICATE_ROOM_NAME",
                    message=f"Duplicate room name '{room.name}'.",
                    target_type="room",
                    target_id=room.id,
                )
            )
        else:
            seen_room_names.add(room.name)

        if room.pos in seen_room_pos:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DUPLICATE_ROOM_POS",
                    message=(
                        f"Room '{room.name}' (ID {room.id}) overlaps room ID {seen_room_pos[room.pos]} "
                        f"at canvas cell {room.pos}."
                    ),
                    target_type="room",
                    target_id=room.id,
                )
            )
        else:
            seen_room_pos[room.pos] = room.id

        # Row groups and row palettes
        invalid_rows: list[int] = []
        invalid_pal_rows: list[int] = []
        for r_idx, ra in enumerate(room.row_groups):
            row_grp = groups_by_name.get(ra.group)
            if row_grp is None:
                invalid_rows.append(r_idx)
            else:
                used_group_names.add(ra.group)
                if row_grp.palettes:
                    pal_name = ra.palette if ra.palette else row_grp.default_palette_name
                    if row_grp.get_named_palette(pal_name) is None:
                        invalid_pal_rows.append(r_idx)
                    else:
                        used_palettes.add((ra.group, pal_name))
        if invalid_rows:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="ROOM_INVALID_ROW_GROUP",
                    message=(
                        f"Room '{room.name}' (ID {room.id}) has unassigned/unknown group on row(s) "
                        f"{invalid_rows[0]}..{invalid_rows[-1]}."
                    ),
                    target_type="room",
                    target_id=room.id,
                    y=invalid_rows[0],
                )
            )
        if invalid_pal_rows:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="ROOM_INVALID_ROW_PALETTE",
                    message=(
                        f"Room '{room.name}' (ID {room.id}) references unknown palette on row(s) "
                        f"{invalid_pal_rows[0]}..{invalid_pal_rows[-1]}."
                    ),
                    target_type="room",
                    target_id=room.id,
                    y=invalid_pal_rows[0],
                )
            )

        # Instances: unknown object, bounds, blockable-only overlap, row-group mismatch
        occupied_blockable: dict[tuple[int, int], int] = {}
        mismatch_reported: set[tuple[int, int, int]] = set()
        for inst in room.instances:
            used_object_ids.add(inst.object_id)
            obj = objects_by_id.get(inst.object_id)
            if obj is None:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="INSTANCE_UNKNOWN_OBJECT",
                        message=(
                            f"Room '{room.name}' (ID {room.id}) references unknown object ID "
                            f"{inst.object_id} at ({inst.x}, {inst.y})."
                        ),
                        target_type="room",
                        target_id=room.id,
                        x=inst.x,
                        y=inst.y,
                    )
                )
                continue

            if (
                inst.x < 0
                or inst.y < 0
                or inst.x + obj.w > ROOM_WIDTH
                or inst.y + obj.h > ROOM_HEIGHT
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="INSTANCE_OUT_OF_BOUNDS",
                        message=(
                            f"Object '{obj.name}' at ({inst.x}, {inst.y}) in room '{room.name}' "
                            f"extends beyond {ROOM_WIDTH}x{ROOM_HEIGHT}."
                        ),
                        target_type="room",
                        target_id=room.id,
                        x=inst.x,
                        y=inst.y,
                    )
                )

            for dx, dy in obj.occupied_offsets():
                cx = inst.x + dx
                cy = inst.y + dy
                if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                    if not obj.non_blockable:
                        if (cx, cy) in occupied_blockable:
                            issues.append(
                                ValidationIssue(
                                    severity="error",
                                    code="INSTANCE_OVERLAP",
                                    message=(
                                        f"Overlapping blockable object instances at ({cx}, {cy}) in room '{room.name}' "
                                        f"(objects {occupied_blockable[(cx, cy)]} and {obj.id})."
                                    ),
                                    target_type="room",
                                    target_id=room.id,
                                    x=cx,
                                    y=cy,
                                )
                            )
                        else:
                            occupied_blockable[(cx, cy)] = obj.id

                    row_ra = room.row_groups[cy]
                    if (
                        row_ra.group in groups_by_name
                        and obj.group in groups_by_name
                        and row_ra.group != obj.group
                        and (obj.id, inst.x, cy) not in mismatch_reported
                    ):
                        mismatch_reported.add((obj.id, inst.x, cy))
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="OBJECT_ROW_GROUP_MISMATCH",
                                message=(
                                    f"Object '{obj.name}' (group '{obj.group}') in room '{room.name}' "
                                    f"at row {cy} uses row group '{row_ra.group}'."
                                ),
                                target_type="room",
                                target_id=room.id,
                                x=inst.x,
                                y=cy,
                            )
                        )

        # Informational warning: non-blockable instance completely hidden by other instances
        _, sources = project.compose_room_with_sources(room)
        visible_indices = {
            src for row in sources for src in row if src is not None
        }
        for inst_idx, inst in enumerate(room.instances):
            obj = objects_by_id.get(inst.object_id)
            if obj is None or not obj.non_blockable:
                continue
            has_in_bounds_char = any(
                0 <= inst.x + dx < ROOM_WIDTH and 0 <= inst.y + dy < ROOM_HEIGHT
                for dx, dy in obj.occupied_offsets()
            )
            if has_in_bounds_char and inst_idx not in visible_indices:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="HIDDEN_NON_BLOCKABLE_INSTANCE",
                        message=(
                            f"Non-blockable object '{obj.name}' at ({inst.x}, {inst.y}) in room "
                            f"'{room.name}' is completely hidden by other instances."
                        ),
                        target_type="room",
                        target_id=room.id,
                        x=inst.x,
                        y=inst.y,
                    )
                )

    # --- Start position ---
    if project.start is None:
        issues.append(
            ValidationIssue(
                severity="error",
                code="NO_START_ROOM",
                message="Project has no hero start position defined.",
                target_type="start",
            )
        )
    else:
        start_room = rooms_by_id.get(project.start.room_id)
        if start_room is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="NO_START_ROOM",
                    message=f"Start position references non-existent room ID {project.start.room_id}.",
                    target_type="start",
                    target_id=project.start.room_id,
                )
            )
        if not (0 <= project.start.x < ROOM_WIDTH and 0 <= project.start.y < ROOM_HEIGHT):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="START_OUT_OF_BOUNDS",
                    message=(
                        f"Start position ({project.start.x}, {project.start.y}) is outside "
                        f"{ROOM_WIDTH}x{ROOM_HEIGHT}."
                    ),
                    target_type="start",
                    target_id=project.start.room_id,
                    x=project.start.x,
                    y=project.start.y,
                )
            )

    # --- Teleports ---
    for idx, tp in enumerate(project.teleports):
        for label, ep in (("A", tp.a), ("B", tp.b)):
            if ep.room_id not in rooms_by_id:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="TELEPORT_INVALID_ROOM",
                        message=(
                            f"Teleport #{idx + 1} endpoint {label} references unknown room ID "
                            f"{ep.room_id}."
                        ),
                        target_type="teleport",
                        target_id=idx,
                    )
                )
            if not (0 <= ep.x < ROOM_WIDTH and 0 <= ep.y < ROOM_HEIGHT):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="TELEPORT_OUT_OF_BOUNDS",
                        message=(
                            f"Teleport #{idx + 1} endpoint {label} position ({ep.x}, {ep.y}) "
                            f"is outside {ROOM_WIDTH}x{ROOM_HEIGHT}."
                        ),
                        target_type="teleport",
                        target_id=idx,
                        x=ep.x,
                        y=ep.y,
                    )
                )

    # --- Warnings: unreachable rooms ---
    if project.start is not None and project.start.room_id in rooms_by_id:
        reachable = compute_reachable_rooms(project)
        for room in project.rooms:
            if room.id not in reachable:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="UNREACHABLE_ROOM",
                        message=(
                            f"Room '{room.name}' (ID {room.id}) is not reachable from the start room "
                            "via adjacency or teleports."
                        ),
                        target_type="room",
                        target_id=room.id,
                    )
                )

    # --- Warnings: adjacent edges with no common free space ---
    checked_pairs: set[tuple[int, int]] = set()
    for room in project.rooms:
        for nb in get_adjacent_rooms(project, room).values():
            pair = (min(room.id, nb.id), max(room.id, nb.id))
            if pair in checked_pairs or room.id == nb.id:
                continue
            checked_pairs.add(pair)
            if not compute_edge_passages(project, room, nb):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="ADJACENT_NO_PASSAGE",
                        message=(
                            f"Adjacent rooms '{room.name}' (ID {room.id}) and '{nb.name}' (ID {nb.id}) "
                            "have no common free space along their shared edge."
                        ),
                        target_type="room",
                        target_id=room.id,
                    )
                )

    # --- Warnings: unused objects, groups, and palettes ---
    for obj in project.objects:
        if obj.id not in used_object_ids:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="UNUSED_OBJECT",
                    message=f"Object '{obj.name}' (ID {obj.id}) is not placed in any room.",
                    target_type="object",
                    target_id=obj.id,
                )
            )

    for grp in project.object_groups:
        if grp.name not in used_group_names:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="UNUSED_GROUP",
                    message=f"Object group '{grp.name}' is not used by any object or room row.",
                    target_type="group",
                    target_id=grp.name,
                )
            )
        for pal in grp.palettes:
            if pal.name.strip() and (grp.name, pal.name) not in used_palettes:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="UNUSED_PALETTE",
                        message=(
                            f"Palette '{pal.name}' in group '{grp.name}' is not assigned to any room row."
                        ),
                        target_type="group",
                        target_id=grp.name,
                    )
                )

    issues.sort(key=lambda i: 0 if i.severity == "error" else 1)
    return issues
