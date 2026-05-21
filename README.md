# Trading Engine

Automated trading signal detection and paper trading system — Phase 1.

Monitors @realDonaldTrump Truth Social posts in real-time, classifies them
using Claude AI, and fires paper trades with calculated entry/stop/target levels.
No broker connection. No real money. Signals and hypothetical P&L tracking only.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     TRADING ENGINE v1.0                        │
│                  Phase 1 — Signal Detection                    │
└────────────────────────────────────────────────────────────────┘

  Truth Social                                       Supabase
  WebSocket Feed ──► Claude Classifier ──────────►  posts table
  wss://...          (Sonnet 4.6)                    classifications table
  account filter     conf < 0.75 → skip
       │             PERSONAL_NOISE → skip
       │             conf >= 0.75 → trade
       │                   │
       │                   ▼
       │             Paper Trader                    Supabase
       │             yfinance prices ─────────────►  signals table
       │             entry / stop / target
       │                   │
       │                   ├──► Telegram: 🚨 SIGNAL FIRED
       │                   │
       │             [+2 hours]
       │                   │
       │             Outcome Check                   Supabase
       │             re-fetch price ──────────────►  update outcome
       │             WIN / LOSS / PARTIAL
       │                   │
       │                   └──► Telegram: ✅/❌/⏰ OUTCOME
       │
       └──► Every event ──► Telegram status
                            📡 POST DETECTED
                            🔍 CLASSIFIED

  Daily 17:00 UTC ──► Query Supabase ──► Telegram: 📊 DAILY SUMMARY
```

---

## Requirements

- Python 3.12+
- Anthropic API key
- Supabase project (URL + anon key)
- Telegram bot token + chat ID

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/gc101888/trading-engine.git
cd trading-engine
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
  price_2hr    float,
  outcome      text,
  pnl_pct      float,
  created_at   timestamptz default now(),
  resolved_at  timestamptz
);
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

> Requires `ANTHROPIC_API_KEY`. Supabase and Telegram are optional for test mode.

---

## Running Live

```bash
python main.py
```

---

## Deploying to VPS (Ubuntu 24)

```bash
# On your VPS as root:
curl -O https://raw.githubusercontent.com/gc101888/trading-engine/main/deploy/setup.sh
chmod +x setup.sh
./setup.sh

# Edit the env file with your API keys:
nano /opt/trading-engine/.env

# Start the service:
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
- **Outcome check**: 2 hours after signal

---

## Notes

- `db_logging/` is named `db_logging` (not `logging`) to avoid shadowing Python's stdlib `logging` module.
- `PAPER_TRADE_ONLY=true` is a guard flag — no broker integration exists in Phase 1.
- All times are UTC.
