"""Space-Track TLE data access client."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


class SpaceTrackClient:
    """Client for Space-Track login/session and TLE retrieval."""

    LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
    QUERY_URL_TEMPLATE = (
        "https://www.space-track.org/basicspacedata/query/"
        "class/tle_latest/NORAD_CAT_ID/{norad_id}/ORDINAL/1/format/tle"
    )

    def __init__(self, timeout: int = 15) -> None:
        load_dotenv()
        self.username = os.getenv("SPACETRACK_USER")
        self.password = os.getenv("SPACETRACK_PWD")
        self.timeout = timeout
        self.session = requests.Session()
        self._is_logged_in = False

        if not self.username or not self.password:
            raise ValueError("SPACETRACK_USER and SPACETRACK_PWD must be configured")

    def _login(self) -> None:
        """Authenticate and persist the cookie-based session."""
        if self._is_logged_in:
            return

        payload = {"identity": self.username, "password": self.password}
        logger.info("Logging into Space-Track")
        response = self.session.post(self.LOGIN_URL, data=payload, timeout=self.timeout)
        response.raise_for_status()

        if "failed" in response.text.lower():
            raise RuntimeError("Space-Track authentication failed")

        self._is_logged_in = True
        logger.info("Space-Track login successful")

    @staticmethod
    def _parse_tle_text(raw_text: str) -> dict[str, str]:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError("Unexpected TLE response; less than two non-empty lines")

        # TLE responses are typically [name?, line1, line2]
        if lines[0].startswith("1 ") and lines[1].startswith("2 "):
            line1, line2 = lines[0], lines[1]
        elif len(lines) >= 3 and lines[1].startswith("1 ") and lines[2].startswith("2 "):
            line1, line2 = lines[1], lines[2]
        else:
            raise ValueError("Unable to locate valid TLE line1/line2 in response")

        return {"line1": line1, "line2": line2}

    def get_latest_tle(self, norad_id: int) -> dict[str, Any]:
        """Fetch latest TLE by NORAD catalog ID."""
        self._login()
        url = self.QUERY_URL_TEMPLATE.format(norad_id=norad_id)
        logger.info("Fetching latest TLE for NORAD ID %s", norad_id)

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.exception("Failed retrieving TLE for NORAD ID %s", norad_id)
            raise RuntimeError(f"Space-Track query failed for NORAD ID {norad_id}") from exc

        parsed = self._parse_tle_text(response.text)
        parsed["norad_id"] = norad_id
        return parsed
