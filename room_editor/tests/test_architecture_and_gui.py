"""Architecture isolation, undo/redo depth, tools, and offscreen PySide6 GUI tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from room_editor.io.png import load_png
from room_editor.io.yaml_io import load_project, save_project
from room_editor.model.commands import AddInstancesCommand, UndoStack
from room_editor.model.glyphs import IndexedImage, StampRegion
from room_editor.model.graph import compute_room_groups
from room_editor.model.palette import NamedPalette, Palette
from room_editor.model.project import (
    ROOM_DISPLAY_HEIGHT,
    ROOM_DISPLAY_WIDTH,
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


def test_model_and_io_do_not_import_pyside6_and_model_has_no_pil() -> None:
    root = Path(__file__).resolve().parent.parent
    for subpkg in ("model", "io"):
        for py_file in (root / subpkg).rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("PySide6"), f"{py_file} imports {alias.name}"
                        if subpkg == "model":
                            assert not alias.name.startswith("PIL"), f"{py_file} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert not mod.startswith("PySide6"), f"{py_file} imports from {mod}"
                    if subpkg == "model":
                        assert not mod.startswith("PIL"), f"{py_file} imports from {mod}"


def test_undo_redo_over_120_steps_and_dirty_tracking() -> None:
    img = IndexedImage(width=4, height=8, pixels=bytes([1] * 32))
    proj = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[GameObject(id=1, name="dot", group="g", region=StampRegion(0, 0, 1, 1))],
        rooms=[Room(id=1, name="K1", pos=(0, 0), row_groups=["g"] * ROOM_HEIGHT)],
    )
    room = proj.rooms[0]

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
    img = IndexedImage(width=4, height=8, pixels=bytes([1] * 32))
    proj = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[GameObject(id=1, name="dot", group="g", region=StampRegion(0, 0, 1, 1))],
        rooms=[Room(id=1, name="K1", pos=(0, 0), row_groups=["g"] * ROOM_HEIGHT)],
    )
    dot = proj.objects[0]
    room = proj.rooms[0]

    line_items = compute_line_placements(proj, room, dot, 0, 0, 3, 0)
    assert [(i.x, i.y) for i in line_items] == [(0, 0), (1, 0), (2, 0), (3, 0)]

    rect_items = compute_rect_placements(proj, room, dot, 1, 1, 3, 2)
    assert len(rect_items) == 6

    for x in range(5):
        room.instances.append(ObjectInstance(1, x, 0))
        room.instances.append(ObjectInstance(1, x, 4))
    for y in range(1, 4):
        room.instances.append(ObjectInstance(1, 0, y))
        room.instances.append(ObjectInstance(1, 4, y))

    fill_items = compute_fill_placements(proj, room, dot, 2, 2)
    assert len(fill_items) == 9


def _make_png(path: Path, seed: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("P", (8, 8))
    img.putpalette([0, 0, 0, 200, 100, 50, 50, 200, 100, 50, 100, 200] + [0] * (768 - 12))
    img.putdata([((x + y + seed) % 3) + 1 for y in range(8) for x in range(8)])
    img.save(path, format="PNG")
    return path


def test_gui_smoke_acceptance_workflow(qapp: QApplication, tmp_path: Path) -> None:
    png_a = _make_png(tmp_path / "images" / "a.png", 1)
    png_b = _make_png(tmp_path / "images" / "b.png", 2)

    win = MainWindow()
    proj = win.project
    proj.tags = ["wall", "deco"]
    proj.object_groups = [
        ObjectGroup(
            name="g1",
            image_path="images/a.png",
            palettes=[NamedPalette("default", Palette(colbk=0, colpf0=40, colpf1=202, colpf2=148, colpf3=15))],
            image=load_png(png_a),
        ),
        ObjectGroup(
            name="g2",
            image_path="images/b.png",
            palettes=[NamedPalette("default", Palette(colbk=0, colpf0=60, colpf1=180, colpf2=132, colpf3=14))],
            image=load_png(png_b),
        ),
    ]
    proj.objects = [
        GameObject(id=1, name="brick", group="g1", tags=["wall"], region=StampRegion(0, 0, 1, 1)),
        GameObject(id=2, name="trim", group="g2", tags=["deco"], non_blockable=True, pickable=True, colpf3=True, region=StampRegion(1, 0, 1, 1)),
    ]
    assert proj.objects[0].pickable is False
    assert not win.objects_view._chk_pickable.isChecked()
    r1 = Room(
        id=1,
        name="K1",
        pos=(0, 0),
        row_groups=["g1"] * 12 + ["g2"] * 12,
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
    proj.rebuild_glyph_tables()

    assert len(compute_room_groups(proj)) == 3
    win._bind_context()
    win._open_room_in_editor(1)
    rendered = win.renderer.render_room_image(proj, r1)
    assert (rendered.width(), rendered.height()) == (ROOM_DISPLAY_WIDTH, ROOM_DISPLAY_HEIGHT)
    win.canvas_view.repaint()
    win.room_editor_view.repaint()
    win.objects_view.repaint()

    proj_file = tmp_path / "acceptance.yaml"
    save_project(proj, proj_file)
    yaml_text = proj_file.read_text(encoding="utf-8")
    assert "version: 4" in yaml_text
    assert "repeat-x: 10" in yaml_text

    reloaded = load_project(proj_file)
    assert reloaded.missing_images == []
    assert reloaded.invalid_images == []
    assert reloaded.glyph_table_mismatches == []
    assert reloaded.project == proj
    win.close()
