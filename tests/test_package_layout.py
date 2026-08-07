"""Guard the sub-package layout described in this repo's CLAUDE.md.

The assertions here are structural on purpose: they say which modules exist,
that sibling modules are reached by relative import, that each package's facade
re-exports only names it actually binds, and that no module has grown back past
the size that made the split necessary. Behavior is covered by the per-package
suites under `tests/akasha/`, `tests/renderer/` and `tests/gui/`.

This module is deliberately static: it walks the filesystem and parses sources
with `ast`, and imports neither `genshin_thumbnail_studio` nor PySide6. That is
what lets it run with no Qt environment and makes it immune to import-order
effects.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = TESTS_ROOT.parent / "src" / "genshin_thumbnail_studio"

EXPECTED_MODULES = {
    "__init__.py",
    "__main__.py",
    "models.py",
    "storage.py",
    "akasha/__init__.py",
    "akasha/errors.py",
    "akasha/http.py",
    "akasha/parsing.py",
    "akasha/rarities.py",
    "akasha/client.py",
    "akasha/assets.py",
    "renderer/__init__.py",
    "renderer/geometry.py",
    "renderer/colors.py",
    "renderer/coverage.py",
    "renderer/cache.py",
    "renderer/art.py",
    "renderer/panels.py",
    "renderer/badges.py",
    "renderer/compose.py",
    "gui/__init__.py",
    "gui/app.py",
    "gui/style.py",
    "gui/main_window.py",
    "gui/asset_loader.py",
    "gui/project_io.py",
    "gui/dialogs.py",
    "gui/state.py",
    "gui/placement.py",
    "gui/presets.py",
    "gui/preview.py",
    "gui/team_slots.py",
    "gui/render_job.py",
    "gui/lineup.py",
    "gui/history.py",
}

PACKAGE_NAME = "genshin_thumbnail_studio"

FACADES = ("akasha/__init__.py", "renderer/__init__.py", "gui/__init__.py")

TEST_PACKAGES = ("akasha", "renderer", "gui")

RETIRED_TEST_FILES = ("test_akasha.py", "test_renderer.py", "test_gui_smoke.py", "test_lineup.py")

# A regression tripwire, not a design target. `gui/main_window.py` is the largest
# module because its remaining flows (`load_profile`, the placement editing and
# the render throttle) are Qt-bound throughout; the blocking dialogs they put up
# live in `gui/dialogs.py`.
# A module crossing this bound is a signal to split it, not to raise the bound.
# Raised from 750 to 800 by explicit decision when the always-on preview left
# `main_window.py` at 756, on the understanding that the next crossing would
# reopen the split question rather than raise this again. That crossing came,
# and the answer was the split: `open_project`, `save_project` and `export` moved
# out into `gui/project_io.py`. Extracting the throttled render pipeline into its
# own module remains the deferred next candidate.
MAX_MODULE_LINES = 800


def source_files() -> list[Path]:
    return sorted(path for path in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in path.parts)


def relative_name(path: Path) -> str:
    return path.relative_to(PACKAGE_ROOT).as_posix()


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_every_expected_module_exists() -> None:
    found = {relative_name(path) for path in source_files()}
    assert sorted(found) == sorted(EXPECTED_MODULES)


def test_the_flat_modules_are_gone() -> None:
    for name in ("akasha.py", "renderer.py", "gui.py"):
        flat = PACKAGE_ROOT / name
        assert not flat.exists(), f"{relative_name(flat)} is back as a flat module; it should be a sub-package"


def test_no_module_imports_its_own_package_absolutely() -> None:
    def is_own_package(name: str | None) -> bool:
        return name == PACKAGE_NAME or (name is not None and name.startswith(f"{PACKAGE_NAME}."))

    violations: list[str] = []
    for path in source_files():
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.Import):
                if any(is_own_package(alias.name) for alias in node.names):
                    violations.append(f"{relative_name(path)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and is_own_package(node.module):
                violations.append(f"{relative_name(path)}:{node.lineno}")

    assert violations == [], f"absolute imports of {PACKAGE_NAME} (use relative imports instead): {violations}"


def facade_all(tree: ast.Module, name: str) -> list[str]:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        assert isinstance(node.value, ast.List | ast.Tuple), f"{name}: __all__ is not a list or tuple literal"
        entries: list[str] = []
        for element in node.value.elts:
            assert isinstance(element, ast.Constant) and isinstance(element.value, str), (
                f"{name}:{element.lineno}: __all__ entry is not a string literal"
            )
            entries.append(element.value)
        return entries
    raise AssertionError(f"{name}: no __all__ assignment found")


def test_every_package_facade_reexports_what_it_declares() -> None:
    for facade in FACADES:
        tree = parse(PACKAGE_ROOT / facade)
        exported = facade_all(tree, facade)
        bound = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert exported, f"{facade}: __all__ is empty"
        # `__all__` ordering is enforced by ruff's RUF022, which uses isort's key
        # (SCREAMING_CASE, CamelCase, snake_case); it is not asserted here.
        assert set(exported) <= bound, f"{facade}: __all__ names that are not imported: {sorted(set(exported) - bound)}"


def test_no_source_module_is_oversized() -> None:
    oversized = {
        relative_name(path): len(path.read_text(encoding="utf-8").splitlines())
        for path in source_files()
        if len(path.read_text(encoding="utf-8").splitlines()) > MAX_MODULE_LINES
    }
    assert oversized == {}, f"modules past the {MAX_MODULE_LINES}-line tripwire (split them): {oversized}"


def test_the_tests_mirror_the_package_layout() -> None:
    for name in TEST_PACKAGES:
        directory = TESTS_ROOT / name
        assert directory.is_dir(), f"tests/{name} is not a directory"
        assert (directory / "__init__.py").is_file(), f"tests/{name}/__init__.py is missing"
        assert sorted(path.name for path in directory.glob("test_*.py")), f"tests/{name} holds no test module"

    for name in RETIRED_TEST_FILES:
        retired = TESTS_ROOT / name
        assert not retired.exists(), f"tests/{name} is back; its tests belong in the mirrored test package"
