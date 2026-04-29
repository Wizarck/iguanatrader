# NautilusTrader — Deep-dive técnico para iguanatrader

**Fecha:** 2026-04-27
**Repo:** https://github.com/nautechsystems/nautilus_trader
**Docs:** https://nautilustrader.io/docs/latest/
**Maintainer:** Nautech Systems Pty Ltd (corporación australiana)
**Branch default:** `develop`
**Última actividad:** 2026-04-27 (commits hoy mismo)
**Stars:** 22.288 ⚠️ (la research previa decía 2.7k — error de un orden de magnitud; **es más popular que Lean**)
**Licencia:** **LGPL-3.0**

---

## 1. Veredicto rápido (TL;DR)

NautilusTrader es **el engine más serio del ecosistema Python OSS** en 2026: Rust-native core, determinismo nanosecond-resolution, MessageBus + engines separados, RiskEngine con pre-trade checks built-in, IBKR adapter completo. **Más popular que Lean** (22k vs 18k stars). Modelo de 3 tiers comercial (OSS / Pro / Cloud).

**Para iguanatrader**: arquitectura **a robar agresivamente** (MessageBus + engines separados es el oro del proyecto). Como base de código, **overkill para el MVP single-user** pero **candidato fuerte como engine subyacente para v2 multi-tenant SaaS**. La LGPL-3.0 es manejable (linking dinámico permite SaaS comercial cerrado encima).

---

## 2. Arquitectura general — el patrón maestro

La arquitectura es **el value-add principal** del proyecto. 6 componentes separados que se comunican por message bus:

| Componente | Rol |
|---|---|
| **NautilusKernel** | Orquestador central. Inicializa componentes, configura messaging, gestiona lifecycle. |
| **DataEngine** | Procesa y rutea market data (quotes, trades, bars, order books, custom data) a consumers. |
| **ExecutionEngine** | Lifecycle completo de órdenes — routing a adapters, tracking de orders/positions, coordina risk checks, maneja execution reports y fills. |
| **RiskEngine** | **Pre-trade risk checks + validation**. Position monitoring + real-time risk calc. |
| **Cache** | "High-performance in-memory storage" — instruments, accounts, orders, positions. **Crítico**: actualizado ANTES de que handlers se ejecuten (ordering guarantee). |
| **MessageBus** | Backbone de comunicación inter-componente. Pub/Sub, Request/Response, Command/Event. Soporte opcional Redis para durabilidad cross-restart. |

**Filosofía**: *"Data corruption is worse than no data"* — fail-fast en validación, rejection inmediata antes de mandar al venue.

---

## 3. Path de ejecución (signal → fill)

```
Strategy.submit_order(order)
    │
    ▼
[MessageBus] Command: SubmitOrder
    │
    ▼
RiskEngine.check_pre_trade()
    ├── Position limits
    ├── Notional exposure limits
    └── Order rate limits
    │
    ├─❌ Failed → OrderDenied event → Strategy.on_order_denied()
    └─✅ Passed
            │
            ▼
        ExecutionClient (broker adapter)
            │
            ▼
        Venue (IBKR, Binance, etc.) via REST/WebSocket
            │
            ▼
        Venue response: Accepted | Filled | Canceled | Rejected | Expired
            │
            ▼
        ExecutionEngine actualiza Cache
            │
            ▼
        MessageBus event → Strategy handler (on_order_filled, etc.)
```

**Lo crítico para iguanatrader**: el RiskEngine es **un engine separado, no un mixin opcional dentro de Strategy**. Estrategias proponen, RiskEngine filtra de manera **no-bypaseable**. Exactamente lo que iguanatrader necesita para risk caps 2/5/15.

---

## 4. Determinismo backtest↔live

El verdadero diferencial técnico:

- **Nanosecond-resolution clock** consistente entre backtest y live.
- **Deterministic event-driven core**: el orden de eventos es reproducible.
- **Single-threaded kernel** → no hay race conditions ocultas.
- **Cache-before-handler**: cuando `on_quote_tick(quote)` se ejecuta, `self.cache.quote_tick(instrument_id)` ya devuelve esa misma quote (ordering guarantee explícito).
- **Mismo runtime**: backtest y live usan el mismo `NautilusKernel` con distinto `Clock` y distinto `ExecutionClient`. **No son dos engines distintos cosidos**.

**Implicación**: en Lumibot/Lean tienes "mismo código" pero "engines distintos detrás de la abstracción". En Nautilus tienes **mismo runtime real** — el determinismo es de otro nivel.

---

## 5. Strategy interface — Python first-class

Aunque el core es Rust, **el usuario escribe estrategias 100% en Python** sin tocar Rust nunca. Lifecycle (parcial, basado en docs):

| Hook | Cuándo |
|---|---|
| `on_start()` | Activación de la estrategia |
| `on_quote_tick(quote)` | Cada quote tick subscrito |
| `on_trade_tick(trade)` | Cada trade tick |
| `on_bar(bar)` | Cada bar agregado |
| `on_event(event)` | Eventos custom del MessageBus |
| `on_order_accepted/filled/canceled/rejected/expired` | Lifecycle de órdenes |
| `on_order_denied` | Rejected por RiskEngine |
| `on_stop()` | Shutdown limpio |

**API de submit**: `self.submit_order(order)` (igual que Lumibot/Lean).

**Acceso al estado**: `self.cache.<entity>(id)` (positions, orders, instruments, accounts).

---

## 6. Boundary Rust ↔ Python

- **Rust**: hot paths críticos — MessageBus dispatch, Cache accesses, time/clock, parsing de market data, serialization.
- **Python**: Strategy API, configuración, integración con ML/AI frameworks, ejemplos.
- **PyO3** como pegamento (binding Rust → Python).

**Para el dev solo Python**: nunca tocas Rust. Pero **debugging de bugs profundos requiere leer Rust**, y eso eleva la barra de contribución externa.

---

## 7. Adapter IBKR

Mencionado como integración primera (junto a Binance, Bybit, Kraken, OKX, Betfair, BitMEX, Deribit, dYdX, Hyperliquid, Deutsche Börse, Tardis.dev). No tuve tiempo de auditar el código del adapter en este pase, pero es **adapter nativo del proyecto** (no community-maintained). Calidad esperada alta dado el rigor del core.

**Caveat conocido**: el research previa mencionó issues con Python 3.14. Verificar antes de adoptar.

---

## 8. Persistencia, Cache y multi-tenant

- **Cache in-memory** primaria (rápida).
- **Redis opcional** para durabilidad cross-restart del MessageBus.
- **Catalog**: persistencia de market data en Parquet (research-driven).
- **Multi-tenancy**: NO out-of-box. El kernel asume single-tenant. Para SaaS multi-tenant habría que correr **un kernel por tenant** (proceso aislado o container) o reescribir Cache + MessageBus con tenant-aware routing.

**Implicación para iguanatrader v2 SaaS**: el modelo "1 kernel por user" en containers k8s es factible y limpio. Mejor que intentar refactorizar el kernel a multi-tenant interno.

---

## 9. HITL / approval gate — **NO existe**

No hay hooks nativos para approval humano por trade. **Insertion point natural en Nautilus**: meter un componente custom suscrito al MessageBus que intercepte el evento `SubmitOrder` ANTES de que llegue al RiskEngine. El componente:

1. Publica un evento `ApprovalRequested(order)` al MessageBus.
2. Espera (con timeout) un evento `ApprovalGranted(order_id)` o `ApprovalRejected(order_id)`.
3. Si granted → republica `SubmitOrder` para que siga el flow normal.
4. Si rejected/timeout → publica `OrderDenied` con razón.

**Esto es un pattern limpio gracias al MessageBus**. En Lumibot tendrías que monkey-patchear `submit_order()`, que es feo. En Nautilus es un componente más.

---

## 10. Modelo comercial — 3 tiers

| Tier | Qué es | Para quién |
|---|---|---|
| **Open Source** | LGPL-3.0 en GitHub. Todo el engine + adapters. | Devs, prosumer, hedge funds que quieren control total. |
| **Pro** | "Production-grade, user-controlled infrastructure". | Hedge funds que quieren soporte + features pro. |
| **Cloud Platform** | "Managed cloud trading infrastructure". | Quants que no quieren operar infra. |

Pricing no público. Competidor directo de QuantConnect Cloud.

**Implicación para iguanatrader**: el modelo OSS+Pro+Cloud es **el template a seguir** si la trayectoria SaaS se materializa. Más limpio que Lumiwealth (educación-driven) o Lumibot (sin tiers definidos).

---

## 11. Governance y bus factor

- **Maintainer**: Nautech Systems Pty Ltd (corp australiana). Bus factor estimado **alto** — corp con incentivo financiero claro.
- **Ritmo**: releases bi-semanales. Commits diarios.
- **Comunidad**: 22.288 stars. Discord activo.
- **API stability**: aún "becoming more stable". Admiten breaking changes entre releases. **Riesgo real para un MVP que quiere estabilidad**.
- **License**: LGPL-3.0. Para SaaS comercial cerrado encima de Nautilus → **debes usar dynamic linking** (no static) y permitir al usuario reemplazar la librería. Manejable pero no tan libre como Apache.

---

## 12. **5 patrones a ROBAR** para iguanatrader

1. **MessageBus + Engines separados** (`DataEngine`, `ExecutionEngine`, `RiskEngine`, `Cache`). Implementable en Python con `asyncio.Queue` + pub/sub interno. **El RiskEngine como componente NO bypaseable es el patrón clave** para iguanatrader (caps 2/5/15 que las estrategias no pueden saltar).
2. **Cache-before-handler ordering guarantee**: cuando un evento se entrega al handler, el Cache ya está actualizado con el dato del evento. Evita "lecturas stale" desde la Strategy.
3. **Approval gate como componente MessageBus-suscrito** (no como monkey-patch de submit_order). Limpio, testeable, opt-in via config.
4. **Single-threaded kernel + nanosecond clock** para determinismo. Para MVP suficiente con asyncio single-event-loop + clock con resolución microsecond (Python time.perf_counter_ns).
5. **Modelo comercial 3-tier OSS/Pro/Cloud** como template para iguanatrader v3 SaaS. Más claro que el modelo "education-flywheel" de Lumiwealth/QuantStart.

## 13. **3 anti-patrones a EVITAR**

1. **Rust core en MVP** — overkill brutal para iguanatrader single-user. Python puro es suficiente para el throughput de un retail con DonchianATR sobre <50 tickers. La complejidad de mantener Rust no se amortiza hasta multi-tenant SaaS con cientos de cuentas.
2. **API breaking changes entre releases** — Nautilus admite que rompe entre minor versions. iguanatrader debe pinear versiones agresivamente (poetry lock + dependabot manual) y NO depender de "última versión" para nada en producción.
3. **LGPL-3.0 para tu propio engine** — manejable pero introduce fricción legal en cada update del SaaS. iguanatrader debe usar **Apache-2.0 + Commons Clause** para no pelear esa batalla.

---

## 14. Verdict honesto para iguanatrader

**¿Forkear en MVP?** **NO**. Overkill técnico (Rust), API inestable, complejidad de setup.

**¿Copiar arquitectura?** **SÍ, agresivamente**. El MessageBus + RiskEngine separado + Cache-before-handler son patrones que iguanatrader debe replicar en su capa Python pura desde día 1. **Esto es la lección arquitectónica más valiosa del ecosistema OSS**.

**¿Como engine subyacente en v2?** **CANDIDATO FUERTE**. Cuando iguanatrader llegue a multi-tenant SaaS y el throughput de un Python puro no llegue, migrar el engine a Nautilus (manteniendo la API de Strategy de iguanatrader como wrapper sobre Nautilus.Strategy) es una jugada limpia. La LGPL es manejable con dynamic linking.

**¿Aprender de su modelo comercial?** **SÍ**. El 3-tier OSS/Pro/Cloud es lo que iguanatrader v3 SaaS debe imitar (más claro que Lumiwealth o Jesse).

**Decisión operativa para el PRD**:
- ADR-002: "iguanatrader replicará la arquitectura MessageBus + Engines separados de NautilusTrader en Python puro para el MVP. Migración a Nautilus como engine subyacente queda en backlog v2."
- ADR-003: "iguanatrader usará Apache-2.0 + Commons Clause como licencia, NO LGPL ni GPL. Razón: preservar opcionalidad de SaaS comercial cerrado en v3."
