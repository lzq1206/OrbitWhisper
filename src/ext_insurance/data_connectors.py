import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class FetchResult:
    ok: bool
    source: str
    endpoint: str
    status: str
    records: int = 0
    data: Optional[Any] = None
    error: Optional[str] = None
    cache_path: Optional[str] = None


class APIClient:
    def __init__(self, cache_dir: str, timeout: int = 25, retries: int = 3, backoff: float = 1.5):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

    def _request_json(self, url: str, headers: Optional[Dict[str, str]] = None) -> Any:
        headers = headers or {}
        headers.setdefault("User-Agent", "openclaw-sat-ins/1.0")
        ctx = ssl.create_default_context()

        last_err = None
        for i in range(self.retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                    body = r.read().decode("utf-8", "ignore")
                    return json.loads(body)
            except Exception as e:
                last_err = e
                time.sleep(self.backoff ** i)
        raise RuntimeError(f"request failed after retries: {url}; err={last_err}")

    def _save_cache(self, name: str, obj: Any) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        p = self.cache_dir / f"{name}_{ts}.json"
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(p)

    def fetch_celestrak_gp(self, group: str = "stations", fmt: str = "json") -> FetchResult:
        url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={urllib.parse.quote(group.upper())}&FORMAT={fmt.upper()}"
        try:
            data = self._request_json(url)
            n = len(data) if isinstance(data, list) else 1
            cp = self._save_cache("celestrak_gp", data)
            return FetchResult(True, "celestrak", url, "ok", n, data=data, cache_path=cp)
        except Exception as e:
            return FetchResult(False, "celestrak", url, "error", error=str(e))

    def fetch_noaa_swpc(self, endpoint: str = "planetary_k_index_1m.json") -> FetchResult:
        url = f"https://services.swpc.noaa.gov/json/{endpoint}"
        try:
            data = self._request_json(url)
            n = len(data) if isinstance(data, list) else 1
            cp = self._save_cache("noaa_swpc", data)
            return FetchResult(True, "noaa_swpc", url, "ok", n, data=data, cache_path=cp)
        except Exception as e:
            return FetchResult(False, "noaa_swpc", url, "error", error=str(e))

    def fetch_launch_library(self, limit: int = 5) -> FetchResult:
        url = f"https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit={int(limit)}"
        try:
            data = self._request_json(url)
            n = len(data.get("results", [])) if isinstance(data, dict) else 0
            cp = self._save_cache("launch_library", data)
            return FetchResult(True, "launch_library", url, "ok", n, data=data, cache_path=cp)
        except Exception as e:
            return FetchResult(False, "launch_library", url, "error", error=str(e))

    def fetch_satnogs(self) -> FetchResult:
        url = "https://db.satnogs.org/api/"
        try:
            data = self._request_json(url)
            n = len(data.keys()) if isinstance(data, dict) else 1
            cp = self._save_cache("satnogs_root", data)
            return FetchResult(True, "satnogs", url, "ok", n, data=data, cache_path=cp)
        except Exception as e:
            return FetchResult(False, "satnogs", url, "error", error=str(e))

    def fetch_space_track_gp(self, norad_cat_id: int = 25544) -> FetchResult:
        username = os.getenv("SPACE_TRACK_USER")
        password = os.getenv("SPACE_TRACK_PASS")
        login_url = "https://www.space-track.org/ajaxauth/login"
        q_url = (
            f"https://www.space-track.org/basicspacedata/query/class/gp/"
            f"NORAD_CAT_ID/{norad_cat_id}/orderby/EPOCH desc/limit/3/format/json"
        )

        if not username or not password:
            return FetchResult(False, "space_track", q_url, "skipped", error="Missing SPACE_TRACK_USER/SPACE_TRACK_PASS")

        try:
            cj = urllib.request.HTTPCookieProcessor()
            opener = urllib.request.build_opener(cj)
            payload = urllib.parse.urlencode({"identity": username, "password": password}).encode("utf-8")
            req_login = urllib.request.Request(login_url, data=payload, headers={"User-Agent": "openclaw-sat-ins/1.0"})
            opener.open(req_login, timeout=self.timeout)

            req_q = urllib.request.Request(q_url, headers={"User-Agent": "openclaw-sat-ins/1.0"})
            with opener.open(req_q, timeout=self.timeout) as r:
                body = r.read().decode("utf-8", "ignore")
                data = json.loads(body)
            cp = self._save_cache("space_track_gp", data)
            n = len(data) if isinstance(data, list) else 1
            return FetchResult(True, "space_track", q_url, "ok", n, data=data, cache_path=cp)
        except Exception as e:
            return FetchResult(False, "space_track", q_url, "error", error=str(e))


def collect_all_sources(cache_dir: str, allow_space_track: bool = True) -> Dict[str, FetchResult]:
    c = APIClient(cache_dir=cache_dir)
    out = {
        "celestrak": c.fetch_celestrak_gp(group="stations", fmt="json"),
        "noaa_swpc": c.fetch_noaa_swpc("planetary_k_index_1m.json"),
        "launch_library": c.fetch_launch_library(limit=5),
        "satnogs": c.fetch_satnogs(),
    }
    if allow_space_track:
        out["space_track"] = c.fetch_space_track_gp(norad_cat_id=25544)
    return out
