"""Scene-item ownership for independent canvas overlays.

Layers own only their graphics and presentation state. The canvas retains
view navigation, mouse events and public signals; clearing one layer never
touches an unrelated overlay.
"""

from __future__ import annotations

import math
from typing import Any, Generic, TypeVar

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem,
)

from ..core.contracts import ROISelection

Item = TypeVar("Item", bound=QGraphicsItem)


class OverlayItems(Generic[Item]):
    """Own a stable collection of items attached to exactly one scene."""

    def __init__(self, scene: QGraphicsScene) -> None:
        self.scene = scene
        self.items: list[Item] = []

    def add(self, item: Item) -> Item:
        self.scene.addItem(item)
        self.items.append(item)
        return item

    def clear(self) -> None:
        for item in self.items:
            if item.scene() is self.scene:
                self.scene.removeItem(item)
        self.items.clear()


class SourceLayer(OverlayItems[QGraphicsEllipseItem]):
    """Detected-source ellipses and their selection styling."""

    def __init__(self, scene: QGraphicsScene, index_key: int) -> None:
        super().__init__(scene)
        self.index_key = index_key
        self.catalog: Any = None
        self.position_transform = None
        self.highlighted_index: int | None = None
        self.pen = QPen(QColor(255, 0, 0))
        self.pen.setWidth(5)
        self.pen.setCosmetic(True)
        self.highlight_pen = QPen(QColor(255, 255, 0))
        self.highlight_pen.setWidth(6)
        self.highlight_pen.setCosmetic(True)

    def clear_sources(self) -> None:
        self.clear()
        self.catalog = None

    def draw_sources(self, catalog: Any) -> None:
        """Draw source ellipses for detected sources.

        Each source is drawn as an ellipse using a, b, theta from the catalog.
        """

        self.clear_sources()
        self.catalog = catalog
        if catalog is None:
            return
        for index, record in enumerate(catalog):
            a = max(record.a, 1.0) * 3
            b = max(record.b, 1.0) * 3
            item = QGraphicsEllipseItem(-a, -b, a * 2, b * 2)
            item.setPen(self.pen)
            px, py = record.x, record.y
            if self.position_transform is not None:
                px, py = self.position_transform(px, py)
            item.setPos(px, py)
            item.setRotation(math.degrees(record.theta))
            item.setData(self.index_key, index)
            self.add(item)

        self._refresh_source_pens()


    def set_source_overlay_style(
        self,
        color: QColor | None = None,
        line_width: int | None = None,
    ) -> None:
        """Update source-overlay color and width, then repaint existing items."""

        if color is not None:
            self.pen.setColor(QColor(color))
        if line_width is not None:
            width = max(1, int(line_width))
            self.pen.setWidth(width)
            self.highlight_pen.setWidth(width + 1)
        self._refresh_source_pens()


    def _refresh_source_pens(self) -> None:
        """Reapply source pens so style changes appear immediately."""

        highlighted_index = self.highlighted_index
        for i, item in enumerate(self.items):
            if highlighted_index is not None and i == highlighted_index:
                item.setPen(self.highlight_pen)
            else:
                item.setPen(self.pen)



class CatalogLayer(OverlayItems[QGraphicsPathItem]):
    """Projected catalog markers with independent catalog selection."""

    def __init__(self, scene: QGraphicsScene, index_key: int) -> None:
        super().__init__(scene)
        self.index_key = index_key

    def clear_catalog_sources(self) -> None:
        self.clear()

    def set_catalog_sources(
        self,
        sources: list[Any],
        pixel_coords: list[tuple[float, float]],
        *,
        transform=None,
    ) -> None:
        """Draw bounded Gaia catalog markers at projected original-image pixels."""

        self.clear_catalog_sources()
        point_transform = transform or (lambda x, y: (x, y))
        base_color = QColor(50, 255, 170)
        for index, (source, point) in enumerate(zip(sources, pixel_coords)):
            x, y = point_transform(float(point[0]), float(point[1]))
            magnitude = getattr(source, "g_mag", None)
            radius = 6.0
            if magnitude is not None and math.isfinite(float(magnitude)):
                radius = max(3.0, min(8.0, 8.0 - 0.22 * (float(magnitude) - 8.0)))
            path = QPainterPath()
            path.addEllipse(QRectF(-radius, -radius, radius * 2.0, radius * 2.0))
            path.moveTo(-radius - 3.0, 0.0)
            path.lineTo(radius + 3.0, 0.0)
            path.moveTo(0.0, -radius - 3.0)
            path.lineTo(0.0, radius + 3.0)
            item = QGraphicsPathItem(path)
            pen = QPen(base_color)
            pen.setWidth(1)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setPos(float(x), float(y))
            item.setZValue(3.0)
            item.setData(self.index_key, index)
            source_id = str(getattr(source, "source_id", index + 1))
            tooltip = f"Gaia DR3 {source_id}"
            if magnitude is not None:
                tooltip += f"\nG = {float(magnitude):.3f} mag"
            item.setToolTip(tooltip)
            self.add(item)


    def highlight_catalog_source(self, index: int | None) -> None:
        for item_index, item in enumerate(self.items):
            pen = QPen(QColor(255, 230, 80) if item_index == index else QColor(50, 255, 170))
            pen.setWidth(2 if item_index == index else 1)
            pen.setCosmetic(True)
            item.setPen(pen)



class RegionLayer:
    """DS9 paths, labels, hit-test identities and original pens."""

    def __init__(self, scene: QGraphicsScene, index_key: int) -> None:
        self.paths: OverlayItems[QGraphicsPathItem] = OverlayItems(scene)
        self.labels: OverlayItems[QGraphicsTextItem] = OverlayItems(scene)
        self.index_key = index_key
        self.items_by_index: dict[int, list[QGraphicsPathItem]] = {}
        self.base_pens: dict[int, QPen] = {}

    def clear_region_overlays(self) -> None:
        self.paths.clear()
        self.labels.clear()
        self.items_by_index.clear()
        self.base_pens.clear()

    def set_region_overlays(self, overlays: list[dict[str, Any]]) -> None:
        """Draw already-projected, bounded DS9 geometries in display coordinates."""

        self.clear_region_overlays()
        for overlay in overlays:
            try:
                index = int(overlay["index"])
                points = [(float(x), float(y)) for x, y in overlay["points"]]
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if not points or any(not (math.isfinite(x) and math.isfinite(y)) for x, y in points):
                continue
            is_point = bool(overlay.get("point", False))
            closed = bool(overlay.get("closed", not is_point))
            path = QPainterPath()
            if is_point:
                x, y = points[0]
                radius = 6.0
                path.moveTo(x - radius, y)
                path.lineTo(x + radius, y)
                path.moveTo(x, y - radius)
                path.lineTo(x, y + radius)
                path.addEllipse(QRectF(x - 2.0, y - 2.0, 4.0, 4.0))
            else:
                path.moveTo(*points[0])
                for point in points[1:]:
                    path.lineTo(*point)
                if closed:
                    path.closeSubpath()

            color = QColor(str(overlay.get("color", "green")))
            if not color.isValid():
                color = QColor(80, 255, 120)
            include = bool(overlay.get("include", True))
            width = max(1, min(int(overlay.get("width", 1)), 10))
            pen = QPen(color)
            pen.setWidth(width)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.SolidLine if include else Qt.PenStyle.DashLine)
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(2.5)
            item.setData(self.index_key, index)
            tooltip = str(overlay.get("tooltip", "DS9 Region"))
            item.setToolTip(tooltip)
            self.paths.add(item)
            self.items_by_index.setdefault(index, []).append(item)
            self.base_pens[id(item)] = QPen(pen)

            label_text = str(overlay.get("label", "")).strip()
            if label_text:
                label = QGraphicsTextItem(label_text)
                label.setDefaultTextColor(color)
                label.setFont(QFont("Segoe UI", 8))
                label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                bounds = path.boundingRect()
                label.setPos(bounds.left() + 3.0, bounds.top() + 3.0)
                label.setZValue(2.6)
                label.setToolTip(tooltip)
                label.setData(self.index_key, index)
                self.labels.add(label)


    def highlight_region(self, index: int | None) -> None:
        for region_index, items in self.items_by_index.items():
            for item in items:
                base = self.base_pens.get(id(item), item.pen())
                pen = QPen(base)
                if index is not None and region_index == int(index):
                    pen.setColor(QColor(255, 230, 80))
                    pen.setWidth(min(12, max(2, base.width() + 2)))
                item.setPen(pen)



class MeasurementLayer:
    """Measured ROI and aperture graphics, cleared independently."""

    def __init__(self, scene: QGraphicsScene) -> None:
        self.roi: OverlayItems[QGraphicsRectItem] = OverlayItems(scene)
        self.apertures: OverlayItems[QGraphicsEllipseItem] = OverlayItems(scene)

    @property
    def roi_item(self) -> QGraphicsRectItem | None:
        return self.roi.items[0] if self.roi.items else None

    def clear_measurement_roi(self) -> None:
        self.roi.clear()

    def clear_aperture_overlay(self) -> None:
        self.apertures.clear()

    def set_measurement_roi(self, selection: ROISelection, *, transform=None) -> None:
        """Persist the most recently measured rectangular ROI on the canvas."""

        self.clear_measurement_roi()
        point_transform = transform or (lambda x, y: (x, y))
        corners = (
            point_transform(selection.x0, selection.y0),
            point_transform(selection.x0 + selection.width, selection.y0 + selection.height),
        )
        x0, x1 = sorted((float(corners[0][0]), float(corners[1][0])))
        y0, y1 = sorted((float(corners[0][1]), float(corners[1][1])))
        item = QGraphicsRectItem(QRectF(x0, y0, x1 - x0, y1 - y0))
        pen = QPen(QColor(255, 196, 64))
        pen.setWidth(2)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        item.setPen(pen)
        item.setZValue(2.0)
        self.roi.add(item)


    def set_aperture_overlay(
        self,
        center_x: float,
        center_y: float,
        radii: tuple[float, float, float],
        *,
        transform=None,
    ) -> None:
        """Draw a circular source aperture plus the two background-annulus edges."""

        self.clear_aperture_overlay()
        point_transform = transform or (lambda x, y: (x, y))
        x, y = point_transform(float(center_x), float(center_y))
        colors = (QColor(255, 225, 80), QColor(80, 220, 255), QColor(80, 220, 255))
        for radius, color in zip(radii, colors):
            normalized_radius = float(radius)
            if not math.isfinite(normalized_radius) or normalized_radius <= 0:
                continue
            item = QGraphicsEllipseItem(
                float(x) - normalized_radius,
                float(y) - normalized_radius,
                normalized_radius * 2.0,
                normalized_radius * 2.0,
            )
            pen = QPen(color)
            pen.setWidth(2 if not self.apertures.items else 1)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine if self.apertures.items else Qt.PenStyle.SolidLine)
            item.setPen(pen)
            item.setZValue(2.2)
            self.apertures.add(item)
