"""Feishu webhook integration for conjunction alerts."""

from __future__ import annotations

import logging
import os
from datetime import datetime

import requests


logger = logging.getLogger(__name__)


class FeishuAlerter:
    """Push high-risk conjunction alerts to Feishu custom bot webhook."""

    def __init__(self, timeout: int = 10, max_retries: int = 3) -> None:
        self.webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
        if not self.webhook_url:
            raise ValueError("FEISHU_WEBHOOK_URL must be configured")

        self.timeout = timeout
        self.max_retries = max_retries

    @staticmethod
    def _build_markdown_card(sat1_id: int, sat2_id: int, tca_time: datetime, miss_distance_km: float) -> dict:
        markdown = (
            "<font color='red'>**🚨 高危空间碰撞预警 / HIGH-RISK CONJUNCTION**</font>\n\n"
            f"- Sat A NORAD: `{sat1_id}`\n"
            f"- Sat B NORAD: `{sat2_id}`\n"
            f"- TCA (UTC): `{tca_time.isoformat()}`\n"
            f"- Miss Distance: `{miss_distance_km:.3f} km`\n"
            "- Trigger Rule: `PoC > 1e-4 and miss_distance < 1 km`"
        )
        return {"msg_type": "interactive", "card": {"elements": [{"tag": "markdown", "content": markdown}]}}

    def send_collision_alert(self, sat1_id: int, sat2_id: int, tca_time: datetime, miss_distance_km: float) -> None:
        payload = self._build_markdown_card(sat1_id, sat2_id, tca_time, miss_distance_km)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
                response.raise_for_status()
                logger.info("Feishu alert sent for pair %s-%s", sat1_id, sat2_id)
                return
            except requests.RequestException as exc:
                logger.warning("Feishu alert attempt %s/%s failed: %s", attempt, self.max_retries, exc)
                last_exc = exc

        raise RuntimeError("Failed to send Feishu alert after retries") from last_exc
