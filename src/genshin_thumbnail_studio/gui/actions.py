"""The four project file actions and their key bindings, as a `ProjectActions`
collaborator wired once to the window it acts on.

Nothing here imports `MainWindow`, so the window can own the actions without a
cycle. What the actions dispatch to is spelled out by the `ProjectActionHost`
Protocol below, which `MainWindow` satisfies structurally.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMenu

from .controls_panel import ControlsPanel


class ProjectActionHost(Protocol):
    """The project file flows the actions dispatch to.

    `MainWindow` satisfies it structurally; nothing has to declare it.
    """

    def new_project(self) -> None: ...
    def open_project(self) -> None: ...
    def save_project(self) -> None: ...
    def save_project_as(self) -> None: ...
    def export(self) -> None: ...


class ProjectActions(QObject):
    """The project actions and the save button's two faces, wired once to the
    window they act on.

    Takes the window twice, as `window: QMainWindow` for the action
    registration and as `host: ProjectActionHost` for the dispatch, because a
    Protocol cannot inherit from `QWidget`, the same reason `project_io.py`
    gives.
    """

    def __init__(self, window: QMainWindow, host: ProjectActionHost) -> None:
        super().__init__(window)
        self._window = window
        self._panel: ControlsPanel | None = None
        # Deliberately `QAction`s and not `QShortcut`s like `history.py` uses:
        # the "Save as..." menu entry needs an action anyway, and a sequence
        # bound to both would be ambiguous and fire neither.
        self.new = self._action("New project", "Ctrl+N", lambda: host.new_project())
        self.open = self._action("Open project", "Ctrl+O", lambda: host.open_project())
        self.save = self._action("Save project", "Ctrl+S", lambda: host.save_project())
        self.save_as = self._action("Save as...", "Ctrl+Shift+S", lambda: host.save_project_as())
        self.export = self._action("Export PNG", "Ctrl+E", lambda: host.export())
        self._save_menu = QMenu(window)
        self._save_menu.addAction(self.save_as)

    def _action(self, text: str, sequence: str, handler: Callable[[], None]) -> QAction:
        """A window-wide action for one of the project file flows.

        Registered on the window with `addAction()`, so its shortcut fires
        wherever the focus is, and so `window.actions()` lists the bindings.
        Callers pass a lambda rather than a bound method, so the dispatch stays
        late-bound and replacing the method on the instance replaces what fires.
        """
        action = QAction(text, self._window)
        action.setShortcut(QKeySequence(sequence))
        action.triggered.connect(handler)
        self._window.addAction(action)
        return action

    def bind_buttons(self, panel: ControlsPanel) -> None:
        """Let the panel's project buttons trigger these actions."""
        self._panel = panel
        panel.new_button.clicked.connect(self.new.trigger)
        panel.open_button.clicked.connect(self.open.trigger)
        panel.save_button.clicked.connect(self.save.trigger)
        panel.export_button.clicked.connect(self.export.trigger)
        panel.new_button.setToolTip("New project (Ctrl+N)")
        panel.open_button.setToolTip("Open project (Ctrl+O)")
        panel.export_button.setToolTip("Export PNG (Ctrl+E)")

    def set_project_path(self, path: Path | None) -> None:
        """Show whether saving overwrites a file or asks for one.

        Driven from `MainWindow.set_project_path()`, the single write path for
        `project_path`, so no transition can miss it.
        """
        if self._panel is None:
            raise RuntimeError("bind_buttons() has to run before the save button can show an action")
        self.save.setText("Save project" if path else "Save project as...")
        self.save.setToolTip(f"Save {path.name} (Ctrl+S)" if path else "Save project as... (Ctrl+S)")
        # Without a file to overwrite the button already *is* "save as", so a
        # menu repeating it would be noise; Ctrl+Shift+S still works, because
        # the action is registered on the window rather than only on the menu.
        self._panel.apply_save_action(self.save.text(), self.save.toolTip(), self._save_menu if path else None)
