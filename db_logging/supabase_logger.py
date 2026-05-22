import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1.0


async def _with_retry(fn, max_retries: int = MAX_RETRIES):
    """Run a synchronous Supabase call in a thread, retrying on failure."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return await asyncio.to_thread(fn)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                logger.warning(
                    "[%s] DB write failed (attempt %d/%d): %s",
                    datetime.now(timezone.utc).isoformat(),
                    attempt + 1,
                    max_retries,
                    exc,
                )
                await asyncio.sleep(RETRY_DELAY)
    raise last_exc


class SupabaseLogger:
    def __init__(self, url: str, key: str):
        self.client: Client = create_client(url, key)

    async def log_post(self, post: dict) -> Optional[str]:
        try:
            await _with_retry(
                lambda: self.client.table("posts").upsert(
                    {
                        "post_id": post["post_id"],
                        "posted_at": post["created_at"],
                        "content": post["content"],
                        "raw_json": post.get("raw_json", {}),
                    }
                ).execute()
            )
            return post["post_id"]
        except Exception as exc:
            logger.error(
                "[%s] Failed to log post %s: %s",
                datetime.now(timezone.utc).isoformat(),
                post.get("post_id"),
                exc,
            )
            return None

    async def log_classification(self, post_id: str, classification: dict) -> Optional[str]:
        try:
            result = await _with_retry(
                lambda: self.client.table("classifications").insert(
                    {
                        "post_id": post_id,
                        "category": classification.get("category"),
                        "confidence": classification.get("confidence"),
                        "tickers": classification.get("tickers", []),
                        "direction": classification.get("direction"),
                        "instruments": classification.get("instruments", []),
                        "reasoning": classification.get("reasoning"),
                        "trade_fired": classification.get("trade_fired", False),
                    }
                ).execute()
            )
            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as exc:
            logger.error(
                "[%s] Failed to log classification for %s: %s",
                datetime.now(timezone.utc).isoformat(),
                post_id,
                exc,
            )
            return None

    async def log_signal(self, signal: dict) -> Optional[str]:
        try:
            result = await _with_retry(
                lambda: self.client.table("signals").insert(
                    {
                        "post_id": signal["post_id"],
                        "instrument": signal["instrument"],
                        "direction": signal["direction"],
                        "entry_price": signal["entry_price"],
                        "stop_price": signal["stop_price"],
                        "target_price": signal["target_price"],
                    }
                ).execute()
            )
            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as exc:
            logger.error(
                "[%s] Failed to log signal: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )
            return None

    async def update_signal_outcome(
        self,
        signal_id: str,
        price_2hr: float,
        outcome: str,
        pnl_pct: float,
        resolved_at: datetime,
    ):
        try:
            await _with_retry(
                lambda: self.client.table("signals")
                .update(
                    {
                        "price_2hr": price_2hr,
                        "outcome": outcome,
                        "pnl_pct": pnl_pct,
                        "resolved_at": resolved_at.isoformat(),
                    }
                )
                .eq("id", signal_id)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "[%s] Failed to update signal outcome %s: %s",
                datetime.now(timezone.utc).isoformat(),
                signal_id,
                exc,
            )

    async def update_classification_trade_fired(self, post_id: str):
        try:
            await _with_retry(
                lambda: self.client.table("classifications")
                .update({"trade_fired": True})
                .eq("post_id", post_id)
                .execute()
            )
        except Exception as exc:
            logger.error(
                "[%s] Failed to update trade_fired for %s: %s",
                datetime.now(timezone.utc).isoformat(),
                post_id,
                exc,
            )

    async def get_daily_summary(self, date_str: str) -> dict:
        """Return win/loss/open counts and total P&L for the given UTC date (YYYY-MM-DD)."""
        try:
            signals_res = await asyncio.to_thread(
                lambda: self.client.table("signals")
                .select("outcome,pnl_pct")
                .gte("created_at", f"{date_str}T00:00:00Z")
                .lte("created_at", f"{date_str}T23:59:59Z")
                .execute()
            )
            rows = signals_res.data or []
            wins = sum(1 for r in rows if r.get("outcome") == "WIN")
            losses = sum(1 for r in rows if r.get("outcome") == "LOSS")
            open_count = sum(1 for r in rows if r.get("outcome") is None)
            total_pnl = round(sum(r.get("pnl_pct") or 0.0 for r in rows), 2)

            cats_res = await asyncio.to_thread(
                lambda: self.client.table("classifications")
                .select("category")
                .gte("created_at", f"{date_str}T00:00:00Z")
                .lte("created_at", f"{date_str}T23:59:59Z")
                .execute()
            )
            cats = [r.get("category") for r in (cats_res.data or []) if r.get("category")]
            top_cat = max(set(cats), key=cats.count) if cats else "N/A"

            return {
                "total": len(rows),
                "wins": wins,
                "losses": losses,
                "open": open_count,
                "total_pnl": total_pnl,
                "top_category": top_cat,
            }
        except Exception as exc:
            logger.error(
                "[%s] Failed to get daily summary: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )
            return {"total": 0, "wins": 0, "losses": 0, "open": 0, "total_pnl": 0.0, "top_category": "N/A"}
