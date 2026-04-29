# Freqtrade — Deep-dive técnico para iguanatrader

**Fecha:** 2026-04-27
**Repo:** https://github.com/freqtrade/freqtrade
**Docs:** https://www.freqtrade.io/en/stable/
**Maintainer:** Comunidad + Matthias Voppichler (lead)
**Branch default:** `develop`
**Última actividad:** 2026-04-27 (commits hoy mismo)
**Stars:** 49.440 ⚠️ (la research previa decía 30k — el más popular del ecosistema **por mucho**)
**Licencia:** **GPL-3.0**

---

## 1. Veredicto rápido (TL;DR)

Freqtrade es **la fuente más rica de patrones a robar** del ecosistema OSS, aunque sea cripto-only y GPL-3.0 (no usable como base para iguanatrader). Tres pilares oro: **(1)** el set completo de comandos Telegram (es la UX que iguanatrader necesita literal), **(2)** el sistema de **Protections** (risk management built-in modular y obligatorio), **(3)** el modelo `dry-run` desde día 1.

**Para iguanatrader**: copiar el patrón Telegram **directo**, copiar la arquitectura de Protections **directo**, ignorar lo demás.

---

## 2. Comandos Telegram — el catálogo completo

Freqtrade expone **~30 comandos Telegram**, divididos en 5 categorías. Esto es **el catálogo más completo del ecosistema OSS**.

### Sistema
| Comando | Args | Función |
|---|---|---|
| `/start` | — | Arranca el trader |
| `/pause` (alias `/stopentry`) | — | Pausa nuevas entradas, mantiene gestión de trades abiertos |
| `/stop` | — | Para el trader completo |
| `/reload_config` | — | Recarga el config sin reiniciar el bot |
| `/show_config` | — | Muestra parte de la config actual |
| `/logs` | `[limit]` | Últimos N mensajes de log |
| `/help` | — | Help |
| `/version` | — | Versión del bot |

### Status & info
| Comando | Args | Función |
|---|---|---|
| `/status` | `[trade_id]` | Lista trades abiertos (todos o uno específico) |
| `/status table` | — | Tabla de trades abiertos con marca de pending |
| `/order` | `<trade_id>` | Lista de órdenes de un trade |
| `/trades` | `[limit]` | Últimos N trades cerrados |
| `/count` | — | Trades abiertos / disponibles |
| `/locks` | — | Pares actualmente locked |
| `/unlock` | `<pair or lock_id>` | Quita lock |
| `/marketdir` | `[long\|short\|even\|none]` | Muestra/cambia dirección de mercado |

### Modificación de trades
| Comando | Args | Función | Restricción |
|---|---|---|---|
| `/forceexit` (alias `/fx`) | `<trade_id>` o `all` | Cierra trade(s) ignorando `minimum_roi` | — |
| `/forcelong` | `<pair> [rate]` | Compra inmediata | `force_entry_enable: true` |
| `/forceshort` | `<pair> [rate]` | Venta corta inmediata | Solo non-spot, `force_entry_enable: true` |
| `/delete` | `<trade_id>` | Borra trade de la DB | Manual exchange handling |
| `/reload_trade` | `<trade_id>` | Recarga trade desde exchange | Solo live |
| `/cancel_open_order` (alias `/coo`) | `<trade_id>` | Cancela orden abierta |

### Performance & finanzas
| Comando | Args | Función |
|---|---|---|
| `/profit` | `[n]` (días) | Resumen P&L de trades cerrados |
| `/profit_long` / `/profit_short` | `[n]` | Idem solo long / solo short |
| `/performance` | — | P&L por par (símbolo) |
| `/balance` | `[full]` | Balance gestionado o full por currency |
| `/daily` | `[n=7]` | P&L por día últimos N días |
| `/weekly` | `[n=8]` | P&L por semana |
| `/monthly` | `[n=6]` | P&L por mes |
| `/stats` (alias `/exits`, `/entries`) | — | Wins/losses por exit reason + holding durations |

### Pair management
| Comando | Args | Función |
|---|---|---|
| `/whitelist` | `[sorted] [baseonly]` | Whitelist actual |
| `/blacklist` | `[pair]` | Muestra blacklist o añade un par |

### Mecánicas clave
- **Custom keyboard buttons**: comandos predefinidos como botones inline (sin args).
- **`authorized_users`**: lista de user IDs Telegram autorizados; rechaza el resto.
- **`notification_settings`**: granularidad de qué eventos disparan notificación.
- **`/reload_config`**: hot-reload sin reiniciar — patrón valioso.

---

## 3. Mapping Freqtrade → iguanatrader (set propuesto)

iguanatrader no necesita los 30 comandos. Mapping recomendado:

| Freqtrade | iguanatrader equivalente | Función en iguanatrader |
|---|---|---|
| `/start` | `/start` | Arranca routines (no trades — los trades requieren approval) |
| `/stop` | `/stop` | Para todo |
| `/pause` | `/pause` | Para nuevas propuestas, mantiene posiciones abiertas |
| `/reload_config` | `/reload_config` | Hot-reload de risk caps, watchlist, etc. |
| — | **`/propose <strategy> <symbol>`** | Fuerza generación de una propuesta manual (research mode) |
| `/forcelong` | **`/approve <proposal_id>`** | Aprueba una propuesta pending (botón inline) |
| — | **`/reject <proposal_id>`** | Rechaza una propuesta (botón inline) |
| `/forceexit` | **`/forceexit <trade_id>`** | Cierra posición abierta (con confirmación) |
| `/status` | `/status` | Posiciones abiertas + propuestas pending |
| `/balance` | `/balance` | Cash + holdings + total equity |
| `/profit` | `/profit [days=1]` | P&L del día/periodo |
| `/daily` | `/daily [n=7]` | P&L por día |
| `/weekly` | `/weekly [n=4]` | P&L por semana |
| `/performance` | `/performance` | P&L por símbolo |
| `/trades` | `/trades [limit=10]` | Últimos N trades cerrados |
| `/logs` | `/logs [limit=20]` | Últimas N entradas de log |
| — | **`/risk_status`** | Estado actual de risk caps (cuánto consumido del 5% diario, 15% semanal) |
| — | **`/cost_today`** y `/cost_week` | Coste LLM acumulado |
| — | **`/halt`** | Activa kill-switch (escribe `.killswitch` file) |
| — | **`/resume`** | Quita kill-switch |
| `/version` | `/version` | Versión del bot |
| `/help` | `/help` | Help |

**Total: ~17 comandos**. Suficientes para cubrir el flow approval-gate + observabilidad de iguanatrader.

**Botones inline (Telegram callback queries)** para cada propuesta:
```
🟢 Aprobar (botón) | 🔴 Rechazar (botón) | ✏️ Modificar (botón)
```

**Mismo set sobre WhatsApp** vía Hermes/Meta API. La capa `ApprovalChannel` traduce el comando text-based a la API correspondiente.

---

## 4. `IStrategy` interface — vectorizada (no event-driven)

A diferencia de Lumibot/Nautilus/Lean (event-driven), Freqtrade es **vectorizado sobre pandas DataFrames**:

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

### Tres métodos mandatory
- `populate_indicators(df, metadata)` — añade indicadores técnicos al df.
- `populate_entry_trend(df, metadata)` — setea `enter_long` / `enter_short` columns (1 ó 0).
- `populate_exit_trend(df, metadata)` — setea `exit_long` / `exit_short` columns.

### Atributos clave
- `minimal_roi`: **time-based ROI dict** — *"a los 0min sal con 4%, a los 20min con 2%, a los 30min con 1%, a los 40min sal sí o sí"*. Patrón muy elegante — ROI degradado en el tiempo.
- `stoploss`: porcentaje base.

### Callbacks (override de comportamiento por trade)
- `custom_entry_price()` — pricing inteligente vs proposed rate.
- `custom_exit_price()` — idem para exits.
- `custom_stake_amount()` — sizing dinámico (ej. menos riesgo si más trades abiertos).
- `custom_stoploss()` — trailing stops o stoploss dinámico.
- `leverage()` — para futuros.
- `confirm_trade_entry()` — **gate booleano antes de entrar** (orderbook check, etc.). **Esto es exactamente el patrón approval-gate, pero implementado con código en vez de humano**.
- `confirm_trade_exit()` — gate booleano antes de salir.

**`confirm_trade_entry` es el insertion point natural para meter approval humano en una integración con Freqtrade**. Pero como Freqtrade es cripto + GPL, mejor robar el concepto y reimplementar.

---

## 5. Protections — risk management built-in modular

Freqtrade tiene una **arquitectura de Protections** declarativa via config:

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

**Protections built-in**:
| Protection | Función |
|---|---|
| **StoplossGuard** | Pausa entries tras N stoploss consecutivos en lookback window |
| **MaxDrawdown** | Pausa si drawdown excede threshold |
| **CooldownPeriod** | Tiempo mínimo entre trades del mismo par |
| **LowProfitPairs** | Bloquea pares que no rinden en lookback |
| **ProfitExitGuard** | Customiza behavior de exit en profit targets |

**Implicación para iguanatrader**: la **arquitectura declarativa de protections** es exactamente lo que iguanatrader necesita para risk caps:

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

Cada protection es una clase pluggable, `enable_protections: true` es un kill-switch maestro. **Patrón a copiar literal**.

---

## 6. Modes operativos — `dry-run` desde día 1

Freqtrade tiene 4 modos:
- `dry-run` (paper) — simula fills contra precios reales.
- `live` (real money).
- `backtesting` — corre histórico.
- `hyperopt` — parameter sweeps via Optuna.

**Switch via single config flag**: `"dry_run": true/false`. **Patrón crítico** — research previa lo destacó como antídoto a "muerte por exposición prematura a live".

Para iguanatrader: `iguana paper` y `iguana live` deben ser **el mismo binario**, mismo código, distinto flag. **Nunca dos código bases**.

---

## 7. Hyperopt (Optuna)

Parameters opcionales declarables en la Strategy:
```python
from freqtrade.strategy import IntParameter, RealParameter, BooleanParameter, CategoricalParameter

class OptimizedStrategy(IStrategy):
    rsi_period = IntParameter(7, 20, default=14, space='buy')
    rsi_threshold = RealParameter(20.0, 40.0, default=30.0, space='buy')
    use_volume_filter = BooleanParameter(default=True, space='buy')
    trend_type = CategoricalParameter(['ema', 'sma', 'tema'], default='ema', space='buy')
```

Run: `freqtrade hyperopt --strategy OptimizedStrategy --spaces buy`.

**Implicación para iguanatrader**: cuando hagas grid-search sobre DonchianATR (lookback period, ATR multiplier), este patrón declarativo es replicable trivialmente con `optuna`. iguanatrader puede usar `vectorbt` para sweeps masivos (research) y `optuna` para optimización dirigida — ambos compatibles.

---

## 8. Anti-patterns documentados ("Looking into the future")

Freqtrade documenta explícitamente los pitfalls de backtest leakage:
- `shift(-1)` → leak directo de futuro.
- `.iloc[-1]` en populate → varía según runmode.
- `.mean()` sobre el df entero → incluye futuro.
- `.resample()` sin `label='right'` → leak.

**Patrón a robar**: documentar estos anti-patterns en `docs/strategies/leakage-checklist.md` de iguanatrader como **checklist obligatorio** antes de aceptar cualquier estrategia nueva.

---

## 9. Persistencia y multi-tenant

- **SQLAlchemy** con SQLite por default (Postgres opcional).
- **Schema**: `Trade`, `Order`, `PairLock`. Append + update (no append-only puro).
- **Multi-tenant**: NO. Single-instance por design. Para multi-user se corre un proceso por user (típicamente Docker container).

**Implicación para iguanatrader**: el modelo "1 proceso por user" en containers es **el patrón realista** para cripto-trading SaaS. Hummingbot lo hace igual. iguanatrader puede ir directo a este modelo en v2 SaaS sin reescribir el core.

---

## 10. Governance y bus factor

- **Maintainer principal**: Matthias Voppichler. Comunidad activa de contributors.
- **Stars**: 49.440 (el más popular del ecosistema).
- **Bus factor estimado**: medio-alto. Aunque hay un lead claro, hay >300 contributors y la comunidad activa indica que un takeover en caso de salida sería viable.
- **Roadmap**: público en GitHub Discussions.
- **License GPL-3.0**: bloquea SaaS comercial cerrado encima.

---

## 11. **5 patrones a ROBAR** para iguanatrader

1. **Set completo de comandos Telegram** — copiar literal el catálogo (ver §3 mapping). Especialmente `/reload_config` para hot-reload de risk caps, `/forceexit` para emergency, `/pause` para parar nuevas entradas sin abandonar gestión.
2. **Protections como arquitectura declarativa** — kill-switch maestro `enable_protections: true` + lista de protections pluggables en yaml. Risk caps de iguanatrader (`DailyLossCap`, `WeeklyLossCap`, `PerTradeRisk`, `MaxOpenPositions`) implementadas como clases que cumplen una interface común.
3. **`dry-run` mode como flag único** — mismo binario, mismo código, `paper: true/false` switch. Inviolable.
4. **`confirm_trade_entry()` callback** — gate booleano antes de entrar. iguanatrader usa exactamente esto pero con humano-en-Telegram en lugar de código (`if not approval_received(): return False`).
5. **Anti-pattern checklist documentado** — los "Looking into the future" pitfalls (shift, iloc, mean, resample). Documentar en `docs/strategies/leakage-checklist.md` como obligatorio para cualquier strategy review.

## 12. **3 anti-patrones a EVITAR**

1. **Vectorizado pandas como modelo principal** — Freqtrade usa DataFrames vectorizados (rápido para backtests, raro para event-driven). iguanatrader necesita event-driven puro (cada bar/news/halt es un evento). El modelo Lumibot/Nautilus es correcto, no el de Freqtrade.
2. **Acoplamiento a CCXT** — Freqtrade asume cripto exchanges via CCXT. Su `Trade` model tiene fields cripto-specific (base/quote currency). iguanatrader sobre IBKR equity tiene un modelo más simple — no copiar el schema cripto.
3. **GPL-3.0 license** — bloquea SaaS comercial. Mismo punto que con Lumibot. iguanatrader = Apache-2.0 + Commons Clause.

---

## 13. Verdict honesto para iguanatrader

**¿Forkear?** **NO**. Cripto-only + GPL-3.0 + arquitectura vectorizada incompatible con tu enfoque event-driven equity.

**¿Copiar interfaces?** **MUY SÍ**. **Tres patrones obligatorios robar**:
1. El catálogo Telegram completo (mapping en §3).
2. La arquitectura de Protections declarativa.
3. `confirm_trade_entry` como gate booleano.

**¿Como referencia UX?** **OBLIGADO**. Es el único OSS con UX battle-tested para retail-bot por Telegram. Cualquier feature que dudas si añadir o no, mira si Freqtrade lo tiene — si sí, hay razón empírica.

**Decisión operativa para el PRD**:
- ADR-006: "iguanatrader implementará Protections como arquitectura declarativa siguiendo el patrón Freqtrade. Risk caps (per-trade, daily, weekly) son protections individuales pluggables vía yaml. Kill-switch maestro `enable_protections: true`."
- ADR-007: "El catálogo de comandos Telegram de iguanatrader replica el set Freqtrade adaptado al flow approval-gate (mapping documentado en `docs/research/platforms/freqtrade.md` §3). El mismo catálogo se expone sobre WhatsApp via Hermes."
