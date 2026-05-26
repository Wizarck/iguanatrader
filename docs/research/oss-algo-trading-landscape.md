# OSS Algorithmic Trading Landscape — Research for iguanatrader

**Date:** 2026-04-26
**Author:** Claude (research agent)
**Audience:** PM (John) → iguanatrader PRD discovery
**Scope:** Open-source algorithmic trading platforms relevant to the single-user MVP (Python + IBKR + LangGraph + human-approval) and to the long-term vision (OSS core + multi-tenant SaaS).

---

## 1. Executive Summary

- **The OSS algorithmic trading space is VERY much alive in 2026**, but polarized: two serious cores for retail/prosumer (QuantConnect Lean, NautilusTrader), an overwhelming dominance of Freqtrade in crypto, and a long tail of zombie projects (Backtrader, PyAlgoTrade, bt, Catalyst).
- **No OSS project combines** the four pillars of iguanatrader: (a) backtest↔live parity in Python, (b) first-class IBKR, (c) human-approval-gate via Telegram + dashboard, (d) LangGraph/LLM orchestration with cost observability. The parts exist; the whole does not.
- **Lean is the "default king"** for retail equity/futures/multi-asset (Apache 2.0, 18.6k★, 13k+ commits, dual-stack Python/C#, same code backtest↔live, IBKR built-in). If iguanatrader were "yet another quant platform", the answer would be "use Lean and end the conversation". It is not.
- **NautilusTrader is the strongest technical bet of the new generation** (Rust core + Python control plane, deterministic event-driven, LGPL-3.0, 2.7k★, bi-weekly releases, native IBKR adapter). Architecturally cleaner than Lean but with a smaller community.
- **Freqtrade dominates crypto** (does not apply to IBKR/equities) but is the **only OSS with mature Telegram/webUI for human-in-the-loop** — a pattern to steal literally.
- **Lumibot is the closest competitor to iguanatrader's MVP**: pure Python, IBKR + Alpaca + crypto, same code backtest↔live, AI hooks (BotSpot/LLM sentiment), open-source with a commercial SaaS on top (Lumiwealth). **Candidate #1 to fork or "be a wrapper around"**.
- **The OSS+SaaS multi-tenant model has clear and profitable precedents**: QuantConnect Cloud (on top of Lean Apache-2.0), Lumiwealth (on top of Lumibot), Hummingbot (on top of HBOT, monetizes via exchange-fee-share, not classic SaaS), Composer (not OSS but the UX and pricing benchmark at $40/month in this vertical). Vectorbt PRO uses Apache-2.0 + Commons Clause as a block against commercial forks — a legal pattern worth copying.
- **The real gap iguanatrader fills**: **retail trading with LLM-orchestrated routines + explicit human approval gate + cost observability of the LLM stack itself**. Nobody does it well today. TradingAgents (academic) and LLM-trading-agents (Medium hype) are on the opposite side: full-auto without an approval gate. Composer is close (visual no-code + AI) but closed and without an LLM-agent layer.
- **Historical pitfalls to avoid**: Quantopian died from (a) a business model based on giving everything away and monetizing later via a fund that failed, and (b) massive crowdsource overfitting. Backtrader/PyAlgoTrade/bt died from **bus factor = 1**. Catalyst died dragged down by SEC / Enigma. Lesson: **keep bus factor ≥ 2, monetize early and modestly, do not bet viability on a single alpha**.
- **Verdict, previewed** (detail in §8): **build the LLM orchestrator + approval gate + cost layer from scratch**, but **do not reinvent the backtest/execution engine**. Do a thin wrap over `ib_async` for the MVP; keep Lean and NautilusTrader as engine migration options when scaling to SaaS.

---

## 2. Comparison Table

| Platform | URL | Alive | ★ | License | Stack | Brokers | Architecture | Backtest↔Live parity | Risk engine | Multi-tenant ready | HITL approval | Business model | Verdict (1 line) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **QuantConnect Lean** | github.com/QuantConnect/Lean | Alive (weekly commits 2026) | 18.6k | Apache-2.0 | C# core + Python via PythonNet | IBKR, Alpaca, Binance, Bybit, Coinbase, OANDA, Tradier, TradeStation, Kraken, Bitfinex, Bitstamp, Zerodha, Tradier, Wolverine | Event-driven | Yes (same algorithm) | Yes (built-in: position sizing, drawdown limits, brokerage models) | Designed for multi-tenant (it's what QC Cloud runs) | Not native (extensible) | OSS Apache + SaaS QC Cloud (free → enterprise $thousands/month) | The de facto multi-asset standard with proven SaaS |
| **NautilusTrader** | github.com/nautechsystems/nautilus_trader | Very alive (bi-weekly releases, 2026) | 2.7k | LGPL-3.0 | Rust core + Python control plane | IBKR, Binance (spot/futures), Bybit, dYdX, Coinbase Intl, Polymarket, Databento | Deterministic event-driven | Yes (same runtime and time model) | Yes (modular: risk engine separated from execution engine) | Designed for production multi-strategy (not multi-tenant out-of-box) | No | Pure OSS (corp Nautech Systems behind it) | Architecturally cleanest, probable future leader |
| **Freqtrade** | github.com/freqtrade/freqtrade | Very alive (daily commits, April 2026) | ~30k | GPL-3.0 | Python | Crypto only (Binance, Kraken, OKX, Bybit, etc. via CCXT) | Event-driven | Yes | Yes (stoploss, tiered, trailing, max-drawdown protection) | No (single-instance by design) | **Mature Telegram + webUI (FreqUI)** | Pure OSS + ecosystem of courses/community | The undisputed king of retail crypto; **Telegram pattern to copy** |
| **Lumibot** | github.com/Lumiwealth/lumibot | Alive (3.x in 2026) | ~2k | Apache-2.0 (appears so) | Python | **IBKR**, Alpaca, Tradier, Coinbase, Binance, Kucoin, TradeStation, Theta Data | Event-driven | Yes (same code) | Yes (basic) | Designed for individual; Lumiwealth SaaS multi-user | Not native, but "BotSpot" adds LLM sentiment | OSS Apache + commercial Lumiwealth SaaS | **The CLOSEST competitor to iguanatrader's MVP** |
| **vectorbt** (OSS) | github.com/polakowo/vectorbt | Minimal maintenance; focus shifted to PRO | ~5k | Apache-2.0 + **Commons Clause** | Python (NumPy/Numba) | N/A (research-only) | Vectorized | No (research-only) | Limited | N/A | N/A | OSS free for research; **paid PRO** | Best for massive parameter grid-search, not for live |
| **vectorbt PRO** | vectorbt.pro | Alive (paid) | N/A | Proprietary | Python | Connectors via CCXT/IB opt-in | Vectorized + event-driven hooks | Limited | Yes | No | No | Private monthly subscription | The most powerful research sandbox on the market, commercial |
| **Hummingbot** | github.com/hummingbot/hummingbot | Very alive, Foundation active 2026 | ~9k | Apache-2.0 | Python + Cython | DEX + 30+ CEX (binance, kucoin, etc.); **no equity** | Event-driven (market-making focus) | Yes | Yes (specialized for MM) | Local-first, not natively multi-tenant | No (Telegram client, no approval) | OSS + revenue via exchange-fee-share + HBOT token | The leader of OSS crypto market-making |
| **Jesse** | github.com/jesse-ai/jesse | Alive, JesseGPT added | ~5.6k | MIT (core) + paid services | Python | Crypto (CCXT-like) | Event-driven | Yes | Yes | No | No | OSS MIT + paid JesseGPT/dashboards | Crypto-only; nice UX; "OSS + premium services" model |
| **Backtrader** | github.com/mementum/backtrader | **Dormant/dead** (no relevant commits since 2023) | ~14k | GPL-3.0 | Python | IBKR (legacy), OANDA, VC, CCXT | Event-driven | Yes | Yes | No | No | Abandoned OSS | Still works but has no future; issues with Python 3.10+ |
| **Zipline-Reloaded** | github.com/stefan-jansen/zipline-reloaded | Alive (single maintainer) | 1.6k | Apache-2.0 | Python | N/A direct (research-first) | Event-driven | No (research) | Yes | N/A | N/A | Personal OSS (Jansen's book) | Excellent for factor-equity research; no live |
| **Backtesting.py** | github.com/kernc/backtesting.py | Alive (2026 commits) | ~6k | **AGPL-3.0** | Python | None (backtest only) | Simple event-driven | No | Basic | N/A | N/A | AGPL OSS | Lightweight; AGPL blocks closed commercial use |
| **QSTrader** | github.com/mhallsmoore/qstrader | Alive (slow maintenance) | ~1k | MIT | Python | Limited | Event-driven schedule-based | Yes (partial) | Yes (modular) | No | No | OSS + QuantStart books | Good architectural example; small community |
| **OctoBot** | github.com/Drakkar-Software/OctoBot | Very alive (v2.1.1 Mar 2026, mobile app, Hyperliquid) | ~3.5k | LGPL-3.0 / GPL | Python 3.12/13 | Crypto (15+ CEX), Polymarket | Event-driven | Yes | Yes | Supports cloud (octobot.cloud) | webUI; Telegram via plugin | OSS + OctoBot.cloud SaaS | Crypto-focused; **functional OSS+cloud SaaS model** |
| **FinRL / FinRL-X** | github.com/AI4Finance-Foundation/FinRL | Alive (research-driven, evolving into FinRL-X) | ~12k | MIT | Python (RL: Stable-Baselines3, Ray) | Limited (paper-trading) | Hybrid | Limited | Limited | N/A | N/A | Academic OSS | Sandbox for RL in finance; not production-ready |
| **Catalyst (Enigma)** | github.com/scrtlabs/catalyst | **DEAD** | ~2.5k | Apache-2.0 | Python (zipline fork) | Crypto (legacy) | Event-driven | Yes | Limited | No | No | Died with Enigma/SEC | Do not use (historical reference) |
| **PyAlgoTrade** | github.com/gbeced/pyalgotrade | **Dormant** (last push 2 years ago) | ~4.5k | Apache-2.0 | Python | Limited (Bitstamp, Xignite) | Event-driven | Partial | Limited | No | No | Abandoned OSS | Zombie; legacy code only |
| **bt** | github.com/pmorissette/bt | **Abandoned** (per Trading Strategy docs) | ~2k | MIT | Python | N/A | Vectorized portfolio | No | Yes (rebalancing) | N/A | N/A | Abandoned OSS | Conceptually good for asset-allocation; dead |
| **Composer.trade** | composer.trade | Alive (not OSS) | N/A | Proprietary | Web (proprietary DSL) | Alpaca underneath | Visual no-code | Yes (unique DSL) | Yes | Multi-tenant SaaS | "Trade With AI" (not approval-gate, it's generation) | Subscription $40/month stocks, 0.2% crypto | The UX/pricing benchmark of modern retail-quant |
| **TradingAgents** | github.com/TauricResearch/TradingAgents | Alive (v0.2.3 Mar 2026) | (high traction 2025-26) | (research) | Python (multi-LLM) | Paper-trading | Multi-agent LLM (no execution engine of its own) | No | No | N/A | No (full-auto agent demos) | Academic/research | The paper that defines "multi-agent trading firm" but is NOT production |

---

## 3. Deep-dives: the 6 most relevant platforms for iguanatrader

### 3.1 QuantConnect Lean (★ 18.6k, Apache-2.0)

**What it is:** The most mature OSS algorithmic trading engine in the retail/prosumer market. C# at the core (94% of the code), Python as first-class via PythonNet. Supports backtest, optimization, paper trading and live trading **with the same algorithm**, against IBKR, Alpaca, Binance, Tradier, Coinbase and ~10 more brokers. QuantConnect Cloud itself runs exactly this code in multi-tenant mode for 300+ hedge funds and thousands of retail users.

**Why it matters for iguanatrader:**
- Apache 2.0 → you can fork, modify and sell SaaS on top without license restrictions.
- Battle-tested IBKR adapter.
- Backtest↔live parity is the project's guiding principle.
- Lean CLI lets you run everything locally via Docker — no vendor lock-in.

**Why NOT to use it as-is:**
- The hybrid C#/Python stack is heavy for a solo dev in pure Python. The API learning curve is real.
- It has no native approval gate or Telegram; you would have to add it as an external layer.
- It has no LLM cost observability (because it doesn't use LLMs).
- The philosophy "the algorithm is the atomic unit" clashes a bit with "LLM proposes, human approves, engine executes".

**Recommendation:** Study the `Algorithm` API and the `BrokerageModel` abstraction. Steal concepts. **Do not fork** unless iguanatrader pivots to "QC clone in Spanish + LLM layer".

### 3.2 NautilusTrader (★ 2.7k, LGPL-3.0)

**What it is:** The "next-generation Lean" — Rust at the core for determinism and performance, Python as control plane. Same runtime for backtest and live (not two distinct engines stitched together). Designed for multi-asset/multi-venue production. Complete IBKR adapter.

**Why it matters:**
- Clock-level determinism — fundamental for real backtest↔live parity (not just "same code", but "same event order").
- Clean modular architecture: separate `DataEngine`, `ExecutionEngine`, `RiskEngine`, `Cache`, `MessageBus`.
- Bi-weekly releases, corporate maintainer (Nautech Systems Pty Ltd) with an incentive to monetize via services.
- Allows writing strategies **in Python only** without touching Rust.

**Caveats:**
- LGPL-3.0 is more restrictive than Apache. If you embed Nautilus in a closed commercial SaaS, you must allow the user to replace the library (typically via dynamic linking). Manageable, but not as free as Apache.
- API "becoming more stable" — they admit breaking changes between releases. Risk for an MVP that wants stability.
- Community ~10x smaller than Lean → fewer examples, fewer answers on Stack Overflow.

**Recommendation:** **If iguanatrader wants to bet on the "engine of the future"**, this is it. For a single-user MVP, overkill; for a v2 multi-tenant SaaS, a strong candidate as the underlying engine.

### 3.3 Lumibot (★ ~2k, Apache-2.0)

**What it is:** Python trading framework created by Lumiwealth (a company with paid education + managed bots). Supports IBKR, Alpaca, Tradier, crypto. Same code backtest↔live. In 2026 it added "BotSpot": a module that connects strategies to LLMs for real-time sentiment/news.

**Why it's the closest to iguanatrader's MVP:**
- Pure Python, ergonomic for a solo dev.
- First-class IBKR (REST + Legacy).
- AI hooks already thought through — does not reject the LLM idea the way Lean/Nautilus do.
- OSS + commercial SaaS business model **already validated in this niche** (Lumiwealth sells managed bots, courses, dashboards).

**Why you need to look at it with a magnifying glass:**
- Small community, less polished code than Lean/Nautilus.
- Uneven documentation.
- "BotSpot" looks marketing-driven, not a serious agentic layer (not LangGraph).
- No explicit approval gate.

**Recommendation:** **Mandatory reading before writing a line of iguanatrader**. Consider forking or, at the very least, literally copying the `Strategy` interface and the `Broker` abstraction. It is the most efficient "stand on the shoulders of giants".

### 3.4 Freqtrade (★ ~30k, GPL-3.0)

**What it is:** The most popular OSS crypto bot on the planet. Does not apply directly to IBKR/equities but **it is the only framework with mature, battle-tested Telegram + webUI + risk engine for retail**.

**Pattern to steal (literally):**
- Telegram commands: `/status`, `/profit`, `/balance`, `/forcebuy`, `/forcesell`, `/stop`, `/reload_config`, `/whitelist`, `/blacklist`. **This is exactly the approval-gate UX iguanatrader needs**.
- Modes: `dry-run` (paper), `live`, `backtesting`, `hyperopt` (Optuna). Impeccable design for iteration.
- FreqAI: opt-in ML module with a reproducible pipeline. A model to follow if iguanatrader adds ML.
- FreqUI: local dashboard served by the bot itself. Pattern: "your bot is also its own UI server".

**Caveats:** GPL-3.0 → if you fork, every derivative must be GPL-3.0 (closed SaaS is not easy). Crypto only, no equity. Not usable as a base, but yes as a UX reference.

**Recommendation:** **Document and imitate the Telegram command set, the dry/live modes, and the embedded webUI pattern**. Do not fork (wrong license + wrong scope).

### 3.5 NautilusTrader vs Lean — the architectural decision

| Axis | Lean | NautilusTrader |
|---|---|---|
| Primary language | C# (94%) | Rust (core) + Python (control) |
| Maturity | 12+ years, 13k commits, 300+ hedge funds | ~5 years, 2.7k★, growing fast |
| License for SaaS | Apache 2.0 (perfect) | LGPL-3.0 (manageable) |
| Backtest↔live determinism | Good | Excellent (single event time model) |
| Footprint for a solo dev | Heavy | Medium |
| IBKR adapter | Yes, mature | Yes, complete (with Python 3.14 caveat) |
| Community ecosystem | Huge | Medium but growing |
| Fits with LangGraph/LLM | Has to be bolted on top | Has to be bolted on top |

Both are technically correct. **Lean** is the "consensus / I won't get fired for picking it" choice. **Nautilus** is the 3-year bet. **Neither solves the approval gate nor LLM cost observability** — iguanatrader writes those.

### 3.6 Composer.trade (not OSS, but a mandatory benchmark)

**What it is:** No-code SaaS for creating "symphonies" (visual flowchart-style strategies). Alpaca underneath for execution. Subscription $40/month for stocks, 0.2% crypto. They launched "Trade With AI" in Oct 2025: NL → strategy. ~$X00M valuation.

**Why it matters for iguanatrader:**
- **It is the pricing and UX benchmark of retail-quant SaaS**. $40/month is the psychological ceiling for non-pro retail.
- Its proprietary DSL + AI generation is exactly "LLM proposes strategy, human approves". It is the conceptual pattern of iguanatrader, **but closed and without a per-trade approval gate**.
- Demonstrates that the market pays for: (a) instant visual backtesting, (b) managed execution (users don't want to touch TWS Gateway), (c) "trade with AI" as a hook.

**What iguanatrader can do better:**
- Open core (Composer is fully closed).
- IBKR (Composer only Alpaca).
- Approval gate **per trade**, not just per strategy.
- LLM cost observability (Composer has no LLMs on the hot path; it doesn't expose them as a cost either).

---

## 4. Sub-group: OSS + multi-tenant SaaS precedents

| Company | OSS layer | SaaS layer | How it splits | License that enables it |
|---|---|---|---|---|
| **QuantConnect** | Lean (engine) | QC Cloud (data, compute, hosting, teams, algo marketplace) | OSS = engine + adapters; SaaS = licensed data feeds, managed compute, multi-user collaboration, alpha streams marketplace, SLA support | Apache 2.0 → lets QC monetize the entire surrounding stack without being forced to open the SaaS |
| **Lumiwealth** | Lumibot | Courses, managed bots, dashboards | OSS = framework; SaaS = "bots-as-a-service" + education + signals | Apache 2.0 |
| **Hummingbot Foundation** | Hummingbot core + Condor UI | NO SaaS; they monetize via **exchange-fee-share** (exchanges pay rebates for volume generated by Hummingbot bots) | OSS 100% free; indirect revenue via partnerships | Apache 2.0 |
| **OctoBot** | OctoBot core | OctoBot.cloud (hosted deploy, strategy packs) | OSS = local engine; SaaS = hosting + premium strategies | LGPL/GPL |
| **Jesse** | jesse (core) | JesseGPT, dashboards, premium datasets | OSS = engine + backtest; SaaS = AI strategy assistant + data | MIT |
| **vectorbt** | vectorbt (research lib) | vectorbt PRO (private repo, Discord, advanced features) | OSS = "demo"; PRO = anything serious | Apache 2.0 + **Commons Clause** (prevents selling the OSS as a service) |
| **Numerai** | Small python libs | Tournament + hedge fund | OSS = SDK; the business is the hedge fund operating with the crowdsourced meta-model. They pay in NMR token. | MIT (libs); the model is not easily replicable |

**Repeatable patterns for iguanatrader:**

1. **OSS = engine + SDK; SaaS = everything "managed"** (data, compute, multi-user, hosted dashboard, support). QC and Lumiwealth.
2. **License moat**: pure Apache 2.0 allows third parties to replicate the SaaS. **Commons Clause** (vectorbt) or **AGPL** (backtesting.py) block competing SaaS but scare off some users. Explicit trade-off.
3. **Education-as-revenue** (Lumiwealth, QuantStart, Jesse): courses and books generate high margins and embed the tool.
4. **Strategy marketplace** (QC Alpha Streams, Numerai meta-model): rare but defensible network effect. Long term.
5. **Exchange-fee-share** (Hummingbot): only applies to crypto, not to equity. Ignore for iguanatrader.

---

## 5. Strategic synthesis

### (a) Is there an OSS so complete that iguanatrader should use it instead of building?

**Honest answer: NO, but you're close.**

- **Lean** covers engine + brokers + backtest↔live perfectly. It does not cover LLM-orchestrated routines, approval gate, or cost observability. If iguanatrader were "yet another Python trading framework", the answer would be "use Lean and you're done". Since it is NOT, Lean is **a possible underlying component**, not the product.
- **Lumibot** is the closest functionally to the MVP. If your goal were "launch tomorrow instead of in 3 months", **you would fork Lumibot and add the approval gate + LLM layer on top**.
- **NautilusTrader** is the 3-year bet for the engine. For MVP it is overkill.

**Conclusion:** Don't abandon the project. Do abandon the idea of **writing the execution engine from scratch**. Wrap `ib_async` in a thin layer and, when the time comes, migrate to Lean or Nautilus as the underlying engine.

### (b) Top candidates to fork

1. **Lumibot** — highest match to the MVP. Pure Python, IBKR, backtest↔live, Apache (likely). Downside: small community, less polished code. Risk of inheriting technical debt.
2. **NautilusTrader** — strong technical bet. Downside: LGPL is an item to audit beforehand; Rust at the core raises the bar for external contribution.
3. **Lean** — the "industrial" option. Downside: hybrid C#-Python is heavy for a solo dev; productivity penalty in MVP.

**Operational recommendation:** **Fork none in the MVP**. Build a custom Python layer with `ib_async` directly. Keep a `BrokerInterface` abstract from day 1 so Lumibot/Nautilus can be plugged as adapters in v2. This is the "embrace but don't couple".

### (c) What gaps does iguanatrader cover that nobody else covers?

**Hypothesis validation: largely yes.**

| Gap | Covered by OSS today | Covered by commercial SaaS today |
|---|---|---|
| LLM-orchestrated routines (pre-market briefing, weekly review) | No (TradingAgents is a demo, not production) | Composer "Trade With AI" partially, Architect.co partially |
| Approval gate **per trade** via Telegram + dashboard | Freqtrade partial commands (crypto) | No |
| Backtest↔live parity in pure Python | Yes (Lean, Nautilus, Lumibot) | N/A |
| Cost observability of the LLM stack itself in USD | **No, nowhere** | No |
| Retail IBKR with approval gate | No | No |
| Risk caps (2%/5%/15%) with automated kill-switch | Partial (Freqtrade, Lean have pieces) | Composer doesn't expose this to the user |

**The real differentiator is the combination**: *"LLM proposes strategy and trades → human approves on Telegram → deterministic engine executes via IBKR → every LLM and broker API call is logged with its USD cost → automatic kill-switch if I exceed 5% daily"*. **This end-to-end flow does not exist in OSS today**.

### (d) Competitive landscape: saturated, growing, dying, niche?

- **Total market**: $25-32B in 2026, CAGR 13-15%, retail = 38.5% of market share. **Growing strong**.
- **OSS crypto bots**: **saturated** — Freqtrade, Hummingbot, OctoBot, Jesse all compete on crypto. Trend: consolidation (Freqtrade wins the long tail; Hummingbot wins market-making; OctoBot wins low-code/UI).
- **OSS equity/multi-asset**: **less saturated, dominated by Lean**. NautilusTrader and Lumibot are the serious challengers.
- **Retail B2C quant SaaS**: **growing and opportunistic**. Composer ($40/month, no-code, AI) is growing; QuantConnect Cloud covers the prosumer segment; but the "retail with a small/medium IBKR account that wants something more serious than Composer and less heavy than QC" segment is **underserved**.
- **LLM-agent trading**: **2025-2026 hype explosion**, most are academic demos (TradingAgents) or Medium tutorials. **None production-grade with a real risk engine and approval gate**. The window is here.

**Key survivors and why they're still alive:**
- **Lean / QuantConnect**: network effect + licensed data + corporate funding.
- **Freqtrade**: huge community + dedicated maintainer + crypto niche with indirect monetization (courses, signals).
- **NautilusTrader**: corporate backing (Nautech Systems Pty Ltd) + clear technical differentiation (Rust).
- **Hummingbot**: Foundation with governance + indirect revenue (exchange fees).

**2026 trend:** **LLM + trading convergence**. Whoever does it well first (with a serious risk engine + approval gate, not full-auto cowboy) defines the category.

---

## 6. Ideas worth stealing

### UX
- **Freqtrade Telegram commands**: `/status`, `/profit`, `/forcebuy`, `/forcesell`, `/stop`, `/reload_config`. Adapt for iguanatrader: `/propose`, `/approve <trade_id>`, `/reject <trade_id>`, `/halt`, `/resume`, `/risk_status`, `/cost_today`.
- **Freqtrade `dry-run` mode**: switch between paper and live with a flag in config. Imitate.
- **Composer "symphony" visual**: even if iguanatrader is not no-code, **a visualizer of the active strategy on the dashboard is gold**.
- **QC auto-generated backtest HTML report**: imitate the format (equity curve, drawdown, trades, Sharpe/Sortino/Calmar metrics).
- **Lumibot "BotSpot" idea**: opt-in module to inject LLM signals (sentiment, news). Same pattern.

### Architecture
- **NautilusTrader's `MessageBus` + separated engines** (`DataEngine`, `ExecutionEngine`, `RiskEngine`): replicable in Python with asyncio + queues. Architectural cleanliness that iguanatrader should embrace from day 1.
- **Lean's `BrokerageModel`**: abstraction that lets you test with an "ideal broker" in backtest and plug in the real one in live. Replicable.
- **Freqtrade's strategy interface**: `populate_indicators`, `populate_entry_trend`, `populate_exit_trend` — clear separation of concerns. Adapt to `propose_signals`, `request_approval`, `execute_approved`.
- **QSTrader's modular schedule-based portfolio construction**: signal → portfolio construction → risk → execution, fully decoupled. Good as a reference.
- **`ib_async`'s sync+async dual API**: use async on the hot path, sync in research scripts. Pattern to follow.

### Monetization (long-term vision)
- **Composer's $40/month flat** = psychological ceiling for non-pro retail in this vertical. Suggested initial pricing: **$29-49/month** individual tier, **$199-499/month** "team" tier (3-5 seats).
- **Freemium tier**: paper trading + 1 free strategy (like QC free). Conversion when the user wants live + risk caps + approval flow.
- **Education flywheel** (Lumiwealth, QuantStart, Jesse): blog + paid course + premium bot. High margin, organic customer acquisition.
- **No strategy marketplace in v1** — high legal and operational complexity, requires a critical mass iguanatrader won't have in year 1.
- **LLM cost-pass-through**: charge a margin on Anthropic/Perplexity API costs. iguanatrader has native cost observability, which is defensible.

### Community building
- **Discord >> Slack** for retail quant (Freqtrade, NautilusTrader, vectorbt PRO all on Discord).
- **Active GitHub Discussions** for structured bug reports (NautilusTrader does it well).
- **Monthly newsletter** (Hummingbot does this excellently — monthly Substack with metrics, releases, roadmap).
- **Cohort-based course** (Lumiwealth style) every quarter: high-touch, high-margin, generates content + advocates.
- **Public open roadmap** on GitHub (Freqtrade, NautilusTrader): transparency attracts contributors.

---

## 7. Risks and pitfalls observed

### Why projects died
- **Quantopian (RIP 2020)**: give everything away and monetize later via a fund whose alpha failed. **Lesson: monetize early and modestly, do not bet viability on a single alpha**.
- **Backtrader (dormant 2023+)**: **bus factor 1**. Maintainer left. Community didn't organize a takeover. **Lesson: bus factor ≥ 2 from day 1; explicit governance**.
- **PyAlgoTrade (dormant)**: same bus factor + Python 3 transition not completed in time.
- **Catalyst (Enigma)**: dragged down by SEC enforcement against Enigma (unregistered ENG ICO). **Lesson: do not tie a trading platform to tokenized/ICO speculative schemes**.
- **bt (abandoned)**: clean API but too niche a scope (portfolio rebalancing); lack of live trading left it without commercial pull.

### Common architectural mistakes
- **Backtest engine ≠ live engine**: when they are different code stitched together, parity fails in production. **Lean and Nautilus solved it by using a single event loop**. Imitate.
- **LLM on the hot path**: latency + cost + non-determinism destroy the risk engine. **Keep LLM only in research/orchestration, NEVER in execution**. iguanatrader already has this right in its 3-layer architecture.
- **Multi-tenancy bolted on later**: impossible to refactor to multi-tenant if SQLite + filesystem is hardcoded. **Design `tenant_id` as first-class from day 1**, even if the MVP is single-user.
- **Risk engine as an afterthought**: in Backtrader and PyAlgoTrade risk caps were opt-in and easy to forget. **The risk engine must be mandatory; strategies propose, the risk engine approves/trims/rejects**.
- **No `dry-run` from day 1**: fatal mistake. Freqtrade has it, and that's why retail doesn't get burned in production on day one.

### Common monetization mistakes
- **Free forever with no path to paid**: Quantopian. Drains resources with no return.
- **Pay-per-feature instead of per-capacity** (e.g. charging for "number of strategies"): retail churns. Better pricing by **AUM managed**, **number of connected accounts** or **flat tier with clear capacity**.
- **Token utility coin** (Numerai NMR, HBOT): works for Numerai because there's a hedge fund behind it. For iguanatrader it would be a regulatory distraction.
- **AGPL can stall corporate adoption**: backtesting.py limits its upside because corps fear AGPL. **Apache 2.0 + Commons Clause is the sweet spot** if you want to block a competing SaaS without scaring off users.

### Regulatory risks
- **US (SEC/FINRA)**: if you give actionable signals to multiple users, you may fall under "investment advisor". A per-user approval gate mitigates (the user decides), but audit it.
- **EU (MiFID II)**: distributing OSS software is safe; offering a managed SaaS in the EU requires care with the definition of "investment service".
- **Tax reporting**: if the SaaS executes trades on behalf of the user (even via approval), it may turn you into a "broker" for tax purposes. **Keep the architecture "the user owns the IBKR account; you only orchestrate their software"** — that is defensible.

---

## 8. Recommendation for iguanatrader (honest verdict)

### MVP (short term, next 3 months)

**Build from scratch, DO NOT fork, but stand on the shoulders of giants.**

1. **Execution engine**: thin wrap over `ib_async` directly. DO NOT put Lean/Nautilus in the MVP — the complexity of their API will slow you down. Keep a `BrokerInterface` abstract so you can plug adapters in v2.
2. **Backtest engine**: write a simple custom event-driven one for Donchian + ATR. Validate parity with a single test: run the same strategy in backtest and in paper trading over the same period, compare fills. If Lean/Nautilus feel necessary later, plug-in via adapter.
3. **Research sandbox**: use **vectorbt** (OSS, Apache + Commons Clause is OK for internal research use) for parameter grid-search. That is exactly what it's for.
4. **Telegram + dashboard**: literally copy Freqtrade's command set adapted: `/propose`, `/approve`, `/reject`, `/halt`, `/risk_status`, `/cost_today`. Local FastAPI serves the dashboard.
5. **Risk engine**: separate, mandatory, kill-switch hardcoded at 5% daily / 15% weekly. Strategies **propose**, the risk engine **filters/trims/rejects** BEFORE the approval gate sees the trade.
6. **LangGraph orchestration**: for routines (pre-market briefing, weekly review). NOT on the hot path. Each node logs its `provider`, `model`, `tokens_in`, `tokens_out`, `usd_cost` to SQLite.
7. **Cost observability**: append-only `llm_calls` table in SQLite. `/cost_today` and `/cost_week` commands on Telegram.

**What NOT to do in the MVP:**
- No multi-asset (US equity only via IBKR).
- No multi-strategy (only Donchian+ATR v0).
- No ML/RL (FinRL is for v3+).
- No marketplace, no community features, no free tier.
- No pre-market scanning of the whole universe — manual watchlist only.

### v2 (6-12 months)

- Decide the underlying engine: **Lumibot** if you want feature velocity, **NautilusTrader** if you want a technical bet, **Lean** if you want consensus. Migration via the `BrokerInterface` that will already be ready.
- Multi-tenant readiness: first-class `tenant_id`, postgres instead of sqlite (or per-tenant sqlite with tenant-router), object storage for parquets.
- Approval gate via Web (not only Telegram) for non-techie users.

### v3 / SaaS (12-24 months)

- Model: **OSS Apache-2.0 + Commons Clause** (blocks competing SaaS) + hosted SaaS tier ($29 individual / $199 team).
- Education flywheel: technical blog + quarterly cohort-based course.
- DO NOT enter the strategy marketplace until you have >1000 paying users.
- Consider entering the EU first (clearer regulation for "user-owned-account orchestration") before the US.

### TL;DR of the verdict

> iguanatrader is **NOT redundant** with today's OSS offering. Its differentiator — **LLM-orchestrated proposals + human approval gate + cost observability + retail IBKR** — does not exist in any OSS project today. Build the MVP in pure Python on top of `ib_async`, **steal UX from Freqtrade**, **steal modular architecture from NautilusTrader**, **steal pricing/positioning from Composer**, and leave the door open for the execution engine to be replaceable by Lumibot/Lean/Nautilus in v2. The market opportunity is real, growing, and the "responsible LLM-orchestrated retail trading" category is wide open.

---

## Sources

- [QuantConnect Lean GitHub](https://github.com/QuantConnect/Lean)
- [QuantConnect Pricing](https://www.quantconnect.com/pricing/)
- [Lean.io](https://www.lean.io/)
- [NautilusTrader GitHub](https://github.com/nautechsystems/nautilus_trader)
- [NautilusTrader Site](https://nautilustrader.io/)
- [NautilusTrader IBKR Docs](https://docs.nautilustrader.io/integrations/ib.html)
- [Freqtrade GitHub](https://github.com/freqtrade/freqtrade)
- [Freqtrade Docs](https://www.freqtrade.io/en/stable/)
- [Lumibot GitHub](https://github.com/Lumiwealth/lumibot)
- [Lumibot Docs](https://lumibot.lumiwealth.com/)
- [vectorbt License](https://vectorbt.dev/terms/license/)
- [vectorbt PRO](https://vectorbt.pro/)
- [Hummingbot Newsletter Apr 2026](https://hummingbot.substack.com/p/hummingbot-newsletter-april-2026)
- [Jesse GitHub](https://github.com/jesse-ai/jesse)
- [OctoBot GitHub](https://github.com/Drakkar-Software/OctoBot)
- [Zipline-Reloaded](https://github.com/stefan-jansen/zipline-reloaded)
- [Backtesting.py](https://github.com/kernc/backtesting.py)
- [QSTrader](https://github.com/mhallsmoore/qstrader)
- [Catalyst (defunct)](https://github.com/scrtlabs/catalyst)
- [PyAlgoTrade](https://github.com/gbeced/pyalgotrade)
- [FinRL](https://github.com/AI4Finance-Foundation/FinRL)
- [TradingAgents](https://github.com/TauricResearch/TradingAgents)
- [Composer.trade](https://www.composer.trade/)
- [ib_async](https://github.com/ib-api-reloaded/ib_async)
- [Numerai](https://numer.ai)
- [Quantopian shutdown postmortem (QuantRocket)](https://www.quantrocket.com/blog/quantopian-shutting-down/)
- [Algorithmic Trading Market Report 2026 (BusinessResearchCompany)](https://www.thebusinessresearchcompany.com/report/algorithmic-trading-global-market-report)
- [Algorithmic Trading for Retail (Power Trading Group 2026)](https://www.powertrading.group/options-trading-blog/algorithmic-trading-retail-traders-2026)
- [Battle-Tested Backtesters Comparison (Medium)](https://medium.com/@trading.dude/battle-tested-backtesters-comparing-vectorbt-zipline-and-backtrader-for-financial-strategy-dee33d33a9e0)
- [Python Backtesting Landscape 2026](https://python.financial/)
- [Trading Strategy frameworks docs](https://tradingstrategy.ai/docs/learn/algorithmic-trading-frameworks.html)
