# TrumpTrader — Full Project Brief

Complete handoff document. Everything needed to bring a new developer or LLM up to speed instantly.

---

## What This System Does

Monitors @realDonaldTrump's Truth Social posts in real-time. The moment he posts, an AI classifies it for market relevance, generates a paper trade signal with entry/stop/target levels, monitors the outcome, and sends instant Telegram alerts with live TradingView chart links.

**The edge:** Truth Social is the instantaneous source. Reuters and Bloomberg report AFTER Trump posts — by then the price has already moved. We read directly from the source before anyone else.

**Phase 1:** Paper trading only — no real broker connected. All P&L is hypothetical. Designed to prove the signal quality before going live.

---

## Current Status (as of May 2026)

### Done
- Truth Social WebSocket feed (24/7 monitoring with auto-reconnect)
- Gemini AI classifier (tested, 3/3 correct at 95% confidence)
- Paper trader with entry/stop/target calculation
- Outcome monitoring loop (every 5 min, 4hr time stop)
- Supabase database (tables created, RLS configured)
- Telegram alerts (7 alert types, TradingView deep links)
- GitHub Pages dashboard (live at gc101888.github.io/APIs/)
- Real-time price feed: Binance WebSocket (crypto) + Alpaca (stocks) + yfinance fallback
- VPS deploy script (Railway or Ubuntu VPS)
- CI fixed (old API list validator disabled)

### Still Needed
- Add Binance API keys to Railway env vars
- Sign up for Alpaca (free) and add keys
- Deploy engine to Railway (not running yet — no signals firing)
- IBKR paper account for NQ/ES futures prices

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
         ├──► Telegram: POST DETECTED
         ▼
classifier/classify.py
  - Google Gemini 2.5-flash-lite (free tier)
  - Direct REST API via aiohttp (no SDK — bypasses gRPC SSL issues)
  - Returns: category, confidence, direction, instruments, reasoning
  - Confidence < 0.75 → skip
  - Category = PERSONAL_NOISE → skip
         │
         ├──► Supabase: classifications table
         ├──► Telegram: CLASSIFIED
         ▼
signals/paper_trade.py
  - Fetch entry price via feeds/price_feed.py
  - Calculate stop (±0.5%) and target (±1.5%)
  - Log signal to Supabase
  - Alert Telegram with TradingView chart link
  - Start monitoring loop
         │
         ├──► Supabase: signals table
         ├──► Telegram: SIGNAL FIRED + TradingView link
         ▼
Outcome Monitor (asyncio background task)
  - Poll price every 5 minutes
  - TARGET_HIT / STOP_HIT / TIME_STOP (4hr)
         │
         ├──► Supabase: update outcome, exit_price, pnl_pct
         └──► Telegram: TARGET HIT / STOP HIT / TIME STOP

Daily 17:00 UTC → Supabase query → Telegram DAILY SUMMARY

GitHub Pages dashboard (docs/index.html)
  - Reads Supabase via REST API every 30s
  - Shows post feed, signals, TradingView charts, stats
```

---

## Price Feed Architecture

```
feeds/price_feed.py — unified get_price(instrument) function

Priority routing:
1. Binance WebSocket (instantaneous, runs permanently in background)
   Covers: BTC, ETH, BNB, SOL and any USDT pair
   Keys: BINANCE_API_KEY, BINANCE_API_SECRET

2. Alpaca REST API (real-time, free tier)
   Covers: SPY, QQQ, AAPL, PLTR, TSLA, NVDA, MSFT, AMZN, META, DJT, GLD
   Keys: ALPACA_API_KEY, ALPACA_API_SECRET

3. yfinance (15-min delay fallback, no key needed)
   Covers: NQ=F, ES=F, and anything else
   Used when Binance and Alpaca don't have the instrument

Future: IBKR API for real-time NQ/ES futures
```

---

## File Structure

```
APIs/
├── main.py                     Entry point (production)
├── test_pipeline.py            Test with 3 simulated posts (no live WS)
├── requirements.txt
├── .env                        All secrets (not committed)
├── .env.example                Template
│
├── feeds/
│   ├── truthsocial_ws.py       Truth Social WebSocket client
│   └── price_feed.py           Unified price feed (Binance/Alpaca/yfinance)
│
├── classifier/
│   └── classify.py             Gemini AI classifier
│
├── signals/
│   └── paper_trade.py          Signal generation + outcome monitoring
│
├── alerts/
│   └── telegram.py             Telegram bot (7 alert types)
│
├── db_logging/
│   └── supabase_logger.py      Supabase async writer
│
├── deploy/
│   ├── setup.sh                Ubuntu 24 VPS one-command setup
│   └── trading-engine.service  Systemd unit file
│
└── docs/
    ├── index.html              GitHub Pages dashboard UI
    └── PROJECT_BRIEF.md        This document
```

---

## Environment Variables

```bash
# Truth Social
TRUTH_SOCIAL_ACCOUNT_ID=107780257626128497
TRUTH_SOCIAL_ACCESS_TOKEN=          # optional, leave blank

# Google Gemini (free — aistudio.google.com)
GEMINI_API_KEY=AIzaSyAlCh3iCve6RFFhsSxl8amFdu6CuN2TVGM

# Supabase (tables already created)
SUPABASE_URL=https://hhnkojvtecsighomybyl.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...  # anon key

# Telegram
TELEGRAM_BOT_TOKEN=8638633345:AAFAp2YXnCR7eJrgo4oaxmTr5WxHekk9uBw
TELEGRAM_CHAT_ID=412222888

# Binance (real-time crypto — read-only key)
BINANCE_API_KEY=                    # add after generating in Binance app
BINANCE_API_SECRET=

# Alpaca (real-time US stocks — free, alpaca.markets)
ALPACA_API_KEY=                     # add after signing up
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

### Categories & Direction

| Category | Direction | Instruments |
|---|---|---|
| TARIFF_ESCALATION | SELL | ES, NQ |
| TARIFF_ROLLBACK | BUY | ES, NQ |
| TRADE_DEAL | BUY | ES, NQ |
| FED_CRITICISM | BUY | GLD, BTC |
| CRYPTO_ENDORSEMENT | BUY | BTC |
| STOCK_MENTION | BUY | Named ticker |
| ENERGY_POLICY | varies | ES |
| DEFENSE_POLICY | varies | ES |
| GEOPOLITICAL | SELL | GLD, ES |
| PERSONAL_NOISE | SKIP | — |

### Risk Parameters (fixed 1:3 R/R)

- Stop: ±0.5% from entry
- Target: ±1.5% from entry
- Monitor: every 5 minutes
- Time stop: 4 hours
- Outcomes: TARGET_HIT / STOP_HIT / TIME_STOP (all hypothetical)

---

## AI Classifier Detail

- **Model:** gemini-2.5-flash-lite (free tier)
- **API:** Direct REST via aiohttp — NOT the Google SDK
- **Why no SDK:** gRPC SSL fails in sandbox/some VPS environments. Direct REST bypasses this entirely.
- **Endpoint:** `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent`
- **Temperature:** 0.0 (deterministic)
- **Retry:** once on JSON parse failure
- **Tested:** 3/3 correct classifications at 95%+ confidence

---

## Dashboard

**URL:** https://gc101888.github.io/APIs/

**Tech:** Single HTML file, no framework, vanilla JS + CSS
- Fetches from Supabase REST API every 30 seconds
- TradingView mini chart widget (free, real-time): NQ→QQQ, ES→SPY, BTC→BTCUSDT, GLD→GLD
- Post feed: Trump post + AI classification + signal card + TradingView link
- Stats bar: total signals, target hits, stop hits, win rate, hypothetical P&L
- Mobile responsive

**Note:** CME futures symbols (NQ1!, ES1!) require paid TradingView. Using QQQ/SPY as free proxies in the widget. Telegram alerts link directly to the correct futures chart.

---

## Deployment

### Railway (recommended — easiest)

1. Go to railway.app → New Project → Deploy from GitHub → gc101888/APIs
2. Add all env vars from the list above
3. Set start command: `python main.py`
4. Deploy — done

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
| Truth Social feed | Free | Built, not deployed |
| Binance prices | Free | Built, needs API keys |
| Alpaca prices | Free | Built, needs sign-up |
| Railway (engine host) | ~$5/month | Not deployed yet |
| IBKR (futures prices + live trading later) | Free API | Not set up yet |

**Total to go live: $5/month**

---

## What's Next

1. Add Binance API keys to env (user has account, just needs to generate key)
2. Sign up for Alpaca (free, 2 min) — alpaca.markets
3. Deploy to Railway ($5/month) — connect GitHub, paste env vars, done
4. Open IBKR paper account (free) for NQ/ES futures prices
5. Rebuild dashboard in Lovable (optional — current one works)
6. Phase 2: connect IBKR for live trading

---

## Key Technical Decisions

| Decision | Reason |
|---|---|
| Gemini not Claude for AI | gRPC SSL fails in sandbox; REST API works everywhere |
| gemini-2.5-flash-lite | Only free model with quota on this project |
| aiohttp not SDK | Bypasses gRPC entirely |
| db_logging not logging | Would shadow Python stdlib logging module |
| asyncio.to_thread for Supabase | supabase-py is sync; can't block the event loop |
| Monitoring loop not one-shot | One-shot 2hr check gives wrong outcome if price whipsaws |
| QQQ/SPY not NQ/ES in widget | CME futures need paid TradingView |
| TARGET_HIT/STOP_HIT not WIN/LOSS | Honest — not actually in a trade |
