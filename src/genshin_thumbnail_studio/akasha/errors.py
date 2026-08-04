from __future__ import annotations

from datetime import datetime


class AkashaError(RuntimeError):
    pass


class StaleProfileError(AkashaError):
    def __init__(self, age_minutes: float, last_update: datetime) -> None:
        super().__init__(f"Akasha profile is {age_minutes:.0f} minutes old.")
        self.age_minutes = age_minutes
        self.last_update = last_update
