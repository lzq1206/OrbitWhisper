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
    PUBLIC_FILES_QUERY_URL_TEMPLATE = (
        "https://www.space-track.org/files/query/"
        "class/tle_latest/NORAD_CAT_ID/{norad_ids}/ORDINAL/1/FORMAT/tle"
    )

    def __init__(
        self,
        timeout: int = 15,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        load_dotenv()
        self.username = username or os.getenv("SPACETRACK_USER")
        self.password = password or os.getenv("SPACETRACK_PWD")
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

    def get_latest_tle_by_ids(self, norad_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch latest TLEs in batch for multiple NORAD IDs."""
        self._login()
        if not norad_ids:
            return []

        id_str = ",".join(str(int(norad_id)) for norad_id in norad_ids)
        query_url = (
            "https://www.space-track.org/basicspacedata/query/"
            f"class/tle_latest/NORAD_CAT_ID/{id_str}/ORDINAL/1/FORMAT/json"
        )
        logger.info("Fetching latest TLEs for %d NORAD IDs", len(norad_ids))
        try:
            response = self.session.get(query_url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.exception("Failed retrieving batched TLEs")
            raise RuntimeError("Space-Track batch query failed") from exc

        if not isinstance(payload, list):
            return []

        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            line1 = str(item.get("TLE_LINE1", "")).strip()
            line2 = str(item.get("TLE_LINE2", "")).strip()
            if not (line1.startswith("1 ") and line2.startswith("2 ")):
                continue
            try:
                norad_id = int(item.get("NORAD_CAT_ID"))
            except (TypeError, ValueError):
                continue
            rows.append({"norad_id": norad_id, "line1": line1, "line2": line2})
        return rows

    @staticmethod
    def _parse_tle_blocks(raw_text: str) -> list[dict[str, Any]]:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        rows: list[dict[str, Any]] = []
        i = 0
        while i < len(lines):
            current = lines[i]
            if current.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
                line1, line2 = current, lines[i + 1]
                i += 2
            elif (
                i + 2 < len(lines)
                and lines[i + 1].startswith("1 ")
                and lines[i + 2].startswith("2 ")
            ):
                line1, line2 = lines[i + 1], lines[i + 2]
                i += 3
            else:
                i += 1
                continue

            norad_id = None
            # Per standard TLE format, catalog number is in columns 3-7 (1-based).
            norad_raw = line1[2:7].strip()
            line1_has_catalog = norad_raw.isdigit()
            line2_norad_raw = line2[2:7].strip()
            line2_has_catalog = line2_norad_raw.isdigit()

            if line1_has_catalog:
                norad_id = int(norad_raw)
            if line1_has_catalog and line2_has_catalog and norad_raw != line2_norad_raw:
                continue
            rows.append({"norad_id": norad_id, "line1": line1, "line2": line2})
        return rows

    def get_public_file_tles_by_ids(self, norad_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch latest TLEs from Space-Track public files endpoint."""
        self._login()
        if not norad_ids:
            return []

        id_str = ",".join(str(int(norad_id)) for norad_id in norad_ids)
        query_url = self.PUBLIC_FILES_QUERY_URL_TEMPLATE.format(norad_ids=id_str)
        logger.info("Fetching public-file TLEs for %d NORAD IDs", len(norad_ids))
        try:
            response = self.session.get(query_url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.exception("Failed retrieving public-file TLEs")
            raise RuntimeError("Space-Track public-files query failed") from exc

        return self._parse_tle_blocks(response.text)
