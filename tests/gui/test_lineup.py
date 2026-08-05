"""Tests for `gui.lineup.parse_lineup()`."""

from genshin_thumbnail_studio.gui.lineup import parse_lineup


def test_parse_lineup_comma_separated() -> None:
    assert parse_lineup("Hu Tao, Xingqiu, Yelan, Zhongli") == [
        "Hu Tao",
        "Xingqiu",
        "Yelan",
        "Zhongli",
    ]


def test_parse_lineup_pipe_separated() -> None:
    assert parse_lineup("Hu Tao|Xingqiu|Yelan|Zhongli") == [
        "Hu Tao",
        "Xingqiu",
        "Yelan",
        "Zhongli",
    ]


def test_parse_lineup_mixed_separators() -> None:
    text = "Hu Tao, Xingqiu; Yelan|Zhongli\nNahida"
    assert parse_lineup(text) == [
        "Hu Tao",
        "Xingqiu",
        "Yelan",
        "Zhongli",
        "Nahida",
    ]


def test_parse_lineup_drops_empty_fragments() -> None:
    text = "  ,Hu Tao,, |Xingqiu||\n\n Yelan ;;;"
    assert parse_lineup(text) == ["Hu Tao", "Xingqiu", "Yelan"]


def test_parse_lineup_empty_text() -> None:
    assert parse_lineup("") == []
    assert parse_lineup("   ,;|\n  ") == []
