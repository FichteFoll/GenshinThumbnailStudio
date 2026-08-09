"""The blocking dialog flows `MainWindow` puts up: confirmations, prompts and
notifications, each a free function taking the parent widget.

Nothing here imports `MainWindow`, so the window can call into this module
without a cycle; what a dialog's answer means is decided by the caller, which is
why these return the user's choice rather than acting on it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMainWindow, QMessageBox, QWidget


def confirm_discard_changes(
    parent: QWidget, action: str, is_dirty: Callable[[], bool], save: Callable[[], None]
) -> bool:
    """Ask whether to save unsaved changes before `action` proceeds.

    Returns True when it is safe to proceed: there were no unsaved changes, the
    user chose to discard them, or the user chose to save and the save
    completed. Returns False when the caller must abort, either because the
    user chose Cancel or the save dialog was itself cancelled.
    """
    if not is_dirty():
        return True
    dialog = QMessageBox(parent)
    dialog.setWindowTitle("Unsaved changes")
    dialog.setText(f"This project has unsaved changes. Save before you {action}?")
    save_button = dialog.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
    discard_button = dialog.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
    dialog.addButton(QMessageBox.StandardButton.Cancel)
    dialog.exec()
    clicked = dialog.clickedButton()
    if clicked == discard_button:
        return True
    if clicked == save_button:
        save()
        return not is_dirty()
    return False


def confirm_cache_refresh(parent: QWidget, age_minutes: float) -> bool:
    """Ask whether to refresh a cached profile older than an hour."""
    dialog = QMessageBox(parent)
    dialog.setWindowTitle("Cached profile is older than one hour")
    dialog.setText(f"Last updated {age_minutes / 60:.1f} hours ago.")
    refresh_button = dialog.addButton("Refresh now", QMessageBox.ButtonRole.AcceptRole)
    dialog.addButton(QMessageBox.StandardButton.Cancel)
    dialog.exec()
    return dialog.clickedButton() == refresh_button


def show_error(parent: QMainWindow, title: str, error: Exception | str) -> None:
    """Report `error` modally and leave it in the window's status bar."""
    QMessageBox.critical(parent, title, str(error))
    parent.statusBar().showMessage(str(error), 10000)


def show_export_finished(parent: QWidget, written: list[Path]) -> None:
    QMessageBox.information(parent, "Export finished", "\n".join(str(path) for path in written))


def ask_lineup_text(parent: QWidget, expected: int) -> str | None:
    """Prompt for a pasted lineup, or return None when the prompt was cancelled."""
    text, ok = QInputDialog.getMultiLineText(
        parent,
        "Lineup",
        f"{expected} character names in order, separated by comma, semicolon, pipe (|), or newline:",
    )
    return text if ok else None


def ask_export_target(parent: QWidget, mode: str, default_dir: Path, stem: str) -> tuple[Path, str] | None:
    """Ask where to export to, as a (directory, file stem) pair, or None if cancelled.

    Abyss writes one PNG, so the user picks its name; stygian writes three files
    at once, so only the folder can be chosen and `stem` is kept as it is.
    """
    if mode != "abyss":
        directory = QFileDialog.getExistingDirectory(parent, "Choose output folder", str(default_dir))
        return (Path(directory), stem) if directory else None
    path, _ = QFileDialog.getSaveFileName(parent, "Export PNG", str(default_dir / f"{stem}.png"), "PNG (*.png)")
    if not path:
        return None
    target = Path(path)
    return target.parent, target.stem
