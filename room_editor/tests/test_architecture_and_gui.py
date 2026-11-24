"""Architecture isolation, undo/redo depth, tools, and offscreen PySide6 GUI tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from room_editor.io.yaml_io import load_project, save_project
from room_editor.model.commands import AddInstancesCommand, UndoStack
from room_editor.model.graph import compute_room_groups
from room_editor.model.palette import Palette
from room_editor.model.project import (
    ROOM_HEIGHT,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)
from room_editor.model.tools import (
    compute_fill_placements,
    compute_line_placements,
    compute_rect_placements,
)
from room_editor.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["-platform", "offscreen"])
    return app


def test_model_and_io_do_not_import_pyside6() -> None:
    root = Path(__file__).resolve().parent.parent
    for subpkg in ("model", "io"):
        for py_file in (root / subpkg).rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("PySide6"), f"{py_file} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert not mod.startswith("PySide6"), f"{py_file} imports from {mod}"


def test_undo_redo_over_120_steps_and_dirty_tracking() -> None:
    proj = Project()
    proj.objects.append(GameObject(id=1, name="dot", group="g", w=1, h=1, chars=[[1]]))
    room = Room(id=1, name="K1", pos=(0, 0), row_groups=["g"] * ROOM_HEIGHT)
    proj.rooms.append(room)

    stack = UndoStack(max_depth=250)
    assert not stack.is_dirty

    for i in range(120):
        x = i % 40
        y = i // 40
        stack.push_and_execute(AddInstancesCommand(room, [ObjectInstance(1, x, y)]))

    assert len(room.instances) == 120
    assert stack.is_dirty

    for _ in range(120):
        stack.undo()
    assert len(room.instances) == 0
    assert not stack.is_dirty

    for _ in range(120):
        stack.redo()
    assert len(room.instances) == 120


def test_room_tools_line_rect_fill() -> None:
    proj = Project()
    proj.object_groups.append(ObjectGroup(name="g"))
    dot = GameObject(id=1, name="dot", group="g", w=1, h=1, chars=[[1]])
    proj.objects.append(dot)
    room = Room(id=1, name="K1", pos=(0, 0), row_groups=["g"] * ROOM_HEIGHT)
    proj.rooms.append(room)

    line_items = compute_line_placements(proj, room, dot, 0, 0, 3, 0)
    assert [(i.x, i.y) for i in line_items] == [(0, 0), (1, 0), (2, 0), (3, 0)]

    rect_items = compute_rect_placements(proj, room, dot, 1, 1, 3, 2)
    assert len(rect_items) == 6

    # Box room interior 3x3 surrounded by walls -> fill places 9 items
    for x in range(5):
        room.instances.append(ObjectInstance(1, x, 0))
        room.instances.append(ObjectInstance(1, x, 4))
    for y in range(1, 4):
        room.instances.append(ObjectInstance(1, 0, y))
        room.instances.append(ObjectInstance(1, 4, y))

    fill_items = compute_fill_placements(proj, room, dot, 2, 2)
    assert len(fill_items) == 9


def test_gui_smoke_acceptance_workflow(qapp: QApplication, tmp_path: Path) -> None:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    fnt_a = fonts_dir / "a.fnt"
    fnt_b = fonts_dir / "b.fnt"
    fnt_a.write_bytes(bytes((i & 0xFF) for i in range(1024)))
    fnt_b.write_bytes(bytes(((i * 3) & 0xFF) for i in range(1024)))

    win = MainWindow()
    proj = win.project
    proj.tags = ["wall", "deco"]
    proj.object_groups = [
        ObjectGroup(name="g1", charset_path="fonts/a.fnt", palette=Palette(colbk=0, colpf0=40, colpf1=202, colpf2=148, colpf3=15)),
        ObjectGroup(name="g2", charset_path="fonts/b.fnt", palette=Palette(colbk=0, colpf0=60, colpf1=180, colpf2=132, colpf3=14)),
    ]
    from room_editor.io.fnt import load_fnt

    proj.object_groups[0].charset = load_fnt(fnt_a)
    proj.object_groups[1].charset = load_fnt(fnt_b)

    proj.objects = [
        GameObject(id=1, name="brick", group="g1", tags=["wall"], w=1, h=1, chars=[[5]]),
        GameObject(id=2, name="trim", group="g2", tags=["deco"], non_blockable=True, w=1, h=1, chars=[[133]]),
    ]
    # 3 disjoint room groups + 2 teleports + mixed row groups
    r1 = Room(
        id=1,
        name="K1",
        pos=(0, 0),
        row_groups=["g1"] * 10 + ["g2"] * 10,
        instances=[ObjectInstance(1, x, 0) for x in range(10)] + [ObjectInstance(2, 5, 12)],
    )
    r2 = Room(id=2, name="K2", pos=(3, 0), row_groups=["g1"] * ROOM_HEIGHT)
    r3 = Room(id=3, name="K3", pos=(6, 0), row_groups=["g2"] * ROOM_HEIGHT)
    proj.rooms = [r1, r2, r3]
    proj.teleports = [
        Teleport(TeleportEndpoint(1, 2, 2), TeleportEndpoint(2, 2, 2)),
        Teleport(TeleportEndpoint(2, 4, 4), TeleportEndpoint(3, 4, 4)),
    ]
    proj.start = StartPosition(room_id=1, x=1, y=1)

    assert len(compute_room_groups(proj)) == 3
    win._bind_context()
    win._open_room_in_editor(1)
    win.canvas_view.repaint()
    win.room_editor_view.repaint()

    proj_file = tmp_path / "acceptance.yaml"
    save_project(proj, proj_file)
    yaml_text = proj_file.read_text(encoding="utf-8")
    assert "repeat-x: 10" in yaml_text

    reloaded = load_project(proj_file)
    assert reloaded.missing_charsets == []
    assert reloaded.project == proj
    win.close()
