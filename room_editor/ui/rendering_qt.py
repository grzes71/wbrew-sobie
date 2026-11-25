"""Qt rendering helpers for ANTIC 4 glyphs, indexed PNGs, objects, and rooms."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from room_editor.model.glyphs import (
    GLYPH_HEIGHT,
    GLYPH_WIDTH,
    IndexedImage,
    render_glyph_bytes_rgba_2x1,
)
from room_editor.model.palette import PalPaletteTable, Palette
from room_editor.model.project import (
    ANTIC4_PIXEL_ASPECT_X,
    ROOM_DISPLAY_HEIGHT,
    ROOM_DISPLAY_WIDTH,
    ROOM_HEIGHT,
    ROOM_WIDTH,
    GameObject,
    ObjectGroup,
    Project,
    Room,
)

CHAR_PX_W = GLYPH_WIDTH * ANTIC4_PIXEL_ASPECT_X  # 4 ANTIC 4 pixels x 2:1 aspect
CHAR_PX_H = GLYPH_HEIGHT  # 8 scanlines


class QtRenderer:
    """Cached ANTIC 4 renderer converting model objects/rooms/images to QImage/QPixmap."""

    def __init__(self, pal_table: PalPaletteTable) -> None:
        self.pal_table = pal_table
        self._glyph_cache: dict[tuple[bytes, tuple[int, ...], bool], QImage] = {}
        self._image_cache: dict[
            tuple[bytes, int, int, tuple[int, ...], tuple[int, ...], bool, bool],
            QImage,
        ] = {}

    def clear_cache(self) -> None:
        self._glyph_cache.clear()
        self._image_cache.clear()

    @staticmethod
    def _pal_key(palette: Palette) -> tuple[int, ...]:
        return (
            palette.colbk,
            palette.colpf0,
            palette.colpf1,
            palette.colpf2,
            palette.colpf3,
        )

    def glyph_image(
        self,
        glyph_bytes: bytes,
        palette: Palette,
        *,
        colpf3: bool = False,
    ) -> QImage:
        """Return an 8x8 QImage (2:1 ANTIC 4 pixel aspect) for 8 glyph bitmap bytes."""
        pal_key = self._pal_key(palette)
        key = (glyph_bytes, pal_key, bool(colpf3))
        cached = self._glyph_cache.get(key)
        if cached is not None:
            return cached

        rgba = render_glyph_bytes_rgba_2x1(
            glyph_bytes, palette, self.pal_table, colpf3=colpf3
        )
        img = QImage(
            rgba, CHAR_PX_W, CHAR_PX_H, CHAR_PX_W * 4, QImage.Format.Format_RGBA8888
        ).copy()
        self._glyph_cache[key] = img
        return img

    def indexed_image_qimage(
        self,
        image: IndexedImage,
        palette: Palette,
        pixel_mapping: tuple[int, int, int, int],
        *,
        colpf3: bool = False,
        use_file_palette: bool = False,
    ) -> QImage:
        """Return a (width * 2) x height QImage (2:1 ANTIC 4 aspect) for an IndexedImage."""
        pal_key = self._pal_key(palette)
        key = (
            image.pixels,
            image.width,
            image.height,
            pal_key,
            tuple(pixel_mapping),
            bool(colpf3),
            bool(use_file_palette),
        )
        cached = self._image_cache.get(key)
        if cached is not None:
            return cached

        rgba = image.render_rgba_2x1(
            palette,
            self.pal_table,
            pixel_mapping,
            colpf3=colpf3,
            use_file_palette=use_file_palette,
        )
        w2x = image.width * 2
        qimg = QImage(
            rgba, w2x, image.height, w2x * 4, QImage.Format.Format_RGBA8888
        ).copy()
        self._image_cache[key] = qimg
        return qimg

    def render_room_image(self, project: Project, room: Room) -> QImage:
        """Render a full 40x24 room as a 320x192 QImage using per-row (group, palette)."""
        img = QImage(
            ROOM_DISPLAY_WIDTH,
            ROOM_DISPLAY_HEIGHT,
            QImage.Format.Format_RGBA8888,
        )
        painter = QPainter(img)

        groups_by_name = {g.name: g for g in project.object_groups}
        default_bg = self.pal_table.rgb(project.settings.default_palette.colbk)
        for row_idx in range(ROOM_HEIGHT):
            ra = room.row_groups[row_idx]
            grp = groups_by_name.get(ra.group)
            row_pal = grp.get_palette(ra.palette) if grp is not None else None
            bg_rgb = (
                self.pal_table.rgb(row_pal.colbk) if row_pal is not None else default_bg
            )
            painter.fillRect(
                0,
                row_idx * CHAR_PX_H,
                ROOM_DISPLAY_WIDTH,
                CHAR_PX_H,
                QColor(*bg_rgb),
            )

        grid = project.compose_room(room)
        for cy in range(ROOM_HEIGHT):
            ra = room.row_groups[cy]
            row_grp = groups_by_name.get(ra.group)
            row_pal = row_grp.get_palette(ra.palette) if row_grp is not None else None
            py = cy * CHAR_PX_H
            for cx in range(ROOM_WIDTH):
                code = grid[cy][cx]
                if code == 0:
                    continue
                px = cx * CHAR_PX_W
                if row_grp is None or row_grp.image is None or row_pal is None:
                    painter.fillRect(px, py, CHAR_PX_W, CHAR_PX_H, QColor(120, 60, 60))
                    continue
                glyph_bytes = row_grp.glyph_table.glyph_bytes(code)
                if glyph_bytes is None:
                    continue
                g_img = self.glyph_image(
                    glyph_bytes,
                    row_pal,
                    colpf3=bool(code & 0x80),
                )
                painter.drawImage(px, py, g_img)

        painter.end()
        return img

    def render_object_pixmap(
        self,
        obj: GameObject,
        group: ObjectGroup | None,
        scale: int = 2,
        project: Project | None = None,
        palette: Palette | None = None,
    ) -> QPixmap:
        """Render an object stamp preview using the given palette (or group's default)."""
        w_px = max(1, obj.w) * CHAR_PX_W * scale
        h_px = max(1, obj.h) * CHAR_PX_H * scale
        pix = QPixmap(w_px, h_px)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)

        active_pal = (
            palette
            if palette is not None
            else (group.default_palette if group is not None else None)
        )
        has_error = project is not None and bool(project.object_placement_error(obj))
        for dy in range(obj.h):
            for dx in range(obj.w):
                code = (
                    obj.chars[dy][dx]
                    if dy < len(obj.chars) and dx < len(obj.chars[dy])
                    else 0
                )
                rx = dx * CHAR_PX_W * scale
                ry = dy * CHAR_PX_H * scale
                rw = CHAR_PX_W * scale
                rh = CHAR_PX_H * scale
                if has_error or group is None or group.image is None or active_pal is None:
                    painter.fillRect(rx, ry, rw, rh, QColor(120, 70, 70))
                elif code == 0:
                    painter.fillRect(rx, ry, rw, rh, QColor(45, 45, 50, 120))
                else:
                    glyph_bytes = group.glyph_table.glyph_bytes(code)
                    if glyph_bytes is None:
                        painter.fillRect(rx, ry, rw, rh, QColor(120, 70, 70))
                    else:
                        g_img = self.glyph_image(
                            glyph_bytes,
                            active_pal,
                            colpf3=bool(code & 0x80),
                        )
                        painter.drawImage(
                            rx,
                            ry,
                            g_img.scaled(
                                rw,
                                rh,
                                Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.FastTransformation,
                            ),
                        )

        painter.end()
        return pix
