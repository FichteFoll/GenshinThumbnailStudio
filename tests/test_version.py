"""Tests that the package version is derived from the latest `v*` git tag."""

import subprocess
from pathlib import Path

from packaging.version import Version

import genshin_thumbnail_studio

ROOT = Path(__file__).resolve().parent.parent


def git_describe(*args: str) -> str:
    return subprocess.run(
        ["git", "describe", "--tags", "--match", "v*", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_package_version_derives_from_the_latest_tag() -> None:
    latest_tag = git_describe("--abbrev=0")
    tagged = Version(latest_tag.removeprefix("v"))
    installed = Version(genshin_thumbnail_studio.__version__)
    past_the_tag = installed.is_devrelease and installed > tagged
    if git_describe() == latest_tag:
        # The editable install is not rebuilt when only the tree's dirty state changes,
        # and a dirty tree on a tag builds as a dev release past it.
        assert installed == tagged or past_the_tag
    else:
        assert past_the_tag, f"{installed} is not a dev release past {latest_tag}"
