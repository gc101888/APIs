import json
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 200
TEMPERATURE = 0.0
CONFIDENCE_THRESHOLD = 0.75
SKIP_CATEGORIES = {"PERSONAL_NOISE"}

SYSTEM_PROMPT = (
    "You are a financial market signal classifier. Analyse this Trump Truth Social post "
    "and return ONLY valid JSON with no other text, no markdown, no explanation:\n"
    "{\n"
    '  "category": "one of [TARIFF_ESCALATION, TARIFF_ROLLBACK, TRADE_DEAL, FED_CRITICISM, '
    "CRYPTO_ENDORSEMENT, STOCK_MENTION, ENERGY_POLICY, DEFENSE_POLICY, GEOPOLITICAL, PERSONAL_NOISE]\",\n"
    '  "confidence": "float 0.0 to 1.0",\n'
    '  "tickers": "array of any stock tickers explicitly mentioned",\n'
    '  "direction": "one of [BUY, SELL, NONE]",\n'
    '  "instruments": "array of suggested instruments to trade e.g. [NQ, ES, GLD, BTC, AAPL]",\n'
    '  "reasoning": "one sentence max explanation"\n'
    "}"
)


class Classifier:
    def __init__(self, api_key: str, on_result: Optional[Callable] = None):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.on_result = on_result

    async def classify(self, post: dict) -> Optional[dict]:
        post_id = post.get("post_id", "unknown")
        result = await self._call_claude(post.get("content", ""))

        if result is None:
            logger.error(
                "[%s] Classification failed for post %s",
                datetime.now(timezone.utc).isoformat(),
                post_id,
            )
            return None

        result["post_id"] = post_id
        result.setdefault("trade_fired", False)

        logger.info(
            "[%s] Classified %s: category=%s confidence=%.2f direction=%s",
            datetime.now(timezone.utc).isoformat(),
            post_id,
            result.get("category"),
            result.get("confidence", 0.0),
            result.get("direction"),
        )

        if self.on_result:
            await self.on_result(post, result)

        return result

    async def _call_claude(self, content: str, is_retry: bool = False) -> Optional[dict]:
        try:
            response = await self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
            raw = response.content[0].text.strip()
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            if not is_retry:
                logger.warning(
                    "[%s] JSON parse failed, retrying: %s",
                    datetime.now(timezone.utc).isoformat(),
                    exc,
                )
                return await self._call_claude(content, is_retry=True)
            logger.error(
                "[%s] JSON parse failed after retry: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )
            return None
        except anthropic.APIError as exc:
            logger.error(
                "[%s] Claude API error: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )
            return None
        except Exception as exc:
            logger.error(
                "[%s] Unexpected classifier error: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )
            return None

    def should_trade(self, result: dict) -> bool:
        if result.get("category") in SKIP_CATEGORIES:
            return False
        return (result.get("confidence") or 0.0) >= CONFIDENCE_THRESHOLD
