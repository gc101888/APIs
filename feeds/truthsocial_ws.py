import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Callable, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = logging.getLogger(__name__)

STREAM_URL = "wss://truthsocial.com/api/v1/streaming/public"
BACKOFF_SEQUENCE = [1, 2, 4, 8, 16, 60]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


class TruthSocialFeed:
    def __init__(self, account_id: str, on_post: Callable, access_token: Optional[str] = None):
        self.account_id = account_id
        self.on_post = on_post
        self.access_token = access_token
        self._seen_ids: Set[str] = set()
        self._running = False

    async def start(self) -> None:
        self._running = True
        attempt = 0
        while self._running:
            try:
                await self._connect()
                attempt = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                delay = BACKOFF_SEQUENCE[min(attempt, len(BACKOFF_SEQUENCE) - 1)]
                logger.error(
                    "[%s] Feed error (attempt %d): %s — reconnecting in %ds",
                    datetime.now(timezone.utc).isoformat(),
                    attempt + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

    async def stop(self) -> None:
        self._running = False

    def _build_url(self) -> str:
        if self.access_token:
            return f"{STREAM_URL}?access_token={self.access_token}"
        return STREAM_URL

    async def _connect(self) -> None:
        url = self._build_url()
        logger.info(
            "[%s] Connecting to Truth Social stream...",
            datetime.now(timezone.utc).isoformat(),
        )
        async with websockets.connect(
            url,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=10,
            additional_headers={"User-Agent": "trading-engine/1.0"},
        ) as ws:
            logger.info(
                "[%s] Connected to Truth Social stream",
                datetime.now(timezone.utc).isoformat(),
            )
            async for raw in ws:
                if not self._running:
                    return
                await self._handle_raw(raw)

    async def _handle_raw(self, raw: str) -> None:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            return

        if envelope.get("event") != "update":
            return

        payload_raw = envelope.get("payload")
        if not payload_raw:
            return

        try:
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        except json.JSONDecodeError:
            return

        account = payload.get("account", {})
        if account.get("id") != self.account_id:
            return

        post_id = payload.get("id")
        if not post_id or post_id in self._seen_ids:
            return

        self._seen_ids.add(post_id)

        post = {
            "post_id": post_id,
            "created_at": payload.get("created_at"),
            "content": _strip_html(payload.get("content", "")),
            "media_attachments": payload.get("media_attachments", []),
            "url": payload.get("url", ""),
            "raw_json": payload,
        }

        logger.info(
            "[%s] New post %s: %.80s",
            datetime.now(timezone.utc).isoformat(),
            post_id,
            post["content"],
        )

        asyncio.create_task(self.on_post(post))
