from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


def _make_crosshair_cursor(size: int = 32, color: QColor | None = None) -> QCursor:
    """Build a bright magnifier-style cursor that stays visible on dark backgrounds."""

    if color is None:
        color = QColor(0, 255, 128)  # lime green
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    mid = size // 2
    gap = 4
    ring_radius = max(7, size // 4)
    outline = QPen(QColor(0, 0, 0, 180))
    outline.setWidth(3)
    p.setPen(outline)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(mid - ring_radius, mid - ring_radius, ring_radius * 2, ring_radius * 2)
    p.drawLine(mid + ring_radius - 1, mid + ring_radius - 1, size - 4, size - 4)
    for x1, y1, x2, y2 in (
        (mid, mid - ring_radius + 2, mid, mid - gap),
        (mid, mid + gap, mid, mid + ring_radius - 2),
        (mid - ring_radius + 2, mid, mid - gap, mid),
        (mid + gap, mid, mid + ring_radius - 2, mid),
    ):
        p.drawLine(x1, y1, x2, y2)
    inner = QPen(color)
    inner.setWidth(2)
    p.setPen(inner)
    p.drawEllipse(mid - ring_radius, mid - ring_radius, ring_radius * 2, ring_radius * 2)
    p.drawLine(mid + ring_radius - 1, mid + ring_radius - 1, size - 4, size - 4)
    for x1, y1, x2, y2 in (
        (mid, mid - ring_radius + 2, mid, mid - gap),
        (mid, mid + gap, mid, mid + ring_radius - 2),
        (mid - ring_radius + 2, mid, mid - gap, mid),
        (mid + gap, mid, mid + ring_radius - 2, mid),
    ):
        p.drawLine(x1, y1, x2, y2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(mid - 1, mid - 1, 3, 3)
    p.end()
    return QCursor(pm, mid, mid)


class MagnifierOverlay(QWidget):
    """Floating magnifier that follows the cursor and shows a zoomed view.

    Owned by ``ImageCanvas``. The magnification is *relative to the current
    viewport zoom*: it samples from the source QImage using the canvas scale
    factor so that zooming the canvas in also zooms the magnifier content,
    without the cost of a viewport grab on every mouse move.
    """

    SIZE = 200
    _OFFSET = 20  # px gap between cursor and overlay edge

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._magnification: int = 4
        self._canvas_scale: float = 1.0
        self._scene_x: float = 0.0
        self._scene_y: float = 0.0
        self._source_image: QImage | None = None
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_magnification(self, value: int) -> None:
        self._magnification = max(2, min(value, 16))
        self.update()

    def update_position(
        self,
        source_image: QImage | None,
        scene_x: float,
        scene_y: float,
        view_pos: QPoint,
        canvas_scale: float,
    ) -> None:
        """Reposition near *view_pos* and repaint from *source_image*."""

        self._source_image = source_image
        self._scene_x = scene_x
        self._scene_y = scene_y
        self._canvas_scale = canvas_scale

        # Place the overlay offset from the cursor, flipping when near edges.
        parent = self.parentWidget()
        if parent is None:
            return
        pw, ph = parent.width(), parent.height()
        x = view_pos.x() + self._OFFSET
        y = view_pos.y() + self._OFFSET
        if x + self.SIZE > pw:
            x = view_pos.x() - self._OFFSET - self.SIZE
        if y + self.SIZE > ph:
            y = view_pos.y() - self._OFFSET - self.SIZE

        self.move(x, y)
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        if self._source_image is None or self._source_image.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # -- background --
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRoundedRect(self.rect(), 6, 6)

        # -- magnified image region --
        # Effective magnification = user magnification * current canvas zoom.
        # src_span = how many source-image pixels fit in the overlay.
        effective_mag = self._magnification * self._canvas_scale
        src_span = self.SIZE / effective_mag
        sx = self._scene_x - src_span / 2.0
        sy = self._scene_y - src_span / 2.0

        src_rect = QRectF(sx, sy, src_span, src_span)
        dst_rect = QRectF(0, 0, self.SIZE, self.SIZE)

        painter.setClipRect(self.rect())
        painter.drawImage(dst_rect, self._source_image, src_rect)

        # -- crosshair --
        mag = self._magnification
        pen = QPen(QColor(0, 255, 128, 200))
        pen.setWidth(1)
        painter.setPen(pen)
        mid = self.SIZE / 2.0
        gap = mag * 0.6
        painter.drawLine(int(mid), 0, int(mid), int(mid - gap))
        painter.drawLine(int(mid), int(mid + gap), int(mid), self.SIZE)
        painter.drawLine(0, int(mid), int(mid - gap), int(mid))
        painter.drawLine(int(mid + gap), int(mid), self.SIZE, int(mid))

        # -- pixel coordinate label --
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        text = self.coordinate_text()
        text_rect = painter.fontMetrics().boundingRect(text)

        label_x = 4
        label_y = self.SIZE - 6
        bg_rect = QRectF(
            label_x - 2,
            label_y - text_rect.height(),
            text_rect.width() + 4,
            text_rect.height() + 4,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRoundedRect(bg_rect, 3, 3)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(label_x, label_y, text)

        # -- border --
        border_pen = QPen(QColor(200, 200, 200, 180))
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)

    def coordinate_text(self) -> str:
        """Return the currently sampled source-image coordinates for the label."""

        return f"({self._scene_x:.2f}, {self._scene_y:.2f})"
