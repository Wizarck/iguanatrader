# QuantConnect Lean — Deep-dive técnico para iguanatrader

**Fecha:** 2026-04-27
**Repo:** https://github.com/QuantConnect/Lean
**Docs:** https://www.lean.io/, https://www.quantconnect.com/docs/v2/
**Maintainer:** QuantConnect Inc (corporación)
**Branch default:** `master`
**Última actividad:** 2026-04-27 (commits hoy mismo)
**Stars:** 18.648
**Licencia:** **Apache-2.0** ✅ (sin restricciones para fork comercial)

---

## 1. Veredicto rápido (TL;DR)

Lean es **el estándar consensus** del trading algorítmico OSS retail/prosumer. C# 94% del código + Python via PythonNet. La **Apache-2.0 es perfecta** para los planes SaaS de iguanatrader. Lleva 12+ años, 13k+ commits, tiene ~$300+ hedge funds usándolo en producción y QuantConnect Cloud (su propio SaaS multi-tenant) corre exactamente este código.

**Para iguanatrader**: el `BrokerageModel` y el `Algorithm Framework` (Universe → Alpha → Portfolio → Execution → Risk) son arquitectura a robar. Como base de código, **demasiado pesado** para un dev solo Python (la curva del API + el stack C#/Python híbrido te frenan en MVP). Como **modelo SaaS comercial** a copiar (5 tiers públicos), template sólido.

---

## 2. Identidad y posicionamiento

- **Filosofía**: "Everything is configurable and pluggable" + "no vendor lock-in".
- **Diferenciadores**:
  - Survivorship bias-free accounting (datos rigurosos, importante para backtests honestos).
  - Universe selection para reducir selection bias.
  - Apache-2.0 = "suitable for compliance requirements" en hedge funds.
- **Stack**: C# para performance + Python para ML. Mismo proyecto, mismo runtime via PythonNet.

---

## 3. Algorithm Framework — el patrón opinionated

Lean impone una **separación de 5 componentes** dentro de toda estrategia:

| Componente | Rol |
|---|---|
| **Universe Selection** | Qué símbolos están en el universo en cada momento (filtros dinámicos). |
| **Alpha Creation** | Genera "insights" (señales con dirección, confianza, magnitud, periodo). |
| **Portfolio Construction** | Convierte insights en target allocations. Modelos built-in: Equal Weighting, Mean-Variance, Black-Litterman. |
| **Execution Models** | Convierte target allocations en órdenes concretas. Maneja TWAP/VWAP/Iceberg si aplica. |
| **Risk Management** | "Pasivo o activo via hedging de posiciones expuestas". Filtros sobre las órdenes generadas. |

**Lo bueno**: separation of concerns extrema. Cada componente swappeable. Puedes combinar tu Alpha con un Portfolio model built-in.

**Lo cuestionable**: para una estrategia simple tipo DonchianATR (un símbolo, un signal, un sizing ATR), esta separación es **overhead**. Lean lo sabe y permite el modo "clásico" donde escribes todo en `OnData`. Pero el framework te empuja hacia los 5 componentes.

---

## 4. Algorithm API — esqueleto

Lean tiene 2 modos:

### Modo clásico (similar a Lumibot/Nautilus)

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

### Modo framework (5 componentes)

```python
class MyFrameworkAlgo(QCAlgorithm):
    def Initialize(self):
        self.SetUniverseSelection(ManualUniverseSelectionModel(["SPY"]))
        self.SetAlpha(MacdAlphaModel())
        self.SetPortfolioConstruction(EqualWeightingPortfolioConstructionModel())
        self.SetExecution(ImmediateExecutionModel())
        self.SetRiskManagement(MaximumDrawdownPercentPerSecurity(0.05))
```

**Nota**: API es **PascalCase** (heredado del C#). Los devs Python puros lo notan inmediatamente — es ruido visual.

---

## 5. `BrokerageModel` — la abstracción a robar

Quizás **el patrón más valioso de Lean**:

- Cada broker tiene su `BrokerageModel`: simula fees, order support (qué tipos de órdenes acepta), API behavior nuances (rate limits, rejects característicos).
- En **backtest** Lean usa el `BrokerageModel` para fingir realismo: comisiones realistas, rejects realistas, slippage característico del broker.
- En **live**, mismo `BrokerageModel` + el `Brokerage` real conectado al venue.
- Permite testar tu algoritmo contra "IBKR ideal" en backtest y luego ejecutar contra IBKR real con confianza.

**Para iguanatrader**: este es el patrón clave para resolver el "gap modelo↔live" del plan original. **Cada broker en iguanatrader debe tener un `BrokerageModel`** (ej. `IBKRBrokerageModel(commission_per_share=0.005, min_commission=1.0, supports_market_on_close=True, ...)`). El `BacktestEngine` usa este modelo para simular fills realistas.

Brokers built-in en Lean: Interactive Brokers, tastytrade, Charles Schwab, Alpaca, OANDA, Tradier, TradeStation, Binance, Coinbase, Bybit, Kraken, Bitfinex, Bitstamp, Zerodha, Wolverine.

---

## 6. Engine de backtest vs live

- **Mismo algorithm**: `QCAlgorithm` corre idéntico en backtest y live.
- **Diferencia**: `IDataFeed` y `IBrokerage` son inyectados según modo.
  - Backtest: `BacktestingDataFeed` + `BacktestingBrokerage` (que usa el `BrokerageModel` para simular).
  - Live: `LiveTradingDataFeed` + el broker real (`InteractiveBrokersBrokerage`).
- **Time model**: `Time` y `UtcTime` se sincronizan con el data feed. En backtest el reloj avanza con cada bar; en live es real-time.
- **Determinismo**: bueno pero no nanosecond como Nautilus. Suficiente para timeframes de minutos/bars.

---

## 7. Lean CLI

```bash
lean init                          # crea proyecto
lean backtest --algorithm-name X   # backtest local con Docker
lean live --brokerage IBKR         # live trading local
lean cloud backtest                # backtest en QC Cloud
lean cloud live                    # live en QC Cloud
lean optimize                      # parameter sweeps
```

- **Docker-first**: el CLI corre Lean dentro de un container. Cero setup de C#/Python en local.
- **VSCode integration**: extensión oficial.
- **Jupyter Lab**: para research interactivo.

**UX**: limpia. Para iguanatrader, **el patrón `iguana <command>` con typer es exactamente esto** (ya en plan).

---

## 8. C# vs Python tradeoffs

| Eje | C# en Lean | Python en Lean (via PythonNet) |
|---|---|---|
| Performance | Top-tier | ~2-3x más lento |
| Acceso a libs ML | Limitado | Pleno (sklearn, pytorch, etc.) |
| Curva de aprendizaje | Empinada para devs Python | Más suave |
| Debugging | Visual Studio + LINQPad | pdb/IPython, pero hay friction con PythonNet |
| Comunidad ejemplos | Menor (la mayoría escribe Python) | Mayor |

**Implicación para iguanatrader**: fuera de cualquier scenario "iguanatrader es Lean fork", el C# es deuda cognitiva. **Python puro como decisión arquitectónica está validada**.

---

## 9. QuantConnect Cloud — el modelo SaaS a estudiar

5 tiers públicos:

| Tier | Audiencia | Qué incluye |
|---|---|---|
| **Free** | Estudiantes, evaluadores | Backtesting unlimited, 1 research node, 200 projects, 500MB workspace, datos básicos. **Sin live trading**. |
| **Researcher** | Quants individuales | Paper trading, local coding (VSCode/CLI), 2 compute nodes, datos extendidos, tick/second data como add-on. |
| **Team** | Startups, equipos pequeños | Hasta 10 miembros, project collaboration, 10 compute nodes, brokerages (IBKR, tastytrade, Schwab, Alpaca). |
| **Trading Firm** | Empresas profesionales | Team ownership, permissions management, unlimited compute nodes. |
| **Institution** | Hedge funds, on-premise | On-premise, AES-256 code encryption, FIX/Professional brokerages, unlimited everything. |

**Pricing**: no disclosed públicamente, "recommended setups" by quote.

**Alpha Streams**: marketplace de estrategias (mencionado históricamente en otras fuentes, no en pricing page).

**Implicación para iguanatrader**: **5 tiers es muy granular para empezar**. Para iguanatrader v3 SaaS, **3 tiers (Solo / Team / Pro)** sería más manejable. Pero el patrón de "Free con compute limitado + paid con live trading" es el embudo correcto.

---

## 10. Governance y bus factor

- **Maintainer**: QuantConnect Inc. Bus factor estimado **muy alto** (corp con SaaS encima — incentivo financiero del orden de millones).
- **Ritmo**: commits semanales 2026.
- **Comunidad**: 18.648 stars + Discord activo + foro.
- **API stability**: alta. Lean es el más conservador en breaking changes del ecosistema.
- **Apache-2.0**: sin restricciones legales para fork comercial cerrado.

---

## 11. **5 patrones a ROBAR** para iguanatrader

1. **`BrokerageModel` abstraction** — separación entre "broker real" y "modelo de comportamiento del broker". Permite que el `BacktestEngine` use el mismo `IBKRBrokerageModel` que define comisiones/slippage/rejects, asegurando paridad real backtest↔live. **Probablemente el patrón más valioso de Lean**.
2. **Algorithm Framework como opt-in** — Lean ofrece tanto el modo clásico (todo en `OnData`) como el modo framework (5 componentes). Para iguanatrader: **modo clásico para MVP** (DonchianATR es trivial), **modo framework para v2** cuando haya múltiples estrategias y portfolio construction sofisticada.
3. **Lean CLI con Docker** — el modelo `iguana backtest` con container ya está en el plan. Replicar la separación local/cloud para v3 (`iguana cloud backtest` cuando exista hosted).
4. **Survivorship bias-free data** como característica explícita y vendible — iguanatrader debe documentar cómo carga histórico (¿incluye delisted? ¿hace adjustments correctos?). Es un "feature" que retail no entiende pero pros sí.
5. **5-tier SaaS pricing structure** como template para v3, simplificado a 3 tiers (Solo / Team / Pro). El patrón "Free con backtest unlimited pero sin live" es el embudo de conversión correcto.

## 12. **3 anti-patrones a EVITAR**

1. **Stack C#/Python híbrido** — para un dev solo Python, el C# es deuda cognitiva permanente. iguanatrader debe ser **Python puro de cabo a rabo**, sin compromiso.
2. **PascalCase API en Python** — Lean usa `SetCash`, `OnData`, `Initialize` (heredado del C#). En Python idiomático sería `set_cash`, `on_data`, `initialize`. iguanatrader debe seguir snake_case PEP-8 estricto.
3. **Algorithm Framework como obligatorio** — los 5 componentes son power user features. Para una estrategia simple (DonchianATR sobre 1 símbolo), forzar la separación Universe→Alpha→Portfolio→Execution→Risk es overhead muerto. iguanatrader debe **NO imponer framework** en MVP; los componentes pueden emerger en v2 si hacen falta.

---

## 13. Verdict honesto para iguanatrader

**¿Forkear?** **NO**. Demasiado pesado para un dev solo Python. La curva del API + el stack C# híbrido + el peso del Algorithm Framework te frenan en MVP.

**¿Copiar interfaces?** **SÍ, selectivamente**. El `BrokerageModel` es **obligatorio robar** (resuelve el "gap backtest↔live realista" del plan original). El modo "clásico" del Algorithm es un buen template para el MVP.

**¿Modelo SaaS a estudiar?** **SÍ**. QuantConnect Cloud es el referente del sector. Sus 5 tiers + el embudo "free backtest, paid live" son lo que iguanatrader v3 debe replicar (simplificado).

**¿Como referencia de "qué bien hecho se ve"?** **SÍ**. Para validar decisiones arquitectónicas tipo "¿separamos Universe Selection?" o "¿qué tipos de órdenes soportamos?", consultar Lean es como tener un senior architect a mano.

**Decisión operativa para el PRD**:
- ADR-004: "iguanatrader implementará un `BrokerageModel` per broker desde MVP siguiendo el patrón Lean. El `BacktestEngine` usará el `BrokerageModel` para simular slippage/comisiones/rejects realistas."
- ADR-005 (post-MVP): "v3 SaaS de iguanatrader seguirá un pricing tiered de 3 niveles (Solo / Team / Pro) inspirado en QuantConnect Cloud (5-tier), con el embudo 'free backtest unlimited, paid live trading'."
