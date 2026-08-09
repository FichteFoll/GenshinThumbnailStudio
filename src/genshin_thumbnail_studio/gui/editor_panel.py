"""`EditorPanel`, the window's right column.

Owns the preview toolbar, the `PreviewWidget` canvas and the placement row, and
reports user intent over its own signals rather than being connected into by the
window. The widgets stay public attributes, which is what
`project_io.ProjectEditor` and the tests reach through. `preview`'s own signals
are not re-exposed: the window connects to `editor_panel.preview` directly.
Nothing here imports `MainWindow`, so the window can build the panel without a
cycle.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .preview import PreviewWidget


def _slider(minimum: int, maximum: int, value: int) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(minimum, maximum)
    slider.setValue(value)
    slider.setMinimumWidth(80)
    return slider


class EditorPanel(QWidget):
    """The preview column: the team selector, the canvas and the placement row."""

    active_team_changed = Signal(int)  # the boss combo's index
    placement_changed = Signal()  # any of the three sliders moved
    flip_toggled = Signal(bool)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        right_layout = QVBoxLayout(self)
        right_layout.setContentsMargins(12, 16, 16, 16)
        right_layout.setSpacing(10)

        preview_toolbar = QHBoxLayout()
        self.preview_team_label = QLabel("Preview")
        self.boss_combo = QComboBox()
        self.boss_combo.addItems(["Boss 1", "Boss 2", "Boss 3"])
        self.boss_combo.setVisible(False)
        self.boss_combo.currentIndexChanged.connect(self.active_team_changed)
        preview_toolbar.addWidget(self.preview_team_label)
        preview_toolbar.addStretch(1)
        preview_toolbar.addWidget(self.boss_combo)
        right_layout.addLayout(preview_toolbar)

        self.preview = PreviewWidget()
        right_layout.addWidget(self.preview, 1)

        placement_row = QHBoxLayout()
        self.selected_label = QLabel("Team 1, character 1")
        # Placeholder offset ranges; sync_controls() sets the reachable ones.
        self.x_slider = _slider(-500, 500, 0)
        self.y_slider = _slider(-500, 500, -20)
        self.zoom_slider = _slider(70, 180, 100)
        self.x_value = QLabel("+0%")
        self.y_value = QLabel("-2%")
        self.zoom_value = QLabel("100%")
        for slider in [self.x_slider, self.y_slider, self.zoom_slider]:
            slider.valueChanged.connect(self.placement_changed)
        self.flip_check = QCheckBox("Flip")
        self.flip_check.setToolTip("Mirror this character horizontally")
        self.flip_check.toggled.connect(self.flip_toggled)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_requested)
        placement_row.addWidget(self.selected_label)
        placement_row.addSpacing(12)
        placement_row.addWidget(QLabel("X"))
        placement_row.addWidget(self.x_slider, 1)
        placement_row.addWidget(self.x_value)
        placement_row.addWidget(QLabel("Y"))
        placement_row.addWidget(self.y_slider, 1)
        placement_row.addWidget(self.y_value)
        placement_row.addWidget(QLabel("Zoom"))
        placement_row.addWidget(self.zoom_slider, 1)
        placement_row.addWidget(self.zoom_value)
        placement_row.addWidget(self.flip_check)
        placement_row.addWidget(self.reset_button)
        right_layout.addLayout(placement_row)
