"""Outbound call trigger for Live Hub / VoiceAI Connect (`/api/v1/actions/dialout`)."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("bridge")


class DialoutClient:
    def __init__(self, *, api_url: str, client_id: str, client_secret: str):
        self._url = api_url.rstrip("/") + "/api/v1/actions/dialout"
        creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._auth = f"Basic {creds}"

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(
            self._url,
            data=json.dumps(body).encode(),
            headers={"Authorization": self._auth, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"dialout failed HTTP {e.code}: {e.read()[:300]!r}") from None

    async def dial(self, *, bot: str, target: str, caller: str, metadata: dict) -> str:
        body = {"bot": bot, "target": f"tel:{target}", "caller": caller, "metadata": metadata}
        result = await asyncio.to_thread(self._post, body)
        log.info("dialout triggered bot=%s conv=%s", bot, result.get("conversationId"))
        return result.get("conversationId", "")
