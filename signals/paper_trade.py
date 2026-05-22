import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

INSTRUMENT_MAP = {
    "NQ": "NQ=F",
    "ES": "ES=F",
    "GLD": "GLD",
    "BTC": "BTC-USD",
}

STOP_PCT = 0.005    # 0.5%
TARGET_PCT = 0.015  # 1.5%
OUTCOME_DELAY_HOURS = 2


def _resolve_ticker(instrument: str) -> str:
    return INSTRUMENT_MAP.get(instrument.upper(), instrument)


def _fetch_price_sync(instrument: str) -> Optional[float]:
    ticker_sym = _resolve_ticker(instrument)
    try:
        t = yf.Ticker(ticker_sym)
        # fast_info is the lowest-latency price available
        price = t.fast_info.last_price
        if price and price > 0:
            return float(price)
        # Fallback to historical data
        hist = t.history(period="1d", interval="1m", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        return None
    except Exception as exc:
        logger.error(
            "[%s] Price fetch failed for %s: %s",
            datetime.now(timezone.utc).isoformat(),
            ticker_sym,
            exc,
        )
        return None


def _calc_levels(entry: float, direction: str) -> dict:
    if direction == "BUY":
        return {
            "entry_price": entry,
            "stop_price": round(entry * (1 - STOP_PCT), 4),
            "target_price": round(entry * (1 + TARGET_PCT), 4),
        }
    return {
        "entry_price": entry,
        "stop_price": round(entry * (1 + STOP_PCT), 4),
        "target_price": round(entry * (1 - TARGET_PCT), 4),
    }


class PaperTrader:
    def __init__(self, supabase_logger=None, telegram=None):
        self.supabase = supabase_logger
        self.telegram = telegram

    async def process_signal(self, post: dict, classification: dict) -> None:
        direction = classification.get("direction", "NONE")
        if direction == "NONE":
            return

        instruments = list(
            {*classification.get("instruments", []), *classification.get("tickers", [])}
        )
        if not instruments:
            logger.info(
                "[%s] No instruments found in classification for post %s",
                datetime.now(timezone.utc).isoformat(),
                post.get("post_id"),
            )
            return

        for instrument in instruments:
            asyncio.create_task(self._fire_signal(post, classification, instrument))

    async def _fire_signal(self, post: dict, classification: dict, instrument: str) -> None:
        entry_price = await asyncio.to_thread(_fetch_price_sync, instrument)
        if entry_price is None:
            logger.error(
                "[%s] Cannot fetch price for %s — signal skipped",
                datetime.now(timezone.utc).isoformat(),
                instrument,
            )
            return

        direction = classification["direction"]
        levels = _calc_levels(entry_price, direction)
        signal_time = datetime.now(timezone.utc)

        signal = {
            "post_id": post["post_id"],
            "instrument": instrument,
            "direction": direction,
            **levels,
        }

        logger.info(
            "[%s] Signal: %s %s entry=%.4f stop=%.4f target=%.4f",
            signal_time.isoformat(),
            instrument,
            direction,
            levels["entry_price"],
            levels["stop_price"],
            levels["target_price"],
        )

        signal_id: Optional[str] = None
        if self.supabase:
            signal_id = await self.supabase.log_signal(signal)
            await self.supabase.update_classification_trade_fired(post["post_id"])

        if self.telegram:
            await self.telegram.send_signal(post, classification, signal)

        asyncio.create_task(
            self._schedule_outcome(signal, signal_id, signal_time)
        )

    async def _schedule_outcome(
        self, signal: dict, signal_id: Optional[str], signal_time: datetime
    ) -> None:
        await asyncio.sleep(OUTCOME_DELAY_HOURS * 3600)
        await self._check_outcome(signal, signal_id, signal_time)

    async def _check_outcome(
        self, signal: dict, signal_id: Optional[str], signal_time: datetime
    ) -> None:
        instrument = signal["instrument"]
        direction = signal["direction"]
        entry = signal["entry_price"]
        stop = signal["stop_price"]
        target = signal["target_price"]

        price_2hr = await asyncio.to_thread(_fetch_price_sync, instrument)
        if price_2hr is None:
            logger.error(
                "[%s] Cannot fetch outcome price for %s",
                datetime.now(timezone.utc).isoformat(),
                instrument,
            )
            return

        if direction == "BUY":
            if price_2hr >= target:
                outcome = "WIN"
            elif price_2hr <= stop:
                outcome = "LOSS"
            else:
                outcome = "PARTIAL"
            pnl_pct = round((price_2hr - entry) / entry * 100, 3)
        else:
            if price_2hr <= target:
                outcome = "WIN"
            elif price_2hr >= stop:
                outcome = "LOSS"
            else:
                outcome = "PARTIAL"
            pnl_pct = round((entry - price_2hr) / entry * 100, 3)

        resolved_at = datetime.now(timezone.utc)
        duration = resolved_at - signal_time

        logger.info(
            "[%s] Outcome: %s %s pnl=%.3f%% price_2hr=%.4f",
            resolved_at.isoformat(),
            instrument,
            outcome,
            pnl_pct,
            price_2hr,
        )

        if self.supabase and signal_id:
            await self.supabase.update_signal_outcome(
                signal_id, price_2hr, outcome, pnl_pct, resolved_at
            )

        if self.telegram:
            await self.telegram.send_outcome(signal, outcome, pnl_pct, duration)
