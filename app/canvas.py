from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView, QRubberBand

from .contracts import CanvasImageState, CanvasOverlayState, ViewFeedbackState
from ..core.contracts import ROISelection, ZoomState


class ImageCanvas(QGraphicsView):
    """Image display and interaction skeleton.

    View contract:
    - Input from `MainWindow`: image frames and source catalogs.
    - Output to `MainWindow`: cursor movement, ROI selection, zoom changes.
    - No direct dependency on FITS or SEP services.
    """

    mouse_moved = Signal(float, float)
    roi_selected = Signal(int, int, int, int)
    zoom_changed = Signal(float)

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.current_image: QImage | None = None
        self.current_catalog: Any = None
        self.zoom_state = ZoomState()
        self.image_state = CanvasImageState()
        self.overlay_state = CanvasOverlayState()
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._feedback_item = QGraphicsTextItem("No Image Loaded")

        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._drag_origin: QPoint | None = None
        self._marker_items: list[QGraphicsEllipseItem] = []
        self._source_items: list[QGraphicsEllipseItem] = []
        self._roi_color = QColor(255, 0, 0)
        self._source_pen = QPen(QColor(255, 0, 0))
        self._source_pen.setWidth(1)
        self._source_pen.setCosmetic(True)
        self._highlight_pen = QPen(QColor(255, 255, 0))
        self._highlight_pen.setWidth(2)
        self._highlight_pen.setCosmetic(True)

        self.setObjectName("image_canvas")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setScene(self._scene)
        self._scene.addItem(self._pixmap_item)
        self._scene.addItem(self._feedback_item)
        self._feedback_item.setVisible(True)
        self.set_roi_color(self._roi_color)

    def set_image(self, image: QImage | None) -> None:
        """Set the current image shown on the canvas.

        Expected caller: `MainWindow.refresh_image()`.
        """

        self.current_image = image
        if image is None:
            self._pixmap_item.setPixmap(QPixmap())
            return
        self._pixmap_item.setPixmap(QPixmap.fromImage(image))
        self._update_scene_rect()

    def clear_image(self) -> None:
        """Clear the currently displayed image."""

        self.current_image = None
        self._pixmap_item.setPixmap(QPixmap())

    def set_image_state(self, state: CanvasImageState) -> None:
        """Apply structured image presentation state to the canvas."""

        self.image_state = state
        self.set_feedback_state(state.feedback)

    def image_view_state(self) -> CanvasImageState:
        """Return the current image presentation state."""

        return self.image_state

    def set_feedback_state(self, state: ViewFeedbackState) -> None:
        """Apply a generic feedback state to the canvas."""

        self.image_state.feedback = state
        message = state.title or state.detail or ""
        self._feedback_item.setPlainText(message)
        self._feedback_item.setVisible(state.visible)

    def fit_to_window(self) -> None:
        """Scale the image to fit the current viewport.

        Expected caller: view action handlers in `MainWindow`.
        """

        if self._pixmap_item.pixmap().isNull():
            return
        self.fitInView(self._pixmap_item, mode=1)
        self.set_zoom_state(ZoomState(scale_factor=1.0, mode="fit"))
        self.zoom_changed.emit(self.zoom_state.scale_factor)

    def show_actual_pixels(self) -> None:
        """Reset the view to 1:1 pixel scale."""

        self.resetTransform()
        self.set_zoom_state(ZoomState(scale_factor=1.0, mode="actual"))
        self.zoom_changed.emit(self.zoom_state.scale_factor)

    def zoom_in(self) -> None:
        """Zoom in from the current scale."""

        self.scale(1.15, 1.15)
        self.set_zoom_state(ZoomState(scale_factor=self.zoom_state.scale_factor * 1.15, mode="custom"))
        self.zoom_changed.emit(self.zoom_state.scale_factor)

    def zoom_out(self) -> None:
        """Zoom out from the current scale."""

        self.scale(1 / 1.15, 1 / 1.15)
        self.set_zoom_state(ZoomState(scale_factor=self.zoom_state.scale_factor / 1.15, mode="custom"))
        self.zoom_changed.emit(self.zoom_state.scale_factor)

    def draw_sources(self, catalog: Any) -> None:
        """Draw source ellipses for detected sources.

        Expected caller: `MainWindow.handle_roi_selected()`.
        Each source is drawn as an ellipse using a, b, theta from the catalog.
        """

        self.clear_sources()
        self.current_catalog = catalog
        if catalog is None:
            return
        for record in catalog:
            a = max(record.a, 1.0) * 3
            b = max(record.b, 1.0) * 3
            item = QGraphicsEllipseItem(-a, -b, a * 2, b * 2)
            item.setPen(self._source_pen)
            item.setPos(record.x, record.y)
            item.setRotation(math.degrees(record.theta))
            self._scene.addItem(item)
            self._source_items.append(item)

    def set_overlay_state(self, state: CanvasOverlayState) -> None:
        """Apply structured overlay presentation state to the canvas."""

        self.overlay_state = state

    def overlay_view_state(self) -> CanvasOverlayState:
        """Return the current overlay presentation state."""

        return self.overlay_state

    def clear_sources(self) -> None:
        """Clear all source overlays."""

        for item in self._source_items:
            self._scene.removeItem(item)
        self._source_items.clear()
        self.current_catalog = None

    def highlight_source(self, index: int) -> None:
        """Highlight a single source overlay, reset others.

        Expected caller: `MainWindow.handle_source_clicked()`.
        """

        self.overlay_state.highlighted_index = index
        for i, item in enumerate(self._source_items):
            if i == index:
                item.setPen(self._highlight_pen)
            else:
                item.setPen(self._source_pen)

    def set_markers(
        self,
        coords: list[tuple[float, float]],
        radius: float = 20.0,
        color: QColor | None = None,
        line_width: int = 2,
    ) -> None:
        """Draw circle markers at the given pixel coordinates."""

        self.clear_markers()
        pen = QPen(color or QColor(255, 0, 0))
        pen.setWidth(line_width)
        pen.setCosmetic(True)
        for x, y in coords:
            item = QGraphicsEllipseItem(
                x - radius, y - radius, radius * 2, radius * 2
            )
            item.setPen(pen)
            self._scene.addItem(item)
            self._marker_items.append(item)

    def clear_markers(self) -> None:
        """Remove all marker items from the scene."""

        for item in self._marker_items:
            self._scene.removeItem(item)
        self._marker_items.clear()

    def set_roi_color(self, color: QColor | None) -> None:
        """Update the right-drag ROI rubber-band color."""

        self._roi_color = QColor(color or QColor(255, 0, 0))
        self._rubber_band.setStyleSheet(
            "QRubberBand {"
            f"border: 2px solid {self._roi_color.name()};"
            f"background-color: rgba({self._roi_color.red()}, {self._roi_color.green()}, {self._roi_color.blue()}, 32);"
            "}"
        )

    def emit_roi_selected(self, selection: ROISelection) -> None:
        """Bridge structured ROI state to the public Qt signal contract."""

        self.roi_selected.emit(selection.x0, selection.y0, selection.width, selection.height)

    def set_zoom_state(self, zoom_state: ZoomState) -> None:
        """Replace the current structured zoom state."""

        self.zoom_state = zoom_state
        self._update_scene_rect()

    def _update_scene_rect(self) -> None:
        """Expand scene rect with large margins so edges can be dragged to center."""

        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return
        img_rect = self._pixmap_item.boundingRect()
        margin = max(img_rect.width(), img_rect.height())
        self.setSceneRect(img_rect.adjusted(-margin, -margin, margin, margin))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start rubber-band ROI selection on right-click."""

        if event.button() == Qt.MouseButton.RightButton and self.current_image is not None:
            self._drag_origin = event.pos()
            self._rubber_band.setGeometry(QRect(self._drag_origin, self._drag_origin))
            self._rubber_band.show()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update rubber band during drag; emit cursor coordinates always."""

        scene_pos = self.mapToScene(event.pos())
        self.mouse_moved.emit(scene_pos.x(), scene_pos.y())

        if self._drag_origin is not None:
            self._rubber_band.setGeometry(QRect(self._drag_origin, event.pos()).normalized())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish rubber-band selection and emit ROI signal."""

        if event.button() == Qt.MouseButton.RightButton and self._drag_origin is not None:
            self._rubber_band.hide()
            rect = QRect(self._drag_origin, event.pos()).normalized()
            self._drag_origin = None

            top_left = self.mapToScene(rect.topLeft())
            bottom_right = self.mapToScene(rect.bottomRight())
            x0 = max(0, int(top_left.x()))
            y0 = max(0, int(top_left.y()))
            x1 = int(bottom_right.x())
            y1 = int(bottom_right.y())
            w = x1 - x0
            h = y1 - y0
            if w > 2 and h > 2:
                self.roi_selected.emit(x0, y0, w, h)
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event: Any) -> None:
        """Zoom in/out with mouse wheel, anchored under cursor."""

        delta = event.angleDelta().y()
        if delta > 0:
            factor = 1.25
        elif delta < 0:
            factor = 1 / 1.25
        else:
            return
        self.scale(factor, factor)
        new_scale = self.zoom_state.scale_factor * factor
        self.set_zoom_state(ZoomState(scale_factor=new_scale, mode="custom"))
        self.zoom_changed.emit(new_scale)
