import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Optional, Set

import aiohttp
import websockets

logger = logging.getLogger(__name__)

STREAM_URL = "wss://truthsocial.com/api/v1/streaming/public"
REST_BASE = "https://truthsocial.com/api/v1"
BACKOFF_SEQUENCE = [1, 2, 4, 8, 16, 60]
POLL_INTERVAL = 60  # seconds between REST fallback polls


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


class TruthSocialFeed:
    def __init__(self, account_id: str, on_post: Callable, access_token: Optional[str] = None):
        self.account_id = account_id
        self.on_post = on_post
        self.access_token = access_token
        self._seen_ids: Set[str] = set()
        self._running = False
        self._last_seen_id: Optional[str] = None  # for REST since_id pagination

    async def start(self) -> None:
        self._running = True
        # Seed seen IDs from the last few posts so we don't re-fire old posts on startup
        await self._poll_rest(seed_only=True)
        # Run WebSocket and REST poller concurrently
        await asyncio.gather(
            self._ws_loop(),
            self._rest_poll_loop(),
        )

    async def stop(self) -> None:
        self._running = False

    # ── WebSocket loop ──────────────────────────────────────────────────────────

    async def _ws_loop(self) -> None:
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
                    "[%s] WebSocket error (attempt %d): %s — reconnecting in %ds",
                    datetime.now(timezone.utc).isoformat(),
                    attempt + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

    def _build_ws_url(self) -> str:
        if self.access_token:
            return f"{STREAM_URL}?access_token={self.access_token}"
        return STREAM_URL

    async def _connect(self) -> None:
        url = self._build_ws_url()
        logger.info("[%s] Connecting to Truth Social stream...", datetime.now(timezone.utc).isoformat())
        async with websockets.connect(
            url,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=10,
            additional_headers={"User-Agent": "trading-engine/1.0"},
        ) as ws:
            logger.info("[%s] Connected to Truth Social stream", datetime.now(timezone.utc).isoformat())
            async for raw in ws:
                if not self._running:
                    return
                await self._handle_ws_message(raw)

    async def _handle_ws_message(self, raw: str) -> None:
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

        await self._emit_if_new(payload)

    # ── REST polling fallback ───────────────────────────────────────────────────

    async def _rest_poll_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                if self._running:
                    await self._poll_rest()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[%s] REST poll error: %s", datetime.now(timezone.utc).isoformat(), exc)

    async def _poll_rest(self, seed_only: bool = False) -> None:
        url = f"{REST_BASE}/accounts/{self.account_id}/statuses"
        params = {"limit": 20, "exclude_replies": "true", "exclude_reblogs": "true"}
        if self._last_seen_id and not seed_only:
            params["since_id"] = self._last_seen_id

        headers = {"User-Agent": "trading-engine/1.0"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("[%s] REST poll returned HTTP %d", datetime.now(timezone.utc).isoformat(), resp.status)
                    return
                statuses = await resp.json()

        if not statuses:
            return

        # statuses are newest-first; update last_seen_id to the most recent
        newest_id = statuses[0].get("id")
        if newest_id:
            self._last_seen_id = newest_id

        if seed_only:
            # Just mark existing posts as seen so they don't re-fire on startup
            for s in statuses:
                sid = s.get("id")
                if sid:
                    self._seen_ids.add(sid)
            logger.info("[%s] Seeded %d existing posts from REST API", datetime.now(timezone.utc).isoformat(), len(statuses))
            return

        # Process newest-last so they fire in chronological order
        new_posts = [s for s in reversed(statuses) if s.get("id") not in self._seen_ids]
        for payload in new_posts:
            logger.info("[%s] REST fallback caught post %s", datetime.now(timezone.utc).isoformat(), payload.get("id"))
            await self._emit_if_new(payload)

    # ── Shared emission ─────────────────────────────────────────────────────────

    async def _emit_if_new(self, payload: dict) -> None:
        post_id = payload.get("id")
        if not post_id or post_id in self._seen_ids:
            return

        self._seen_ids.add(post_id)
        if not self._last_seen_id or post_id > self._last_seen_id:
            self._last_seen_id = post_id

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
