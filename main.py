import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

REQUIRED_ENV = [
    "GEMINI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]


def _check_env() -> None:
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        logger.critical("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)


async def _daily_summary_loop(telegram, supabase) -> None:
    """Fire a daily summary at 17:00 UTC every day."""
    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=17, minute=0, second=0, microsecond=0)
        if now >= target:
            # Already past 17:00 today — schedule for tomorrow
            target = target.replace(day=target.day + 1)
        await asyncio.sleep((target - now).total_seconds())
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        summary = await supabase.get_daily_summary(date_str)
        await telegram.send_daily_summary(summary)


async def main() -> None:
    _check_env()

    from alerts.telegram import TelegramAlerter
    from classifier.classify import Classifier
    from db_logging.supabase_logger import SupabaseLogger
    from feeds.price_feed import start_binance_stream
    from feeds.truthsocial_ws import TruthSocialFeed
    from signals.paper_trade import PaperTrader

    start_binance_stream()
    logger.info("Binance price stream started")

    supabase = SupabaseLogger(
        url=os.environ["SUPABASE_URL"],
        key=os.environ["SUPABASE_KEY"],
    )
    telegram = TelegramAlerter(
        token=os.environ["TELEGRAM_BOT_TOKEN"],
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
    )
    trader = PaperTrader(supabase_logger=supabase, telegram=telegram)

    async def on_classification(post: dict, result: dict) -> None:
        await supabase.log_classification(post["post_id"], result)
        if classifier.should_trade(result):
            result["trade_fired"] = True
            await telegram.send_post_detected(post)
            await telegram.send_classification(result)
            await trader.process_signal(post, result)

    classifier = Classifier(
        api_key=os.environ["GEMINI_API_KEY"],
        on_result=on_classification,
    )

    async def on_post(post: dict) -> None:
        await supabase.log_post(post)
        await classifier.classify(post)

    feed = TruthSocialFeed(
        account_id=os.getenv("TRUTH_SOCIAL_ACCOUNT_ID", "107780257626128497"),
        on_post=on_post,
        access_token=os.getenv("TRUTH_SOCIAL_ACCESS_TOKEN") or None,
    )

    x_poller = None
    x_task = None
    if all(os.getenv(k) for k in ("X_USERNAME", "X_EMAIL", "X_PASSWORD")):
        from feeds.x_poller import XPoller
        x_poller = XPoller(
            username=os.environ["X_USERNAME"],
            email=os.environ["X_EMAIL"],
            password=os.environ["X_PASSWORD"],
            on_post=on_post,
        )
        logger.info("X poller configured — will monitor Elon, Altman, Fed Reserve")
    else:
        logger.info("X credentials not set — X poller disabled")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass  # Windows

    await telegram.send_startup()
    logger.info("[%s] Trading engine started", datetime.now(timezone.utc).isoformat())

    summary_task = asyncio.create_task(_daily_summary_loop(telegram, supabase))
    feed_task = asyncio.create_task(feed.start())
    if x_poller:
        x_task = asyncio.create_task(x_poller.start())

    try:
        await stop_event.wait()
    except Exception as exc:
        logger.critical("Fatal error in main: %s", exc, exc_info=True)
        await telegram.send_error(f"Fatal crash: {exc}")
        raise
    finally:
        logger.info("Shutting down...")
        await feed.stop()
        if x_poller:
            x_poller.stop()
        tasks = [summary_task, feed_task]
        if x_task:
            tasks.append(x_task)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Trading engine stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logging.critical("Unhandled top-level exception: %s", exc, exc_info=True)
        sys.exit(1)
