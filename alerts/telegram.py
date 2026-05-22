import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


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
            )
        except TelegramError as exc:
            logger.error(
                "[%s] Telegram send error: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )
        except Exception as exc:
            logger.error(
                "[%s] Unexpected Telegram error: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )

    async def send_startup(self) -> None:
        await self._send(
            "✅ <b>Trading Engine Online</b>\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            "Watching: @realDonaldTrump"
        )

    async def send_post_detected(self, post: dict) -> None:
        preview = post.get("content", "")[:150]
        await self._send(
            "📡 <b>POST DETECTED</b>\n"
            f"{preview}\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

    async def send_classification(self, classification: dict) -> None:
        conf_pct = round((classification.get("confidence") or 0.0) * 100, 1)
        await self._send(
            "🔍 <b>CLASSIFIED</b>\n"
            f"Category: {classification.get('category')}\n"
            f"Confidence: {conf_pct}%\n"
            f"Direction: {classification.get('direction')}\n"
            f"{classification.get('reasoning', '')}"
        )

    async def send_signal(self, post: dict, classification: dict, signal: dict) -> None:
        post_preview = post.get("content", "")[:100]
        conf_pct = round((classification.get("confidence") or 0.0) * 100, 1)
        await self._send(
            "🚨 <b>SIGNAL FIRED</b>\n"
            f"Post: {post_preview}\n"
            f"Category: {classification.get('category')}\n"
            f"Confidence: {conf_pct}%\n"
            f"Instrument: {signal.get('instrument')}\n"
            f"Direction: {signal.get('direction')}\n"
            f"Entry: {signal.get('entry_price')}\n"
            f"Stop: {signal.get('stop_price')}\n"
            f"Target: {signal.get('target_price')}\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

    async def send_outcome(
        self,
        signal: dict,
        outcome: str,
        pnl_pct: float,
        duration: timedelta,
    ) -> None:
        emoji = {"WIN": "✅", "LOSS": "❌", "PARTIAL": "⏰"}.get(outcome, "📊")
        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes = remainder // 60
        await self._send(
            f"{emoji} <b>{outcome}</b>\n"
            f"Instrument: {signal.get('instrument')}\n"
            f"P&L: {pnl_pct:+.2f}%\n"
            f"Duration: {hours}h {minutes}m"
        )

    async def send_daily_summary(self, summary: dict) -> None:
        await self._send(
            "📊 <b>DAILY SUMMARY</b>\n"
            f"Signals today: {summary.get('total', 0)}\n"
            f"Wins: {summary.get('wins', 0)} | "
            f"Losses: {summary.get('losses', 0)} | "
            f"Open: {summary.get('open', 0)}\n"
            f"Hypothetical P&L: {summary.get('total_pnl', 0.0):+.2f}%\n"
            f"Top category: {summary.get('top_category', 'N/A')}"
        )

    async def send_error(self, error: str) -> None:
        await self._send(
            "⚠️ <b>ERROR</b>\n"
            f"{error}\n"
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
