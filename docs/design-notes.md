# Design notes

Why the non-obvious parts are the way they are.
Read the entry for a module before changing it;
each of these was arrived at by fixing something.
For what lives where, see [architecture.md](architecture.md).

## `enka/`

**`character.icon.gacha` ignores an equipped costume.**
It is a full URL to the *default* gacha art regardless of what the character is wearing,
so `parsing.art_url()` reads `costume.data["Art"]` instead when a costume is equipped,
falling back to `icon.gacha` only when the costume carries no usable `Art` entry.

**Never touch `costume.icon`.**
It is a computed pydantic property that reads a `sideIconName` key,
which the current asset data does not have;
merely `repr()`-ing a costume with an equipped skin raises `KeyError: 'sideIconName'`.

**The library's asset directory is CWD-relative, with no public setting.**
`enka`'s `ASSET_PATH` is `.enka_py/assets`, about 5 MB across seven files,
resolved relative to the working directory rather than the app data dir.
`client.redirect_asset_files()` rewrites the private `_path` of every entry
on the library's asset manager before the first client starts,
which is the only way to move it.

**The live build comes from the showcase, not from the builds endpoint's `live: true` entries.**
The saved-builds endpoint marks entries the user snapshotted
the last time they pressed "refresh" on enka.network, which may be arbitrarily old.
`fetch_showcase(uid)` is genuinely current, so that is what becomes the build
named `"Live"`, and `live: true` entries from the builds endpoint are dropped as duplicates.

**The downloaded-art dict is keyed by character *and* build.**
Two stygian bosses can use different builds of one character,
which means different weapon icons and possibly a different skin,
so a key of the bare character name would let one slot's asset
overwrite or be served to the other's.

**That key travels on the `Placement` as `asset_key`, rather than being resolved where it is needed.**
The renderer never sees the editor's `builds` map,
so it cannot turn a bare character name into "whichever build this slot has selected".
The editor therefore assigns `Placement.build` eagerly, as soon as a build is resolvable,
and both sides read the one key off it.
The panel render cache keys on `asset_key` for the same reason:
without it, two builds of one character would serve each other's cached panel.

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

`main_window.py` is the window and little else:
the splitter holding the two panels,
the selection and placement handlers,
the asset-arrival handlers, the close sequence,
and thin delegates to the collaborators.
Everything else it used to hold lives in a module of its own:
the two columns of the layout in `controls_panel.py` and `editor_panel.py`,
the blocking dialogs in `dialogs.py`,
the project file flows in `project_io.py`,
profile loading and lineup entry in `profile_io.py`,
the project actions and the save button's two faces in `actions.py`,
the throttled preview loop in `render_pipeline.py`,
and the team slot fields with their drag reordering in `team_fields.py`.
All of them take the window, or the Protocol it satisfies,
as a parameter rather than importing `MainWindow`,
which is what keeps the package acyclic.

The delegates that remain on the window are not compat shims.
`schedule_render()`, `rebuild_team_fields()`, `populate_combo_items()`,
`load_profile()`, `validate_team()`, `save_project()`, `save_project_as()`,
`open_project()` and `export()` are the contract
`project_io.ProjectEditor` requires,
and `dialogs.confirm_discard_changes()` takes `save_project` as a callback.
Widget access is not delegated:
`ProjectEditor`, `ProfileEditor` and the tests
reach every widget through `controls_panel` or `editor_panel`.

Every collaborator has the same shape:
a class taking its parent widget,
the Protocol object it works on,
and any collaborator of its own that it needs,
constructed once in `MainWindow.__init__` and kept there.
`dialogs.py` is the deliberate exception and stays free functions:
their parent genuinely varies,
they hold no state between calls,
and they are called from the window and the collaborators alike.

`RenderPipeline` owns the throttle timer, the request token
and the in-flight/stale flags,
and reports back over `rendered` and `failed`
rather than writing to the preview or the status bar itself,
so it needs no widget at all.
Its throttle is deliberately not a debounce:
restarting the timer on every mouse-move event
would mean it never fires during a drag.
(`HistoryController.schedule()` is the debounce, for the opposite reason.)

`ControlsPanel` is a `QWidget` that owns its children
and exposes them both ways:
as public attributes, which `project_io.ProjectEditor` and the tests reach through,
and as its own signals
(`mode_changed`, `profile_requested`, `paste_requested`,
`output_name_changed`, `resolution_changed`),
which keep the window from reaching into the panel to connect a handler.
The new, open, save and export buttons get no signal:
they trigger the project `QAction`s,
which `actions.ProjectActions.bind_buttons()` connects them to.
`align_save_button_height()` is a method rather than part of the constructor,
because it can only run once the window has applied the stylesheet
both buttons size against.

`EditorPanel` is the same shape for the right column,
owning the preview toolbar, the canvas and the placement row,
and reporting
`active_team_changed`, `placement_changed`, `flip_toggled` and `reset_requested`.
`PreviewWidget`'s own `slot_selected`, `placement_dragged` and `zoom_requested`
are deliberately not re-exposed:
they are the canvas's signals rather than the column's,
and forwarding them would only add a hop,
so the window connects to `editor_panel.preview` directly.
The three sliders share one `placement_changed`,
because the window's handler already reads all three values back.

`TeamFieldsController` owns the combos rather than the window,
and fills the `team_layout` `ControlsPanel` hands it,
so the panel describes the column's shape and the controller its contents.
It takes the `HistoryController` as a constructor argument
for the same reason `ProjectFiles` does,
because the drag handlers commit through it.
`MainWindow.member_changed()` is public rather than private
so the window satisfies the `TeamFieldsEditor` Protocol.

`ProjectFiles` takes the window twice,
as `parent: QMainWindow` for the dialogs and status bar
and as `editor: ProjectEditor` for everything else,
because a Protocol cannot inherit from `QWidget`.
`ProjectEditor` extends `EditorState` and lives in `project_io.py`
rather than `state.py`, which is Qt-free and must stay that way.
The window's `HistoryController` is a third constructor argument,
which `open()` alone uses,
and passing it keeps `MainWindow._history` private.
Capturing those three objects is safe;
capturing `project`, `builds` or `assets` off the editor is not,
for the reason "Collaborators read state freshly" gives below.

`ProfileLoader` mirrors that shape for profile fetching and lineup entry:
it takes the window twice, as `parent: QMainWindow` and as `editor: ProfileEditor`,
for the same reason `ProjectFiles` does, and needs no `HistoryController`,
since none of `load()`, `paste_lineup()` or `validate_team()` touch undo history.
`validate_team()` puts up no dialog itself: it raises `ValueError` on a name
the loaded profile does not resolve, and its callers
(`project_io.ProjectFiles._write_project`/`export`) decide what to do with that.

### Actions and the save button

All of this lives in `actions.py` as `ProjectActions`,
constructed once in `MainWindow.__init__` with the window
and the window as `ProjectActionHost`,
the shape the other collaborators have.
It is built after the layout on purpose:
having the panels already there is what lets `bind_buttons()`
wire the buttons in one call,
instead of forcing the actions to exist before the buttons do.

The five project actions are `QAction`s, not `QShortcut`s,
because the "Save as..." menu entry needs an action anyway
and a `QMenu` renders an action's shortcut in the item itself.
A sequence bound to both a `QShortcut` and a `QAction` is ambiguous and fires neither,
so these four must not also get `QShortcut`s.
(`history.py` uses `QShortcut`s for undo/redo, which have no menu entry.)
Each action dispatches through a lambda rather than a bound method,
so a test that replaces the method on the instance replaces what fires;
capturing a bound method at construction would make
`tests/gui/test_shortcuts.py` fail.
Each is registered on the window with `addAction()` rather than on
`ProjectActions` itself, which is what makes the shortcut window-wide
and what keeps `window.actions()` populated for that test to look bindings up in.

`ProjectActions.set_project_path()` keeps the save button in step with `project_path`:
with a file it reads "Save project" and carries the menu holding "Save as...",
without one it reads "Save project as..." and carries no menu,
since the primary button already *is* "save as" then
(`Ctrl+Shift+S` still works, the action being registered on the window).
That policy is deliberately split from the widget writes,
which are `ControlsPanel.apply_save_action(text, tooltip, menu)`:
letting the panel decide from a `Path`
would put project-file knowledge into a layout widget.
`MainWindow.set_project_path()` is the single write path for `project_path`
after construction precisely so no transition can miss that update;
`__init__`'s own `self.project_path = None` cannot go through it,
the buttons not existing yet,
which is what the explicit call after `bind_buttons()` covers.

The save button is a `QToolButton` for its dropdown,
so `style.py`'s `QToolButton` rule repeats the `QPushButton` colors, border and padding;
change the two together.
Its `QToolButton::menu-button` rule is not cosmetic:
once stylesheet-rendered, the tool button stops drawing
the divider between its main and arrow sections for itself.
The button also takes its height from `open_button` after the stylesheet is applied,
because a `QToolButton` derives a taller box than a `QPushButton` from the same padding;
that is `ControlsPanel.align_save_button_height()`.

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
the end of `member_changed` (which is also what `paste_teams` goes through),
the end of `build_selected`, which swaps one build's art for another's,
both of `project_io.ProjectFiles.open`'s profile paths,
and `_history_restored()`,
because an undo can bring back a name whose art `member_changed` pruned,
and it writes the combos before their signals are connected.

`export()` therefore cannot wait for a download:
it still runs `validate_team()` so an unresolved slot refuses to export,
but when the art is merely still missing
it starts `asset_loader.ensure()` and asks the user to retry.

### Placeholder slots are inert

`_filled_slots()` returns the `(team, slot)` pairs
whose member name is non-empty
and whose resolved build's `key` is in `self.assets`.
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
then sets `_closing`, calls `RenderPipeline.stop()`
and drains the pool (`waitForDone(2000)`).
`EnkaClient` holds no session between calls, so there is nothing to close.
Draining alone does not guarantee both job kinds' queued-connection signals
are delivered before the window goes away,
which is why `RenderPipeline.schedule()` and `dispatch()`
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
Continuous edits (sliders, drag, zoom, flip, per-keystroke `member_changed`,
and `_on_asset_ready`, where an arriving asset's preset reframes its member
outside any edit handler) schedule;
the discrete `reset_placement`
and `team_fields.TeamFieldsController.on_drag_ended()` `commit_now()`;
`_mode_changed` and both of `project_io.ProjectFiles.open`'s exits `reset()`,
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

`TeamFieldsController.reorder()` moves a `Placement` by insert/shift
over the flattened, team-major sequence of all slots.
`on_drag_hover()` calls it once per slot the drag passes over,
so the reorder happens live rather than only on drop.
`on_drag_started()` deep-copies the teams into `self._drag_snapshot`;
if the drag ends without a drop, `on_drag_ended()` restores it.

Nothing may be snapshotted mid-gesture:
`reorder()` checks `self._drag_position` and records nothing there,
so a whole drag-and-drop is a single undo step that `on_drag_ended()` commits
(a no-op after a cancelled drag, whose restore already put the teams back).
`MainWindow._on_asset_ready` reads the same state through the public `dragging`,
for the same reason.
Nothing may be *scheduled* mid-gesture either,
which is why `on_drag_started()` calls `commit_now()` first:
a debounce firing while the user rests over a slot would snapshot a half-finished arrangement,
and a cancelled drag would then leave the reorder it just reverted one `Ctrl+Z` away.

### Collaborators read state freshly

Every collaborator
(`PlacementController`, `PresetStore`, `AssetLoader`, `HistoryController`,
`TeamFieldsController`, `RenderPipeline`, `ProjectFiles` and `ProfileLoader`)
reads the window's `project`/`builds`/`assets` through `EditorState` on *every* call
instead of capturing them at construction,
because `_mode_changed`, `project_io.ProjectFiles.open`, `load_profile` and `member_changed`
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
This is also why `main_window` imports `dialogs` as a module
rather than importing its functions by name.
From `project_io` it may import `ProjectFiles` by name instead,
because that patch lands on `QFileDialog` itself
rather than on an attribute of the module.
`profile_io` is imported as a module too
(`from . import dialogs, profile_io`), matching `dialogs`,
even though nothing today patches a module-level name on it;
should a test ever need to, the import already supports it.
