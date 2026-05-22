"""
Test pipeline — runs 3 simulated Trump posts through the full stack
without connecting to the live WebSocket.

Usage:
    python test_pipeline.py

Requires:  GEMINI_API_KEY (mandatory — free at aistudio.google.com)
Optional:  SUPABASE_URL + SUPABASE_KEY  (skipped if absent)
           TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID  (skipped if absent)
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level="DEBUG",
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("test_pipeline")

TEST_POSTS = [
    {
        "post_id": "test-001",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content": (
            "China is becoming very hostile. We will be imposing additional TARIFFS immediately!"
        ),
        "media_attachments": [],
        "url": "https://truthsocial.com/@realDonaldTrump/test-001",
        "raw_json": {},
    },
    {
        "post_id": "test-002",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content": (
            "Palantir (PLTR) is doing an incredible job for our country. BUY AMERICAN!"
        ),
        "media_attachments": [],
        "url": "https://truthsocial.com/@realDonaldTrump/test-002",
        "raw_json": {},
    },
    {
        "post_id": "test-003",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content": "Happy Tuesday everyone! God bless the USA!",
        "media_attachments": [],
        "url": "https://truthsocial.com/@realDonaldTrump/test-003",
        "raw_json": {},
    },
]


async def run_test_post(post: dict, classifier, trader, supabase, telegram) -> dict:
    logger.info("")
    logger.info("=" * 65)
    logger.info("POST  %s", post["post_id"])
    logger.info("TEXT  %s", post["content"])
    logger.info("=" * 65)

    result = {"post": post, "classification": None, "trade_fired": False}

    if supabase:
        await supabase.log_post(post)

    classification = await classifier.classify(post)
    result["classification"] = classification

    if classification is None:
        logger.error("Classification returned None")
        return result

    logger.info("RESULT  %s", json.dumps(classification, indent=2))

    if supabase:
        await supabase.log_classification(post["post_id"], classification)

    if telegram:
        await telegram.send_classification(classification)

    if classifier.should_trade(classification):
        logger.info("→ Confidence %.0f%% meets threshold — firing paper trade",
                    (classification.get("confidence") or 0) * 100)
        result["trade_fired"] = True
        await trader.process_signal(post, classification)
    else:
        reason = (
            "PERSONAL_NOISE" if classification.get("category") == "PERSONAL_NOISE"
            else f"confidence {classification.get('confidence', 0):.2f} < 0.75"
        )
        logger.info("→ Skipped: %s", reason)

    return result


async def main() -> None:
    if not os.getenv("GEMINI_API_KEY"):
        logger.critical("GEMINI_API_KEY is required")
        sys.exit(1)

    # Optional integrations — silently skip if not configured
    supabase = None
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"):
        from db_logging.supabase_logger import SupabaseLogger
        supabase = SupabaseLogger(
            url=os.environ["SUPABASE_URL"],
            key=os.environ["SUPABASE_KEY"],
        )
        logger.info("Supabase: connected")
    else:
        logger.info("Supabase: not configured (set SUPABASE_URL + SUPABASE_KEY to enable)")

    telegram = None
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        from alerts.telegram import TelegramAlerter
        telegram = TelegramAlerter(
            token=os.environ["TELEGRAM_BOT_TOKEN"],
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
        )
        logger.info("Telegram: connected")
    else:
        logger.info("Telegram: not configured (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to enable)")

    from classifier.classify import Classifier
    from signals.paper_trade import PaperTrader

    classifier = Classifier(api_key=os.environ["GEMINI_API_KEY"])
    trader = PaperTrader(supabase_logger=supabase, telegram=telegram)

    logger.info("")
    logger.info("Running %d test posts through the pipeline...", len(TEST_POSTS))

    results = []
    for post in TEST_POSTS:
        r = await run_test_post(post, classifier, trader, supabase, telegram)
        results.append(r)
        await asyncio.sleep(0.5)

    logger.info("")
    logger.info("=" * 65)
    logger.info("PIPELINE SUMMARY")
    logger.info("=" * 65)
    for r in results:
        c = r.get("classification") or {}
        fired = "SIGNAL FIRED" if r["trade_fired"] else "skipped"
        logger.info(
            "  %s  %-20s  conf=%.2f  dir=%-4s  → %s",
            r["post"]["post_id"],
            c.get("category", "FAILED"),
            c.get("confidence", 0.0),
            c.get("direction", "N/A"),
            fired,
        )
    logger.info("=" * 65)
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
