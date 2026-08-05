"""`TeamSlotWidget`, one draggable combo box row in the team overview."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

SLOT_MIME_TYPE = "application/x-genshin-slot"


class _SlotDragHandle(QLabel):
    """Small grip label; the only part of a team slot that starts a drag."""

    def __init__(self, slot_widget: TeamSlotWidget) -> None:
        super().__init__("☰")
        self._slot_widget = slot_widget
        self.setFixedWidth(18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to swap slots")
        self._drag_start: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self._drag_start = None
            self._slot_widget.drag_started.emit(self._slot_widget.team, self._slot_widget.slot)
            drag = QDrag(self)
            mime = QMimeData()
            payload = f"{self._slot_widget.team}:{self._slot_widget.slot}"
            mime.setData(SLOT_MIME_TYPE, payload.encode("utf-8"))
            drag.setMimeData(mime)
            action = drag.exec(Qt.DropAction.MoveAction)
            self._slot_widget.drag_ended.emit(action != Qt.DropAction.IgnoreAction)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start = None
        super().mouseReleaseEvent(event)


class TeamSlotWidget(QWidget):
    """One combo box row in the team overview, draggable via its handle."""

    drag_started = Signal(int, int)  # source team, slot
    drag_hover = Signal(int, int)  # this widget's team, slot
    drag_ended = Signal(bool)  # accepted

    def __init__(self, team: int, slot: int, combo: QComboBox) -> None:
        super().__init__()
        self.team = team
        self.slot = slot
        self.setAcceptDrops(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.handle = _SlotDragHandle(self)
        layout.addWidget(self.handle)
        layout.addWidget(combo, 1)

    def _set_drop_target(self, active: bool) -> None:
        self.setProperty("dropTarget", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(SLOT_MIME_TYPE):
            event.acceptProposedAction()
            self._set_drop_target(True)
            self.drag_hover.emit(self.team, self.slot)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._set_drop_target(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_target(False)
        event.acceptProposedAction()
