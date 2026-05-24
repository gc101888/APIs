import json
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_TOKENS = 200
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
    "}\n\n"
    "Category guidance — use these as your default unless the post clearly contradicts them:\n"
    "TARIFF_ESCALATION: SELL ES, NQ (risk-off)\n"
    "TARIFF_ROLLBACK: BUY ES, NQ (relief rally)\n"
    "TRADE_DEAL: BUY ES, NQ\n"
    "FED_CRITICISM: BUY GLD, BTC (dollar distrust / inflation hedge)\n"
    "CRYPTO_ENDORSEMENT: BUY BTC\n"
    "STOCK_MENTION: BUY the mentioned ticker\n"
    "GEOPOLITICAL: BUY GLD (safe haven), SELL ES (risk-off)\n"
    "ENERGY_POLICY: use judgment — oil/gas expansion = BUY energy stocks\n"
    "DEFENSE_POLICY: BUY defense stocks if named, else NONE\n"
    "PERSONAL_NOISE: NONE, no instruments\n"
)


class Classifier:
    def __init__(self, api_key: str, on_result: Optional[Callable] = None):
        self.api_key = api_key
        self.on_result = on_result

    async def classify(self, post: dict) -> Optional[dict]:
        post_id = post.get("post_id", "unknown")
        result = await self._call_gemini(post.get("content", ""))

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

    async def _call_gemini(self, content: str, is_retry: bool = False) -> Optional[dict]:
        url = f"{GEMINI_BASE}/{GEMINI_MODEL}:generateContent?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": content}]}],
            "generationConfig": {
                "maxOutputTokens": MAX_TOKENS,
                "temperature": 0.0,
            },
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())

        except json.JSONDecodeError as exc:
            if not is_retry:
                logger.warning(
                    "[%s] JSON parse failed, retrying: %s",
                    datetime.now(timezone.utc).isoformat(),
                    exc,
                )
                return await self._call_gemini(content, is_retry=True)
            logger.error(
                "[%s] JSON parse failed after retry: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )
            return None
        except Exception as exc:
            logger.error(
                "[%s] Gemini API error: %s",
                datetime.now(timezone.utc).isoformat(),
                exc,
            )
            return None

    def should_trade(self, result: dict) -> bool:
        if result.get("category") in SKIP_CATEGORIES:
            return False
        return (result.get("confidence") or 0.0) >= CONFIDENCE_THRESHOLD
