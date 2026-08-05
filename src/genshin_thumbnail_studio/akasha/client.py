"""`AkashaWebClient`, which drives an offscreen `QWebEnginePage` to load
`akasha.cv` API endpoints and read back JSON, because Akasha requires a real
browser context rather than a plain HTTP request.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

from ..models import Build
from .errors import AkashaError, StaleProfileError
from .http import USER_AGENT
from .parsing import as_mapping, parse_builds, profile_age_minutes
from .rarities import load_enka_rarities

API_ROOT = "https://akasha.cv/api"


class AkashaWebClient:
    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self.profile = QWebEngineProfile("GenshinThumbnailStudio")
        self.profile.setCachePath(str(cache_path / "web-cache"))
        self.profile.setPersistentStoragePath(str(cache_path / "web-profile"))
        self.profile.setHttpUserAgent(USER_AGENT)
        self.page = QWebEnginePage(self.profile)

    def close(self) -> None:
        self.page.deleteLater()
        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()
        del self.page
        self.profile.deleteLater()
        loop2 = QEventLoop()
        QTimer.singleShot(0, loop2.quit)
        loop2.exec()
        del self.profile

    def _wait_load(self, url: str, timeout_ms: int = 120_000) -> bool:
        loop = QEventLoop()
        result = {"ok": False, "timed_out": False}
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: (result.update(timed_out=True), loop.quit()))

        def finished(ok: bool) -> None:
            result["ok"] = ok
            loop.quit()

        self.page.loadFinished.connect(finished)
        timer.start(timeout_ms)
        self.page.load(QUrl(url))
        loop.exec()
        timer.stop()
        self.page.loadFinished.disconnect(finished)
        if result["timed_out"]:
            raise AkashaError(f"Timeout while loading {url}")
        return bool(result["ok"])

    def _plain_text(self, timeout_ms: int = 30_000) -> str:
        loop = QEventLoop()
        result: dict[str, str | None] = {"value": None}
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def ready(value: str) -> None:
            result["value"] = value
            loop.quit()

        timer.start(timeout_ms)
        self.page.toPlainText(ready)
        loop.exec()
        timer.stop()
        if result["value"] is None:
            raise AkashaError("Timeout while reading Akasha response.")
        return str(result["value"])

    def run_javascript(self, script: str, timeout_ms: int = 30_000) -> Any:
        loop = QEventLoop()
        result = {"done": False, "value": None}
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def ready(value: Any) -> None:
            result.update(done=True, value=value)
            loop.quit()

        timer.start(timeout_ms)
        self.page.runJavaScript(script, ready)
        loop.exec()
        timer.stop()
        if not result["done"]:
            raise AkashaError("Timeout while executing browser action.")
        return result["value"]

    def json(self, url: str) -> dict[str, Any]:
        self._wait_load(url)
        text = self._plain_text().strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            title = self.page.title()
            raise AkashaError(f"Akasha returned no JSON ({title or 'unknown page'}).") from error
        payload_dict = as_mapping(payload)
        if payload_dict is None:
            raise AkashaError("Akasha returned an unexpected response.")
        if payload_dict.get("error"):
            raise AkashaError(str(payload_dict["error"]))
        return payload_dict

    def load_profile(
        self, uid: str, max_age_minutes: int = 60, allow_stale: bool = False
    ) -> tuple[list[Build], float, datetime]:
        if not re.fullmatch(r"\d{6,12}", uid):
            raise AkashaError("UID must contain 6 to 12 digits.")
        user = self.json(f"{API_ROOT}/user/{uid}")
        age, last = profile_age_minutes(user)
        if age > max_age_minutes and not allow_stale:
            raise StaleProfileError(age, last)
        query = urllib.parse.urlencode(
            {
                "sort": "critValue",
                "order": "-1",
                "size": "100",
                "page": "1",
                "filter": "",
                "uids": "",
                "p": "",
                "fromId": "",
                "li": "",
                "uid": uid,
            }
        )
        character_rarity_map, weapon_rarity_map = load_enka_rarities(self.cache_path / "enka-rarities.json")
        builds = parse_builds(self.json(f"{API_ROOT}/builds/?{query}"), character_rarity_map, weapon_rarity_map)
        return builds, age, last

    def refresh_profile(
        self, uid: str, timeout_seconds: int = 90, progress: Callable[[str], None] | None = None
    ) -> bool:
        before = self.json(f"{API_ROOT}/user/{uid}")
        _, old_time = profile_age_minutes(before)
        self._wait_load(f"https://akasha.cv/profile/{uid}")
        deadline = time.monotonic() + 30
        clicked = False
        while time.monotonic() < deadline and not clicked:
            clicked = bool(
                self.run_javascript(
                    "(() => { const e=document.querySelector('[title=\"Refresh builds\"]'); "
                    "if(!e) return false; e.click(); return true; })()"
                )
            )
            if not clicked:
                QEventLoop().processEvents()
                time.sleep(0.5)
        if not clicked:
            raise AkashaError("Akasha refresh button was not found.")

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if progress:
                progress("Akasha is refreshing the builds ...")
            time.sleep(3)
            try:
                payload = self.json(f"{API_ROOT}/user/{uid}")
                _, current = profile_age_minutes(payload)
                if current > old_time:
                    return True
            except AkashaError:
                pass
        return False
