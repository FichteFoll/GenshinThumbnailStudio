# Design notes

Why the non-obvious parts are the way they are.
Read the entry for a module before changing it;
each of these was arrived at by fixing something.
For what lives where, see [architecture.md](architecture.md).

## `akasha/`

**Enka asset naming is the fragile part.**
`exact_art_url()` reconstructs the exact Enka asset stem
(including costume/skin IDs) from the Akasha character icon URL.
This is what breaks first if Akasha or Enka change their asset naming.

**`client.py` drives a browser, not HTTP.**
Akasha requires a real browser context,
so `AkashaWebClient` loads `akasha.cv` API endpoints through an offscreen `QWebEnginePage`
and reads the JSON back.

**Teardown order is manual.**
`close()` releases the `QWebEnginePage` before its `QWebEngineProfile`,
spinning the event loop between the two.
Qt does not do this automatically:
the profile passed to the page's constructor is not its Qt parent,
and QtWebEngine's cleanup is deferred.

## `renderer/`

**One pan-range formula.**
`zoom_offset_limits()` composes `cover_scale()`/`scaled_size()`/`offset_limits()`
into the reachable +/- offset per axis
for a source size cover-fit into a target at a zoom.
`max_offset()` is that applied to a panel's own target size,
and is what `cover_resize_offset()` clamps with by default,
so the GUI sliders and the renderer cannot disagree.

**A zoom below 100% never stretches.**
`scaled_size()` scales both art axes by the same factor,
leaving a transparent margin that the panel background and glow show through.

**Helpers carry no leading underscore.**
`scaled_size()` and `offset_limits()` are not part of the intended public surface,
but basedpyright's strict mode rejects cross-module use of
underscore-prefixed module-level names.

**Glow and portrait share one clamp.**
`glow_zoom()` is strictly proportional to the placement zoom
(`zoom * GLOW_ZOOM_FACTOR`, the factor currently `1.0`),
so the glow's framing tracks the portrait's at every zoom
instead of freezing below a threshold.
`make_panel()` computes `zoom_offset_limits(art.size, target, member.zoom)` once
and passes it as `limits` to both `panel_art()` calls,
so the two layers stop at the same offset
instead of each capping at its own, differently zoomed range.

**Flip crops rather than mirroring the source.**
`panel_art()` crops at the negated horizontal offset and mirrors the panel-sized crop,
which equals cropping mirrored source art at the original offset
but leaves the shared, read-only `source_art()` cache untouched.
Both the glow layer and the sharp portrait go through it,
so they cannot disagree about the mirroring.

**`compose.py` reaches `panels` as a module.**
`from . import panels`, deliberately,
rather than binding `make_panel`/`placeholder_panel` into its own globals:
that is what lets the panel-cache tests patch them on `renderer.panels`
and intercept a render already in flight.

## `gui/`

### Decomposition

`main_window.py` was reduced by moving the blocking dialogs to `dialogs.py`,
the project file flows to `project_io.py`,
and the throttled preview loop to `render_pipeline.py`.
The extracted modules take the window, or the state Protocol it satisfies,
as a parameter rather than importing `MainWindow`,
which is what keeps the package acyclic.

`RenderPipeline` owns the throttle timer, the request token
and the in-flight/stale flags,
and reports back over `rendered` and `failed`
rather than writing to the preview or the status bar itself,
so it needs no widget at all.
`MainWindow.schedule_render()` is a one-line delegate to it,
kept because `project_io.ProjectEditor` requires the method.
Its throttle is deliberately not a debounce:
restarting the timer on every mouse-move event
would mean it never fires during a drag.
(`HistoryController.schedule()` is the debounce, for the opposite reason.)

`project_io`'s functions take the window twice,
as `parent: QMainWindow` for the dialogs and status bar
and as `editor: ProjectEditor` for everything else,
because a Protocol cannot inherit from `QWidget`.
`ProjectEditor` extends `EditorState` and lives in `project_io.py`
rather than `state.py`, which is Qt-free and must stay that way.
`open_project()` additionally takes the window's `HistoryController`,
since it is that function's alone
and passing it keeps `MainWindow._history` private.

### Actions and the save button

The four project actions are `QAction`s, not `QShortcut`s,
because the "Save as..." menu entry needs an action anyway
and a `QMenu` renders an action's shortcut in the item itself.
A sequence bound to both a `QShortcut` and a `QAction` is ambiguous and fires neither,
so these four must not also get `QShortcut`s.
(`history.py` uses `QShortcut`s for undo/redo, which have no menu entry.)
Each action dispatches through a lambda rather than a bound method,
so a test that replaces the method on the instance replaces what fires.

`_update_save_button()` keeps the save button in step with `project_path`:
with a file it reads "Save project" and carries the menu holding "Save as...",
without one it reads "Save project as..." and carries no menu,
since the primary button already *is* "save as" then
(`Ctrl+Shift+S` still works, the action being registered on the window).
`set_project_path()` is the single write path for `project_path` after construction
precisely so no transition can miss that update;
`__init__`'s own `self.project_path = None` cannot go through it,
the buttons not existing yet,
which is what the call at `_build_ui`'s end covers.

The save button is a `QToolButton` for its dropdown,
so `style.py`'s `QToolButton` rule repeats the `QPushButton` colors, border and padding;
change the two together.
Its `QToolButton::menu-button` rule is not cosmetic:
once stylesheet-rendered, the tool button stops drawing
the divider between its main and arrow sections for itself.
The button also takes its height from `open_button` after the stylesheet is applied,
because a `QToolButton` derives a taller box than a `QPushButton` from the same padding.

### Continuous preview

There is no "Generate preview" button and no blocking download on the GUI thread.
`schedule_render()` starts its throttle timer whether or not any art has been downloaded,
`__init__` schedules the first render itself,
and `_mode_changed` schedules one instead of blanking the canvas,
so a slot without a downloaded `Asset` renders as `placeholder_panel()`
and the window always shows something.

The window owns an `AssetLoader` sharing its thread pool.
Its `failed` writes to the status bar with an 8000 ms timeout
rather than opening a dialog that would interrupt typing.
`ensure()` must be called wherever the set of named characters or loaded builds can change:
the success path of `load_profile`,
the end of `_member_changed` (which is also what `paste_teams` goes through),
both of `project_io.open_project`'s profile paths,
and `_history_restored()`,
because an undo can bring back a name whose art `_member_changed` pruned,
and it writes the combos before their signals are connected.

`export()` therefore cannot wait for a download:
it still runs `validate_team()` so an unresolved slot refuses to export,
but when the art is merely still missing
it starts `asset_loader.ensure()` and asks the user to retry.

### Placeholder slots are inert

`_filled_slots()` returns the `(team, slot)` pairs
whose member name is non-empty and casefolds into `self.assets`.
`sync_controls()` passes it to `PreviewWidget.set_context()`
and enables or disables the X/Y/zoom sliders, the flip check and the reset button
on whether the selection is in it.
`drag_placement`/`change_zoom` early-return on the same check,
so the programmatic path cannot pan a placeholder or record an undo step for a no-op.
In `PreviewWidget`, `mousePressEvent` neither selects nor starts a drag on a placeholder,
`wheelEvent` ignores the wheel when the *selected* slot is one
(the wheel zooms the selection, not what the pointer is over),
and `paintEvent` draws no selection highlight around one.
`_on_asset_ready` calls `sync_controls()` for this reason:
re-deriving `_filled_slots()` is what turns the slot whose art just arrived
into an editable portrait.

### Shutdown

`closeEvent` first confirms discarding unsaved changes
through the same `dialogs.confirm_discard_changes()` `_mode_changed` uses,
then sets `_closing`, calls `RenderPipeline.stop()`,
drains the pool (`waitForDone(2000)`)
and finally calls `AkashaWebClient.close()`.
Draining alone is not enough:
both job kinds signal the GUI thread over a queued connection,
so `waitForDone()` returns with their slots still in the event queue,
and the `client.close()` that follows spins the loops that deliver them.
That is why `RenderPipeline.schedule()` and `dispatch()`
both bail on its own `closing` flag
rather than reviving the timer or re-dispatching onto the drained pool,
and why `_on_asset_ready` bails on the window's `_closing` too.
The window keeps a flag of its own because that handler reads it.

### Undo/redo

A history state is a deep copy of `Project.teams`,
so it carries every member's name, framing, color and order.
The rest of the `Project` (mode, uid, output settings, active team) is deliberately excluded,
since undoing must not switch the mode and thereby discard all teams.
Every state stored or handed out is deep-copied,
and `commit()` is a no-op returning `False` when the teams equal the current state.

`HistoryController.schedule()` is a debounce (600 ms),
not the throttle `MainWindow.schedule_render()` is,
so a whole drag or slider sweep becomes one undo step.
Continuous edits (sliders, drag, zoom, flip, per-keystroke `_member_changed`,
and `_on_asset_ready`, where an arriving asset's preset reframes its member
outside any edit handler) schedule;
the discrete `reset_placement` and `_on_slot_drag_ended` `commit_now()`;
`_mode_changed` and both of `project_io.open_project`'s exits `reset()`,
since they replace `self.project` wholesale
and an older snapshot would let `Ctrl+Z` resurrect a lineup from a different document.

`_history_restored()` is the `on_restored` callback the window passes in:
it rebuilds the team fields, syncs the controls,
re-saves the selected character's preset
so `PresetStore` and the visible framing do not disagree,
and schedules a render.

`undo()`/`redo()` restore onto `state.project.teams`,
call that callback, then `replace_current()` the result:
`_history_restored()` runs `sync_controls()`, which quantizes every offset to per-mille,
and without recording that normalized form
the next `commit_now()` would read the quantization as a fresh edit and truncate the redo tail.

The `Ctrl+Z`/`Ctrl+Y`/`Ctrl+Shift+Z` shortcuts are window-level
and are dispatched before a focused `QLineEdit` sees the key,
so `undo()`/`redo()` first check `QApplication.focusWidget()`
and delegate to that widget's own undo stack when it is one,
letting text fields and the editable team combos keep their own undo.

### Slot drag-and-drop

`reorder_slots()` moves a `Placement` by insert/shift
over the flattened, team-major sequence of all slots.
`_on_slot_drag_hover` calls it once per slot the drag passes over,
so the reorder happens live rather than only on drop.
`_on_slot_drag_started` deep-copies the teams into `self._drag_snapshot`;
if the drag ends without a drop, `_on_slot_drag_ended` restores it.

Nothing may be snapshotted mid-gesture:
`reorder_slots()` checks `self._drag_position` and records nothing there,
so a whole drag-and-drop is a single undo step that `_on_slot_drag_ended` commits
(a no-op after a cancelled drag, whose restore already put the teams back).
Nothing may be *scheduled* mid-gesture either,
which is why `_on_slot_drag_started` calls `commit_now()` first:
a debounce firing while the user rests over a slot would snapshot a half-finished arrangement,
and a cancelled drag would then leave the reorder it just reverted one `Ctrl+Z` away.

### Collaborators read state freshly

`PlacementController`, `PresetStore`, `AssetLoader` and `HistoryController`
read the window's `project`/`builds`/`assets` through `EditorState` on *every* call
instead of capturing them at construction,
because `_mode_changed`, `project_io.open_project`, `load_profile` and `_member_changed`
all replace those attributes wholesale.
A captured reference would go stale,
and a stale `assets` would silently fall back to `STANDARD_ART_SIZE`
and compute the wrong offset bounds.

`MAX_ZOOM` in `placement.py` *is* the renderer's `MAX_PLACEMENT_ZOOM`,
not a copy of its value,
because the renderer sizes its cached working copy of the source art for exactly that ceiling;
a placement zoomed past it would be upsampled.

### Where the tests patch

`dialogs.py` is where the `QMessageBox`/`QInputDialog` construction lives,
so the gui tests patch it there
(`monkeypatch.setattr(dialogs, "QMessageBox", ...)`).
The `QFileDialog` calls live in `project_io.py`,
so the tests name that module instead
(`monkeypatch.setattr(project_io.QFileDialog, "getSaveFileName", ...)`);
the patch lands on `QFileDialog`'s class attribute either way.
This is also why `main_window` imports both as modules
rather than importing their functions by name.
