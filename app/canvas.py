from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QMouseEvent, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QRubberBand,
)

from .compass_overlay import CompassOverlay
from .magnifier_overlay import MagnifierOverlay, _make_crosshair_cursor
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
    source_double_clicked = Signal(int)
    zoom_changed = Signal(float)
    files_dropped = Signal(list)
    _SOURCE_INDEX_DATA_KEY = 1

    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.current_image: QImage | None = None
        self.current_catalog: Any = None
        self.zoom_state = ZoomState()
        self.image_state = CanvasImageState()
        self.overlay_state = CanvasOverlayState()
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._feedback_background_item = QGraphicsRectItem()
        self._feedback_item = QGraphicsTextItem("No Image Loaded")

        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._drag_origin: QPoint | None = None
        self._marker_items: list[QGraphicsEllipseItem] = []
        self._source_items: list[QGraphicsEllipseItem] = []
        self._roi_color = QColor(255, 0, 0)
        self._roi_line_width = 5
        self._source_pen = QPen(QColor(255, 0, 0))
        self._source_pen.setWidth(5)
        self._source_pen.setCosmetic(True)
        self._highlight_pen = QPen(QColor(255, 255, 0))
        self._highlight_pen.setWidth(6)
        self._highlight_pen.setCosmetic(True)

        self.setObjectName("image_canvas")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setScene(self._scene)
        self._scene.addItem(self._pixmap_item)
        self._scene.addItem(self._feedback_background_item)
        self._scene.addItem(self._feedback_item)
        self._feedback_background_item.setZValue(9)
        self._feedback_item.setZValue(10)
        self._feedback_item.document().setDocumentMargin(0)
        self._feedback_item.setFont(QFont("Segoe UI", 12))
        self._feedback_item.setVisible(True)
        self._feedback_background_item.setVisible(True)
        self._apply_feedback_style("empty")
        self.set_roi_color(self._roi_color)

        self._source_position_transform = None  # callable (x, y) -> (x, y)
        self.compass = CompassOverlay(self)
        self.compass.move(self.width() - self.compass.width() - 12, 12)
        self.compass.raise_()
        self.compass.show()

        self.magnifier = MagnifierOverlay(self)
        self.magnifier.hide()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self.compass.move(self.width() - self.compass.width() - 12, 12)
        self._layout_feedback_item()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._layout_feedback_item()

    def set_magnifier_visible(self, visible: bool) -> None:
        self.magnifier.setVisible(visible)
        if visible:
            self.magnifier.raise_()
            self.viewport().setCursor(_make_crosshair_cursor())
        else:
            self.viewport().unsetCursor()

    def set_magnifier_magnification(self, value: int) -> None:
        self.magnifier.set_magnification(value)

    def set_source_position_transform(self, transform) -> None:
        """Install a callable that maps catalog (x, y) into displayed coords."""

        self._source_position_transform = transform
        if self.current_catalog is not None:
            self.draw_sources(self.current_catalog)

    def set_image(self, image: QImage | None) -> None:
        """Set the current image shown on the canvas.

        Expected caller: `MainWindow.refresh_image()`.
        """

        self.current_image = image
        if image is None:
            self._pixmap_item.setPixmap(QPixmap())
            self._layout_feedback_item()
            return
        self._pixmap_item.setPixmap(QPixmap.fromImage(image))
        self._update_scene_rect()
        self._layout_feedback_item()

    def capture_view_state(self) -> dict[str, float | str] | None:
        """Snapshot the current view so image replacements can restore it."""

        pixmap = self._pixmap_item.pixmap()
        image_rect = self._pixmap_item.boundingRect()
        if pixmap.isNull() or image_rect.isNull():
            return None

        center = self.mapToScene(self.viewport().rect().center())
        width = image_rect.width()
        height = image_rect.height()
        center_x = 0.5 if width <= 0 else (center.x() - image_rect.left()) / width
        center_y = 0.5 if height <= 0 else (center.y() - image_rect.top()) / height

        return {
            "mode": self.zoom_state.mode,
            "scale_factor": self.transform().m11(),
            "center_x": min(max(center_x, 0.0), 1.0),
            "center_y": min(max(center_y, 0.0), 1.0),
            "image_width": width,
            "image_height": height,
        }

    def restore_view_state(self, state: dict[str, float | str] | None) -> None:
        """Reapply a captured view state after the pixmap changes."""

        if not state:
            return

        pixmap = self._pixmap_item.pixmap()
        image_rect = self._pixmap_item.boundingRect()
        if pixmap.isNull() or image_rect.isNull():
            return

        mode = str(state.get("mode", "custom"))
        previous_width = float(state.get("image_width", image_rect.width()))
        previous_height = float(state.get("image_height", image_rect.height()))
        width = image_rect.width()
        height = image_rect.height()

        width_ratio = previous_width / width if previous_width > 0 and width > 0 else 1.0
        height_ratio = previous_height / height if previous_height > 0 and height > 0 else 1.0
        image_scale_ratio = min(width_ratio, height_ratio)
        target_scale = float(state.get("scale_factor", self.transform().m11()))

        previous_anchor = self.transformationAnchor()
        previous_resize_anchor = self.resizeAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        try:
            if mode == "fit":
                self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
                target_scale = self.transform().m11()
            elif mode == "custom":
                target_scale = max(0.01, target_scale * image_scale_ratio)
                self.resetTransform()
                self.scale(target_scale, target_scale)
            else:
                target_scale = 1.0
                self.resetTransform()

            center_x = min(max(float(state.get("center_x", 0.5)), 0.0), 1.0)
            center_y = min(max(float(state.get("center_y", 0.5)), 0.0), 1.0)
            self.centerOn(
                image_rect.left() + center_x * width,
                image_rect.top() + center_y * height,
            )
        finally:
            self.setTransformationAnchor(previous_anchor)
            self.setResizeAnchor(previous_resize_anchor)

        self.set_zoom_state(ZoomState(scale_factor=target_scale, mode=mode))
        self.zoom_changed.emit(target_scale)

    def clear_image(self) -> None:
        """Clear the currently displayed image."""

        self.current_image = None
        self._pixmap_item.setPixmap(QPixmap())
        self._layout_feedback_item()

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
        parts = [part for part in (state.title.strip(), state.detail.strip()) if part]
        message = "\n\n".join(parts)
        self._apply_feedback_style(state.status)
        self._feedback_item.setPlainText(message)
        self._feedback_item.setVisible(state.visible)
        self._feedback_background_item.setVisible(state.visible and bool(message))
        self._layout_feedback_item()

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
        for index, record in enumerate(catalog):
            a = max(record.a, 1.0) * 3
            b = max(record.b, 1.0) * 3
            item = QGraphicsEllipseItem(-a, -b, a * 2, b * 2)
            item.setPen(self._source_pen)
            px, py = record.x, record.y
            if self._source_position_transform is not None:
                px, py = self._source_position_transform(px, py)
            item.setPos(px, py)
            item.setRotation(math.degrees(record.theta))
            item.setData(self._SOURCE_INDEX_DATA_KEY, index)
            self._scene.addItem(item)
            self._source_items.append(item)

        self._refresh_source_pens()

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
        self._refresh_source_pens()

    def center_on_source(self, index: int) -> None:
        """Center the viewport on the selected source overlay when available."""

        if not (0 <= index < len(self._source_items)):
            return
        self.centerOn(self._source_items[index].scenePos())

    def set_source_overlay_style(
        self,
        color: QColor | None = None,
        line_width: int | None = None,
    ) -> None:
        """Update source-overlay color and width, then repaint existing items."""

        if color is not None:
            self._source_pen.setColor(QColor(color))
        if line_width is not None:
            width = max(1, int(line_width))
            self._source_pen.setWidth(width)
            self._highlight_pen.setWidth(width + 1)
        self._refresh_source_pens()

    def _refresh_source_pens(self) -> None:
        """Reapply source pens so style changes appear immediately."""

        highlighted_index = self.overlay_state.highlighted_index
        for i, item in enumerate(self._source_items):
            if highlighted_index is not None and i == highlighted_index:
                item.setPen(self._highlight_pen)
            else:
                item.setPen(self._source_pen)

    def set_markers(
        self,
        coords: list[tuple[float, float]],
        radius: float = 20.0,
        color: QColor | None = None,
        line_width: int = 5,
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
        self._apply_roi_style()

    def set_roi_line_width(self, line_width: int) -> None:
        """Update the right-drag ROI rubber-band border width."""

        self._roi_line_width = max(1, int(line_width))
        self._apply_roi_style()

    def _apply_roi_style(self) -> None:
        """Refresh the rubber-band stylesheet from the stored ROI settings."""

        self._rubber_band.setStyleSheet(
            "QRubberBand {"
            f"border: {self._roi_line_width}px solid {self._roi_color.name()};"
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
            self._layout_feedback_item()
            return
        img_rect = self._pixmap_item.boundingRect()
        margin = max(img_rect.width(), img_rect.height())
        self.setSceneRect(img_rect.adjusted(-margin, -margin, margin, margin))
        self._layout_feedback_item()

    def _layout_feedback_item(self) -> None:
        """Center feedback text within the current viewport."""

        if not self._feedback_item.isVisible() or not self._feedback_item.toPlainText().strip():
            self._feedback_background_item.setVisible(False)
            return

        text_width = min(max(self.viewport().width() * 0.58, 260.0), 520.0)
        self._feedback_item.setTextWidth(text_width)
        bounds = self._feedback_item.boundingRect()
        scene_center = self.mapToScene(self.viewport().rect().center())
        padding_x = 18.0
        padding_y = 14.0
        bg_width = bounds.width() + padding_x * 2.0
        bg_height = bounds.height() + padding_y * 2.0
        bg_x = scene_center.x() - bg_width / 2.0
        bg_y = scene_center.y() - bg_height / 2.0
        self._feedback_background_item.setRect(bg_x, bg_y, bg_width, bg_height)
        self._feedback_background_item.setVisible(True)
        self._feedback_item.setPos(bg_x + padding_x, bg_y + padding_y)

    def _apply_feedback_style(self, status: str) -> None:
        """Apply high-contrast colors for canvas feedback cards."""

        if status == "error":
            background = QColor(69, 10, 10, 228)
            border = QColor(248, 113, 113, 240)
            text = QColor(255, 241, 242)
        elif status == "loading":
            background = QColor(8, 24, 48, 228)
            border = QColor(96, 165, 250, 240)
            text = QColor(239, 246, 255)
        else:
            background = QColor(15, 23, 42, 228)
            border = QColor(56, 189, 248, 240)
            text = QColor(239, 246, 255)

        pen = QPen(border)
        pen.setWidth(2)
        self._feedback_background_item.setPen(pen)
        self._feedback_background_item.setBrush(QBrush(background))
        self._feedback_item.setDefaultTextColor(text)

    def _source_index_at_view_pos(self, view_pos: QPoint) -> int | None:
        """Return the source index under the given viewport position."""

        for item in self.items(view_pos):
            source_index = item.data(self._SOURCE_INDEX_DATA_KEY)
            if source_index is not None:
                return int(source_index)
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start rubber-band ROI selection on right-click."""

        if event.button() == Qt.MouseButton.RightButton and self.current_image is not None:
            self._drag_origin = event.pos()
            self._rubber_band.setGeometry(QRect(self._drag_origin, self._drag_origin))
            self._rubber_band.show()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Emit the clicked source index when a source overlay is double-clicked."""

        if event.button() == Qt.MouseButton.LeftButton:
            source_index = self._source_index_at_view_pos(event.position().toPoint())
            if source_index is not None:
                self.source_double_clicked.emit(source_index)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update rubber band during drag; emit cursor coordinates always."""

        scene_pos = self._scene_pos_from_view_pos(event.position())
        self.mouse_moved.emit(scene_pos.x(), scene_pos.y())

        if self.magnifier.isVisible():
            self.magnifier.update_position(
                self.current_image,
                scene_pos.x(),
                scene_pos.y(),
                event.pos(),
                self.zoom_state.scale_factor,
            )

        if self._drag_origin is not None:
            self._rubber_band.setGeometry(QRect(self._drag_origin, event.pos()).normalized())
        else:
            super().mouseMoveEvent(event)

    def _scene_pos_from_view_pos(self, view_pos: QPointF | QPoint) -> QPointF:
        """Map viewport coordinates into scene coordinates with subpixel precision."""

        point = QPointF(view_pos)
        if math.isclose(point.x(), round(point.x()), abs_tol=1e-6):
            point.setX(point.x() + 0.5)
        if math.isclose(point.y(), round(point.y()), abs_tol=1e-6):
            point.setY(point.y() + 0.5)
        inverse, invertible = self.viewportTransform().inverted()
        if not invertible:
            return QPointF()
        return inverse.map(point)

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
        self._layout_feedback_item()
        self.zoom_changed.emit(new_scale)

    def dragEnterEvent(self, event: Any) -> None:
        """Accept local file drags so the main window can open dropped FITS files."""

        mime_data = event.mimeData()
        if mime_data is not None and mime_data.hasUrls():
            local_paths = [
                url.toLocalFile()
                for url in mime_data.urls()
                if hasattr(url, "isLocalFile") and url.isLocalFile()
            ]
            if local_paths:
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event: Any) -> None:
        """Continue accepting valid local-file drags over the canvas."""

        self.dragEnterEvent(event)

    def dropEvent(self, event: Any) -> None:
        """Emit dropped local file paths back to the window controller."""

        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            event.ignore()
            return

        local_paths = [
            url.toLocalFile()
            for url in mime_data.urls()
            if hasattr(url, "isLocalFile") and url.isLocalFile()
        ]
        if not local_paths:
            event.ignore()
            return

        self.files_dropped.emit(local_paths)
        event.acceptProposedAction()
