"""
Real-time price feed — three sources:
  - Binance WebSocket  : BTC, ETH and any USDT pair (instantaneous)
  - Alpaca             : US stocks and ETFs (real-time, free tier)
  - yfinance fallback  : everything else (15-min delay, no key needed)
"""
import asyncio
import json
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── Binance ────────────────────────────────────────────────────────────────

BINANCE_WS = "wss://stream.binance.com:9443/ws"

CRYPTO_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "BNB": "BNBUSDT",
    "SOL": "SOLUSDT",
}

_binance_prices: dict[str, float] = {}
_binance_task: Optional[asyncio.Task] = None


async def _binance_stream(symbols: list[str]) -> None:
    streams = "/".join(f"{s.lower()}@miniTicker" for s in symbols)
    url = f"{BINANCE_WS}/{streams}"
    backoff = 1
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as ws:
                    logger.info("Binance WebSocket connected: %s", symbols)
                    backoff = 1
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            symbol = data.get("s", "")
                            price = float(data.get("c", 0))
                            if price > 0:
                                _binance_prices[symbol] = price
        except Exception as exc:
            logger.warning("Binance WS error: %s — reconnecting in %ds", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def start_binance_stream() -> None:
    global _binance_task
    symbols = list(CRYPTO_MAP.values())
    if _binance_task is None or _binance_task.done():
        _binance_task = asyncio.create_task(_binance_stream(symbols))


def get_binance_price(instrument: str) -> Optional[float]:
    symbol = CRYPTO_MAP.get(instrument.upper())
    if symbol is None:
        symbol = instrument.upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
    return _binance_prices.get(symbol)


# ── Alpaca ─────────────────────────────────────────────────────────────────

ALPACA_BASE = "https://data.alpaca.markets/v2"

_alpaca_key = os.getenv("ALPACA_API_KEY", "")
_alpaca_secret = os.getenv("ALPACA_API_SECRET", "")

US_STOCKS = {
    "SPY", "QQQ", "AAPL", "PLTR", "TSLA", "NVDA",
    "MSFT", "AMZN", "META", "DJT", "GLD", "TLT",
}


async def get_alpaca_price(symbol: str) -> Optional[float]:
    if not _alpaca_key or not _alpaca_secret:
        return None
    url = f"{ALPACA_BASE}/stocks/{symbol.upper()}/quotes/latest"
    headers = {
        "APCA-API-KEY-ID": _alpaca_key,
        "APCA-API-SECRET-KEY": _alpaca_secret,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    quote = data.get("quote", {})
                    ask = quote.get("ap", 0)
                    bid = quote.get("bp", 0)
                    if ask and bid:
                        return round((ask + bid) / 2, 4)
    except Exception as exc:
        logger.warning("Alpaca price fetch failed for %s: %s", symbol, exc)
    return None


# ── yfinance fallback ──────────────────────────────────────────────────────

# NQ/ES are futures with no free real-time feed — proxy to ETFs that track them
FUTURES_PROXY = {
    "NQ": "QQQ",
    "ES": "SPY",
}

YFINANCE_MAP = {
    "NQ": "NQ=F", "ES": "ES=F",
    "GLD": "GLD", "BTC": "BTC-USD",
    "SPY": "SPY", "QQQ": "QQQ",
}


def _yf_price_sync(instrument: str) -> Optional[float]:
    try:
        import yfinance as yf
        sym = YFINANCE_MAP.get(instrument.upper(), instrument)
        t = yf.Ticker(sym)
        price = t.fast_info.last_price
        if price and price > 0:
            return float(price)
        hist = t.history(period="1d", interval="1m", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        logger.warning("yfinance fallback failed for %s: %s", instrument, exc)
    return None


# ── Unified entry point ────────────────────────────────────────────────────

async def get_price(instrument: str) -> Optional[float]:
    """
    Returns the best available price for an instrument.
    Priority: Binance (instant) → Alpaca (real-time) → yfinance (fallback)
    """
    upper = instrument.upper()

    # Crypto — Binance first
    if upper in CRYPTO_MAP or upper in ("BTC", "ETH", "BNB", "SOL"):
        price = get_binance_price(upper)
        if price:
            logger.debug("Price %s = %.4f (Binance)", upper, price)
            return price

    # Futures — proxy to ETF for real-time price via Alpaca
    proxy = FUTURES_PROXY.get(upper)
    if proxy and _alpaca_key:
        price = await get_alpaca_price(proxy)
        if price:
            logger.debug("Price %s = %.4f via proxy %s (Alpaca)", upper, proxy, price)
            return price

    # US stocks — Alpaca
    if upper in US_STOCKS and _alpaca_key:
        price = await get_alpaca_price(upper)
        if price:
            logger.debug("Price %s = %.4f (Alpaca)", upper, price)
            return price

    # Fallback — yfinance
    price = await asyncio.to_thread(_yf_price_sync, instrument)
    if price:
        logger.debug("Price %s = %.4f (yfinance fallback)", upper, price)
    return price
