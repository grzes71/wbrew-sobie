"""Deterministic YAML v4 project serialization and deserialization (F-22..F-26)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from room_editor.io.png import (
    PngLoadError,
    PngMissingError,
    load_png,
    resolve_image_path,
    to_relative_posix_path,
)
from room_editor.model.compression import (
    CompressedPlacement,
    compress_room_instances,
    decompress_placements,
)
from room_editor.model.glyphs import (
    DEFAULT_PIXEL_MAPPING,
    StampRegion,
    is_valid_pixel_mapping,
)
from room_editor.model.palette import NamedPalette, Palette
from room_editor.model.project import (
    PROJECT_VERSION,
    ROOM_HEIGHT,
    GameObject,
    ImageStatus,
    ObjectGroup,
    Project,
    Room,
    RowAssignment,
    Settings,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)


class ProjectIOError(Exception):
    """Raised when loading or saving a project fails."""


class UnsupportedVersionError(ProjectIOError):
    """Raised when a project file specifies an unsupported version."""


@dataclass
class ProjectLoadResult:
    """Loaded Project along with missing/invalid image references and glyph table mismatches."""

    project: Project
    missing_images: list[tuple[str, str]] = field(default_factory=list)
    invalid_images: list[tuple[str, str, str]] = field(default_factory=list)
    glyph_table_mismatches: list[tuple[str, str]] = field(default_factory=list)


class _FlowMap(dict):
    """Dict rendered in YAML flow style ({k: v, ...})."""


class _FlowList(list):
    """List rendered in YAML flow style ([a, b, ...])."""


class _QuotedStr(str):
    """String always emitted with double quotes in YAML (e.g. 16-char hex glyph data)."""


class CompactYamlDumper(yaml.SafeDumper):
    """SafeDumper preserving key order and rendering flow containers cleanly."""


def _represent_flow_map(dumper: yaml.SafeDumper, data: _FlowMap) -> yaml.MappingNode:
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=True)


def _represent_flow_list(dumper: yaml.SafeDumper, data: _FlowList) -> yaml.SequenceNode:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


def _represent_quoted_str(dumper: yaml.SafeDumper, data: _QuotedStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


CompactYamlDumper.add_representer(_FlowMap, _represent_flow_map)
CompactYamlDumper.add_representer(_FlowList, _represent_flow_list)
CompactYamlDumper.add_representer(_QuotedStr, _represent_quoted_str)


def _compress_entry_to_yaml(entry: CompressedPlacement) -> _FlowMap:
    item = _FlowMap({"object": entry.object_id, "x": entry.x, "y": entry.y})
    if entry.repeat_x > 1 and entry.repeat_y > 1:
        item["repeat-xy"] = _FlowList([entry.repeat_x, entry.repeat_y])
    elif entry.repeat_x > 1:
        item["repeat-x"] = entry.repeat_x
    elif entry.repeat_y > 1:
        item["repeat-y"] = entry.repeat_y
    return item


def _encode_row_assignment(
    ra: RowAssignment,
    groups_by_name: dict[str, ObjectGroup],
) -> str | _FlowMap:
    """Emit compact group string when using the group's first (default) palette."""
    grp = groups_by_name.get(ra.group)
    if grp is not None and grp.palettes:
        if ra.palette == "" or ra.palette == grp.default_palette_name:
            return ra.group
        return _FlowMap({"group": ra.group, "palette": ra.palette})
    if ra.palette == "":
        return ra.group
    return _FlowMap({"group": ra.group, "palette": ra.palette})


def _project_to_yaml_dict(project: Project) -> dict[str, Any]:
    project.resolve_row_assignments()
    project.rebuild_glyph_tables()
    objects_by_id = {o.id: o for o in project.objects}
    groups_by_name = {g.name: g for g in project.object_groups}

    groups_list = []
    for grp in project.object_groups:
        glyphs_list = [
            _FlowMap(
                {
                    "code": entry.code,
                    "data": _QuotedStr(entry.data_hex),
                    "src": _FlowList([entry.src[0], entry.src[1]]),
                }
            )
            for entry in grp.glyph_table.entries
        ]
        palettes_list = [_FlowMap(p.to_dict()) for p in grp.palettes]
        groups_list.append(
            {
                "name": grp.name,
                "image": grp.image_path,
                "pixel_mapping": _FlowList(list(grp.pixel_mapping)),
                "palettes": palettes_list,
                "glyphs": glyphs_list,
            }
        )

    objects_list = []
    for obj in project.objects:
        objects_list.append(
            _FlowMap(
                {
                    "id": obj.id,
                    "name": obj.name,
                    "group": obj.group,
                    "tags": _FlowList(list(obj.tags)),
                    "non-blockable": bool(obj.non_blockable),
                    "colpf3": bool(obj.colpf3),
                    "region": _FlowMap(obj.region.to_dict()),
                }
            )
        )

    rooms_list = []
    for room in project.rooms:
        encoded_rows = [
            _encode_row_assignment(ra, groups_by_name) for ra in room.row_groups
        ]
        if len(set(room.row_groups)) == 1:
            row_groups_val = _FlowList([encoded_rows[0]])
        else:
            row_groups_val = _FlowList(encoded_rows)

        compressed = compress_room_instances(room, objects_by_id)
        placed_list = [_compress_entry_to_yaml(entry) for entry in compressed]

        rooms_list.append(
            {
                "id": room.id,
                "name": room.name,
                "pos": _FlowList([room.pos[0], room.pos[1]]),
                "row_groups": row_groups_val,
                "placed": placed_list,
            }
        )

    teleports_list = [
        _FlowMap(
            {
                "a": _FlowMap({"room": tp.a.room_id, "x": tp.a.x, "y": tp.a.y}),
                "b": _FlowMap({"room": tp.b.room_id, "x": tp.b.x, "y": tp.b.y}),
            }
        )
        for tp in project.teleports
    ]

    start_val: _FlowMap | None = None
    if project.start is not None:
        start_val = _FlowMap(
            {
                "room": project.start.room_id,
                "x": project.start.x,
                "y": project.start.y,
            }
        )

    return {
        "version": int(project.version),
        "settings": {
            "default_palette": _FlowMap(project.settings.default_palette.to_dict()),
        },
        "tags": _FlowList(list(project.tags)),
        "object_groups": groups_list,
        "objects": objects_list,
        "rooms": rooms_list,
        "teleports": teleports_list,
        "start": start_val,
    }


def serialize_project_to_yaml(project: Project) -> str:
    """Serialize a Project to deterministic YAML v4 text, regenerating glyph tables."""
    payload = _project_to_yaml_dict(project)
    return yaml.dump(
        payload,
        Dumper=CompactYamlDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10000,
    )


def save_project(project: Project, path: Path) -> None:
    """Save a Project to a .yaml file, normalizing any absolute image paths to relative."""
    for grp in project.object_groups:
        if grp.image_path:
            ip = Path(grp.image_path)
            if ip.is_absolute():
                grp.image_path = to_relative_posix_path(ip, path)
            else:
                grp.image_path = ip.as_posix()

    yaml_text = serialize_project_to_yaml(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8", newline="\n")


def _parse_int(val: Any, field_name: str) -> int:
    if isinstance(val, bool) or not isinstance(val, int):
        raise ProjectIOError(f"Expected integer for '{field_name}', got {val!r}.")
    return int(val)


def _normalize_stored_glyphs(
    raw_glyphs: Any,
) -> tuple[list[tuple[int, str, tuple[int, int]]] | None, str]:
    """Normalize stored YAML glyphs list for comparison against derived GlyphTable."""
    if raw_glyphs is None:
        return None, "stored 'glyphs' table is missing"
    if not isinstance(raw_glyphs, list):
        return None, "stored 'glyphs' field is not a list"

    normalized: list[tuple[int, str, tuple[int, int]]] = []
    for idx, entry in enumerate(raw_glyphs):
        if not isinstance(entry, dict):
            return None, f"stored glyphs[{idx}] is not a mapping"
        code = entry.get("code")
        data = entry.get("data")
        src = entry.get("src")
        if (
            isinstance(code, bool)
            or not isinstance(code, int)
            or not isinstance(data, str)
            or not isinstance(src, list)
            or len(src) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in src)
        ):
            return None, f"stored glyphs[{idx}] has malformed fields: {entry!r}"
        normalized.append((int(code), data.strip().upper(), (int(src[0]), int(src[1]))))
    return normalized, ""


def _decode_row_entry(
    entry: Any,
    groups_by_name: dict[str, ObjectGroup],
) -> RowAssignment:
    """Decode and validate a single YAML row_groups entry (str or {group, palette})."""
    if isinstance(entry, str):
        if entry == "":
            return RowAssignment("", "")
        grp = groups_by_name.get(entry)
        if grp is None:
            raise ProjectIOError(f"Room row references unknown object group '{entry}'.")
        if not grp.palettes:
            raise ProjectIOError(
                f"Room row references object group '{entry}' which defines no palettes."
            )
        return RowAssignment(entry, grp.default_palette_name)

    if isinstance(entry, dict):
        if "group" not in entry:
            raise ProjectIOError(f"Row assignment mapping missing 'group': {entry!r}.")
        g_name = entry.get("group")
        p_name = entry.get("palette", "")
        if not isinstance(g_name, str) or not isinstance(p_name, str):
            raise ProjectIOError(
                f"Row assignment 'group' and 'palette' must be strings; got {entry!r}."
            )
        if g_name == "":
            return RowAssignment("", p_name)
        grp = groups_by_name.get(g_name)
        if grp is None:
            raise ProjectIOError(f"Room row references unknown object group '{g_name}'.")
        if not grp.palettes:
            raise ProjectIOError(
                f"Room row references object group '{g_name}' which defines no palettes."
            )
        resolved_pal = p_name if p_name else grp.default_palette_name
        if grp.get_named_palette(resolved_pal) is None:
            raise ProjectIOError(
                f"Room row references unknown palette '{resolved_pal}' in group '{g_name}'."
            )
        return RowAssignment(g_name, resolved_pal)

    raise ProjectIOError(f"Invalid room row_groups entry: {entry!r}.")


def deserialize_project_from_yaml(
    text: str,
    base_dir: Path | None = None,
) -> ProjectLoadResult:
    """Deserialize YAML v4 text into a Project, load PNGs, and verify glyph tables."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProjectIOError(f"Invalid YAML syntax: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProjectIOError("Project YAML root must be a mapping.")

    if "version" not in raw:
        raise UnsupportedVersionError("Project file is missing required 'version' field.")
    version = raw["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != PROJECT_VERSION:
        raise UnsupportedVersionError(
            f"Unsupported project version {version!r}; only version {PROJECT_VERSION} is supported."
        )

    settings_raw = raw.get("settings") or {}
    settings = Settings(
        default_palette=Palette.from_dict(settings_raw.get("default_palette"))
    )

    tags = [str(t) for t in (raw.get("tags") or [])]

    object_groups: list[ObjectGroup] = []
    missing_images: list[tuple[str, str]] = []
    invalid_images: list[tuple[str, str, str]] = []
    stored_glyphs_by_group: dict[str, Any] = {}

    for grp_raw in raw.get("object_groups") or []:
        name = str(grp_raw.get("name", ""))
        image_path = str(grp_raw.get("image", ""))
        pm_raw = grp_raw.get("pixel_mapping", list(DEFAULT_PIXEL_MAPPING))
        if isinstance(pm_raw, (list, tuple)):
            pixel_mapping = tuple(pm_raw)
        else:
            pixel_mapping = ()

        pals_raw = grp_raw.get("palettes")
        if not isinstance(pals_raw, list):
            raise ProjectIOError(
                f"Object group '{name}' must define a 'palettes' list."
            )
        try:
            palettes = [NamedPalette.from_dict(p) for p in pals_raw]
        except ValueError as exc:
            raise ProjectIOError(f"Invalid palette in group '{name}': {exc}") from exc

        image_data = None
        image_status: ImageStatus = "none"
        image_error = ""

        if image_path and base_dir is not None:
            resolved = resolve_image_path(image_path, base_dir)
            try:
                image_data = load_png(resolved)
                image_status = "ok"
            except PngMissingError:
                image_status = "missing"
                missing_images.append((name, image_path))
            except PngLoadError as exc:
                image_status = "invalid"
                image_error = str(exc)
                invalid_images.append((name, image_path, str(exc)))
        elif image_path:
            image_status = "missing"
            missing_images.append((name, image_path))

        stored_glyphs_by_group[name] = grp_raw.get("glyphs")
        object_groups.append(
            ObjectGroup(
                name=name,
                image_path=image_path,
                pixel_mapping=pixel_mapping,  # type: ignore[arg-type]
                palettes=palettes,
                image=image_data,
                image_status=image_status,
                image_error=image_error,
            )
        )

    groups_by_name = {g.name: g for g in object_groups}

    objects: list[GameObject] = []
    for obj_raw in raw.get("objects") or []:
        reg_raw = obj_raw.get("region")
        if not isinstance(reg_raw, dict):
            raise ProjectIOError(
                f"Object {obj_raw.get('id')!r} is missing required 'region' mapping."
            )
        region = StampRegion(
            x=_parse_int(reg_raw.get("x", 0), "objects[].region.x"),
            y=_parse_int(reg_raw.get("y", 0), "objects[].region.y"),
            w=_parse_int(reg_raw.get("w", 1), "objects[].region.w"),
            h=_parse_int(reg_raw.get("h", 1), "objects[].region.h"),
        )
        objects.append(
            GameObject(
                id=_parse_int(obj_raw.get("id"), "objects[].id"),
                name=str(obj_raw.get("name", "")),
                group=str(obj_raw.get("group", "")),
                tags=[str(t) for t in (obj_raw.get("tags") or [])],
                non_blockable=bool(obj_raw.get("non-blockable", False)),
                colpf3=bool(obj_raw.get("colpf3", False)),
                region=region,
            )
        )

    objects_by_id = {o.id: o for o in objects}

    rooms: list[Room] = []
    for room_raw in raw.get("rooms") or []:
        pos_raw = room_raw.get("pos") or [0, 0]
        if len(pos_raw) != 2:
            raise ProjectIOError(f"Room 'pos' must have 2 elements; got {pos_raw!r}.")
        pos = (_parse_int(pos_raw[0], "rooms[].pos[0]"), _parse_int(pos_raw[1], "rooms[].pos[1]"))

        rg_raw = room_raw.get("row_groups")
        if rg_raw is None:
            row_groups = [RowAssignment("", "")] * ROOM_HEIGHT
        elif isinstance(rg_raw, list):
            if len(rg_raw) == 1:
                row_groups = [_decode_row_entry(rg_raw[0], groups_by_name)] * ROOM_HEIGHT
            elif len(rg_raw) == ROOM_HEIGHT:
                row_groups = [_decode_row_entry(x, groups_by_name) for x in rg_raw]
            else:
                raise ProjectIOError(
                    f"Room 'row_groups' must have 1 or {ROOM_HEIGHT} entries; got {len(rg_raw)}."
                )
        else:
            row_groups = [_decode_row_entry(rg_raw, groups_by_name)] * ROOM_HEIGHT

        compressed_entries: list[CompressedPlacement] = []
        for p_raw in room_raw.get("placed") or []:
            obj_id = _parse_int(p_raw.get("object"), "placed[].object")
            px = _parse_int(p_raw.get("x"), "placed[].x")
            py = _parse_int(p_raw.get("y"), "placed[].y")
            rx = 1
            ry = 1
            if "repeat-xy" in p_raw:
                rxy = p_raw["repeat-xy"]
                if not isinstance(rxy, list) or len(rxy) != 2:
                    raise ProjectIOError(f"Invalid repeat-xy value: {rxy!r}.")
                rx = _parse_int(rxy[0], "placed[].repeat-xy[0]")
                ry = _parse_int(rxy[1], "placed[].repeat-xy[1]")
            elif "repeat-x" in p_raw:
                rx = _parse_int(p_raw["repeat-x"], "placed[].repeat-x")
            elif "repeat-y" in p_raw:
                ry = _parse_int(p_raw["repeat-y"], "placed[].repeat-y")

            if rx < 1 or ry < 1:
                raise ProjectIOError(f"Repeat counts must be >= 1; got ({rx}, {ry}).")

            compressed_entries.append(
                CompressedPlacement(
                    object_id=obj_id,
                    x=px,
                    y=py,
                    repeat_x=rx,
                    repeat_y=ry,
                )
            )

        instances = decompress_placements(compressed_entries, objects_by_id)
        rooms.append(
            Room(
                id=_parse_int(room_raw.get("id"), "rooms[].id"),
                name=str(room_raw.get("name", "")),
                pos=pos,
                row_groups=row_groups,
                instances=instances,
            )
        )

    teleports: list[Teleport] = []
    for tp_raw in raw.get("teleports") or []:
        a_raw = tp_raw.get("a") or {}
        b_raw = tp_raw.get("b") or {}
        teleports.append(
            Teleport(
                a=TeleportEndpoint(
                    room_id=_parse_int(a_raw.get("room"), "teleports[].a.room"),
                    x=_parse_int(a_raw.get("x", 0), "teleports[].a.x"),
                    y=_parse_int(a_raw.get("y", 0), "teleports[].a.y"),
                ),
                b=TeleportEndpoint(
                    room_id=_parse_int(b_raw.get("room"), "teleports[].b.room"),
                    x=_parse_int(b_raw.get("x", 0), "teleports[].b.x"),
                    y=_parse_int(b_raw.get("y", 0), "teleports[].b.y"),
                ),
            )
        )

    start_raw = raw.get("start")
    start: StartPosition | None = None
    if start_raw is not None:
        start = StartPosition(
            room_id=_parse_int(start_raw.get("room"), "start.room"),
            x=_parse_int(start_raw.get("x", 0), "start.x"),
            y=_parse_int(start_raw.get("y", 0), "start.y"),
        )

    project = Project(
        version=version,
        settings=settings,
        tags=tags,
        object_groups=object_groups,
        objects=objects,
        rooms=rooms,
        teleports=teleports,
        start=start,
    )

    glyph_table_mismatches: list[tuple[str, str]] = []
    for grp in project.object_groups:
        if grp.image is None or not is_valid_pixel_mapping(grp.pixel_mapping):
            continue
        stored_norm, err_msg = _normalize_stored_glyphs(stored_glyphs_by_group.get(grp.name))
        if stored_norm is None:
            glyph_table_mismatches.append((grp.name, err_msg))
            continue
        derived_norm = [
            (entry.code, entry.data_hex, entry.src)
            for entry in grp.glyph_table.entries
        ]
        if stored_norm != derived_norm:
            glyph_table_mismatches.append(
                (
                    grp.name,
                    f"Stored glyph table ({len(stored_norm)} glyph(s)) does not match "
                    f"PNG-derived table ({len(derived_norm)} glyph(s)).",
                )
            )

    return ProjectLoadResult(
        project=project,
        missing_images=missing_images,
        invalid_images=invalid_images,
        glyph_table_mismatches=glyph_table_mismatches,
    )


def load_project(path: Path) -> ProjectLoadResult:
    """Load a Project from a .yaml file on disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectIOError(f"Failed to read project file '{path}': {exc}") from exc
    return deserialize_project_from_yaml(text, base_dir=path.resolve().parent)
