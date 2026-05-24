import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds between checks per account

X_ACCOUNTS = [
    {"screen_name": "elonmusk",        "display_name": "Elon Musk"},
    {"screen_name": "sama",            "display_name": "Sam Altman"},
    {"screen_name": "federalreserve",  "display_name": "Federal Reserve"},
]


def _parse_time(created_at: str) -> str:
    try:
        return parsedate_to_datetime(created_at).astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


class XPoller:
    def __init__(self, username: str, email: str, password: str, on_post):
        self.username = username
        self.email = email
        self.password = password
        self.on_post = on_post
        self._client = None
        self._seen: dict[str, set] = {a["screen_name"]: set() for a in X_ACCOUNTS}
        self._user_ids: dict[str, str] = {}
        self._running = False

    async def _login(self) -> None:
        from twikit import Client
        self._client = Client("en-US")
        await self._client.login(
            auth_info_1=self.username,
            auth_info_2=self.email,
            password=self.password,
        )
        logger.info("X poller: logged in as @%s", self.username)

    async def _resolve_users(self) -> None:
        for acct in X_ACCOUNTS:
            sn = acct["screen_name"]
            try:
                user = await self._client.get_user_by_screen_name(sn)
                self._user_ids[sn] = user.id
                logger.info("X poller: resolved @%s → id %s", sn, user.id)
            except Exception as exc:
                logger.warning("X poller: could not resolve @%s: %s", sn, exc)

    async def _poll_account(self, acct: dict) -> None:
        sn = acct["screen_name"]
        uid = self._user_ids.get(sn)
        if not uid:
            return
        try:
            tweets = await self._client.get_user_tweets(uid, "Tweets", count=5)
            initialized = bool(self._seen[sn])
            new_tweets = []
            for tweet in tweets:
                tid = str(tweet.id)
                if tid not in self._seen[sn]:
                    self._seen[sn].add(tid)
                    if initialized:
                        new_tweets.append(tweet)
            for tweet in new_tweets:
                post = {
                    "post_id": f"x_{tweet.id}",
                    "posted_at": _parse_time(tweet.created_at),
                    "content": tweet.text,
                    "raw_json": {
                        "platform": "x",
                        "author": sn,
                        "display_name": acct["display_name"],
                        "tweet_id": str(tweet.id),
                    },
                }
                logger.info("X: new post @%s — %s", sn, tweet.text[:80])
                await self.on_post(post)
        except Exception as exc:
            logger.warning("X poller: error polling @%s: %s", sn, exc)

    async def start(self) -> None:
        self._running = True
        backoff = 30
        while self._running:
            try:
                await self._login()
                await self._resolve_users()
                # Seed seen IDs on startup — don't fire for existing tweets
                for acct in X_ACCOUNTS:
                    await self._poll_account(acct)
                logger.info("X poller: active — checking every %ds", POLL_INTERVAL)
                backoff = 30
                while self._running:
                    await asyncio.sleep(POLL_INTERVAL)
                    for acct in X_ACCOUNTS:
                        await self._poll_account(acct)
            except Exception as exc:
                logger.error("X poller: crash, retrying in %ds — %s", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 600)

    def stop(self) -> None:
        self._running = False
