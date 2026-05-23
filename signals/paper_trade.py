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
    "SPY": "SPY",
    "QQQ": "QQQ",
    "AAPL": "AAPL",
    "PLTR": "PLTR",
    "TSLA": "TSLA",
    "NVDA": "NVDA",
    "MSFT": "MSFT",
    "AMZN": "AMZN",
    "META": "META",
    "DJT": "DJT",
}

TV_SYMBOL_MAP = {
    "NQ": "CME_MINI:NQ1!",
    "ES": "CME_MINI:ES1!",
    "GLD": "AMEX:GLD",
    "BTC": "BINANCE:BTCUSDT",
    "SPY": "AMEX:SPY",
    "QQQ": "NASDAQ:QQQ",
    "AAPL": "NASDAQ:AAPL",
    "PLTR": "NASDAQ:PLTR",
    "TSLA": "NASDAQ:TSLA",
    "NVDA": "NASDAQ:NVDA",
    "MSFT": "NASDAQ:MSFT",
    "AMZN": "NASDAQ:AMZN",
    "META": "NASDAQ:META",
    "DJT": "NASDAQ:DJT",
}

STOP_PCT = 0.005     # 0.5%
TARGET_PCT = 0.015   # 1.5%
TIME_STOP_HOURS = 4  # exit after 4 hours if neither stop nor target hit
CHECK_INTERVAL_SECS = 300  # poll every 5 minutes

# Outcome labels — honest: we are NOT in a real trade
OUTCOME_TARGET_HIT = "TARGET_HIT"
OUTCOME_STOP_HIT = "STOP_HIT"
OUTCOME_TIME_STOP = "TIME_STOP"


def get_tradingview_url(instrument: str) -> str:
    sym = TV_SYMBOL_MAP.get(instrument.upper(), instrument.upper())
    return f"https://www.tradingview.com/chart/?symbol={sym}"


def _resolve_ticker(instrument: str) -> str:
    return INSTRUMENT_MAP.get(instrument.upper(), instrument)


def _fetch_price_sync(instrument: str) -> Optional[float]:
    ticker_sym = _resolve_ticker(instrument)
    try:
        t = yf.Ticker(ticker_sym)
        price = t.fast_info.last_price
        if price and price > 0:
            return float(price)
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
            self._monitor_outcome(signal, signal_id, signal_time)
        )

    async def _monitor_outcome(
        self, signal: dict, signal_id: Optional[str], signal_time: datetime
    ) -> None:
        """Poll every CHECK_INTERVAL_SECS until stop/target hit or TIME_STOP_HOURS elapsed."""
        instrument = signal["instrument"]
        direction = signal["direction"]
        entry = signal["entry_price"]
        stop = signal["stop_price"]
        target = signal["target_price"]
        deadline = signal_time + timedelta(hours=TIME_STOP_HOURS)

        while True:
            await asyncio.sleep(CHECK_INTERVAL_SECS)
            now = datetime.now(timezone.utc)

            current_price = await asyncio.to_thread(_fetch_price_sync, instrument)
            if current_price is None:
                logger.warning(
                    "[%s] Price unavailable for %s during outcome check — will retry",
                    now.isoformat(), instrument,
                )
                continue

            if direction == "BUY":
                pnl_pct = round((current_price - entry) / entry * 100, 3)
                if current_price >= target:
                    outcome = OUTCOME_TARGET_HIT
                elif current_price <= stop:
                    outcome = OUTCOME_STOP_HIT
                elif now >= deadline:
                    outcome = OUTCOME_TIME_STOP
                else:
                    continue
            else:  # SELL
                pnl_pct = round((entry - current_price) / entry * 100, 3)
                if current_price <= target:
                    outcome = OUTCOME_TARGET_HIT
                elif current_price >= stop:
                    outcome = OUTCOME_STOP_HIT
                elif now >= deadline:
                    outcome = OUTCOME_TIME_STOP
                else:
                    continue

            logger.info(
                "[%s] Outcome: %s %s → %s  pnl=%.3f%%  price=%.4f",
                now.isoformat(), instrument, direction, outcome, pnl_pct, current_price,
            )

            if self.supabase and signal_id:
                await self.supabase.update_signal_outcome(
                    signal_id, current_price, outcome, pnl_pct, now
                )

            if self.telegram:
                duration = now - signal_time
                await self.telegram.send_outcome(signal, outcome, pnl_pct, duration)

            break
