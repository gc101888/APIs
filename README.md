# Trading Engine

Automated trading signal detection and paper trading system — Phase 1.

Monitors @realDonaldTrump Truth Social posts in real-time, classifies them
using Google Gemini AI, and fires paper trades with calculated entry/stop/target levels.
No broker connection. No real money. Signals and hypothetical P&L tracking only.

**Live dashboard:** https://gc101888.github.io/APIs/

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     TRADING ENGINE v1.0                        │
│                  Phase 1 — Signal Detection                    │
└────────────────────────────────────────────────────────────────┘

  Truth Social                                       Supabase
  WebSocket Feed ──► Gemini Classifier ──────────►  posts table
  wss://...          (2.5-flash-lite)                classifications table
  account filter     conf < 0.75 → skip
       │             PERSONAL_NOISE → skip
       │             conf >= 0.75 → trade
       │                   │
       │                   ▼
       │             Paper Trader                    Supabase
       │             yfinance prices ─────────────►  signals table
       │             entry / stop / target
       │                   │
       │                   ├──► Telegram: 🚨 SIGNAL + TradingView link
       │                   │
       │             [every 5 min, max 4hr]
       │                   │
       │             Outcome Monitor                 Supabase
       │             re-fetch price ──────────────►  update outcome
       │             TARGET_HIT / STOP_HIT / TIME_STOP
       │                   │
       │                   └──► Telegram: ✅/❌/⏰ OUTCOME
       │
       └──► Every event ──► Telegram status
                            📡 POST DETECTED
                            🔍 CLASSIFIED

  Daily 17:00 UTC ──► Query Supabase ──► Telegram: 📊 DAILY SUMMARY
  GitHub Pages ──────────────────────────────────► Live dashboard UI
```

---

## Requirements

- Python 3.12+
- Google Gemini API key (free — aistudio.google.com)
- Supabase project (URL + anon key)
- Telegram bot token + chat ID

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/gc101888/APIs.git
cd APIs
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env   # fill in your API keys
```

### 3. Create Supabase tables

Run this SQL in your Supabase SQL editor:

```sql
create table posts (
  id          uuid primary key default gen_random_uuid(),
  post_id     text unique not null,
  posted_at   timestamptz not null,
  content     text,
  raw_json    jsonb,
  created_at  timestamptz default now()
);

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

create table signals (
  id           uuid primary key default gen_random_uuid(),
  post_id      text references posts(post_id),
  instrument   text,
  direction    text,
  entry_price  float,
  stop_price   float,
  target_price float,
  exit_price   float,
  outcome      text,   -- TARGET_HIT | STOP_HIT | TIME_STOP
  pnl_pct      float,
  created_at   timestamptz default now(),
  resolved_at  timestamptz
);

-- Enable anonymous read access for the dashboard
alter table posts          enable row level security;
alter table classifications enable row level security;
alter table signals        enable row level security;

create policy "anon read posts"           on posts          for select using (true);
create policy "anon read classifications" on classifications for select using (true);
create policy "anon read signals"         on signals        for select using (true);
```

---

## Running Test Mode

Test mode runs 3 simulated Trump posts through the full pipeline
without connecting to the live WebSocket. **Start here.**

```bash
python test_pipeline.py
```

Expected results:
| Post | Expected Category | Expected Action |
|---|---|---|
| China tariff threat | TARIFF_ESCALATION | Signal fired |
| PLTR mention | STOCK_MENTION | Signal fired |
| Happy Tuesday | PERSONAL_NOISE | Skipped |

> Requires `GEMINI_API_KEY`. Supabase and Telegram are optional for test mode.

---

## Running Live

```bash
python main.py
```

---

## Deploying to VPS (Ubuntu 24)

```bash
# On your VPS as root — one command does everything:
curl -fsSL https://raw.githubusercontent.com/gc101888/APIs/main/deploy/setup.sh | bash

# Fill in your API keys (script will prompt you if empty):
nano /opt/trading-engine/.env

# Run the test pipeline to confirm everything works:
cd /opt/trading-engine
sudo -u trading .venv/bin/python test_pipeline.py

# Start the live engine:
systemctl start trading-engine
systemctl status trading-engine

# Live logs:
journalctl -u trading-engine -f
```

---

## Signal Categories

| Category | Instruments | Direction |
|---|---|---|
| TARIFF_ESCALATION | ES, NQ, GLD | SELL |
| TARIFF_ROLLBACK | ES, NQ | BUY |
| TRADE_DEAL | ES, NQ | BUY |
| FED_CRITICISM | GLD, BTC | BUY |
| CRYPTO_ENDORSEMENT | BTC | BUY |
| STOCK_MENTION | Named ticker | BUY |
| ENERGY_POLICY | ES | varies |
| DEFENSE_POLICY | ES | varies |
| GEOPOLITICAL | GLD, ES | SELL |
| PERSONAL_NOISE | — | SKIP |

---

## Risk Parameters

Fixed 1:3 risk/reward on every signal:
- **Stop**: ±0.5% from entry
- **Target**: ±1.5% from entry  
- **Risk/reward**: 1:3
- **Monitoring**: poll every 5 minutes, 4-hour time stop
- **Outcomes**: `TARGET_HIT` | `STOP_HIT` | `TIME_STOP`

All outcomes are **hypothetical** — no real account connected.

---

## Notes

- `db_logging/` is named `db_logging` (not `logging`) to avoid shadowing Python's stdlib `logging` module.
- `PAPER_TRADE_ONLY=true` is a guard flag — no broker integration exists in Phase 1.
- All times are UTC.
