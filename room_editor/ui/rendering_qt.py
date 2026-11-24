"""Qt rendering helpers for ANTIC 4 characters, objects, charsets, and rooms."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from room_editor.model.charset import CharsetData
from room_editor.model.palette import PalPaletteTable, Palette
from room_editor.model.project import (
    ROOM_HEIGHT,
    ROOM_WIDTH,
    GameObject,
    ObjectGroup,
    Project,
    Room,
)

CHAR_PX_W = 8  # 4 ANTIC 4 pixels x 2:1 aspect
CHAR_PX_H = 8  # 8 scanlines


class QtRenderer:
    """Cached ANTIC 4 renderer converting model objects/rooms to QImage/QPixmap."""

    def __init__(self, pal_table: PalPaletteTable) -> None:
        self.pal_table = pal_table
        self._glyph_cache: dict[tuple[bytes, int, tuple[int, ...]], QImage] = {}

    def clear_cache(self) -> None:
        self._glyph_cache.clear()

    def glyph_image(
        self,
        charset: CharsetData,
        char_code: int,
        palette: Palette,
    ) -> QImage:
        """Return an 8x8 QImage (2:1 ANTIC 4 pixel aspect) for char_code."""
        pal_key = (
            palette.colbk,
            palette.colpf0,
            palette.colpf1,
            palette.colpf2,
            palette.colpf3,
        )
        key = (charset.raw, char_code, pal_key)
        cached = self._glyph_cache.get(key)
        if cached is not None:
            return cached

        rgba = charset.render_glyph_rgba_2x1(char_code, palette, self.pal_table)
        img = QImage(rgba, CHAR_PX_W, CHAR_PX_H, CHAR_PX_W * 4, QImage.Format.Format_RGBA8888).copy()
        self._glyph_cache[key] = img
        return img

    def render_room_image(self, project: Project, room: Room) -> QImage:
        """Render a full 40x20 room as a 320x160 QImage using per-row groups (F-18)."""
        img = QImage(
            ROOM_WIDTH * CHAR_PX_W,
            ROOM_HEIGHT * CHAR_PX_H,
            QImage.Format.Format_RGBA8888,
        )
        painter = QPainter(img)

        # Fill each row band with its row group's COLBK background color
        groups_by_name = {g.name: g for g in project.object_groups}
        default_bg = self.pal_table.rgb(project.settings.default_palette.colbk)
        for row_idx in range(ROOM_HEIGHT):
            grp = groups_by_name.get(room.row_groups[row_idx])
            bg_rgb = (
                self.pal_table.rgb(grp.palette.colbk) if grp is not None else default_bg
            )
            painter.fillRect(
                0,
                row_idx * CHAR_PX_H,
                ROOM_WIDTH * CHAR_PX_W,
                CHAR_PX_H,
                QColor(*bg_rgb),
            )

        # Compose 40x20 grid (Layer 1 non-blockable in z-order, then Layer 2 blockable; 0=transparent)
        # and draw each non-zero cell with the charset & palette of the row it lies in (F-18).
        grid = project.compose_room(room)
        for cy in range(ROOM_HEIGHT):
            row_grp = groups_by_name.get(room.row_groups[cy])
            py = cy * CHAR_PX_H
            for cx in range(ROOM_WIDTH):
                code = grid[cy][cx]
                if code == 0:
                    continue
                px = cx * CHAR_PX_W
                if row_grp is not None and row_grp.charset is not None:
                    g_img = self.glyph_image(row_grp.charset, code, row_grp.palette)
                    painter.drawImage(px, py, g_img)
                else:
                    painter.fillRect(px, py, CHAR_PX_W, CHAR_PX_H, QColor(120, 60, 60))

        painter.end()
        return img

    def render_object_pixmap(
        self,
        obj: GameObject,
        group: ObjectGroup | None,
        scale: int = 2,
    ) -> QPixmap:
        """Render an object stamp preview with transparent/checkerboard empty cells."""
        w_px = max(1, obj.w) * CHAR_PX_W * scale
        h_px = max(1, obj.h) * CHAR_PX_H * scale
        pix = QPixmap(w_px, h_px)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)

        for dy in range(obj.h):
            for dx in range(obj.w):
                code = obj.chars[dy][dx] if dy < len(obj.chars) and dx < len(obj.chars[dy]) else 0
                rx = dx * CHAR_PX_W * scale
                ry = dy * CHAR_PX_H * scale
                rw = CHAR_PX_W * scale
                rh = CHAR_PX_H * scale
                if code == 0:
                    painter.fillRect(rx, ry, rw, rh, QColor(45, 45, 50, 120))
                elif group is not None and group.charset is not None:
                    g_img = self.glyph_image(group.charset, code, group.palette)
                    painter.drawImage(
                        rx,
                        ry,
                        g_img.scaled(rw, rh, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation),
                    )
                else:
                    painter.fillRect(rx, ry, rw, rh, QColor(120, 80, 80))

        painter.end()
        return pix

    def render_charset_grid_pixmap(
        self,
        group: ObjectGroup | None,
        cols: int = 16,
        cell_px: int = 16,
    ) -> QPixmap:
        """Render all 256 codes (0..127 COLPF2, 128..255 COLPF3) in a cols x rows grid."""
        rows = (256 + cols - 1) // cols
        pix = QPixmap(cols * cell_px, rows * cell_px)
        pix.fill(QColor(30, 30, 34))
        if group is None or group.charset is None:
            return pix

        painter = QPainter(pix)
        for code in range(256):
            gx = (code % cols) * cell_px
            gy = (code // cols) * cell_px
            if code == 0:
                # Code 0 represents transparent/empty in objects
                painter.fillRect(gx, gy, cell_px, cell_px, QColor(40, 40, 46))
                painter.setPen(QColor(130, 130, 140))
                painter.drawLine(gx + 2, gy + 2, gx + cell_px - 3, gy + cell_px - 3)
                painter.drawLine(gx + cell_px - 3, gy + 2, gx + 2, gy + cell_px - 3)
            else:
                g_img = self.glyph_image(group.charset, code, group.palette)
                painter.drawImage(
                    gx,
                    gy,
                    g_img.scaled(
                        cell_px,
                        cell_px,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    ),
                )
        painter.end()
        return pix
