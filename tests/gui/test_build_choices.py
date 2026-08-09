"""Tests for merging the profile's builds with the one a project remembers.

Qt-free: `build_choices()` is the pure rule the dropdown renders.
"""

from genshin_thumbnail_studio.gui.build_choices import BuildChoice, build_choices
from genshin_thumbnail_studio.models import LIVE_BUILD_NAME, Build


def make_build(
    build_name: str = LIVE_BUILD_NAME,
    *,
    name: str = "Furina",
    constellation: int = 1,
    refinement: int = 2,
    weapon_name: str = "Splendor of Tranquil Waters",
    costume_id: str | None = None,
) -> Build:
    return Build(
        name=name,
        constellation=constellation,
        refinement=refinement,
        weapon_name=weapon_name,
        costume_id=costume_id,
        build_name=build_name,
        build_id=f"{name}-{build_name}",
        art_url=f"https://enka.network/ui/{name}.png",
        weapon_url="https://enka.network/ui/weapon.png",
    )


def labels(choices: list[BuildChoice]) -> list[str]:
    return [choice.label for choice in choices]


def selected_labels(choices: list[BuildChoice]) -> list[str]:
    return [choice.label for choice in choices if choice.selected]


def project_labels(choices: list[BuildChoice]) -> list[str]:
    return [choice.label for choice in choices if choice.label.endswith(" (project)")]


def test_without_a_stored_build_the_live_one_is_selected() -> None:
    """The live build, which the profile lists first, is the default."""
    live = make_build()
    saved = make_build("Bow DPS")

    choices = build_choices([live, saved], None)

    assert labels(choices) == [LIVE_BUILD_NAME, "Bow DPS"]
    assert [choice.build for choice in choices] == [live, saved]
    assert selected_labels(choices) == [LIVE_BUILD_NAME]


def test_a_stored_build_the_profile_no_longer_offers_is_appended_and_selected() -> None:
    """R2: a snapshot the profile has lost is still the build the slot uses,
    labelled as coming from the project."""
    live = make_build()
    stored = make_build("Retired", weapon_name="Aqua Simulacra")

    choices = build_choices([live], stored)

    assert labels(choices) == [LIVE_BUILD_NAME, "Retired (project)"]
    assert choices[1].build is stored
    assert selected_labels(choices) == ["Retired (project)"]


def test_a_stored_build_matching_the_profile_yields_one_bare_choice() -> None:
    """R2: only a choice that actually carries the snapshot is labelled.

    A snapshot with identical details is merged into the profile's own `Build`,
    so the single entry left is the profile's and keeps its bare name.
    """
    live = make_build()
    saved = make_build("Bow DPS")
    stored = make_build("Bow DPS")

    choices = build_choices([live, saved], stored)

    assert labels(choices) == [LIVE_BUILD_NAME, "Bow DPS"]
    assert selected_labels(choices) == ["Bow DPS"]
    # It carries the profile's Build, since the details are identical.
    assert choices[1].build is saved


def test_a_stored_build_differing_from_the_live_one_offers_both() -> None:
    """R2/R4: same name, different details, so both are on offer; the stored
    one is labelled "(project)" and selected, the profile's own entry keeps its
    bare name and is not selected."""
    live = make_build(constellation=6, refinement=5, costume_id="203201")
    other = make_build("Bow DPS")
    stored = make_build()

    choices = build_choices([live, other], stored)

    assert labels(choices) == [
        f"{LIVE_BUILD_NAME} (project)",
        LIVE_BUILD_NAME,
        "Bow DPS",
    ]
    assert choices[0].build is stored
    assert choices[1].build is live
    assert selected_labels(choices) == [f"{LIVE_BUILD_NAME} (project)"]
    # The other profile builds are untouched by the split.
    assert choices[2].build is other


def test_nothing_known_yields_no_choices() -> None:
    assert build_choices([], None) == []


def test_a_duplicated_build_name_still_selects_exactly_one_choice() -> None:
    """Build names are free text, so a profile can hold two of one name.

    Merging the snapshot into each of them would check several entries at once,
    which the dropdown renders as an incoherent menu.
    """
    stored = make_build("Bow DPS", constellation=6)
    profile = [
        make_build(),
        make_build("Bow DPS"),
        make_build("Bow DPS", refinement=5),
    ]

    choices = build_choices(profile, stored)

    assert selected_labels(choices) == ["Bow DPS (project)"]
    assert labels(choices) == [LIVE_BUILD_NAME, "Bow DPS (project)", "Bow DPS", "Bow DPS"]


def test_no_choice_of_any_case_carries_a_suffixed_build_name() -> None:
    """R3: the suffix is display-only and must never reach `Build.build_name`,
    since `Project.to_dict()` serializes it verbatim."""
    live = make_build()
    drifted = make_build(constellation=6, refinement=5, costume_id="203201")
    saved = make_build("Bow DPS")
    cases = [
        build_choices([live, saved], None),
        build_choices([live], make_build("Retired", weapon_name="Aqua Simulacra")),
        build_choices([live, saved], make_build("Bow DPS")),
        build_choices([drifted, saved], live),
    ]

    for choices in cases:
        assert [choice for choice in choices if choice.build.build_name.endswith(" (project)")] == []
    # Not vacuous: two of the four cases do label a choice.
    assert [project_labels(choices) for choices in cases] == [
        [],
        ["Retired (project)"],
        [],
        [f"{LIVE_BUILD_NAME} (project)"],
    ]
