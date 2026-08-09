"""`TeamSlotWidget`, one draggable combo box row in the team overview."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QDragEnterEvent, QDropEvent, QFontMetrics, QMouseEvent
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QToolButton, QWidget

SLOT_MIME_TYPE = "application/x-genshin-slot"

# Every slot's build button is the same width, so that the combos beside them
# end at one edge instead of each row breaking where its caption happens to.
BUILD_BUTTON_WIDTH = 150
# What the arrow, the QToolButton#buildButton padding in style.py and the gap
# between them take off that width, leaving the budget the caption is elided to;
# a saved build's name is free text and would otherwise stretch the row.
_BUILD_BUTTON_CHROME_WIDTH = 34
MAX_BUILD_CAPTION_WIDTH = BUILD_BUTTON_WIDTH - _BUILD_BUTTON_CHROME_WIDTH


class _SlotDragHandle(QLabel):
    """Small grip label; the only part of a team slot that starts a drag."""

    def __init__(self, slot_widget: TeamSlotWidget) -> None:
        super().__init__("☰")
        self._slot_widget = slot_widget
        self.setFixedWidth(18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to reorder")
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
    build_menu_requested = Signal(int, int)  # this widget's team, slot

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
        self.build_button = QToolButton()
        self.build_button.setObjectName("buildButton")
        # An arrow-type tool button draws the arrow where the icon would go,
        # so the caption sits beside it.
        self.build_button.setArrowType(Qt.ArrowType.DownArrow)
        self.build_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.build_button.setFixedWidth(BUILD_BUTTON_WIDTH)
        self.build_button.setToolTip("Choose build")
        self.build_button.clicked.connect(lambda: self.build_menu_requested.emit(self.team, self.slot))
        layout.addWidget(self.build_button)

    def set_build_caption(self, label: str) -> None:
        """Show `label` beside the arrow, elided, with the full text as tooltip."""
        if not label:
            self.build_button.setText("")
            self.build_button.setToolTip("Choose build")
            return
        metrics = QFontMetrics(self.build_button.font())
        self.build_button.setText(
            metrics.elidedText(label, Qt.TextElideMode.ElideRight, MAX_BUILD_CAPTION_WIDTH)
        )
        self.build_button.setToolTip(label)

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
