import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

TV_SYMBOL_MAP = {
    "NQ": "CME_MINI:NQ1!", "ES": "CME_MINI:ES1!",
    "GLD": "AMEX:GLD", "BTC": "BINANCE:BTCUSDT",
    "SPY": "AMEX:SPY", "QQQ": "NASDAQ:QQQ",
    "AAPL": "NASDAQ:AAPL", "PLTR": "NASDAQ:PLTR",
    "TSLA": "NASDAQ:TSLA", "NVDA": "NASDAQ:NVDA",
    "MSFT": "NASDAQ:MSFT", "AMZN": "NASDAQ:AMZN",
    "META": "NASDAQ:META", "DJT": "NASDAQ:DJT",
}


def _tv_url(instrument: str) -> str:
    sym = TV_SYMBOL_MAP.get(instrument.upper(), instrument.upper())
    return f"https://www.tradingview.com/chart/?symbol={sym}"


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str):
        self.bot = Bot(token=token)
        self.chat_id = chat_id

    async def _send(self, text: str) -> None:
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except TelegramError as exc:
            logger.error(
                "[%s] Telegram send error: %s",
                datetime.now(timezone.utc).isoformat(), exc,
            )
        except Exception as exc:
            logger.error(
                "[%s] Unexpected Telegram error: %s",
                datetime.now(timezone.utc).isoformat(), exc,
            )

    async def send_startup(self) -> None:
        await self._send(
            "✅ <b>Trading Engine Online</b>\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            "Watching: @realDonaldTrump on Truth Social"
        )

    async def send_post_detected(self, post: dict) -> None:
        preview = post.get("content", "")[:200]
        await self._send(
            "📡 <b>TRUMP POST DETECTED</b>\n\n"
            f"{preview}\n\n"
            f"<i>{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC</i>"
        )

    async def send_classification(self, classification: dict) -> None:
        conf_pct = round((classification.get("confidence") or 0.0) * 100, 1)
        dir_emoji = {"BUY": "🟢", "SELL": "🔴"}.get(classification.get("direction"), "⚪️")
        await self._send(
            f"🔍 <b>AI CLASSIFICATION</b>\n\n"
            f"Category: <b>{classification.get('category')}</b>\n"
            f"Direction: {dir_emoji} <b>{classification.get('direction')}</b>\n"
            f"Confidence: {conf_pct}%\n\n"
            f"<i>{classification.get('reasoning', '')}</i>"
        )

    async def send_signal(self, post: dict, classification: dict, signal: dict) -> None:
        instrument = signal.get("instrument", "")
        direction = signal.get("direction", "")
        conf_pct = round((classification.get("confidence") or 0.0) * 100, 1)
        dir_emoji = "🟢 LONG" if direction == "BUY" else "🔴 SHORT"
        chart_url = _tv_url(instrument)

        await self._send(
            f"🚨 <b>SIGNAL FIRED</b>\n\n"
            f"<b>{instrument} {dir_emoji}</b>\n\n"
            f"📍 Entry:  <code>{signal.get('entry_price')}</code>\n"
            f"🛑 Stop:   <code>{signal.get('stop_price')}</code>\n"
            f"🎯 Target: <code>{signal.get('target_price')}</code>\n\n"
            f"Category: {classification.get('category')} ({conf_pct}%)\n"
            f"Post: {post.get('content', '')[:120]}\n\n"
            f"📈 <a href=\"{chart_url}\">View Live Chart</a>\n"
            f"<i>{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC · Paper trade only</i>"
        )

    async def send_outcome(
        self,
        signal: dict,
        outcome: str,
        pnl_pct: float,
        duration: timedelta,
    ) -> None:
        emoji_map = {
            "TARGET_HIT": "✅",
            "STOP_HIT": "❌",
            "TIME_STOP": "⏰",
        }
        label_map = {
            "TARGET_HIT": "TARGET HIT",
            "STOP_HIT": "STOP HIT",
            "TIME_STOP": "TIME STOP (4hr)",
        }
        emoji = emoji_map.get(outcome, "📊")
        label = label_map.get(outcome, outcome)
        hours, rem = divmod(int(duration.total_seconds()), 3600)
        minutes = rem // 60
        instrument = signal.get("instrument", "")
        chart_url = _tv_url(instrument)

        await self._send(
            f"{emoji} <b>{label}</b>\n\n"
            f"Instrument: <b>{instrument}</b> {signal.get('direction')}\n"
            f"Hypothetical P&amp;L: <b>{pnl_pct:+.2f}%</b>\n"
            f"Duration: {hours}h {minutes}m\n\n"
            f"📈 <a href=\"{chart_url}\">View Chart</a>"
        )

    async def send_daily_summary(self, summary: dict) -> None:
        total = summary.get('total', 0)
        wins = summary.get('wins', 0)
        losses = summary.get('losses', 0)
        pnl = summary.get('total_pnl', 0.0)
        rate = round(wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

        await self._send(
            "📊 <b>DAILY SUMMARY</b>\n\n"
            f"Signals: {total}\n"
            f"Target Hits: {wins}  |  Stop Hits: {losses}  |  Open: {summary.get('open', 0)}\n"
            f"Win Rate: {rate}%\n"
            f"Hypothetical P&amp;L: <b>{pnl:+.2f}%</b>\n"
            f"Top category: {summary.get('top_category', 'N/A')}"
        )

    async def send_error(self, error: str) -> None:
        await self._send(
            "⚠️ <b>ERROR</b>\n\n"
            f"{error}\n\n"
            f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
        )
