# Lumibot — Technical deep-dive for iguanatrader

**Date:** 2026-04-27
**Repo:** https://github.com/Lumiwealth/lumibot
**Docs:** https://lumibot.lumiwealth.com/
**Maintainer:** Lumiwealth (corporation with a commercial product layered on top)
**Default branch:** `dev`
**Latest activity:** 2026-04-26 (alive, regular commits)
**Stars:** 1,366
**License:** ⚠️ **GPL-3.0** (not Apache-2.0 as the previous research stated — important correction)

---

## 1. Quick verdict (TL;DR)

Lumibot **is functionally** the closest competitor to the iguanatrader MVP. It covers IBKR, backtest↔live parity, a well-designed Strategy lifecycle, and pioneering LLM-in-backtest integration. **But the GPL-3.0 license rules it out as a base for a closed commercial fork** — and that is exactly the trajectory iguanatrader contemplates post-MVP. Useful as an **API and pattern reference**, not as a code base.

---

## 2. Overall architecture

Four main components:

| Component | Role |
|---|---|
| `Strategy` | The user's class. All the logic lives here. Inherits from `lumibot.strategies.strategy.Strategy`. |
| `Broker` | Connection layer. Implementations: `Alpaca`, `InteractiveBrokers`, `Schwab`, `Tradier`, `Ccxt` (crypto), `Tradovate`, etc. |
| `Backtesting` | Historical simulation engine. Variants by data source: `YahooDataBacktesting`, `PolygonDataBacktesting`, `DataBentoBacktesting`. |
| `Trader` | Orchestrator. Loads strategies, spins up the loop, handles crash-recovery. |

**Architectural model**: event-driven (not vectorized). The same `Strategy` runs in backtest and in live; the differences are absorbed by `Broker` and `Backtesting`.

---

## 3. `Strategy` interface — the pattern to steal

### Minimal skeleton

```python
from datetime import datetime
from lumibot.backtesting import YahooDataBacktesting
from lumibot.brokers import Alpaca
from lumibot.strategies.strategy import Strategy
from lumibot.traders import Trader

class MyStrategy(Strategy):
    parameters = {
        "symbol": "SPY",
        "quantity": 1,
        "side": "buy",
    }

    def initialize(self):
        self.sleeptime = "180M"  # every 180 minutes

    def on_trading_iteration(self):
        symbol = self.parameters["symbol"]
        order = self.create_order(symbol, self.parameters["quantity"], self.parameters["side"])
        self.submit_order(order)
```

### Full lifecycle (12 hooks)

| Hook | When it fires |
|---|---|
| `initialize()` | Once at startup |
| `before_starting_trading()` | Before the day's first `on_trading_iteration` |
| `before_market_opens()` | Pre-market |
| `on_trading_iteration()` | Main loop (every `sleeptime`) |
| `before_market_closes()` | Pre-close |
| `after_market_closes()` | Post-close |
| `on_new_order(order)` | Confirmation that an order was created |
| `on_partially_filled_order(order, qty)` | Partial fill |
| `on_filled_order(order)` | Full fill |
| `on_canceled_order(order)` | Cancellation |
| `on_parameters_updated()` | Dynamic change to `parameters` (hot-reload) |
| `on_bot_crash()` / `on_abrupt_closing()` | Error handling and abrupt shutdown |

### Order API

`create_order()`, `submit_order()`, `submit_orders()` (batch), `cancel_order()`, `cancel_open_orders()`, `wait_for_order_execution()` (sync blocking), `wait_for_order_registration()`.

### Portfolio state

`get_position(symbol)`, `get_positions()`, `get_cash()`, `adjust_cash()`, `deposit_cash()`, `withdraw_cash()`.

**The good**: excellent separation of concerns. The user only needs to think about `on_trading_iteration` and the `on_*_order` callbacks. The backtest vs live difference is absorbed by the framework.

**The mediocre**: `sleeptime` as a string ("180M") is ergonomic but implies that the loop is NOT purely event-driven at the `Strategy` level — it's polling with sleep. The `Broker` does handle events, but the `Strategy` is sleeping between iterations. For an event-driven strategy (DonchianATR on tick/bar new), you have to poll or use `on_filled_order` as a proxy.

---

## 4. `Broker` abstraction — the other pattern to steal

```python
from lumibot.brokers import Alpaca, InteractiveBrokers

ALPACA_CONFIG = {"API_KEY": "...", "API_SECRET": "...", "PAPER": True}
broker = Alpaca(ALPACA_CONFIG)

# or
broker = InteractiveBrokers(IBKR_CONFIG)
```

**Key design**:
- One class per broker, all implementing the same implicit interface.
- `PAPER: True/False` switch in config — same object, different endpoint. **Pattern to copy literally in iguanatrader**.
- ENV vars `TRADING_BROKER` and `DATA_SOURCE` allow **separating** execution broker from data broker. Useful for using IBKR for fills + Polygon for data in backtest, for example.

**Available brokers** (2026):
- **Equity/options**: Alpaca, Interactive Brokers, Schwab, Tradier
- **Crypto**: Binance, Coinbase, Kraken, KuCoin (via CCXT wrapper)
- **Futures**: Tradovate, DataBento, Bitunix
- **Forex**: via existing broker integrations

---

## 5. Backtest engine

- **Same code** as live (the difference is absorbed by the injected `Broker`).
- **Event-based** (not vectorized): simulates iteration by iteration.
- **Slippage** modeled via the `TradingSlippage` entity.
- **Commissions** modeled via the `TradingFee` entity (per-order or percentage).
- **Data sources**: `YahooDataBacktesting` (free), `PolygonDataBacktesting` (premium), `DataBentoBacktesting` (premium futures), `AlpacaBacktesting` (data from the broker itself).
- **Cash management**: `adjust_cash()`, `deposit_cash()`, `withdraw_cash()` record external flows so the equity curve correctly reflects capital inflows/outflows.

```python
backtesting_start = datetime(2020, 1, 1)
backtesting_end = datetime(2020, 12, 31)

strategy.run_backtest(
    YahooDataBacktesting,
    backtesting_start,
    backtesting_end,
    parameters={"symbol": "SPY"},
)
```

**The good**: trivial API. The `run_backtest` method belongs to the Strategy class itself.

**The questionable**: I could not find a configurable parametric slippage model (5-15 bps small-cap / 1-3 bps large-cap as the iguanatrader plan requires). It needs to be verified in the code whether `TradingSlippage` allows that level of granularity or whether it's a fixed value.

---

## 6. Risk engine — **THE SERIOUS GAP**

**No built-in module for**:
- Risk caps (per-trade %, daily loss %, weekly loss %)
- Kill-switch
- Automatic drawdown protection
- Pre-trade checks that reject orders
- Position sizing based on ATR / volatility

All of the above is the **user's responsibility** inside `on_trading_iteration`. Lumibot only provides primitives: `get_cash`, `get_positions`, `cancel_open_orders`. If you want 2/5/15 caps, you implement them yourself.

**Implication for iguanatrader**: the `RiskEngine` that iguanatrader needs to write **is the main value-add over Lumibot**. Lumibot has engine + brokers + lifecycle; iguanatrader adds risk + approval + LLM observability.

---

## 7. AI/LLM integration — the surprise

Lumibot has integrated **LLM agents inside the backtest loop** with a notable pattern:

- The agents reason and call external tools **on every bar** during simulation.
- **Replay caching**: the first backtest run persists every LLM call; warm runs reuse the cache → deterministic and nearly free reruns.
- Support for **external MCP servers** as data sources / tools.
- "Same code for backtest and live" extends to the agents — the agent runs identically in both modes.

**This is GOLD for iguanatrader**: the "replay cache of LLM calls" pattern is exactly what you need so that a backtest with LLM-orchestrated routines is reproducible without paying tokens every time.

**Commercial product on top**: **BotSpot.trade** — "Build trading bots using natural language and AI" (LLM generates strategies). It's not agentic auto-trade, it's **LLM-as-codegen**.

---

## 8. HITL / approval gate — **does NOT exist**

There are no native hooks for human approval per trade. The natural insertion point would be to **intercept `submit_order()`** from the strategy and put a wait on an external signal there (Telegram, webhook, etc.). Lumibot doesn't provide it, but the lifecycle doesn't block it.

---

## 9. Persistence and configuration

- **`Variable Backup & Restore`**: documentation mentions persistence of Strategy variables between runs. Implementation not detailed in public docs — you'd have to look at the code.
- **Configuration**: dict passed to the Broker + ENV vars (`TRADING_BROKER`, `DATA_SOURCE`). Does not use pydantic/yaml natively.
- **`parameters` first-class** in Strategy + hot-reload via `on_parameters_updated()`. Good.

**Multi-tenancy**: NO. Lumibot assumes single-strategy single-broker single-user. For multi-tenant you'd have to wrap it in an external layer.

---

## 10. Lumiwealth — the commercial layer

Lumibot OSS (GPL-3.0) is the base. On top of it, Lumiwealth sells:

| Product | What it is |
|---|---|
| **BotSpot.trade** | SaaS platform where you describe the strategy in NL and an LLM generates and runs it. |
| **Algorithmic Trading course** | Paid course. |
| **Machine Learning for Trading course** | Paid course. |
| **Options Trading course** | Paid course. |

**Monetization model**: education-flywheel + premium SaaS on top of the OSS. Analogous to QuantStart/Jesse.

**Legal implication**: Lumiwealth can sell BotSpot because **they** are the authors of the GPL-3.0 OSS and maintain implicit dual-licensing. **A third party legally CANNOT do the same** without releasing the entire SaaS under GPL-3.0.

---

## 11. Governance and bus factor

- **Maintainer**: Lumiwealth (company). Estimated bus factor **medium**: you depend on the corp's survival, but not on a single individual.
- **Cadence**: regular commits in 2026.
- **Community**: small (~1.4k stars). Modest traction vs Lean (18.6k) or Freqtrade (30k).
- **Breaking-change policy**: default branch is `dev` → API stability release-to-release is not guaranteed.

---

## 12. **5 patterns to STEAL** for iguanatrader

1. **`Strategy` lifecycle with 12 hooks** — copy literally the `initialize` / `before_market_opens` / `on_trading_iteration` / `on_filled_order` separation. Clean and testable.
2. **`Broker` switch via config dict + `PAPER` flag** — same object, different endpoint. Adapt to `IBKR(config={'PAPER': True})` from day 1, avoid the dual-class `IbkrPaper` + `IbkrLive`.
3. **ENV vars `TRADING_BROKER` + `DATA_SOURCE`** — separation of execution broker vs data broker. Useful when using IBKR fills + Polygon historical data.
4. **Replay caching of LLM calls in backtest** — critical pattern for reproducibility. Implement in `CostMeter`: hash of the prompt → JSON cache; in backtest, read the cache; in live, call the real API and persist.
5. **`parameters` first-class + `on_parameters_updated()` hot-reload** — allows tuning DonchianATR via Telegram (`/set period 20`) without restarting the bot.

## 13. **3 anti-patterns to AVOID**

1. **GPL-3.0 license without dual-licensing** — blocks the commercial SaaS trajectory. iguanatrader should use **Apache-2.0 + Commons Clause** from the first commit.
2. **No built-in risk engine** — Lumibot leaves it to the user. iguanatrader must make it **mandatory and non-bypassable**: strategies propose, the `RiskEngine` filters/trims/rejects BEFORE the approval gate. Not opt-in.
3. **`sleeptime` polling as the main model** — Lumibot iterates by sleep. For iguanatrader (event-driven on bars/news/alerts), the correct model is asyncio + queues + event loop over IBKR streaming, not polling.

---

## 14. Honest verdict for iguanatrader

**Fork it?** **NO**. GPL-3.0 kills the closed commercial SaaS option. Even if iguanatrader started out as GPL-3.0 OSS too, you'd lose the optionality of changing the model without rewriting.

**Copy interfaces?** **YES, aggressively**. The `Strategy` lifecycle, the `Broker` config-switch, the LLM replay-cache pattern. These three patterns on their own already justify the deep-dive.

**Ignore it?** **NO**. BotSpot.trade is direct competition for iguanatrader's commercial trajectory; it must be studied.

**Operational decision for the PRD**: Lumibot stays as a **mandatory design reference** (link this document from `docs/architecture-decisions.md` ADR-001) and as a **competitor to watch** (not to replace — the per-trade approval gate + cost observability of the LLM stack itself remain gaps that Lumibot/BotSpot do not cover).
