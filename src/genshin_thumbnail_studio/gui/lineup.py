from __future__ import annotations

import re


def parse_lineup(text: str) -> list[str]:
    """Split pasted lineup text into character names.

    Accepts comma, semicolon, pipe, and newline as separators (and any
    mix/repetition thereof), stripping whitespace and dropping empty
    fragments (e.g. from trailing or doubled separators).
    """
    return [value.strip() for value in re.split(r"[,;|\n]+", text) if value.strip()]
