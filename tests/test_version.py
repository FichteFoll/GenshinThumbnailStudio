"""Tests that the two places the version lives agree."""

from importlib.metadata import version

import genshin_thumbnail_studio


def test_package_version_matches_the_project_metadata() -> None:
    assert genshin_thumbnail_studio.__version__ == version("genshin-thumbnail-studio")
