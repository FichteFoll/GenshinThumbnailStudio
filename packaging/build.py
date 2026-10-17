"""Build the standalone package for the current OS into `release/`.

Clears `build/`, `dist/` and `release/`, runs the test suite,
freezes the app with PyInstaller from the committed spec,
smoke-tests the frozen binary and archives it.
Run it as `uv run python packaging/build.py [--skip-tests]`.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from genshin_thumbnail_studio import __version__

PACKAGING = Path(__file__).resolve().parent
ROOT = PACKAGING.parent
SPEC = PACKAGING / "GenshinThumbnailStudio.spec"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
RELEASE = ROOT / "release"
APP_NAME = "GenshinThumbnailStudio"
SMOKE_TEST_TIMEOUT_S = 120

OS_NAMES = {"linux": "linux", "win32": "windows"}
ARCHIVE_FORMATS = {"linux": "gztar", "windows": "zip"}
X64_MACHINES = {"x86_64", "AMD64"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-tests", action="store_true", help="do not run the test suite first")
    args = parser.parse_args()

    os_name = OS_NAMES.get(sys.platform)
    if os_name is None:
        sys.exit(f"Unsupported platform for a package: {sys.platform}")
    if platform.machine() not in X64_MACHINES:
        sys.exit(f"Unsupported architecture for an x64 package: {platform.machine()}")

    clean()
    if not args.skip_tests:
        run_tests()
    freeze()
    smoke_test(DIST / APP_NAME / executable_name(os_name))
    archive_path = archive(os_name)
    print(f"Created {archive_path}")
    return 0


def clean() -> None:
    # Before the tests, so that no failed step leaves an earlier archive behind looking current.
    for directory in (BUILD, DIST, RELEASE):
        shutil.rmtree(directory, ignore_errors=True)


def run_tests() -> None:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    subprocess.run([sys.executable, "-m", "pytest"], cwd=ROOT, env=env, check=True)


def freeze() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD),
            str(SPEC),
        ],
        cwd=ROOT,
        check=True,
    )


def executable_name(os_name: str) -> str:
    return f"{APP_NAME}.exe" if os_name == "windows" else APP_NAME


def smoke_test(executable: Path) -> None:
    # A fresh data dir keeps the run away from the user's real projects and cache,
    # and gives its log file a known place to be printed from on failure.
    with tempfile.TemporaryDirectory(prefix="gts-smoke-") as data_dir:
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "GENSHIN_THUMBNAIL_STUDIO_DATA_DIR": data_dir}
        try:
            # `subprocess.run` waits for the process itself, so it also waits for a
            # GUI-subsystem `.exe`, which a Windows shell would detach from.
            subprocess.run([str(executable), "--smoke-test"], env=env, timeout=SMOKE_TEST_TIMEOUT_S, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            # A windowed exe has no console, so its log file is the only diagnostic CI gets.
            print_log(Path(data_dir) / "logs" / "app.log")
            sys.exit(f"Smoke test of {executable} failed: {error}")
    print(f"Smoke test of {executable} passed")


def print_log(log_file: Path) -> None:
    if not log_file.is_file():
        print(f"No log file at {log_file}", file=sys.stderr)
        return
    print(f"--- {log_file} ---", file=sys.stderr)
    print(log_file.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)


def archive(os_name: str) -> str:
    return shutil.make_archive(
        str(RELEASE / f"{APP_NAME}-{__version__}-{os_name}-x64"),
        ARCHIVE_FORMATS[os_name],
        root_dir=DIST,
        base_dir=APP_NAME,
    )


if __name__ == "__main__":
    sys.exit(main())
