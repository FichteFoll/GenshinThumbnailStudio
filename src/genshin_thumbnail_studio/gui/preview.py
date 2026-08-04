from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QFrame


class PreviewWidget(QFrame):
    slot_selected = Signal(int, int)
    # Carries the drag delta in canvas pixels (not placement offsets); the
    # receiver converts it against the panel size it is placing into.
    placement_dragged = Signal(float, float)
    zoom_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(640, 360)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._pixmap: QPixmap | None = None
        self._mode = "abyss"
        self._active_team = 0
        self._selected = (0, 0)
        self._drag_last: QPoint | None = None

    def set_preview(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def set_context(self, mode: str, active_team: int, selected: tuple[int, int]) -> None:
        self._mode = mode
        self._active_team = active_team
        self._selected = selected
        self.update()

    def _image_rect(self) -> QRect:
        if not self._pixmap:
            return QRect()
        fitted = self._pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect(
            (self.width() - fitted.width()) // 2,
            (self.height() - fitted.height()) // 2,
            fitted.width(),
            fitted.height(),
        )

    def _image_point(self, point: QPoint) -> tuple[float, float] | None:
        rect = self._image_rect()
        if rect.isEmpty() or not rect.contains(point):
            return None
        return (
            (point.x() - rect.x()) * 1280 / rect.width(),
            (point.y() - rect.y()) * 720 / rect.height(),
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111216"))
        rect = self._image_rect()
        if not self._pixmap or rect.isEmpty():
            painter.setPen(QColor("#8f96a3"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Load a profile and generate a preview")
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(rect, self._pixmap)

        team, slot = self._selected
        visible_team = team if self._mode == "abyss" else 0
        if self._mode == "stygian" and team != self._active_team:
            return
        cell_w = rect.width() / 4
        cell_h = rect.height() / (2 if self._mode == "abyss" else 1)
        highlight = QRect(
            int(rect.x() + slot * cell_w),
            int(rect.y() + visible_team * cell_h),
            int(cell_w),
            int(cell_h),
        ).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(QColor("#ffd95d"), 3))
        painter.drawRect(highlight)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self._image_point(event.position().toPoint())
        if point is None:
            return
        x, y = point
        slot = min(3, max(0, int(x // 320)))
        team = min(1, max(0, int(y // 360))) if self._mode == "abyss" else self._active_team
        self._selected = (team, slot)
        self._drag_last = event.position().toPoint()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.slot_selected.emit(team, slot)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_last is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        rect = self._image_rect()
        if rect.isEmpty():
            return
        current = event.position().toPoint()
        delta = current - self._drag_last
        self._drag_last = current
        image_dx = delta.x() * 1280 / rect.width()
        image_dy = delta.y() * 720 / rect.height()
        self.placement_dragged.emit(image_dx, image_dy)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_last = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._image_point(event.position().toPoint()) is None:
            return
        self.zoom_requested.emit(0.04 if event.angleDelta().y() > 0 else -0.04)
        event.accept()
