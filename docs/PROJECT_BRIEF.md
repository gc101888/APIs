# TrumpTrader — Full Project Brief

Complete handoff document. Everything needed to bring a new developer or LLM up to speed instantly.

---

## What This System Does

Monitors @realDonaldTrump's Truth Social posts in real-time. The moment he posts, an AI classifies it for market relevance, generates a paper trade signal with entry/stop/target levels, monitors the outcome, and sends instant Telegram alerts with live TradingView chart links.

**The edge:** Truth Social is the instantaneous source. Reuters and Bloomberg report AFTER Trump posts — by then the price has already moved. We read directly from the source before anyone else.

**Phase 1:** Paper trading only — no real broker connected. All P&L is hypothetical. Designed to prove signal quality before going live.

**Future:** Native app (not web). Architecture decisions should keep this in mind.

---

## Current Status (as of 2026-05-24)

### Done — fully live

- Truth Social WebSocket feed (24/7 monitoring, auto-reconnect, exponential backoff)
- Gemini AI classifier (gemini-2.5-flash-lite, direct REST via aiohttp, 3/3 correct at 95%+)
- Paper trader with entry/stop/target (0.5% stop, 1.5% target, 1:3 R/R)
- Outcome monitoring loop (every 5 min, 4hr time stop)
- Supabase database (3 tables: posts, classifications, signals — RLS configured)
- Telegram alerts — fires only on tradeable signals (PERSONAL_NOISE is silent)
- Real-time price feed: Binance WebSocket (crypto) + Alpaca REST (stocks) + yfinance fallback
- NQ/ES proxied to QQQ/SPY via Alpaca for real-time prices (yfinance is 15min delayed)
- Gemini prompt has explicit per-category direction guidance (e.g. GEOPOLITICAL → BUY GLD)
- **Railway engine deployed and running** (project: blissful-miracle, service: Trading-engine)
- Binance API keys added to Railway env
- Dashboard live at gc101888.github.io/APIs/ — X-style UI, dark/light mode

### Still Needed

- Sign up for Alpaca (free, alpaca.markets) and add ALPACA_API_KEY + ALPACA_API_SECRET to Railway
- IBKR paper account for real-time NQ/ES futures prices (currently falls back to yfinance 15min delay)
- Phase 2: connect live broker (IBKR) for real execution

---

## Architecture

```
Truth Social WebSocket
wss://truthsocial.com/api/v1/streaming/public
Account: 107780257626128497 (@realDonaldTrump)
         │
         │ New post detected instantly
         ▼
feeds/truthsocial_ws.py
  - Filter by account ID
  - Deduplicate by post_id
  - Reconnect with backoff [1,2,4,8,16,60]s
         │
         ├──► Supabase: posts table
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
  - Reason for loop: one-shot check gives wrong outcome on price whipsaws
  - TARGET_HIT / STOP_HIT / TIME_STOP (all hypothetical — paper trading)
         │
         ├──► Supabase: update outcome, exit_price, pnl_pct
         └──► Telegram: TARGET HIT / STOP HIT / TIME STOP

Daily at 17:00 UTC → Supabase query → Telegram DAILY SUMMARY
Fatal crash → Telegram ERROR

GitHub Pages dashboard (docs/index.html)
  - Polls Supabase REST API every 30 seconds
  - X-style layout: sidebar nav, center post feed, right trade panel
```

---

## Price Feed Architecture

```
feeds/price_feed.py — unified get_price(instrument) function

Priority routing:
1. Binance WebSocket (instantaneous, runs permanently in background)
   Covers: BTC, ETH, BNB, SOL and any USDT pair
   Keys: BINANCE_API_KEY, BINANCE_API_SECRET ← ADDED TO RAILWAY

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
    ├── index.html              Dashboard UI (X-style, dark/light mode)
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

# Supabase (tables already created, RLS configured)
SUPABASE_URL=https://hhnkojvtecsighomybyl.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhobmtvanZ0ZWNzaWdob215YnlsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzkzODgzNDEsImV4cCI6MjA5NDk2NDM0MX0.t6-LKo2zYi3wSt62jirkB3f1y0C81yX6eWKX4jZpOnc

# Telegram
TELEGRAM_BOT_TOKEN=8638633345:AAFAp2YXnCR7eJrgo4oaxmTr5WxHekk9uBw
TELEGRAM_CHAT_ID=412222888

# Binance (real-time crypto prices — read-only key) ← ADDED TO RAILWAY
BINANCE_API_KEY=<in Railway env>
BINANCE_API_SECRET=<in Railway env>

# Alpaca (real-time US stocks — free, alpaca.markets) ← STILL NEEDED
ALPACA_API_KEY=
ALPACA_API_SECRET=

# System
LOG_LEVEL=INFO
PAPER_TRADE_ONLY=true
```

---

## Supabase Tables (already created)

```sql
-- posts: one row per Trump post
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

## Telegram Alert System

Alerts fire only when a trade signal actually fires (confidence ≥ 0.75, not PERSONAL_NOISE).
PERSONAL_NOISE and low-confidence posts are completely silent.

| Trigger | Message |
|---|---|
| Engine starts | ✅ Trading Engine Online |
| Signal fires → post detected | 📡 TRUMP POST DETECTED |
| Signal fires → classification | 🔍 AI CLASSIFICATION + reasoning |
| Signal fires → trade opened | 🚨 SIGNAL FIRED + entry/stop/target + chart link |
| Trade resolves | ✅❌⏰ TARGET HIT / STOP HIT / TIME STOP + P&L |
| Daily at 17:00 UTC | 📊 DAILY SUMMARY |
| Fatal crash | ⚠️ ERROR |

---

## Dashboard (docs/index.html)

**URL:** https://gc101888.github.io/APIs/

**Design:** X (Twitter) inspired — 3-column layout

- **Left sidebar:** Home, Following, Analytics nav + dark/light mode toggle + radar animation
- **Center feed:** Trump posts in X-style cards — "Live Feed" and "Signals Only" tabs
- **Right panel:** Click any post → shows trade details. Open trade = live chart + entry/stop/target levels. Closed trade = outcome + P&L + chart
- **Following page:** Account management — follow/unfollow accounts. Trump active, Elon Musk + Jerome Powell shown as coming soon. Followed accounts stored in localStorage and filter the feed/signals
- **Analytics page:** Full signal stats — signals, wins, losses, open, win rate, P&L, posts tracked
- **Live feel:** Scan bar animation across feed header, radar sweep in sidebar, second-by-second "Checked Xs ago" counter, new posts banner when refresh detects fresh data

**Theme:** Dark mode by default, light mode available via toggle. Preference saved to localStorage.

**Tech:** Single HTML file, vanilla JS, no framework. Supabase REST polled every 30s.

**TradingView notes:**
- CME futures (NQ1!, ES1!) require paid TradingView — using QQQ/SPY as free proxies
- Chart tabs in sidebar are dynamic — show instruments from recent signals, not hardcoded
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

## Cost Summary

| Service | Cost | Status |
|---|---|---|
| Gemini AI | Free | Live |
| Supabase | Free | Live (tables created) |
| GitHub Pages | Free | Live |
| Telegram | Free | Live |
| Truth Social feed | Free | Live (Railway) |
| Binance prices | Free | Live (keys in Railway) |
| Alpaca prices | Free | Keys still needed |
| Railway (engine host) | ~$5/month | Live — blissful-miracle |
| IBKR (futures + live trading) | Free API | Not set up yet |

**Total running cost: ~$5/month**

---

## What's Next

1. **Sign up for Alpaca** (free, 2 min) at alpaca.markets → add ALPACA_API_KEY + ALPACA_API_SECRET to Railway → NQ/ES signals get real-time prices instead of 15min yfinance delay
2. **IBKR paper account** — for real-time NQ/ES futures prices (replaces yfinance fallback entirely)
3. **Phase 2: live trading** — connect IBKR broker to execute real trades when signals fire
4. **Native app** — user wants to move from web to native app eventually. Dashboard at gc101888.github.io/APIs/ is fine for now but keep native architecture in mind

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
