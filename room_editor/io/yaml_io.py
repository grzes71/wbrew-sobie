"""Deterministic YAML project serialization and deserialization (F-22..F-26)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from room_editor.io.fnt import FontLoadError, load_fnt, resolve_fnt_path, to_relative_posix_path
from room_editor.model.compression import (
    CompressedPlacement,
    compress_room_instances,
    decompress_placements,
)
from room_editor.model.palette import Palette
from room_editor.model.project import (
    PROJECT_VERSION,
    ROOM_HEIGHT,
    GameObject,
    ObjectGroup,
    Project,
    Room,
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
    """Loaded Project along with any missing/invalid charset references."""

    project: Project
    missing_charsets: list[tuple[str, str]]  # (group_name, stored_charset_path)


class _FlowMap(dict):
    """Dict rendered in YAML flow style ({k: v, ...})."""


class _FlowList(list):
    """List rendered in YAML flow style ([a, b, ...])."""


class CompactYamlDumper(yaml.SafeDumper):
    """SafeDumper preserving key order and rendering flow containers cleanly."""


def _represent_flow_map(dumper: yaml.SafeDumper, data: _FlowMap) -> yaml.MappingNode:
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=True)


def _represent_flow_list(dumper: yaml.SafeDumper, data: _FlowList) -> yaml.SequenceNode:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


CompactYamlDumper.add_representer(_FlowMap, _represent_flow_map)
CompactYamlDumper.add_representer(_FlowList, _represent_flow_list)


def _compress_entry_to_yaml(entry: CompressedPlacement) -> _FlowMap:
    item = _FlowMap({"object": entry.object_id, "x": entry.x, "y": entry.y})
    if entry.repeat_x > 1 and entry.repeat_y > 1:
        item["repeat-xy"] = _FlowList([entry.repeat_x, entry.repeat_y])
    elif entry.repeat_x > 1:
        item["repeat-x"] = entry.repeat_x
    elif entry.repeat_y > 1:
        item["repeat-y"] = entry.repeat_y
    return item


def _project_to_yaml_dict(project: Project) -> dict[str, Any]:
    objects_by_id = {o.id: o for o in project.objects}

    groups_list = []
    for grp in project.object_groups:
        groups_list.append(
            {
                "name": grp.name,
                "charset": grp.charset_path,
                "palette": _FlowMap(grp.palette.to_dict()),
            }
        )

    objects_list = []
    for obj in project.objects:
        chars_flow = _FlowList([_FlowList([int(c) for c in row]) for row in obj.chars])
        objects_list.append(
            _FlowMap(
                {
                    "id": obj.id,
                    "name": obj.name,
                    "group": obj.group,
                    "tags": _FlowList(list(obj.tags)),
                    "non-blockable": bool(obj.non_blockable),
                    "w": obj.w,
                    "h": obj.h,
                    "chars": chars_flow,
                }
            )
        )

    rooms_list = []
    for room in project.rooms:
        if len(set(room.row_groups)) == 1:
            row_groups_val = _FlowList([room.row_groups[0]])
        else:
            row_groups_val = _FlowList(list(room.row_groups))

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
    """Serialize a Project to deterministic YAML text."""
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
    """Save a Project to a .yaml file, normalizing any absolute charset paths to relative."""
    for grp in project.object_groups:
        if grp.charset_path:
            cp = Path(grp.charset_path)
            if cp.is_absolute():
                grp.charset_path = to_relative_posix_path(cp, path)
            else:
                grp.charset_path = cp.as_posix()

    yaml_text = serialize_project_to_yaml(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8", newline="\n")


def _parse_int(val: Any, field_name: str) -> int:
    if isinstance(val, bool) or not isinstance(val, int):
        raise ProjectIOError(f"Expected integer for '{field_name}', got {val!r}.")
    return int(val)


def deserialize_project_from_yaml(
    text: str,
    base_dir: Path | None = None,
) -> ProjectLoadResult:
    """Deserialize YAML text into a Project and resolve linked .fnt files."""
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
    missing_charsets: list[tuple[str, str]] = []
    for grp_raw in raw.get("object_groups") or []:
        name = str(grp_raw.get("name", ""))
        charset_path = str(grp_raw.get("charset", ""))
        palette = Palette.from_dict(grp_raw.get("palette"))
        charset_data = None
        if charset_path and base_dir is not None:
            resolved = resolve_fnt_path(charset_path, base_dir)
            try:
                charset_data = load_fnt(resolved)
            except FontLoadError:
                missing_charsets.append((name, charset_path))
        elif not charset_path:
            missing_charsets.append((name, ""))
        object_groups.append(
            ObjectGroup(
                name=name,
                charset_path=charset_path,
                palette=palette,
                charset=charset_data,
            )
        )

    objects: list[GameObject] = []
    for obj_raw in raw.get("objects") or []:
        chars_raw = obj_raw.get("chars") or []
        chars = [[int(c) & 0xFF for c in row] for row in chars_raw]
        objects.append(
            GameObject(
                id=_parse_int(obj_raw.get("id"), "objects[].id"),
                name=str(obj_raw.get("name", "")),
                group=str(obj_raw.get("group", "")),
                tags=[str(t) for t in (obj_raw.get("tags") or [])],
                non_blockable=bool(obj_raw.get("non-blockable", False)),
                w=_parse_int(obj_raw.get("w", 1), "objects[].w"),
                h=_parse_int(obj_raw.get("h", 1), "objects[].h"),
                chars=chars,
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
            row_groups = [""] * ROOM_HEIGHT
        elif isinstance(rg_raw, list):
            if len(rg_raw) == 1:
                row_groups = [str(rg_raw[0])] * ROOM_HEIGHT
            elif len(rg_raw) == ROOM_HEIGHT:
                row_groups = [str(x) for x in rg_raw]
            else:
                raise ProjectIOError(
                    f"Room 'row_groups' must have 1 or {ROOM_HEIGHT} entries; got {len(rg_raw)}."
                )
        else:
            row_groups = [str(rg_raw)] * ROOM_HEIGHT

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
    return ProjectLoadResult(project=project, missing_charsets=missing_charsets)


def load_project(path: Path) -> ProjectLoadResult:
    """Load a Project from a .yaml file on disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectIOError(f"Failed to read project file '{path}': {exc}") from exc
    return deserialize_project_from_yaml(text, base_dir=path.resolve().parent)
