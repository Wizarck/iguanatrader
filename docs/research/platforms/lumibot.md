# Lumibot — Deep-dive técnico para iguanatrader

**Fecha:** 2026-04-27
**Repo:** https://github.com/Lumiwealth/lumibot
**Docs:** https://lumibot.lumiwealth.com/
**Maintainer:** Lumiwealth (corporación con producto comercial encima)
**Branch default:** `dev`
**Última actividad:** 2026-04-26 (vivo, commits regulares)
**Stars:** 1.366
**Licencia:** ⚠️ **GPL-3.0** (no Apache-2.0 como decía la research previa — corrección importante)

---

## 1. Veredicto rápido (TL;DR)

Lumibot **es funcionalmente** el competidor más cercano al MVP de iguanatrader. Cubre IBKR, backtest↔live parity, lifecycle de Strategy bien diseñado, integración LLM-en-backtest pionera. **Pero la licencia GPL-3.0 lo descarta como base para fork comercial cerrado** — y eso es exactamente la trayectoria que iguanatrader contempla post-MVP. Útil como **referencia de API y patrones**, no como base de código.

---

## 2. Arquitectura general

Cuatro componentes principales:

| Componente | Rol |
|---|---|
| `Strategy` | Clase del usuario. Toda la lógica vive aquí. Hereda de `lumibot.strategies.strategy.Strategy`. |
| `Broker` | Capa de conexión. Implementaciones: `Alpaca`, `InteractiveBrokers`, `Schwab`, `Tradier`, `Ccxt` (cripto), `Tradovate`, etc. |
| `Backtesting` | Engine de simulación histórica. Variantes por data source: `YahooDataBacktesting`, `PolygonDataBacktesting`, `DataBentoBacktesting`. |
| `Trader` | Orquestador. Carga estrategias, levanta el loop, gestiona crash-recovery. |

**Modelo arquitectónico**: event-driven (no vectorizado). Mismo `Strategy` corre en backtest y en live; las diferencias las absorben `Broker` y `Backtesting`.

---

## 3. `Strategy` interface — el patrón a robar

### Esqueleto mínimo

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
        self.sleeptime = "180M"  # cada 180 minutos

    def on_trading_iteration(self):
        symbol = self.parameters["symbol"]
        order = self.create_order(symbol, self.parameters["quantity"], self.parameters["side"])
        self.submit_order(order)
```

### Lifecycle completo (12 hooks)

| Hook | Cuándo dispara |
|---|---|
| `initialize()` | Una vez al arranque |
| `before_starting_trading()` | Antes del primer `on_trading_iteration` del día |
| `before_market_opens()` | Pre-mercado |
| `on_trading_iteration()` | Loop principal (cada `sleeptime`) |
| `before_market_closes()` | Pre-cierre |
| `after_market_closes()` | Post-cierre |
| `on_new_order(order)` | Confirmación de orden creada |
| `on_partially_filled_order(order, qty)` | Fill parcial |
| `on_filled_order(order)` | Fill completo |
| `on_canceled_order(order)` | Cancelación |
| `on_parameters_updated()` | Cambio dinámico de `parameters` (hot-reload) |
| `on_bot_crash()` / `on_abrupt_closing()` | Manejo de errores y cierre abrupto |

### API de órdenes

`create_order()`, `submit_order()`, `submit_orders()` (batch), `cancel_order()`, `cancel_open_orders()`, `wait_for_order_execution()` (sync blocking), `wait_for_order_registration()`.

### Estado del portfolio

`get_position(symbol)`, `get_positions()`, `get_cash()`, `adjust_cash()`, `deposit_cash()`, `withdraw_cash()`.

**Lo bueno**: separación de concerns excelente. El usuario solo necesita pensar en `on_trading_iteration` y los `on_*_order` callbacks. La diferencia backtest vs live la absorbe el framework.

**Lo regular**: `sleeptime` como string ("180M") es ergonómico pero implica que el loop NO es event-driven puro a nivel `Strategy` — es polling con sleep. El `Broker` sí maneja eventos, pero la `Strategy` está sleeping entre iteraciones. Para una estrategia event-driven (DonchianATR sobre tick/bar new), tienes que polear o usar `on_filled_order` como proxy.

---

## 4. Abstracción `Broker` — el otro patrón a robar

```python
from lumibot.brokers import Alpaca, InteractiveBrokers

ALPACA_CONFIG = {"API_KEY": "...", "API_SECRET": "...", "PAPER": True}
broker = Alpaca(ALPACA_CONFIG)

# o
broker = InteractiveBrokers(IBKR_CONFIG)
```

**Diseño clave**:
- Una clase por broker, todas implementan la misma interface implícita.
- `PAPER: True/False` switch en config — mismo objeto, distinto endpoint. **Patrón a copiar literal en iguanatrader**.
- ENV vars `TRADING_BROKER` y `DATA_SOURCE` permiten **separar** broker de ejecución y broker de datos. Útil para usar IBKR para fills + Polygon para datos en backtest, por ejemplo.

**Brokers disponibles** (2026):
- **Equity/options**: Alpaca, Interactive Brokers, Schwab, Tradier
- **Cripto**: Binance, Coinbase, Kraken, KuCoin (vía CCXT wrapper)
- **Futures**: Tradovate, DataBento, Bitunix
- **Forex**: vía broker integrations existentes

---

## 5. Backtest engine

- **Mismo código** que live (la diferencia la absorbe el `Broker` que se inyecta).
- **Event-based** (no vectorizado): simula iteración a iteración.
- **Slippage** modelado vía entidad `TradingSlippage`.
- **Comisiones** modeladas vía entidad `TradingFee` (per-order o porcentual).
- **Data sources**: `YahooDataBacktesting` (gratis), `PolygonDataBacktesting` (premium), `DataBentoBacktesting` (premium futures), `AlpacaBacktesting` (data del propio broker).
- **Cash management**: `adjust_cash()`, `deposit_cash()`, `withdraw_cash()` registran flujos externos para que el equity curve refleje correctamente entradas/salidas de capital.

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

**Lo bueno**: API trivial. El método `run_backtest` es de la propia clase Strategy.

**Lo cuestionable**: no encontré modelo de slippage paramétrico configurable (5-15 bps small-cap / 1-3 bps large-cap como pide el plan de iguanatrader). Hay que verificar en el código si `TradingSlippage` permite ese nivel de granularidad o si es un valor fijo.

---

## 6. Risk engine — **EL HUECO GRAVE**

**Ningún módulo built-in para**:
- Risk caps (per-trade %, daily loss %, weekly loss %)
- Kill-switch
- Drawdown protection automática
- Pre-trade checks que rechacen órdenes
- Position sizing basado en ATR / volatilidad

Todo lo anterior es **responsabilidad del usuario** dentro de `on_trading_iteration`. Lumibot solo provee primitivas: `get_cash`, `get_positions`, `cancel_open_orders`. Si quieres caps 2/5/15, los implementas tú.

**Implicación para iguanatrader**: el `RiskEngine` que iguanatrader necesita escribir **es el principal aporte de valor sobre Lumibot**. Lumibot tiene engine + brokers + lifecycle; iguanatrader añade risk + approval + LLM observability.

---

## 7. AI/LLM integration — la sorpresa

Lumibot ha integrado **agentes LLM dentro del backtest loop** con un patrón notable:

- Los agentes razonan y llaman tools externos **en cada bar** durante simulación.
- **Replay caching**: la primera corrida de backtest persiste todas las llamadas LLM; corridas warm reutilizan el cache → reruns deterministas y casi gratis.
- Soporte para **MCP servers externos** como data sources / tools.
- "Same code for backtest and live" se extiende a los agentes — el agente corre idéntico en ambos modos.

**Esto es ORO para iguanatrader**: el patrón "replay cache de llamadas LLM" es exactamente lo que necesitas para que un backtest con LLM-orchestrated routines sea reproducible sin pagar tokens cada vez.

**Producto comercial encima**: **BotSpot.trade** — "Build trading bots using natural language and AI" (LLM genera estrategias). No es agentic auto-trade, es **LLM-as-codegen**.

---

## 8. HITL / approval gate — **NO existe**

No hay hooks nativos para approval humano por trade. El insertion point natural sería **interceptar `submit_order()`** desde la estrategia y meter ahí un wait sobre un signal externo (Telegram, webhook, etc.). Lumibot no lo provee, pero el lifecycle no lo bloquea.

---

## 9. Persistencia y configuración

- **`Variable Backup & Restore`**: documentación menciona persistencia de variables de Strategy entre runs. Implementación no detallada en docs públicas — habría que ver el código.
- **Configuración**: dict pasado al Broker + ENV vars (`TRADING_BROKER`, `DATA_SOURCE`). No usa pydantic/yaml nativo.
- **`parameters` first-class** en Strategy + hot-reload via `on_parameters_updated()`. Bueno.

**Multi-tenancy**: NO. Lumibot asume single-strategy single-broker single-user. Para multi-tenant habría que envolverlo en una capa externa.

---

## 10. Lumiwealth — la capa comercial

Lumibot OSS (GPL-3.0) es la base. Encima Lumiwealth vende:

| Producto | Qué es |
|---|---|
| **BotSpot.trade** | Plataforma SaaS donde describes la estrategia en NL y un LLM la genera + corre. |
| **Algorithmic Trading course** | Curso de pago. |
| **Machine Learning for Trading course** | Curso de pago. |
| **Options Trading course** | Curso de pago. |

**Modelo monetización**: education-flywheel + SaaS premium encima del OSS. Análogo a QuantStart/Jesse.

**Implicación legal**: Lumiwealth puede vender BotSpot porque **ellos** son los autores del OSS GPL-3.0 y mantienen dual-licensing implícito. **Un tercero NO puede hacer lo mismo legalmente** sin liberar todo el SaaS bajo GPL-3.0.

---

## 11. Governance y bus factor

- **Maintainer**: Lumiwealth (empresa). Bus factor estimado **medio**: dependes del survival de la corp, pero no de un único individuo.
- **Ritmo**: commits regulares 2026.
- **Comunidad**: pequeña (~1.4k stars). Tracción modesta vs Lean (18.6k) o Freqtrade (30k).
- **Política de breaking changes**: branch default es `dev` → no garantizan estabilidad de API release-to-release.

---

## 12. **5 patrones a ROBAR** para iguanatrader

1. **`Strategy` lifecycle de 12 hooks** — copia literal la separación `initialize` / `before_market_opens` / `on_trading_iteration` / `on_filled_order`. Limpia y testeable.
2. **`Broker` switch via config dict + flag `PAPER`** — mismo objeto, distinto endpoint. Adaptar para `IBKR(config={'PAPER': True})` desde día 1, evita el dual-class `IbkrPaper` + `IbkrLive`.
3. **ENV vars `TRADING_BROKER` + `DATA_SOURCE`** — separación broker-de-ejecución vs broker-de-datos. Útil cuando IBKR fills + Polygon data históricos.
4. **Replay caching de llamadas LLM en backtest** — patrón crítico para reproducibilidad. Implementar en `CostMeter`: hash del prompt → cache JSON; en backtest, lee cache; en live, llama API real y persiste.
5. **`parameters` first-class + `on_parameters_updated()` hot-reload** — permite tunear DonchianATR via Telegram (`/set period 20`) sin reiniciar el bot.

## 13. **3 anti-patrones a EVITAR**

1. **Licencia GPL-3.0 sin dual-licensing** — bloquea la trayectoria SaaS comercial. iguanatrader debe usar **Apache-2.0 + Commons Clause** desde el primer commit.
2. **Risk engine ausente built-in** — Lumibot lo deja al usuario. iguanatrader debe hacerlo **obligatorio y no-bypaseable**: las estrategias proponen, el `RiskEngine` filtra/recorta/rechaza ANTES del approval gate. No opt-in.
3. **`sleeptime` polling como modelo principal** — Lumibot itera por sleep. Para iguanatrader (event-driven sobre bars/news/alertas), el modelo correcto es asyncio + queues + event loop sobre IBKR streaming, no polling.

---

## 14. Verdict honesto para iguanatrader

**¿Forkear?** **NO**. La GPL-3.0 mata la opción SaaS comercial cerrado. Aunque iguanatrader empezara como OSS GPL-3.0 también, perderías la opcionalidad de cambiar de modelo sin reescribir.

**¿Copiar interfaces?** **SÍ, agresivamente**. El `Strategy` lifecycle, el `Broker` config-switch, el patrón replay-cache de LLM. Estos tres patrones por separado ya justifican el deep-dive.

**¿Ignorar?** **NO**. BotSpot.trade es competencia directa con la trayectoria comercial de iguanatrader; hay que estudiarla.

**Decisión operativa para el PRD**: Lumibot queda como **referencia de diseño obligada** (linkear este documento desde `docs/architecture-decisions.md` ADR-001) y como **competidor a vigilar** (no a reemplazar — el approval gate por trade + cost observability del propio LLM stack siguen siendo huecos que Lumibot/BotSpot no cubren).
