"""The whole application's stylesheet, applied once to the main window.

`TeamSlotWidget[dropTarget="true"]` selects on the property that
`TeamSlotWidget._set_drop_target()` sets, so the two must be changed together.
"""

from __future__ import annotations

MAIN_STYLESHEET = """
QMainWindow, QWidget { background: #1a1b20; color: #f1f2f4; }
QLineEdit, QComboBox { background: #26282f; border: 1px solid #484b55; padding: 6px; min-height: 22px; }
/* The QPushButton and QToolButton rules are a pair: the save button is a
   QToolButton for its dropdown, and has to look like the buttons around it. */
QPushButton { background: #30333b; border: 1px solid #515561; padding: 7px 10px; }
QPushButton:hover { background: #3a3e48; border-color: #777d8b; }
QPushButton:pressed { background: #25272d; }
QToolButton { background: #30333b; border: 1px solid #515561; padding: 7px 10px; }
QToolButton:hover { background: #3a3e48; border-color: #777d8b; }
QToolButton:pressed { background: #25272d; }
/* Once the tool button is stylesheet-rendered it stops drawing the divider
   between its main and its arrow section for itself, so ::menu-button has to. */
QToolButton::menu-button { width: 16px; border-left: 1px solid #515561; }
QRadioButton { spacing: 6px; }
QSlider::groove:horizontal { height: 4px; background: #454954; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #ffd95d; border-radius: 7px; }
QLabel#secondary { color: #aeb3bf; }
QScrollArea { background: transparent; }
TeamSlotWidget[dropTarget="true"] { background: #3a3e48; border: 1px solid #ffd95d; }
"""
