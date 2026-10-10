"""A sampled raster whose scene extent remains the original image extent."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsPixmapItem


class ImagePixmapItem(QGraphicsPixmapItem):
    """Paint a small texture in original pixel coordinates without enlarging it.

    The last sampled row/column can extend past the logical image boundary.
    Clipping, and a negative offset after a flip, preserve the same block
    alignment as repeating samples then cropping and orienting the full image.
    """

    def __init__(self) -> None:
        super().__init__()
        self._logical_rect = QRectF()
        self._image_to_scene = QTransform()

    @property
    def image_to_scene(self) -> QTransform:
        return QTransform(self._image_to_scene)

    def set_raster(
        self,
        pixmap: QPixmap,
        *,
        logical_size: tuple[int, int] | None = None,
        sample_step: int | None = None,
        sampling_offset: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        self.prepareGeometryChange()
        if pixmap.isNull():
            self._logical_rect = QRectF()
            self._image_to_scene = QTransform()
        else:
            width, height = logical_size or (pixmap.width(), pixmap.height())
            if width <= 0 or height <= 0:
                raise ValueError("Logical image dimensions must be positive")
            if sample_step is not None and sample_step < 1:
                raise ValueError("Sample step must be positive")
            scale_x = sample_step if sample_step is not None else width / pixmap.width()
            scale_y = sample_step if sample_step is not None else height / pixmap.height()
            self._logical_rect = QRectF(0.0, 0.0, float(width), float(height))
            self._image_to_scene = QTransform(
                float(scale_x), 0.0, 0.0, float(scale_y),
                float(sampling_offset[0]), float(sampling_offset[1]),
            )
        self.setPixmap(pixmap)
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(self._logical_rect)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self._logical_rect)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pixmap = self.pixmap()
        if pixmap.isNull():
            return
        painter.save()
        try:
            painter.setClipRect(self._logical_rect, Qt.ClipOperation.IntersectClip)
            painter.setRenderHint(
                QPainter.RenderHint.SmoothPixmapTransform,
                self.transformationMode() == Qt.TransformationMode.SmoothTransformation,
            )
            source = QRectF(0.0, 0.0, float(pixmap.width()), float(pixmap.height()))
            target = self._image_to_scene.mapRect(source)
            painter.drawPixmap(target, pixmap, source)
        finally:
            painter.restore()
