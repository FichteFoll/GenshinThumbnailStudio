"""`ControlsPanel`, the window's left column.

Owns the mode radios, the UID entry, the team slot container, the output
settings and the project buttons, and reports user intent over its own signals
rather than being connected into by the window. The widgets stay public
attributes, which is what `project_io.ProjectEditor` and the tests reach
through. Nothing here imports `MainWindow`, so the window can build the panel
without a cycle.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

RESOLUTION_OPTIONS = [
    ("720p", 720),
    ("1080p", 1080),
    ("1440p", 1440),
    ("2160p", 2160),
]


class ControlsPanel(QWidget):
    """The controls column: mode, profile, teams, output and the project buttons."""

    mode_changed = Signal(bool)  # True when Spiral Abyss is checked
    profile_requested = Signal()
    paste_requested = Signal()
    output_name_changed = Signal(str)
    resolution_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(330)
        self.setMaximumWidth(430)
        controls_layout = QVBoxLayout(self)
        controls_layout.setContentsMargins(16, 16, 12, 16)
        controls_layout.setSpacing(12)

        mode_row = QHBoxLayout()
        self.abyss_radio = QRadioButton("Spiral Abyss")
        self.stygian_radio = QRadioButton("Stygian Onslaught")
        self.abyss_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.abyss_radio)
        mode_group.addButton(self.stygian_radio)
        mode_row.addWidget(self.abyss_radio)
        mode_row.addWidget(self.stygian_radio)
        controls_layout.addLayout(mode_row)
        self.abyss_radio.toggled.connect(self.mode_changed)

        uid_row = QHBoxLayout()
        self.uid_edit = QLineEdit()
        self.uid_edit.setPlaceholderText("Genshin UID")
        self.uid_edit.setMaxLength(12)
        self.load_button = QPushButton("Load profile")
        self.load_button.clicked.connect(self.profile_requested)
        uid_row.addWidget(self.uid_edit, 1)
        uid_row.addWidget(self.load_button)
        controls_layout.addLayout(uid_row)

        self.profile_status = QLabel("No profile loaded")
        self.profile_status.setObjectName("secondary")
        self.profile_status.setWordWrap(True)
        controls_layout.addWidget(self.profile_status)

        self.paste_button = QPushButton("Paste lineup")
        self.paste_button.clicked.connect(self.paste_requested)
        controls_layout.addWidget(self.paste_button)

        self.team_container = QWidget()
        self.team_layout = QVBoxLayout(self.team_container)
        self.team_layout.setContentsMargins(0, 0, 0, 0)
        self.team_layout.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.team_container)
        controls_layout.addWidget(scroll, 1)

        output_form = QFormLayout()
        self.output_name = QLineEdit("genshin_thumbnail")
        self.output_name.textChanged.connect(self.output_name_changed)
        output_form.addRow("File name", self.output_name)
        self.resolution_combo = QComboBox()
        for label, height in RESOLUTION_OPTIONS:
            self.resolution_combo.addItem(label, height)
        self.resolution_combo.currentIndexChanged.connect(self.resolution_changed)
        output_form.addRow("Resolution", self.resolution_combo)
        controls_layout.addLayout(output_form)

        project_row = QHBoxLayout()
        self.open_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogOpenButton), "Open project")
        self.open_button.setToolTip("Open project (Ctrl+O)")
        # A QToolButton, so its arrow section can open the "Save as..." menu
        # while the main section still saves; the window's save-button update
        # fills in the caption, the tooltip and whether the menu is attached.
        self.save_button = QToolButton()
        self.save_button.setIcon(self._icon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.save_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.save_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.save_button.setSizePolicy(self.open_button.sizePolicy())
        project_row.addWidget(self.open_button)
        project_row.addWidget(self.save_button)
        controls_layout.addLayout(project_row)

        self.export_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogSaveButton), "Export PNG")
        self.export_button.setToolTip("Export PNG (Ctrl+E)")
        controls_layout.addWidget(self.export_button)

    def _icon(self, standard: QStyle.StandardPixmap):
        return self.style().standardIcon(standard)

    def align_save_button_height(self) -> None:
        # A QToolButton derives a taller box than a QPushButton from the same
        # stylesheet padding, so the save button takes its height from the
        # button beside it, once the stylesheet both of them size against is on.
        self.save_button.setFixedHeight(self.open_button.sizeHint().height())
