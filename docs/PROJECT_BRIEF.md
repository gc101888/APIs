# TrumpTrader — Full Project Brief

Complete handoff document. Everything needed to bring a new developer or LLM up to speed instantly.

---

## What This System Does

Monitors social media posts from market-moving figures in real-time. The moment they post, an AI classifies it for market relevance, generates a paper trade signal with entry/stop/target levels, monitors the outcome, and sends instant Telegram alerts with live TradingView chart links.

**Accounts monitored:**
- @realDonaldTrump — Truth Social WebSocket (near-instant, sub-second)
- @elonmusk — X (Twitter), polled every 60s via twikit
- @sama (Sam Altman) — X (Twitter), polled every 60s via twikit
- @federalreserve — X (Twitter), polled every 60s via twikit

**The edge:** Truth Social is the instantaneous source for Trump. Reuters and Bloomberg report AFTER he posts — by then the price has already moved. We read directly from the source before anyone else.

**Phase 1:** Paper trading only — no real broker connected. All P&L is hypothetical. Designed to prove signal quality before going live.

**Future:** Native app (not web). Architecture decisions should keep this in mind.

---

## Current Status (as of 2026-05-24)

### Done — fully live

- Truth Social WebSocket feed (24/7 monitoring, auto-reconnect, exponential backoff)
- X (Twitter) poller via twikit — Elon, Altman, Fed Reserve (60s polling, same pipeline as Truth Social)
- Gemini AI classifier (gemini-2.5-flash-lite, direct REST via aiohttp, 3/3 correct at 95%+)
- Paper trader with entry/stop/target (0.5% stop, 1.5% target, 1:3 R/R)
- Outcome monitoring loop (every 5 min, 4hr time stop)
- Supabase database (3 tables: posts, classifications, signals — RLS configured)
- Supabase Realtime enabled on posts + signals tables (near-instant dashboard push)
- Telegram alerts — fires only on tradeable signals (PERSONAL_NOISE is silent)
- Real-time price feed: Binance WebSocket (crypto) + Alpaca REST (stocks) + yfinance fallback
- NQ/ES proxied to QQQ/SPY via Alpaca for real-time prices (yfinance is 15min delayed)
- Gemini prompt has explicit per-category direction guidance (e.g. GEOPOLITICAL → BUY GLD)
- **Railway engine deployed and running** (project: blissful-miracle, service: Trading-engine)
- Binance API keys added to Railway env
- X credentials added to Railway env (X_USERNAME, X_EMAIL, X_PASSWORD)
- Dashboard live at gc101888.github.io/APIs/ — X-style UI, dark/light mode, multi-account

### Still Needed

- Sign up for Alpaca (free, alpaca.markets) and add ALPACA_API_KEY + ALPACA_API_SECRET to Railway
- **Custom domain via IONOS** — user has a domain ready, session ended before setup. Steps: add CNAME file to repo, configure GitHub Pages custom domain in repo settings, point IONOS DNS to gc101888.github.io
- IBKR paper account for real-time NQ/ES futures prices (currently falls back to yfinance 15min delay)
- Phase 2: connect live broker (IBKR) for real execution

---

## Architecture

```
Truth Social WebSocket                    X (Twitter) Poller
wss://truthsocial.com/api/v1/...          feeds/x_poller.py
Account: 107780257626128497               Accounts: elonmusk, sama, federalreserve
  - Sub-second detection                    - Polls every 60s via twikit
  - Auto-reconnect with backoff             - Deduplicates by tweet ID
         │                                         │
         └──────────────┬────────────────────────────┘
                        │ on_post(post) callback — same for both sources
                        ▼
              Supabase: posts table
              (post_id prefixed "x_" for X posts)
                        │
                        ▼
              classifier/classify.py
                - Google Gemini 2.5-flash-lite (free tier)
                - Direct REST via aiohttp (no SDK — bypasses gRPC SSL issues)
                - Returns: category, confidence, direction, instruments, reasoning
                - Confidence < 0.75 → skip silently
                - Category = PERSONAL_NOISE → skip silently
                        │
                        ├──► Supabase: classifications table
                        │
                        │ [Only if should_trade() passes]
                        ├──► Telegram: POST DETECTED + CLASSIFIED
                        ▼
              signals/paper_trade.py
                - Fetch entry price via feeds/price_feed.py
                - Calculate stop (±0.5%) and target (±1.5%)
                        │
                        ├──► Supabase: signals table
                        ├──► Telegram: SIGNAL FIRED + TradingView chart link
                        ▼
              Outcome Monitor (asyncio background loop, not one-shot)
                - Poll price every 5 minutes for up to 4 hours
                - TARGET_HIT / STOP_HIT / TIME_STOP (all hypothetical — paper trading)
                        │
                        ├──► Supabase: update outcome, exit_price, pnl_pct
                        └──► Telegram: TARGET HIT / STOP HIT / TIME STOP

Daily at 17:00 UTC → Supabase query → Telegram DAILY SUMMARY
Fatal crash → Telegram ERROR

Dashboard (docs/index.html — GitHub Pages)
  - Supabase Realtime WebSocket → near-instant push when posts/signals arrive
  - 30s polling kept as silent fallback if WebSocket drops
  - X-style layout: sidebar nav, center post feed, right trade panel
```

---

## Price Feed Architecture

```
feeds/price_feed.py — unified get_price(instrument) function

Priority routing:
1. Binance WebSocket (instantaneous, runs permanently in background)
   Covers: BTC, ETH, BNB, SOL and any USDT pair
   Keys: BINANCE_API_KEY, BINANCE_API_SECRET ← IN RAILWAY

2. Futures proxy via Alpaca (real-time, free tier)
   NQ → QQQ, ES → SPY (ETF proxies — CME futures have no free real-time feed)
   Keys: ALPACA_API_KEY, ALPACA_API_SECRET ← STILL NEEDED

3. Alpaca REST (real-time, free tier)
   Covers: SPY, QQQ, AAPL, PLTR, TSLA, NVDA, MSFT, AMZN, META, DJT, GLD

4. yfinance fallback (15-min delay — used when Alpaca not configured)
   Covers: NQ=F, ES=F, and everything else

Future: IBKR API for real-time NQ/ES futures (replaces yfinance fallback)
```

---

## File Structure

```
APIs/
├── main.py                     Entry point (production)
├── test_pipeline.py            Test with 3 simulated posts (no live WebSocket)
├── requirements.txt
├── .env                        All secrets (not committed to git)
├── .env.example                Template
│
├── feeds/
│   ├── truthsocial_ws.py       Truth Social WebSocket client
│   ├── x_poller.py             X (Twitter) poller via twikit (Elon, Altman, Fed)
│   └── price_feed.py           Unified price feed (Binance/Alpaca/yfinance)
│
├── classifier/
│   └── classify.py             Gemini AI classifier + system prompt
│
├── signals/
│   └── paper_trade.py          Signal generation + outcome monitoring loop
│
├── alerts/
│   └── telegram.py             Telegram bot (7 alert types)
│
├── db_logging/
│   └── supabase_logger.py      Async Supabase writer (asyncio.to_thread)
│
├── deploy/
│   ├── setup.sh                Ubuntu 24 VPS one-command setup
│   └── trading-engine.service  Systemd unit file
│
└── docs/
    ├── index.html              Dashboard UI (X-style, dark/light mode, multi-account)
    └── PROJECT_BRIEF.md        This document
```

---

## Environment Variables

```bash
# Truth Social
TRUTH_SOCIAL_ACCOUNT_ID=107780257626128497
TRUTH_SOCIAL_ACCESS_TOKEN=          # optional — public stream works without it
                                    # Truth Social blocks app registration API
                                    # Extract from browser DevTools if needed

# Google Gemini (free — aistudio.google.com)
GEMINI_API_KEY=AIzaSyAlCh3iCve6RFFhsSxl8amFdu6CuN2TVGM

# Supabase (tables already created, RLS configured, Realtime enabled)
SUPABASE_URL=https://hhnkojvtecsighomybyl.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhobmtvanZ0ZWNzaWdob215YnlsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzkzODgzNDEsImV4cCI6MjA5NDk2NDM0MX0.t6-LKo2zYi3wSt62jirkB3f1y0C81yX6eWKX4jZpOnc

# Telegram
TELEGRAM_BOT_TOKEN=8638633345:AAFAp2YXnCR7eJrgo4oaxmTr5WxHekk9uBw
TELEGRAM_CHAT_ID=412222888

# Binance (real-time crypto prices — read-only key) ← IN RAILWAY
BINANCE_API_KEY=<in Railway env>
BINANCE_API_SECRET=<in Railway env>

# Alpaca (real-time US stocks — free, alpaca.markets) ← STILL NEEDED
ALPACA_API_KEY=
ALPACA_API_SECRET=

# X (Twitter) poller — throwaway account credentials ← IN RAILWAY
# Engine only starts X poller if all three are present
X_USERNAME=<in Railway env>     # handle without @
X_EMAIL=<in Railway env>        # email used to register the account
X_PASSWORD=<in Railway env>     # account password

# System
LOG_LEVEL=INFO
PAPER_TRADE_ONLY=true
```

---

## Supabase Tables (already created)

```sql
-- posts: one row per post (Truth Social or X)
-- X posts have post_id prefixed with "x_" e.g. "x_1234567890"
-- raw_json includes platform/author for X posts: {"platform":"x","author":"elonmusk",...}
create table posts (
  id         uuid primary key default gen_random_uuid(),
  post_id    text unique not null,
  posted_at  timestamptz not null,
  content    text,
  raw_json   jsonb,
  created_at timestamptz default now()
);

-- classifications: AI result for each post
create table classifications (
  id          uuid primary key default gen_random_uuid(),
  post_id     text references posts(post_id),
  category    text,
  confidence  float,
  tickers     text[],
  direction   text,
  instruments text[],
  reasoning   text,
  trade_fired boolean default false,
  created_at  timestamptz default now()
);

-- signals: paper trades
create table signals (
  id           uuid primary key default gen_random_uuid(),
  post_id      text references posts(post_id),
  instrument   text,
  direction    text,
  entry_price  float,
  stop_price   float,
  target_price float,
  exit_price   float,
  outcome      text,    -- TARGET_HIT | STOP_HIT | TIME_STOP
  pnl_pct      float,
  created_at   timestamptz default now(),
  resolved_at  timestamptz
);

-- RLS: allow dashboard to read anonymously
alter table posts          enable row level security;
alter table classifications enable row level security;
alter table signals        enable row level security;
create policy "anon read posts"           on posts          for select using (true);
create policy "anon read classifications" on classifications for select using (true);
create policy "anon read signals"         on signals        for select using (true);

-- Realtime: enabled in Supabase dashboard
-- Database → Publications → supabase_realtime → posts and signals tables toggled ON
-- This enables near-instant push to dashboard WebSocket when rows are inserted/updated
```

---

## Signal Strategy

### Categories & Direction (set in Gemini system prompt in classifier/classify.py)

| Category | Direction | Instruments |
|---|---|---|
| TARIFF_ESCALATION | SELL | ES, NQ |
| TARIFF_ROLLBACK | BUY | ES, NQ |
| TRADE_DEAL | BUY | ES, NQ |
| FED_CRITICISM | BUY | GLD, BTC (inflation/dollar distrust hedge) |
| CRYPTO_ENDORSEMENT | BUY | BTC |
| STOCK_MENTION | BUY | Named ticker |
| ENERGY_POLICY | varies | judgment call |
| DEFENSE_POLICY | varies | defense stocks if named |
| GEOPOLITICAL | BUY GLD, SELL ES | safe haven + risk-off |
| PERSONAL_NOISE | SKIP | — (no Telegram alert, no signal) |

**Note:** Direction guidance is embedded in the Gemini system prompt — Gemini makes the final call but defaults to these. The GEOPOLITICAL → BUY GLD fix was applied (original brief had it wrong as SELL GLD).

### Risk Parameters (fixed 1:3 R/R)

- Confidence threshold: 0.75 minimum to fire
- Stop: ±0.5% from entry
- Target: ±1.5% from entry
- Monitor: every 5 minutes
- Time stop: 4 hours
- Outcomes: TARGET_HIT / STOP_HIT / TIME_STOP (all hypothetical)
- Labels are honest — NOT WIN/LOSS since we're not actually in a trade

---

## AI Classifier Detail

- **Model:** gemini-2.5-flash-lite (the only free model with quota on this Gemini project)
- **API:** Direct REST via aiohttp — NOT the Google SDK
- **Why no SDK:** gRPC SSL fails in Railway sandbox. Direct REST bypasses this entirely.
- **Endpoint:** `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent`
- **Temperature:** 0.0 (deterministic output)
- **Retry:** once on JSON parse failure
- **System prompt:** includes per-category direction guidance table

---

## X (Twitter) Poller Detail

- **File:** `feeds/x_poller.py`
- **Library:** twikit — unofficial X app API, no API key required
- **Auth:** Throwaway Twitter account. Credentials in Railway env: X_USERNAME, X_EMAIL, X_PASSWORD
- **Accounts:** @elonmusk, @sama, @federalreserve
- **Poll interval:** 60 seconds per account
- **Deduplication:** tracks seen tweet IDs per account in memory; seeds on startup so old tweets don't fire
- **Post format:** post_id = `x_{tweet_id}`, raw_json includes `{"platform":"x","author":"elonmusk","display_name":"Elon Musk","tweet_id":"..."}`
- **Pipeline:** identical to Truth Social — same on_post() → Supabase → Gemini → paper trade → Telegram
- **Startup:** only starts if all 3 X env vars are present; logs warning and skips if not
- **Reconnect:** exponential backoff on crash: 30s → 60s → 120s → ... → 600s max
- **Risk:** twikit uses X's internal app API — against ToS, could break if X changes internals. Throwaway account means no personal account risk.

---

## Telegram Alert System

Alerts fire only when a trade signal actually fires (confidence ≥ 0.75, not PERSONAL_NOISE).
PERSONAL_NOISE and low-confidence posts are completely silent.

| Trigger | Message |
|---|---|
| Engine starts | ✅ Trading Engine Online |
| Signal fires → post detected | 📡 TRUMP POST DETECTED (or relevant account) |
| Signal fires → classification | 🔍 AI CLASSIFICATION + reasoning |
| Signal fires → trade opened | 🚨 SIGNAL FIRED + entry/stop/target + chart link |
| Trade resolves | ✅❌⏰ TARGET HIT / STOP HIT / TIME STOP + P&L |
| Daily at 17:00 UTC | 📊 DAILY SUMMARY |
| Fatal crash | ⚠️ ERROR |

---

## Dashboard (docs/index.html)

**URL:** https://gc101888.github.io/APIs/
**Custom domain:** pending — user has IONOS domain. Not yet configured.

**Design:** X (Twitter) inspired — 3-column layout

- **Left sidebar:** Home, Following, Analytics nav + dark/light mode toggle + live monitor box
- **Center feed:** Posts in X-style cards — "Live Feed" and "Signals Only" tabs. Shows all followed accounts (Trump, Elon, Altman, Fed).
- **Right panel:** Click any post → shows trade details. Open trade = live chart + entry/stop/target levels. Closed trade = outcome + P&L + chart
- **Following page:** Account management — Trump (Truth Social, live), Elon Musk (X, live), Sam Altman (X, live), Federal Reserve (X, live). Followed accounts stored in localStorage, filter feed/signals. Default: only Trump followed.
- **Analytics page:** Full signal stats — signals, wins, losses, open, win rate, P&L, posts tracked

**Monitor box (sidebar):**
- "● Live" pulsing green when Supabase Realtime WebSocket is connected
- Uptime counter: "47 posts · uptime 4m 32s" — ticks every second
- Scrolling activity log in monospace — timestamps for: session started, feed sync, realtime connected, heartbeat checks, new post detected, signal updates, errors

**Live update mechanism:**
- Primary: Supabase Realtime WebSocket — push notification to browser the instant a row is inserted. Near-instant.
- Fallback: 30s silent background poll — runs regardless, keeps data fresh if WebSocket drops
- Supabase setup required: Database → Publications → supabase_realtime → enable posts + signals tables

**Multi-account post cards:**
- `getPostAuthor(post)` helper reads `raw_json.platform` and `raw_json.author` to identify source
- Each card shows correct name, handle, avatar gradient per account
- Feed filter uses `getPostAccountId(post)` — not hardcoded to Trump ID
- Right panel author label is dynamic

**Theme:** Dark mode by default, light mode available via toggle. Preference saved to localStorage.

**Tech:** Single HTML file, vanilla JS, no framework. Supabase JS client loaded from CDN for Realtime.

**TradingView notes:**
- CME futures (NQ1!, ES1!) require paid TradingView — using QQQ/SPY as free proxies
- "Open Full Chart" button links to tradingview.com with correct symbol

---

## Deployment

### Railway (live — blissful-miracle project)

- **Service:** Trading-engine
- **Status:** Online
- **Repo:** gc101888/APIs (master branch)
- **Start command:** `python main.py`
- **Python version:** 3.13.13 (US West)

To redeploy after code changes: push to master → Railway auto-deploys.

To view logs: railway.app → blissful-miracle → Trading-engine → Deploy Logs

### Ubuntu VPS (alternative)

```bash
curl -fsSL https://raw.githubusercontent.com/gc101888/APIs/master/deploy/setup.sh | bash
nano /opt/trading-engine/.env   # paste your keys
systemctl start trading-engine
journalctl -u trading-engine -f
```

---

## Custom Domain Setup (PENDING)

User has an IONOS domain. Dashboard currently at gc101888.github.io/APIs/.

**To set up (5 minutes):**

For a subdomain e.g. `trade.yourdomain.com` (recommended — simplest):
1. In IONOS DNS: add CNAME record → `trade` → `gc101888.github.io`
2. In repo: create file `docs/CNAME` containing just `trade.yourdomain.com`
3. In GitHub: repo Settings → Pages → Custom domain → enter `trade.yourdomain.com`
4. GitHub auto-provisions SSL via Let's Encrypt (takes ~10 min)

For apex domain `yourdomain.com`:
1. In IONOS DNS: add 4 A records for `@` pointing to GitHub Pages IPs:
   - 185.199.108.153
   - 185.199.109.153
   - 185.199.110.153
   - 185.199.111.153
2. Steps 2-4 same as above

---

## Cost Summary

| Service | Cost | Status |
|---|---|---|
| Gemini AI | Free | Live |
| Supabase | Free | Live (Realtime enabled) |
| GitHub Pages | Free | Live |
| Telegram | Free | Live |
| Truth Social feed | Free | Live (Railway) |
| X (Twitter) poller | Free | Live (twikit, throwaway account) |
| Binance prices | Free | Live (keys in Railway) |
| Alpaca prices | Free | Keys still needed |
| Railway (engine host) | ~$5/month | Live — blissful-miracle |
| IBKR (futures + live trading) | Free API | Not set up yet |
| Custom domain (IONOS) | User already pays | Pending setup |

**Total running cost: ~$5/month**

---

## What's Next

1. **Custom domain** — user has IONOS domain ready. Provide the domain name and preferred subdomain, follow steps in Custom Domain Setup section above
2. **Sign up for Alpaca** (free, 2 min) at alpaca.markets → add ALPACA_API_KEY + ALPACA_API_SECRET to Railway → NQ/ES signals get real-time prices instead of 15min yfinance delay
3. **IBKR paper account** — for real-time NQ/ES futures prices (replaces yfinance fallback entirely)
4. **Phase 2: live trading** — connect IBKR broker to execute real trades when signals fire
5. **Native app** — user wants to move from web to native app eventually. Dashboard at gc101888.github.io/APIs/ is fine for now but keep native architecture in mind

---

## Key Technical Decisions

| Decision | Reason |
|---|---|
| Gemini not Claude for AI | gRPC SSL fails in Railway/sandbox; direct REST works everywhere |
| gemini-2.5-flash-lite | Only free model with quota on this Gemini project — do not change |
| aiohttp not SDK | Bypasses gRPC entirely |
| db_logging not logging | Would shadow Python stdlib logging module silently |
| asyncio.to_thread for Supabase | supabase-py is synchronous; blocks event loop without it |
| Outcome monitoring loop not one-shot | One-shot 2hr check gives wrong outcome if price whipsaws hit/miss/hit |
| NQ/ES proxied to QQQ/SPY | CME futures have no free real-time data feed |
| QQQ/SPY in TradingView widget | CME_MINI:NQ1! requires paid TradingView subscription |
| TARGET_HIT/STOP_HIT not WIN/LOSS | Honest — not actually in a trade, paper only |
| Telegram silent on PERSONAL_NOISE | Trump posts ~10-20x/day; most are noise. Alerts only when signal fires |
| Truth Social token optional | Public stream works unauthenticated; API registration endpoint is 403 blocked |
| GEOPOLITICAL → BUY GLD | Geopolitical tension is safe-haven positive for gold (original brief had SELL which was wrong) |
| twikit for X not official API | X API costs $100/month minimum. twikit uses internal app API — free but against ToS. Throwaway account used to isolate risk. |
| Supabase Realtime not polling | 30s polling gives 30s lag on dashboard. Realtime WebSocket pushes instantly on INSERT. Requires enabling tables in Database → Publications → supabase_realtime. |
| X post_id prefixed "x_" | Avoids collision with Truth Social post IDs in the shared posts table |
| X poller seeds on startup | Without seeding, every existing tweet from each account would fire as a "new" signal on engine restart |

---

## Local Development

Repo is cloned at: `C:\Users\glenn\APIs`

```bash
# Windows — packages don't install cleanly on Python 3.14 (pyiceberg build issue)
# Run and test via Railway instead

# To push changes:
cd C:\Users\glenn\APIs
git add .
git commit -m "your message"
git push origin master
# Railway auto-redeploys on push
```
