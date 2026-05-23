# TrumpTrader — Full Project Brief

> Complete project documentation for handoff to another developer or LLM.
> Covers strategy, architecture, all integrations, deployment, and code decisions.

---

## 1. What This System Does

TrumpTrader is a fully automated trading signal detection system (Phase 1 — paper trading only, no real broker connection).

**The core idea**: Donald Trump's Truth Social posts move markets instantaneously. When he posts about tariffs, a stock, crypto, or geopolitics, futures and equities react within seconds — before Reuters, Bloomberg, or any news wire picks it up. **Truth Social IS the instantaneous source**. The edge is being first.

The system:
1. Monitors Trump's Truth Social account via WebSocket 24/7
2. Every new post is immediately sent to Google Gemini AI for classification
3. If Gemini identifies a market-relevant signal (≥75% confidence), it generates a paper trade with entry, stop, and target levels
4. The trade is monitored every 5 minutes for up to 4 hours
5. Alerts are sent to a mobile Telegram bot throughout
6. Everything is logged to Supabase (PostgreSQL)
7. A live dashboard on GitHub Pages shows the full signal feed with TradingView charts

---

## 2. The Strategy

### Why Truth Social?

Reuters and Bloomberg are **slower** than Truth Social. By the time a news wire reports "Trump threatens tariffs", the price has already moved. Truth Social is the primary source — we're reading directly from the horse's mouth, milliseconds after posting.

### Signal Categories

Gemini classifies each post into one of these categories:

| Category | Market Signal | Typical Instruments |
|---|---|---|
| TARIFF_ESCALATION | Risk-off: sell equities | ES, NQ (short) |
| TARIFF_ROLLBACK | Risk-on: buy equities | ES, NQ (long) |
| TRADE_DEAL | Risk-on | ES, NQ (long) |
| FED_CRITICISM | Weak dollar, safe haven | GLD, BTC (long) |
| CRYPTO_ENDORSEMENT | Crypto rally | BTC (long) |
| STOCK_MENTION | Individual stock attention | Named ticker |
| ENERGY_POLICY | Sector impact | ES, specific ETFs |
| DEFENSE_POLICY | Defense stocks | ES |
| GEOPOLITICAL | Risk-off | GLD, ES |
| PERSONAL_NOISE | No trade — skip | — |

### Risk Parameters (Fixed 1:3 R/R)

- **Entry**: market price at signal generation
- **Stop**: 0.5% against trade direction
- **Target**: 1.5% with trade direction
- **Risk/reward**: 1:3
- **Time stop**: 4 hours (if neither stop nor target hit)
- **Monitoring**: price checked every 5 minutes

### Outcome Labels (Honest — No Real Account)

Since we are NOT connected to a broker and NOT actually in a trade, the labels are factual about what the price did vs the levels:

- `TARGET_HIT` — price reached the target level within 4 hours
- `STOP_HIT` — price reached the stop level within 4 hours
- `TIME_STOP` — 4 hours elapsed with price between stop and target

These are **hypothetical outcomes** showing what would have happened. All P&L figures are hypothetical.

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      TRADING ENGINE v1.0                         │
│                   Phase 1 — Signal Detection                     │
└─────────────────────────────────────────────────────────────────┘

  Truth Social WebSocket (wss://truthsocial.com/api/v1/streaming/public)
       │
       │  Filter: account_id = 107780257626128497 (@realDonaldTrump)
       │  Dedup: skip seen post_ids
       │  Backoff: [1,2,4,8,16,60]s on disconnect
       ▼
  feeds/truthsocial_ws.py → on_post(post)
       │
       ├──► Supabase: posts table (log_post)
       ├──► Telegram: 📡 POST DETECTED
       │
       ▼
  classifier/classify.py → Gemini 2.5-flash-lite (REST API via aiohttp)
       │
       │  Confidence < 0.75 → skip
       │  Category = PERSONAL_NOISE → skip
       │  Otherwise → fire signal
       │
       ├──► Supabase: classifications table (log_classification)
       ├──► Telegram: 🔍 CLASSIFIED
       │
       ▼
  signals/paper_trade.py → PaperTrader
       │
       │  1. Fetch entry price (yfinance)
       │  2. Calculate stop (±0.5%) and target (±1.5%)
       │  3. Log signal to Supabase
       │  4. Alert Telegram with TradingView chart link
       │  5. Start monitoring loop (every 5 min, max 4hr)
       │
       ├──► Supabase: signals table (log_signal)
       ├──► Telegram: 🚨 SIGNAL FIRED + 📈 View Live Chart
       │
       ▼
  Outcome Monitor (asyncio background task)
       │
       │  Poll price every 5 min
       │  TARGET_HIT: price >= target (BUY) or <= target (SELL)
       │  STOP_HIT: price <= stop (BUY) or >= stop (SELL)
       │  TIME_STOP: 4 hours elapsed
       │
       ├──► Supabase: signals.outcome, exit_price, pnl_pct
       └──► Telegram: ✅ TARGET HIT / ❌ STOP HIT / ⏰ TIME STOP

  Daily 17:00 UTC ──► Supabase query ──► Telegram: 📊 DAILY SUMMARY

  GitHub Pages ──────────────────────────────────► Live dashboard UI
  (gc101888.github.io/APIs)
```

---

## 4. File Structure

```
APIs/
├── main.py                    # Entry point (production)
├── test_pipeline.py           # Test with 3 simulated posts
├── requirements.txt
├── .env                       # All secrets (not committed)
├── .env.example               # Template
│
├── feeds/
│   └── truthsocial_ws.py      # WebSocket feed
│
├── classifier/
│   └── classify.py            # Gemini AI classifier
│
├── signals/
│   └── paper_trade.py         # Signal generation + outcome monitor
│
├── alerts/
│   └── telegram.py            # Telegram bot alerts
│
├── db_logging/
│   └── supabase_logger.py     # Supabase async logger
│
├── deploy/
│   ├── setup.sh               # Ubuntu 24 VPS setup script
│   └── trading-engine.service # Systemd unit file
│
└── docs/
    ├── index.html             # GitHub Pages dashboard UI
    └── PROJECT_BRIEF.md       # This document
```

---

## 5. All Integrations

### 5.1 Truth Social WebSocket

**File**: `feeds/truthsocial_ws.py`

**Endpoint**: `wss://truthsocial.com/api/v1/streaming/public`

**Why**: Truth Social uses the Mastodon API. The streaming endpoint delivers events in real-time over WebSocket. No polling needed. Each `update` event contains a post JSON. We filter client-side for Trump's account ID.

**Account ID**: `107780257626128497` (@realDonaldTrump)

**Auth**: Optional `access_token` in headers. Works without authentication for public accounts (public streaming endpoint).

**Reconnection**: Exponential backoff [1,2,4,8,16,60]s. After 60s it stays at 60s intervals.

**Deduplication**: Set of seen `post_id`s in memory to prevent double-processing on reconnect.

**Key logic**:
```python
# Filter by account ID
if str(status.get("account", {}).get("id")) != str(self.account_id):
    return

# Dedup
if post_id in self._seen_ids:
    return
self._seen_ids.add(post_id)
```

---

### 5.2 Google Gemini AI Classifier

**File**: `classifier/classify.py`

**Model**: `gemini-2.5-flash-lite` (free tier)

**Why Gemini, not Claude?**: The sandbox environment has SSL certificate issues with gRPC (used by the google-generativeai SDK and Anthropic SDK). We use the Gemini REST API directly via `aiohttp` to bypass gRPC entirely. On a real VPS, either the SDK or direct REST works.

**API**: Direct HTTP POST — no SDK:
```
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={API_KEY}
```

**Why this model?**: Free tier. Tested alternatives:
- `gemini-1.5-flash` → 404 (deprecated)
- `gemini-2.0-flash` → 429 with limit:0 (no free quota on this project)
- `gemini-2.5-flash-lite` ✅ Works, fast, free tier available

**System prompt**: Instructs Gemini to return ONLY valid JSON with category, confidence, direction, tickers, instruments, and reasoning. No markdown, no explanation.

**Temperature**: 0.0 (deterministic, consistent classifications)

**Retry**: On JSON parse failure, retries once with the same content.

**Confidence threshold**: 0.75 (75%) — below this, signal is skipped.

**PERSONAL_NOISE**: Always skipped regardless of confidence.

**Tested results** (3/3 correct at 95% confidence):
- "China tariffs" → TARIFF_ESCALATION, SELL, NQ
- "PLTR incredible job" → STOCK_MENTION, BUY, PLTR
- "Happy Tuesday" → PERSONAL_NOISE, NONE, skipped

---

### 5.3 yfinance (Price Data)

**File**: `signals/paper_trade.py`

**Why**: Free, no API key required. Yahoo Finance data.

**Limitation**: ~15-minute delay for free tier. Fine for paper trading price fetching at signal time and outcome monitoring (we're checking whether the price would have hit stop/target over a 4-hour window).

**Limitation on VPS**: Works fine. In the development sandbox, outbound connections to Yahoo Finance are blocked (403). On a real VPS this works normally.

**Instrument mapping**:
```python
INSTRUMENT_MAP = {
    "NQ": "NQ=F",      # Nasdaq futures
    "ES": "ES=F",      # S&P 500 futures
    "GLD": "GLD",      # Gold ETF
    "BTC": "BTC-USD",  # Bitcoin
    "PLTR": "PLTR",    # Palantir
    # ...etc
}
```

**Future upgrade**: Polygon.io ($29/month) gives real-time tick-by-tick data for all instruments via WebSocket. This is the recommended upgrade for production.

---

### 5.4 Supabase (Database)

**File**: `db_logging/supabase_logger.py`

**Project URL**: `https://hhnkojvtecsighomybyl.supabase.co`

**Why**: Managed PostgreSQL, free tier, REST API, works well with Python.

**Auth**: Anon/public key (read-only for the dashboard). The service key is used for writes from the trading engine.

**Three tables**:

```sql
-- posts: one row per Trump post
create table posts (
  id         uuid primary key default gen_random_uuid(),
  post_id    text unique not null,   -- Truth Social post ID
  posted_at  timestamptz not null,
  content    text,
  raw_json   jsonb,
  created_at timestamptz default now()
);

-- classifications: AI analysis of each post
create table classifications (
  id          uuid primary key default gen_random_uuid(),
  post_id     text references posts(post_id),
  category    text,
  confidence  float,
  tickers     text[],
  direction   text,        -- BUY | SELL | NONE
  instruments text[],
  reasoning   text,
  trade_fired boolean default false,
  created_at  timestamptz default now()
);

-- signals: paper trades generated from classifications
create table signals (
  id           uuid primary key default gen_random_uuid(),
  post_id      text references posts(post_id),
  instrument   text,
  direction    text,
  entry_price  float,
  stop_price   float,
  target_price float,
  exit_price   float,      -- price when outcome was determined
  outcome      text,       -- TARGET_HIT | STOP_HIT | TIME_STOP
  pnl_pct      float,      -- hypothetical P&L percentage
  created_at   timestamptz default now(),
  resolved_at  timestamptz
);
```

**RLS (Row Level Security)**: Required for dashboard to read data anonymously:
```sql
alter table posts          enable row level security;
alter table classifications enable row level security;
alter table signals        enable row level security;

create policy "anon read posts"           on posts          for select using (true);
create policy "anon read classifications" on classifications for select using (true);
create policy "anon read signals"         on signals        for select using (true);
```

**Async writes**: All Supabase writes run in `asyncio.to_thread()` (the Python Supabase client is synchronous) with 3-retry logic and 1s delay between retries.

---

### 5.5 Telegram Bot

**File**: `alerts/telegram.py`

**Bot token**: `8638633345:AAFAp2YXnCR7eJrgo4oaxmTr5WxHekk9uBw`

**Chat ID**: `412222888`

**Why**: Free, instant mobile notifications. Perfect for an on-the-go trader who wants to tap their phone the instant Trump posts.

**7 alert types**:

| Method | Trigger | Contains |
|---|---|---|
| `send_startup` | Engine starts | Confirmation message |
| `send_post_detected` | New Trump post | First 200 chars of post |
| `send_classification` | Gemini result | Category, direction, confidence, reasoning |
| `send_signal` | Signal fired | Instrument, entry/stop/target, TradingView link |
| `send_outcome` | Monitoring resolves | TARGET HIT / STOP HIT / TIME STOP, P&L |
| `send_daily_summary` | 17:00 UTC daily | Win rate, total signals, P&L |
| `send_error` | Fatal errors | Error message |

**TradingView links**: Every `send_signal` and `send_outcome` message includes a one-tap deep link to the live chart:
```
https://www.tradingview.com/chart/?symbol=CME_MINI:NQ1!
```

**Library**: `python-telegram-bot` async. All sends use `parse_mode="HTML"`.

---

### 5.6 TradingView (Live Charts)

**How it's used**: Two ways:
1. **Dashboard embed** — TradingView mini symbol overview widget (free, real-time) embedded in the GitHub Pages dashboard
2. **Deep links** — Every Telegram signal alert contains a one-tap link to the full TradingView chart

**Symbol mappings**:
```python
TV_SYMBOL_MAP = {
    "NQ": "CME_MINI:NQ1!",       # Nasdaq E-mini futures
    "ES": "CME_MINI:ES1!",       # S&P 500 E-mini futures
    "GLD": "AMEX:GLD",           # Gold ETF
    "BTC": "BINANCE:BTCUSDT",    # Bitcoin
    "AAPL": "NASDAQ:AAPL",
    "PLTR": "NASDAQ:PLTR",
    "TSLA": "NASDAQ:TSLA",
    # ...14 instruments total
}
```

**Why TradingView**: Free embedded widgets show real-time data. The widget auto-updates in the browser. Clicking the "expand" icon on any widget opens the full interactive chart on tradingview.com.

---

### 5.7 GitHub Pages (Dashboard)

**File**: `docs/index.html`

**URL**: `https://gc101888.github.io/APIs/`

**How to enable**: In GitHub repo settings → Pages → Source: Deploy from branch `main` (or the working branch), folder `/docs`.

**Design**: Light theme, Twitter/X-style post feed, modern card design.

**Features**:
- Stats bar: total signals, target hits, stop hits, open, win rate, hypothetical P&L
- Live post feed: each card shows the Trump post, AI classification, and signal if fired
- Signal cards: entry/stop/target levels, outcome badge, one-tap TradingView link
- TradingView chart sidebar: real-time mini chart for NQ/ES/BTC/GLD
- Open signals sidebar: active positions with live chart links
- Auto-refreshes Supabase data every 30 seconds
- Mobile responsive

**Data source**: Fetches directly from Supabase REST API using the anon (public) key. No server needed.

---

## 6. Environment Variables

All in `.env`:

```bash
# Truth Social
TRUTH_SOCIAL_ACCOUNT_ID=107780257626128497
TRUTH_SOCIAL_ACCESS_TOKEN=      # Optional — leave blank for public streaming

# Google Gemini (free — aistudio.google.com)
GEMINI_API_KEY=AIzaSyAlCh3iCve6RFFhsSxl8amFdu6CuN2TVGM

# Supabase
SUPABASE_URL=https://hhnkojvtecsighomybyl.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...  # anon key

# Telegram
TELEGRAM_BOT_TOKEN=8638633345:AAFAp2YXnCR7eJrgo4oaxmTr5WxHekk9uBw
TELEGRAM_CHAT_ID=412222888

# System
LOG_LEVEL=INFO
PAPER_TRADE_ONLY=true
```

---

## 7. Key Code Decisions

### Why no Claude SDK / Anthropic API?

The development sandbox (and some VPS environments) have SSL certificate chain issues with gRPC. Both the Anthropic SDK and Google's `google-generativeai` SDK use gRPC, which fails with `CERTIFICATE_VERIFY_FAILED: self signed certificate in certificate chain`.

**Solution**: Use Google Gemini via direct HTTP REST calls (`aiohttp`). This bypasses gRPC entirely. The REST endpoint works perfectly.

### Why Gemini 2.5-flash-lite specifically?

Tested in order:
- `gemini-1.5-flash` → 404 (model deprecated/removed)
- `gemini-2.0-flash` → 429 with `limit:0` (free tier quota = 0 for this model on this API project)
- `gemini-2.5-flash-lite` → ✅ Works, fast, free tier available

### Why `db_logging/` not `logging/`?

Python has a stdlib module called `logging`. A directory called `logging/` would shadow it and break all imports of `import logging` throughout the codebase.

### Why `asyncio.to_thread()` for Supabase?

The Python Supabase client (`supabase-py`) is synchronous. Running it directly in an async event loop would block the event loop. `asyncio.to_thread()` runs it in a thread pool, keeping the event loop free.

### Why outcome monitoring instead of a one-shot 2hr check?

The original design checked price once after 2 hours. This is inaccurate because:
- The stop might have been hit after 30 minutes, then price recovered to target by 2hr
- The 2hr check would record the wrong outcome

The monitoring loop polls every 5 minutes and exits immediately when stop or target is hit, recording the first hit.

### Why fixed 1:3 risk/reward?

Simplicity and consistency. A 1:3 R/R means the system only needs to be right ~25% of the time to break even. Trump's market-moving posts tend to have strong directional moves when they happen — the 1.5% target is realistic for major news.

---

## 8. Deployment

### VPS Requirements

- Ubuntu 24.04 LTS
- Python 3.12+
- 512MB RAM minimum
- Outbound internet (Truth Social WS, Gemini API, Yahoo Finance, Supabase, Telegram)

### Deployment Steps

```bash
# 1. SSH into your VPS as root

# 2. One command to set everything up
curl -fsSL https://raw.githubusercontent.com/gc101888/APIs/main/deploy/setup.sh | bash
# Creates: trading user, /opt/trading-engine/, venv, installs all deps

# 3. Copy .env with your credentials
nano /opt/trading-engine/.env

# 4. Enable and start
systemctl enable trading-engine
systemctl start trading-engine

# 5. Check status
systemctl status trading-engine
journalctl -u trading-engine -f
```

### Systemd Service

File: `deploy/trading-engine.service`

Key security settings:
- `NoNewPrivileges=yes`
- `PrivateTmp=yes`
- `RestartSec=10` (auto-restart on crash)

---

## 9. GitHub Pages Dashboard Setup

1. Push code to `main` branch (or merge feature branch)
2. GitHub repo → Settings → Pages
3. Source: "Deploy from a branch"
4. Branch: `main` (or your branch), Folder: `/docs`
5. Save — GitHub deploys automatically
6. URL: `https://gc101888.github.io/APIs/`

**IMPORTANT**: You must run the Supabase SQL from Section 5.4 to create the tables and set up RLS before the dashboard will show data.

---

## 10. Testing

### Test Pipeline (no live WebSocket needed)

```bash
python test_pipeline.py
```

Sends 3 simulated posts through the full pipeline:
1. China tariff post → should classify as TARIFF_ESCALATION, SELL, NQ ← signal fired
2. PLTR mention → STOCK_MENTION, BUY, PLTR ← signal fired
3. "Happy Tuesday" → PERSONAL_NOISE ← skipped

Expected output confirms Gemini is working and signal logic is correct.

Supabase and Telegram are **optional** for test mode (silently skipped if env vars missing).

---

## 11. Current Status (Phase 1)

### Done ✅
- [x] Truth Social WebSocket feed with reconnect and dedup
- [x] Gemini AI classifier (tested, working, 3/3 correct)
- [x] Paper trader with entry/stop/target calculation
- [x] Outcome monitoring loop (5-min polls, 4hr time stop)
- [x] Supabase logging (posts, classifications, signals)
- [x] Telegram alerts (7 alert types, TradingView links)
- [x] GitHub Pages dashboard UI (live feed, TradingView chart, stats)
- [x] VPS deployment scripts (setup.sh + systemd service)
- [x] Test pipeline
- [x] Honest outcome labels (TARGET_HIT / STOP_HIT / TIME_STOP)

### Still Needed 🔄
- [ ] Run the Supabase SQL to create the tables
- [ ] Deploy to a VPS
- [ ] Enable GitHub Pages on the repo
- [ ] Supabase RLS policies (see SQL in README)
- [ ] Test on live VPS with real Trump posts

### Future Enhancements (Phase 2)
- [ ] Real-time price feed: Polygon.io ($29/month) for tick-by-tick WebSocket data — needed for accurate stop/target monitoring
- [ ] Expand sources: Trump speeches, press conferences (YouTube live transcription), official White House statements
- [ ] More instruments: Crude oil (CL), Treasury bonds (ZN), DXY (dollar index)
- [ ] News source disambiguation: detect if a post is a reaction to prior news vs original
- [ ] Backtesting: run historical Trump posts through the classifier to validate signal quality
- [ ] Position sizing: Kelly criterion or fixed fractional
- [ ] Real broker integration (Interactive Brokers, Alpaca) — Phase 3

---

## 12. Repository

- **Repo**: `gc101888/APIs` (GitHub)
- **Dev branch**: `claude/trading-engine-phase-1-1ByHz`
- **Language**: Python 3.12 (async throughout)
- **Key dependencies**: `aiohttp`, `websockets`, `python-telegram-bot`, `supabase`, `yfinance`, `python-dotenv`

---

## 13. Credentials Summary

| Service | Credential | Value |
|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | `AIzaSyAlCh3iCve6RFFhsSxl8amFdu6CuN2TVGM` |
| Supabase | `SUPABASE_URL` | `https://hhnkojvtecsighomybyl.supabase.co` |
| Supabase | `SUPABASE_KEY` | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` (anon key) |
| Telegram | `TELEGRAM_BOT_TOKEN` | `8638633345:AAFAp2YXnCR7eJrgo4oaxmTr5WxHekk9uBw` |
| Telegram | `TELEGRAM_CHAT_ID` | `412222888` |
| Truth Social | `TRUTH_SOCIAL_ACCOUNT_ID` | `107780257626128497` |

---

*Last updated: 2026-05-22*
