import pytest
from PySide6.QtWidgets import QApplication
from sprite_studio.models import Sprite, Frame
from sprite_studio.main import MainWindow
from sprite_studio.widgets.timeline import TimelineWidget

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["-platform", "offscreen"])
    return app

def test_timeline_widget_reverse_button(qapp):
    timeline = TimelineWidget()
    assert hasattr(timeline, "btn_reverse")
    assert timeline.btn_reverse.text() == "Reverse"

    emitted = []
    timeline.reverse_requested.connect(lambda: emitted.append(True))
    timeline.btn_reverse.click()
    assert len(emitted) == 1

def test_main_window_reverse_frames(qapp):
    win = MainWindow()
    sprite = Sprite(id=1, height=2)
    # Create 5 distinct frames
    f1 = Frame(pixels=["10000000", "00000000"])
    f2 = Frame(pixels=["01000000", "00000000"])
    f3 = Frame(pixels=["00100000", "00000000"])
    f4 = Frame(pixels=["00010000", "00000000"])
    f5 = Frame(pixels=["00001000", "00000000"])
    sprite.frames = [f1, f2, f3, f4, f5]

    win.project.sprites.append(sprite)
    win._on_sprite_selected(sprite)
    win._on_frame_selected(0) # Select Frame 1 (index 0)

    assert win.current_sprite.frames == [f1, f2, f3, f4, f5]
    assert win.current_frame_idx == 0

    # Trigger reverse
    win.timeline.btn_reverse.click()

    # Order should now be f5, f4, f3, f2, f1
    assert win.current_sprite.frames == [f5, f4, f3, f2, f1]
    # Selected frame should track the original frame (f1 now at index 4)
    assert win.current_frame_idx == 4
    assert win.current_sprite.frames[win.current_frame_idx] == f1

    # Test Undo
    win._undo()
    assert win.current_sprite.frames == [f1, f2, f3, f4, f5]
    assert win.current_frame_idx == 0

    # Test Redo
    win._redo()
    assert win.current_sprite.frames == [f5, f4, f3, f2, f1]
    assert win.current_frame_idx == 4

def test_reverse_single_or_empty_frame(qapp):
    win = MainWindow()
    sprite = Sprite(id=2, height=1)
    sprite.frames = [Frame(pixels=["11111111"])]
    win.project.sprites.append(sprite)
    win._on_sprite_selected(sprite)

    initial_frames = list(sprite.frames)
    win.timeline.btn_reverse.click()
    assert sprite.frames == initial_frames

