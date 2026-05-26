# QuantConnect Lean — Technical deep-dive for iguanatrader

**Date:** 2026-04-27
**Repo:** https://github.com/QuantConnect/Lean
**Docs:** https://www.lean.io/, https://www.quantconnect.com/docs/v2/
**Maintainer:** QuantConnect Inc (corporation)
**Default branch:** `master`
**Last activity:** 2026-04-27 (commits today)
**Stars:** 18,648
**License:** **Apache-2.0** ✅ (no restrictions for commercial fork)

---

## 1. Quick verdict (TL;DR)

Lean is **the consensus standard** of OSS retail/prosumer algorithmic trading. C# 94% of the code + Python via PythonNet. The **Apache-2.0 license is perfect** for iguanatrader's SaaS plans. It has been around for 12+ years, has 13k+ commits, ~$300+ hedge funds running it in production, and QuantConnect Cloud (its own multi-tenant SaaS) runs exactly this code.

**For iguanatrader**: the `BrokerageModel` and the `Algorithm Framework` (Universe → Alpha → Portfolio → Execution → Risk) are architecture worth stealing. As a codebase, **too heavy** for a solo Python dev (the API curve + the hybrid C#/Python stack will slow you down at MVP). As a **commercial SaaS model** to copy (5 public tiers), it's a solid template.

---

## 2. Identity and positioning

- **Philosophy**: "Everything is configurable and pluggable" + "no vendor lock-in".
- **Differentiators**:
  - Survivorship bias-free accounting (rigorous data, important for honest backtests).
  - Universe selection to reduce selection bias.
  - Apache-2.0 = "suitable for compliance requirements" at hedge funds.
- **Stack**: C# for performance + Python for ML. Same project, same runtime via PythonNet.

---

## 3. Algorithm Framework — the opinionated pattern

Lean imposes a **5-component separation** within every strategy:

| Component | Role |
|---|---|
| **Universe Selection** | Which symbols are in the universe at each point in time (dynamic filters). |
| **Alpha Creation** | Generates "insights" (signals with direction, confidence, magnitude, period). |
| **Portfolio Construction** | Converts insights into target allocations. Built-in models: Equal Weighting, Mean-Variance, Black-Litterman. |
| **Execution Models** | Converts target allocations into concrete orders. Handles TWAP/VWAP/Iceberg when applicable. |
| **Risk Management** | "Passive or active via hedging of exposed positions". Filters on generated orders. |

**The good**: extreme separation of concerns. Each component is swappable. You can combine your Alpha with a built-in Portfolio model.

**The questionable**: for a simple strategy like DonchianATR (one symbol, one signal, ATR sizing), this separation is **overhead**. Lean knows this and allows the "classic" mode where you write everything in `OnData`. But the framework pushes you toward the 5 components.

---

## 4. Algorithm API — skeleton

Lean has 2 modes:

### Classic mode (similar to Lumibot/Nautilus)

```python
class MyAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2020, 12, 31)
        self.SetCash(100000)
        self.AddEquity("SPY", Resolution.Daily)

    def OnData(self, data):
        if not self.Portfolio.Invested:
            self.SetHoldings("SPY", 1.0)

    def OnOrderEvent(self, orderEvent):
        self.Debug(f"Order event: {orderEvent}")
```

### Framework mode (5 components)

```python
class MyFrameworkAlgo(QCAlgorithm):
    def Initialize(self):
        self.SetUniverseSelection(ManualUniverseSelectionModel(["SPY"]))
        self.SetAlpha(MacdAlphaModel())
        self.SetPortfolioConstruction(EqualWeightingPortfolioConstructionModel())
        self.SetExecution(ImmediateExecutionModel())
        self.SetRiskManagement(MaximumDrawdownPercentPerSecurity(0.05))
```

**Note**: API is **PascalCase** (inherited from C#). Pure Python devs notice it immediately — it's visual noise.

---

## 5. `BrokerageModel` — the abstraction worth stealing

Perhaps **the most valuable pattern in Lean**:

- Each broker has its own `BrokerageModel`: simulates fees, order support (which order types it accepts), API behavior nuances (rate limits, characteristic rejects).
- In **backtest** Lean uses the `BrokerageModel` to fake realism: realistic commissions, realistic rejects, broker-characteristic slippage.
- In **live**, the same `BrokerageModel` + the real `Brokerage` connected to the venue.
- Allows you to test your algorithm against "ideal IBKR" in backtest and then run against real IBKR with confidence.

**For iguanatrader**: this is the key pattern to solve the "model↔live gap" from the original plan. **Every broker in iguanatrader should have a `BrokerageModel`** (e.g. `IBKRBrokerageModel(commission_per_share=0.005, min_commission=1.0, supports_market_on_close=True, ...)`). The `BacktestEngine` uses this model to simulate realistic fills.

Built-in brokers in Lean: Interactive Brokers, tastytrade, Charles Schwab, Alpaca, OANDA, Tradier, TradeStation, Binance, Coinbase, Bybit, Kraken, Bitfinex, Bitstamp, Zerodha, Wolverine.

---

## 6. Backtest vs live engine

- **Same algorithm**: `QCAlgorithm` runs identically in backtest and live.
- **Difference**: `IDataFeed` and `IBrokerage` are injected according to mode.
  - Backtest: `BacktestingDataFeed` + `BacktestingBrokerage` (which uses the `BrokerageModel` to simulate).
  - Live: `LiveTradingDataFeed` + the real broker (`InteractiveBrokersBrokerage`).
- **Time model**: `Time` and `UtcTime` sync with the data feed. In backtest the clock advances with each bar; in live it's real-time.
- **Determinism**: good but not nanosecond like Nautilus. Sufficient for minute/bar timeframes.

---

## 7. Lean CLI

```bash
lean init                          # creates project
lean backtest --algorithm-name X   # local backtest with Docker
lean live --brokerage IBKR         # local live trading
lean cloud backtest                # backtest on QC Cloud
lean cloud live                    # live on QC Cloud
lean optimize                      # parameter sweeps
```

- **Docker-first**: the CLI runs Lean inside a container. Zero local C#/Python setup.
- **VSCode integration**: official extension.
- **Jupyter Lab**: for interactive research.

**UX**: clean. For iguanatrader, **the `iguana <command>` pattern with typer is exactly this** (already in the plan).

---

## 8. C# vs Python tradeoffs

| Axis | C# in Lean | Python in Lean (via PythonNet) |
|---|---|---|
| Performance | Top-tier | ~2-3x slower |
| Access to ML libs | Limited | Full (sklearn, pytorch, etc.) |
| Learning curve | Steep for Python devs | Smoother |
| Debugging | Visual Studio + LINQPad | pdb/IPython, but friction with PythonNet |
| Community examples | Smaller (most write Python) | Larger |

**Implication for iguanatrader**: outside any "iguanatrader is a Lean fork" scenario, C# is cognitive debt. **Pure Python as an architectural decision is validated**.

---

## 9. QuantConnect Cloud — the SaaS model to study

5 public tiers:

| Tier | Audience | What's included |
|---|---|---|
| **Free** | Students, evaluators | Unlimited backtesting, 1 research node, 200 projects, 500MB workspace, basic data. **No live trading**. |
| **Researcher** | Individual quants | Paper trading, local coding (VSCode/CLI), 2 compute nodes, extended data, tick/second data as add-on. |
| **Team** | Startups, small teams | Up to 10 members, project collaboration, 10 compute nodes, brokerages (IBKR, tastytrade, Schwab, Alpaca). |
| **Trading Firm** | Professional firms | Team ownership, permissions management, unlimited compute nodes. |
| **Institution** | Hedge funds, on-premise | On-premise, AES-256 code encryption, FIX/Professional brokerages, unlimited everything. |

**Pricing**: not publicly disclosed, "recommended setups" by quote.

**Alpha Streams**: strategy marketplace (mentioned historically in other sources, not on the pricing page).

**Implication for iguanatrader**: **5 tiers is too granular to start with**. For iguanatrader v3 SaaS, **3 tiers (Solo / Team / Pro)** would be more manageable. But the "Free with limited compute + paid with live trading" pattern is the correct funnel.

---

## 10. Governance and bus factor

- **Maintainer**: QuantConnect Inc. Estimated bus factor **very high** (corp with SaaS on top — financial incentive in the order of millions).
- **Pace**: weekly commits in 2026.
- **Community**: 18,648 stars + active Discord + forum.
- **API stability**: high. Lean is the most conservative on breaking changes in the ecosystem.
- **Apache-2.0**: no legal restrictions for a closed commercial fork.

---

## 11. **5 patterns to STEAL** for iguanatrader

1. **`BrokerageModel` abstraction** — separation between "real broker" and "model of broker behavior". Allows the `BacktestEngine` to use the same `IBKRBrokerageModel` that defines commissions/slippage/rejects, ensuring real backtest↔live parity. **Probably the most valuable pattern in Lean**.
2. **Algorithm Framework as opt-in** — Lean offers both classic mode (everything in `OnData`) and framework mode (5 components). For iguanatrader: **classic mode for MVP** (DonchianATR is trivial), **framework mode for v2** when there are multiple strategies and sophisticated portfolio construction.
3. **Lean CLI with Docker** — the `iguana backtest` with container model is already in the plan. Replicate the local/cloud separation for v3 (`iguana cloud backtest` when hosted exists).
4. **Survivorship bias-free data** as an explicit and sellable feature — iguanatrader must document how it loads history (does it include delisted? does it do correct adjustments?). It's a "feature" that retail doesn't understand but pros do.
5. **5-tier SaaS pricing structure** as a template for v3, simplified to 3 tiers (Solo / Team / Pro). The "Free with unlimited backtest but no live" pattern is the correct conversion funnel.

## 12. **3 anti-patterns to AVOID**

1. **Hybrid C#/Python stack** — for a solo Python dev, C# is permanent cognitive debt. iguanatrader must be **pure Python end-to-end**, no compromise.
2. **PascalCase API in Python** — Lean uses `SetCash`, `OnData`, `Initialize` (inherited from C#). Idiomatic Python would be `set_cash`, `on_data`, `initialize`. iguanatrader must follow strict snake_case PEP-8.
3. **Algorithm Framework as mandatory** — the 5 components are power user features. For a simple strategy (DonchianATR on 1 symbol), forcing the Universe→Alpha→Portfolio→Execution→Risk separation is dead overhead. iguanatrader must **NOT impose a framework** at MVP; components can emerge in v2 if needed.

---

## 13. Honest verdict for iguanatrader

**Fork it?** **NO**. Too heavy for a solo Python dev. The API curve + the hybrid C# stack + the weight of the Algorithm Framework will slow you down at MVP.

**Copy interfaces?** **YES, selectively**. The `BrokerageModel` is **mandatory to steal** (it solves the "realistic backtest↔live gap" from the original plan). The Algorithm's "classic" mode is a good template for the MVP.

**SaaS model to study?** **YES**. QuantConnect Cloud is the sector benchmark. Its 5 tiers + the "free backtest, paid live" funnel are what iguanatrader v3 should replicate (simplified).

**As a reference for "what well-done looks like"?** **YES**. To validate architectural decisions like "do we separate Universe Selection?" or "which order types do we support?", consulting Lean is like having a senior architect on hand.

**Operational decision for the PRD**:
- ADR-004: "iguanatrader will implement a `BrokerageModel` per broker from MVP following the Lean pattern. The `BacktestEngine` will use the `BrokerageModel` to simulate realistic slippage/commissions/rejects."
- ADR-005 (post-MVP): "iguanatrader's v3 SaaS will follow a 3-tier (Solo / Team / Pro) tiered pricing inspired by QuantConnect Cloud (5-tier), with the 'free unlimited backtest, paid live trading' funnel."
