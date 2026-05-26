# Freqtrade — Technical deep-dive for iguanatrader

**Date:** 2026-04-27
**Repo:** https://github.com/freqtrade/freqtrade
**Docs:** https://www.freqtrade.io/en/stable/
**Maintainer:** Community + Matthias Voppichler (lead)
**Default branch:** `develop`
**Last activity:** 2026-04-27 (commits today)
**Stars:** 49,440 ⚠️ (prior research said 30k — by far the most popular in the ecosystem)
**License:** **GPL-3.0**

---

## 1. Quick verdict (TL;DR)

Freqtrade is **the richest source of patterns to steal** in the OSS ecosystem, even though it is crypto-only and GPL-3.0 (not usable as a base for iguanatrader). Three golden pillars: **(1)** the full Telegram command set (it is literally the UX iguanatrader needs), **(2)** the **Protections** system (built-in, modular, mandatory risk management), **(3)** the `dry-run` model from day 1.

**For iguanatrader**: copy the Telegram pattern **directly**, copy the Protections architecture **directly**, ignore the rest.

---

## 2. Telegram commands — the full catalog

Freqtrade exposes **~30 Telegram commands**, split into 5 categories. This is **the most complete catalog in the OSS ecosystem**.

### System
| Command | Args | Function |
|---|---|---|
| `/start` | — | Starts the trader |
| `/pause` (alias `/stopentry`) | — | Pauses new entries, keeps managing open trades |
| `/stop` | — | Stops the trader completely |
| `/reload_config` | — | Reloads the config without restarting the bot |
| `/show_config` | — | Shows part of the current config |
| `/logs` | `[limit]` | Last N log messages |
| `/help` | — | Help |
| `/version` | — | Bot version |

### Status & info
| Command | Args | Function |
|---|---|---|
| `/status` | `[trade_id]` | Lists open trades (all or a specific one) |
| `/status table` | — | Table of open trades with pending marker |
| `/order` | `<trade_id>` | List of orders for a trade |
| `/trades` | `[limit]` | Last N closed trades |
| `/count` | — | Open / available trades |
| `/locks` | — | Currently locked pairs |
| `/unlock` | `<pair or lock_id>` | Removes lock |
| `/marketdir` | `[long\|short\|even\|none]` | Shows/changes market direction |

### Trade modification
| Command | Args | Function | Restriction |
|---|---|---|---|
| `/forceexit` (alias `/fx`) | `<trade_id>` or `all` | Closes trade(s) ignoring `minimum_roi` | — |
| `/forcelong` | `<pair> [rate]` | Immediate buy | `force_entry_enable: true` |
| `/forceshort` | `<pair> [rate]` | Immediate short sell | Non-spot only, `force_entry_enable: true` |
| `/delete` | `<trade_id>` | Deletes trade from DB | Manual exchange handling |
| `/reload_trade` | `<trade_id>` | Reloads trade from exchange | Live only |
| `/cancel_open_order` (alias `/coo`) | `<trade_id>` | Cancels open order |

### Performance & finance
| Command | Args | Function |
|---|---|---|
| `/profit` | `[n]` (days) | P&L summary of closed trades |
| `/profit_long` / `/profit_short` | `[n]` | Same, long-only / short-only |
| `/performance` | — | P&L per pair (symbol) |
| `/balance` | `[full]` | Managed or full balance per currency |
| `/daily` | `[n=7]` | P&L per day over last N days |
| `/weekly` | `[n=8]` | P&L per week |
| `/monthly` | `[n=6]` | P&L per month |
| `/stats` (alias `/exits`, `/entries`) | — | Wins/losses per exit reason + holding durations |

### Pair management
| Command | Args | Function |
|---|---|---|
| `/whitelist` | `[sorted] [baseonly]` | Current whitelist |
| `/blacklist` | `[pair]` | Shows blacklist or adds a pair |

### Key mechanics
- **Custom keyboard buttons**: predefined commands as inline buttons (no args).
- **`authorized_users`**: list of authorized Telegram user IDs; rejects everyone else.
- **`notification_settings`**: granularity over which events fire notifications.
- **`/reload_config`**: hot-reload without restart — valuable pattern.

---

## 3. Mapping Freqtrade → iguanatrader (proposed set)

iguanatrader does not need all 30 commands. Recommended mapping:

| Freqtrade | iguanatrader equivalent | Function in iguanatrader |
|---|---|---|
| `/start` | `/start` | Starts routines (no trades — trades require approval) |
| `/stop` | `/stop` | Stops everything |
| `/pause` | `/pause` | Stops new proposals, keeps open positions |
| `/reload_config` | `/reload_config` | Hot-reload of risk caps, watchlist, etc. |
| — | **`/propose <strategy> <symbol>`** | Forces generation of a manual proposal (research mode) |
| `/forcelong` | **`/approve <proposal_id>`** | Approves a pending proposal (inline button) |
| — | **`/reject <proposal_id>`** | Rejects a proposal (inline button) |
| `/forceexit` | **`/forceexit <trade_id>`** | Closes open position (with confirmation) |
| `/status` | `/status` | Open positions + pending proposals |
| `/balance` | `/balance` | Cash + holdings + total equity |
| `/profit` | `/profit [days=1]` | P&L for the day/period |
| `/daily` | `/daily [n=7]` | P&L per day |
| `/weekly` | `/weekly [n=4]` | P&L per week |
| `/performance` | `/performance` | P&L per symbol |
| `/trades` | `/trades [limit=10]` | Last N closed trades |
| `/logs` | `/logs [limit=20]` | Last N log entries |
| — | **`/risk_status`** | Current state of risk caps (how much of the 5% daily, 15% weekly consumed) |
| — | **`/cost_today`** and `/cost_week` | Cumulative LLM cost |
| — | **`/halt`** | Activates kill-switch (writes `.killswitch` file) |
| — | **`/resume`** | Removes kill-switch |
| `/version` | `/version` | Bot version |
| `/help` | `/help` | Help |

**Total: ~17 commands**. Enough to cover the approval-gate flow + observability for iguanatrader.

**Inline buttons (Telegram callback queries)** for each proposal:
```
🟢 Approve (button) | 🔴 Reject (button) | ✏️ Modify (button)
```

**Same set over WhatsApp** via Hermes/Meta API. The `ApprovalChannel` layer translates the text-based command to the corresponding API.

---

## 4. `IStrategy` interface — vectorized (not event-driven)

Unlike Lumibot/Nautilus/Lean (event-driven), Freqtrade is **vectorized over pandas DataFrames**:

```python
class AwesomeStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    startup_candle_count = 400

    minimal_roi = {"40": 0.0, "30": 0.01, "20": 0.02, "0": 0.04}
    stoploss = -0.10

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (qtpylib.crossed_above(dataframe['rsi'], 30)) & (dataframe['volume'] > 0),
            ['enter_long', 'enter_tag']] = (1, 'rsi_cross')
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (qtpylib.crossed_above(dataframe['rsi'], 70)),
            ['exit_long', 'exit_tag']] = (1, 'rsi_too_high')
        return dataframe
```

### Three mandatory methods
- `populate_indicators(df, metadata)` — adds technical indicators to the df.
- `populate_entry_trend(df, metadata)` — sets `enter_long` / `enter_short` columns (1 or 0).
- `populate_exit_trend(df, metadata)` — sets `exit_long` / `exit_short` columns.

### Key attributes
- `minimal_roi`: **time-based ROI dict** — *"at 0min exit at 4%, at 20min at 2%, at 30min at 1%, at 40min exit no matter what"*. A very elegant pattern — ROI decayed over time.
- `stoploss`: base percentage.

### Callbacks (per-trade behavior override)
- `custom_entry_price()` — smart pricing vs proposed rate.
- `custom_exit_price()` — same for exits.
- `custom_stake_amount()` — dynamic sizing (e.g. less risk if more open trades).
- `custom_stoploss()` — trailing stops or dynamic stoploss.
- `leverage()` — for futures.
- `confirm_trade_entry()` — **boolean gate before entering** (orderbook check, etc.). **This is exactly the approval-gate pattern, but implemented with code instead of a human.**
- `confirm_trade_exit()` — boolean gate before exiting.

**`confirm_trade_entry` is the natural insertion point for plugging human approval into a Freqtrade integration**. But since Freqtrade is crypto + GPL, better to steal the concept and reimplement.

---

## 5. Protections — built-in modular risk management

Freqtrade has a **declarative Protections architecture** via config:

```json
{
  "enable_protections": true,
  "protections": [
    {
      "method": "StoplossGuard",
      "lookback_period_candles": 24,
      "trade_limit": 2,
      "stop_duration_candles": 12
    },
    {
      "method": "MaxDrawdown",
      "lookback_period_candles": 168,
      "trade_limit": 20,
      "stop_duration_candles": 12,
      "max_allowed_drawdown": 0.15
    }
  ]
}
```

**Built-in protections**:
| Protection | Function |
|---|---|
| **StoplossGuard** | Pauses entries after N consecutive stoplosses in lookback window |
| **MaxDrawdown** | Pauses if drawdown exceeds threshold |
| **CooldownPeriod** | Minimum time between trades on the same pair |
| **LowProfitPairs** | Blocks pairs that underperform in lookback |
| **ProfitExitGuard** | Customizes exit behavior on profit targets |

**Implication for iguanatrader**: the **declarative protections architecture** is exactly what iguanatrader needs for risk caps:

```yaml
# config/risk.yaml
protections:
  - method: DailyLossCap
    max_pct: 0.05
    on_breach: kill_switch_until_t1
  - method: WeeklyLossCap
    max_pct: 0.15
    on_breach: kill_switch_until_l1
  - method: PerTradeRisk
    max_pct: 0.02
  - method: MaxOpenPositions
    max: 5
```

Each protection is a pluggable class, `enable_protections: true` is a master kill-switch. **Pattern to copy verbatim.**

---

## 6. Operating modes — `dry-run` from day 1

Freqtrade has 4 modes:
- `dry-run` (paper) — simulates fills against real prices.
- `live` (real money).
- `backtesting` — runs against history.
- `hyperopt` — parameter sweeps via Optuna.

**Switch via a single config flag**: `"dry_run": true/false`. **Critical pattern** — prior research highlighted it as the antidote to "death by premature exposure to live".

For iguanatrader: `iguana paper` and `iguana live` must be **the same binary**, same code, different flag. **Never two codebases.**

---

## 7. Hyperopt (Optuna)

Optional parameters declarable in the Strategy:
```python
from freqtrade.strategy import IntParameter, RealParameter, BooleanParameter, CategoricalParameter

class OptimizedStrategy(IStrategy):
    rsi_period = IntParameter(7, 20, default=14, space='buy')
    rsi_threshold = RealParameter(20.0, 40.0, default=30.0, space='buy')
    use_volume_filter = BooleanParameter(default=True, space='buy')
    trend_type = CategoricalParameter(['ema', 'sma', 'tema'], default='ema', space='buy')
```

Run: `freqtrade hyperopt --strategy OptimizedStrategy --spaces buy`.

**Implication for iguanatrader**: when you grid-search over DonchianATR (lookback period, ATR multiplier), this declarative pattern is trivially replicable with `optuna`. iguanatrader can use `vectorbt` for massive sweeps (research) and `optuna` for directed optimization — both compatible.

---

## 8. Documented anti-patterns ("Looking into the future")

Freqtrade explicitly documents backtest leakage pitfalls:
- `shift(-1)` → direct future leak.
- `.iloc[-1]` in populate → varies by runmode.
- `.mean()` over the entire df → includes the future.
- `.resample()` without `label='right'` → leak.

**Pattern to steal**: document these anti-patterns in iguanatrader's `docs/strategies/leakage-checklist.md` as a **mandatory checklist** before accepting any new strategy.

---

## 9. Persistence and multi-tenancy

- **SQLAlchemy** with SQLite by default (Postgres optional).
- **Schema**: `Trade`, `Order`, `PairLock`. Append + update (not pure append-only).
- **Multi-tenant**: NO. Single-instance by design. For multi-user, one process per user is run (typically a Docker container).

**Implication for iguanatrader**: the "1 process per user" model in containers is **the realistic pattern** for crypto-trading SaaS. Hummingbot does the same. iguanatrader can go straight to this model in v2 SaaS without rewriting the core.

---

## 10. Governance and bus factor

- **Lead maintainer**: Matthias Voppichler. Active community of contributors.
- **Stars**: 49,440 (most popular in the ecosystem).
- **Estimated bus factor**: medium-high. Even with a clear lead, there are >300 contributors and an active community, indicating a takeover in case of departure would be viable.
- **Roadmap**: public on GitHub Discussions.
- **GPL-3.0 license**: blocks closed commercial SaaS on top.

---

## 11. **5 patterns to STEAL** for iguanatrader

1. **Full set of Telegram commands** — copy the catalog verbatim (see §3 mapping). Especially `/reload_config` for hot-reload of risk caps, `/forceexit` for emergencies, `/pause` to stop new entries without abandoning management.
2. **Protections as declarative architecture** — master kill-switch `enable_protections: true` + list of pluggable protections in yaml. iguanatrader's risk caps (`DailyLossCap`, `WeeklyLossCap`, `PerTradeRisk`, `MaxOpenPositions`) implemented as classes that conform to a common interface.
3. **`dry-run` mode as a single flag** — same binary, same code, `paper: true/false` switch. Inviolable.
4. **`confirm_trade_entry()` callback** — boolean gate before entering. iguanatrader uses exactly this but with a human-in-Telegram instead of code (`if not approval_received(): return False`).
5. **Documented anti-pattern checklist** — the "Looking into the future" pitfalls (shift, iloc, mean, resample). Document in `docs/strategies/leakage-checklist.md` as mandatory for any strategy review.

## 12. **3 anti-patterns to AVOID**

1. **Vectorized pandas as the main model** — Freqtrade uses vectorized DataFrames (fast for backtests, awkward for event-driven). iguanatrader needs pure event-driven (each bar/news/halt is an event). The Lumibot/Nautilus model is the right one, not Freqtrade's.
2. **Coupling to CCXT** — Freqtrade assumes crypto exchanges via CCXT. Its `Trade` model has crypto-specific fields (base/quote currency). iguanatrader on IBKR equity has a simpler model — do not copy the crypto schema.
3. **GPL-3.0 license** — blocks commercial SaaS. Same point as Lumibot. iguanatrader = Apache-2.0 + Commons Clause.

---

## 13. Honest verdict for iguanatrader

**Fork it?** **NO.** Crypto-only + GPL-3.0 + vectorized architecture incompatible with your event-driven equity focus.

**Copy interfaces?** **VERY MUCH YES.** **Three mandatory patterns to steal**:
1. The full Telegram catalog (mapping in §3).
2. The declarative Protections architecture.
3. `confirm_trade_entry` as a boolean gate.

**As a UX reference?** **MANDATORY.** It is the only OSS with battle-tested UX for retail bots over Telegram. Any feature you doubt whether to add or not, check if Freqtrade has it — if it does, there is empirical justification.

**Operational decision for the PRD**:
- ADR-006: "iguanatrader will implement Protections as a declarative architecture following the Freqtrade pattern. Risk caps (per-trade, daily, weekly) are individual pluggable protections via yaml. Master kill-switch `enable_protections: true`."
- ADR-007: "iguanatrader's Telegram command catalog replicates the Freqtrade set adapted to the approval-gate flow (mapping documented in `docs/research/platforms/freqtrade.md` §3). The same catalog is exposed over WhatsApp via Hermes."
