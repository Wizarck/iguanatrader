# OSS Algorithmic Trading Landscape — Investigación para iguanatrader

**Fecha:** 2026-04-26
**Autor:** Claude (research agent)
**Audiencia:** PM (John) → discovery del PRD de iguanatrader
**Alcance:** Plataformas open-source de trading algorítmico relevantes para el MVP single-user (Python + IBKR + LangGraph + human-approval) y para la visión a largo plazo (OSS core + SaaS multi-tenant).

---

## 1. Executive Summary

- **El espacio OSS de trading algorítmico está MUY vivo en 2026**, pero polarizado: dos núcleos serios para retail/prosumer (QuantConnect Lean, NautilusTrader), un dominio aplastante de Freqtrade en cripto, y una larga cola de proyectos zombi (Backtrader, PyAlgoTrade, bt, Catalyst).
- **Ningún proyecto OSS combina** los cuatro pilares de iguanatrader: (a) backtest↔live parity en Python, (b) IBKR de primera clase, (c) human-approval-gate vía Telegram + dashboard, (d) orquestación LangGraph/LLM con observabilidad de coste. Existen partes; no existe el todo.
- **Lean es el "rey por defecto"** para equity/futuros/multi-asset retail (Apache 2.0, 18.6k★, 13k+ commits, dual-stack Python/C#, mismo código backtest↔live, IBKR built-in). Si iguanatrader fuera "yet another quant platform", la respuesta sería "use Lean y termina la conversación". No lo es.
- **NautilusTrader es la apuesta técnica más fuerte de la nueva generación** (Rust core + Python control plane, event-driven determinista, LGPL-3.0, 2.7k★, releases bi-semanales, IBKR adapter nativo). Más limpio arquitectónicamente que Lean pero con menos community.
- **Freqtrade domina cripto** (no aplica a IBKR/equities) pero es el **único OSS con Telegram/webUI maduros para human-in-the-loop** — patrón a robar literal.
- **Lumibot es el competidor más cercano al MVP de iguanatrader**: Python-puro, IBKR + Alpaca + crypto, mismo código backtest↔live, AI hooks (BotSpot/LLM sentiment), open-source con SaaS comercial encima (Lumiwealth). **Candidato #1 para fork o "be a wrapper around"**.
- **Modelo OSS+SaaS multi-tenant tiene precedentes claros y rentables**: QuantConnect Cloud (sobre Lean Apache-2.0), Lumiwealth (sobre Lumibot), Hummingbot (sobre HBOT, monetiza vía exchange-fee-share, no SaaS clásico), Composer (no es OSS pero es el benchmark de UX y pricing $40/mes en este vertical). Vectorbt PRO usa Apache-2.0 + Commons Clause como bloqueo a forks comerciales — patrón legal a copiar.
- **El gap real que cubre iguanatrader**: **trading retail con LLM-orchestrated routines + human approval gate explícito + cost observability del propio LLM stack**. Nadie lo hace bien hoy. TradingAgents (académico) y LLM-trading-agents (Medium hype) están en el lado opuesto: full-auto sin approval gate. Composer está cerca (no-code visual + AI) pero cerrado y sin LLM-agent layer.
- **Pitfalls históricos a evitar**: Quantopian murió por (a) modelo de negocio basado en regalar y monetizar después con un fondo que falló y (b) overfitting masivo del crowdsource. Backtrader/PyAlgoTrade/bt murieron por **bus factor = 1**. Catalyst murió arrastrado por SEC / Enigma. Lección: **mantener bus factor ≥ 2, monetizar antes y modesto, no apostar la viabilidad a un único alpha**.
- **Veredicto adelantado** (detalle en §8): **construir desde cero el orquestador LLM + approval gate + cost layer**, pero **no reinventar el engine de backtest/execution**. Hacer wrapping fino sobre `ib_async` para el MVP; mantener Lean y NautilusTrader como opciones de migración del engine cuando se escale al SaaS.

---

## 2. Tabla comparativa

| Plataforma | URL | Vivo | ★ | Licencia | Stack | Brokers | Arquitectura | Backtest↔Live parity | Risk engine | Multi-tenant ready | HITL approval | Modelo de negocio | Verdict (1 línea) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **QuantConnect Lean** | github.com/QuantConnect/Lean | Vivo (commits semanales 2026) | 18.6k | Apache-2.0 | C# core + Python via PythonNet | IBKR, Alpaca, Binance, Bybit, Coinbase, OANDA, Tradier, TradeStation, Kraken, Bitfinex, Bitstamp, Zerodha, Tradier, Wolverine | Event-driven | Sí (mismo algoritmo) | Sí (built-in: position sizing, drawdown limits, brokerage models) | Diseñado para multi-tenant (es lo que corre QC Cloud) | No nativo (extensible) | OSS Apache + SaaS QC Cloud (free → enterprise $thousands/mes) | El estándar de facto multi-asset con SaaS probada |
| **NautilusTrader** | github.com/nautechsystems/nautilus_trader | Muy vivo (releases bi-weekly, 2026) | 2.7k | LGPL-3.0 | Rust core + Python control plane | IBKR, Binance (spot/futures), Bybit, dYdX, Coinbase Intl, Polymarket, Databento | Event-driven determinista | Sí (mismo runtime y time model) | Sí (modular: risk engine separado del execution engine) | Diseñado para production multi-strategy (no multi-tenant out-of-box) | No | Pure OSS (corp Nautech Systems detrás) | El más limpio arquitectónicamente, futuro probable líder |
| **Freqtrade** | github.com/freqtrade/freqtrade | Muy vivo (commits diarios, abril 2026) | ~30k | GPL-3.0 | Python | Solo cripto (Binance, Kraken, OKX, Bybit, etc. via CCXT) | Event-driven | Sí | Sí (stoploss, tiered, trailing, max-drawdown protection) | No (single-instance por design) | **Telegram + webUI (FreqUI)** maduros | OSS puro + ecosystem de cursos/comunidad | El rey indiscutible de cripto retail; **patrón Telegram a copiar** |
| **Lumibot** | github.com/Lumiwealth/lumibot | Vivo (3.x en 2026) | ~2k | Apache-2.0 (parece) | Python | **IBKR**, Alpaca, Tradier, Coinbase, Binance, Kucoin, TradeStation, Theta Data | Event-driven | Sí (mismo código) | Sí (basic) | Diseñado para individual; SaaS Lumiwealth multi-user | No nativo, pero "BotSpot" añade LLM sentiment | OSS Apache + Lumiwealth SaaS comercial | **El competidor MÁS CERCANO al MVP de iguanatrader** |
| **vectorbt** (OSS) | github.com/polakowo/vectorbt | Mantenimiento mínimo; foco se desplazó a PRO | ~5k | Apache-2.0 + **Commons Clause** | Python (NumPy/Numba) | N/A (research-only) | Vectorizado | No (research-only) | Limitado | N/A | N/A | OSS gratis para research; **PRO de pago** | Mejor para grid-search masivo de parámetros, no para live |
| **vectorbt PRO** | vectorbt.pro | Vivo (pago) | N/A | Propietario | Python | Conectores via CCXT/IB opt-in | Vectorizado + event-driven hooks | Limitado | Sí | No | No | Subscripción mensual privada | El sandbox de research más potente del mercado, comercial |
| **Hummingbot** | github.com/hummingbot/hummingbot | Muy vivo, Foundation activa 2026 | ~9k | Apache-2.0 | Python + Cython | DEX + 30+ CEX (binance, kucoin, etc.); **no equity** | Event-driven (market-making focus) | Sí | Sí (specialized para MM) | Local-first, no multi-tenant nativo | No (Telegram cliente, no approval) | OSS + revenue por exchange-fee-share + token HBOT | El líder de market-making cripto OSS |
| **Jesse** | github.com/jesse-ai/jesse | Vivo, JesseGPT añadido | ~5.6k | MIT (core) + servicios pago | Python | Cripto (CCXT-like) | Event-driven | Sí | Sí | No | No | OSS MIT + JesseGPT/dashboards de pago | Crypto-only; UX agradable; modelo "OSS + serv premium" |
| **Backtrader** | github.com/mementum/backtrader | **Dormant/dead** (sin commits relevantes desde 2023) | ~14k | GPL-3.0 | Python | IBKR (legacy), OANDA, VC, CCXT | Event-driven | Sí | Sí | No | No | OSS abandonado | Aún funciona pero sin futuro; problemas con Python 3.10+ |
| **Zipline-Reloaded** | github.com/stefan-jansen/zipline-reloaded | Vivo (mantenedor único) | 1.6k | Apache-2.0 | Python | N/A directo (research-first) | Event-driven | No (research) | Sí | N/A | N/A | OSS personal (libro de Jansen) | Excelente para research factor-equity; no live |
| **Backtesting.py** | github.com/kernc/backtesting.py | Vivo (commits 2026) | ~6k | **AGPL-3.0** | Python | Ninguno (backtest only) | Event-driven simple | No | Básico | N/A | N/A | OSS AGPL | Lightweight; AGPL bloquea uso comercial cerrado |
| **QSTrader** | github.com/mhallsmoore/qstrader | Vivo (mantenimiento lento) | ~1k | MIT | Python | Limited | Event-driven schedule-based | Sí (parcial) | Sí (modular) | No | No | OSS + libros QuantStart | Buen ejemplo arquitectónico; comunidad pequeña |
| **OctoBot** | github.com/Drakkar-Software/OctoBot | Muy vivo (v2.1.1 mar 2026, mobile app, Hyperliquid) | ~3.5k | LGPL-3.0 / GPL | Python 3.12/13 | Cripto (15+ CEX), Polymarket | Event-driven | Sí | Sí | Soporta cloud (octobot.cloud) | webUI; Telegram via plugin | OSS + OctoBot.cloud SaaS | Crypto-focused; **modelo OSS+cloud SaaS funcional** |
| **FinRL / FinRL-X** | github.com/AI4Finance-Foundation/FinRL | Vivo (research-driven, evoluciona a FinRL-X) | ~12k | MIT | Python (RL: Stable-Baselines3, Ray) | Limited (paper-trading) | Hybrid | Limited | Limited | N/A | N/A | OSS académico | Sandbox para RL en finanzas; no production-ready |
| **Catalyst (Enigma)** | github.com/scrtlabs/catalyst | **DEAD** | ~2.5k | Apache-2.0 | Python (zipline fork) | Cripto (legacy) | Event-driven | Sí | Limited | No | No | Murió con Enigma/SEC | No usar (referencia histórica) |
| **PyAlgoTrade** | github.com/gbeced/pyalgotrade | **Dormant** (último push hace 2 años) | ~4.5k | Apache-2.0 | Python | Limited (Bitstamp, Xignite) | Event-driven | Parcial | Limited | No | No | OSS abandonado | Zombi; legacy code only |
| **bt** | github.com/pmorissette/bt | **Abandoned** (per Trading Strategy docs) | ~2k | MIT | Python | N/A | Vectorizado portfolio | No | Sí (rebalancing) | N/A | N/A | OSS abandonado | Bueno conceptualmente para asset-allocation; muerto |
| **Composer.trade** | composer.trade | Vivo (no OSS) | N/A | Propietario | Web (DSL propio) | Alpaca subyacente | Visual no-code | Sí (DSL único) | Sí | Multi-tenant SaaS | "Trade With AI" (no es approval-gate, es generación) | Subscripción $40/mes stocks, 0.2% crypto | El benchmark UX/pricing del retail-quant moderno |
| **TradingAgents** | github.com/TauricResearch/TradingAgents | Vivo (v0.2.3 mar 2026) | (alta tracción 2025-26) | (research) | Python (multi-LLM) | Paper-trading | Multi-agent LLM (sin engine de execution propio) | No | No | N/A | No (full-auto agent demos) | Académico/research | El paper que define "multi-agent trading firm" pero NO es production |

---

## 3. Deep-dives: las 6 plataformas más relevantes para iguanatrader

### 3.1 QuantConnect Lean (★ 18.6k, Apache-2.0)

**Qué es:** El motor de trading algorítmico OSS más maduro del mercado retail/prosumer. C# en el core (94% del código), Python como first-class via PythonNet. Soporta backtest, optimization, paper trading y live trading **con el mismo algoritmo**, contra IBKR, Alpaca, Binance, Tradier, Coinbase y ~10 brokers más. El propio QuantConnect Cloud corre exactamente este código en multi-tenant para 300+ hedge funds y miles de retail.

**Por qué importa para iguanatrader:**
- Apache 2.0 → puedes forkear, modificar y vender SaaS encima sin restricciones de licencia.
- IBKR adapter battle-tested.
- Backtest↔live parity es el principio rector del proyecto.
- Lean CLI permite correr todo localmente vía Docker — no hay vendor lock-in.

**Por qué NO usarlo tal cual:**
- Stack C#/Python híbrido es pesado para un dev solo en Python puro. La curva de aprendizaje del API es real.
- No tiene approval gate ni Telegram nativo; tendrías que añadirlo en una capa externa.
- No tiene observabilidad de coste de LLM (porque no usa LLMs).
- Filosofía "el algoritmo es la unidad atómica" choca un poco con la idea de "LLM propone, humano aprueba, engine ejecuta".

**Recomendación:** Estudiar el `Algorithm` API y el `BrokerageModel` abstraction. Robar conceptos. **No forkear** salvo que iguanatrader vire a "QC clon en español + LLM layer".

### 3.2 NautilusTrader (★ 2.7k, LGPL-3.0)

**Qué es:** El "Lean de nueva generación" — Rust en el core para determinismo y performance, Python como control plane. Mismo runtime para backtest y live (no son dos engines distintos cosidos). Diseñado para producción multi-asset/multi-venue. Adapter IBKR completo.

**Por qué importa:**
- Determinismo a nivel reloj — fundamental para backtest↔live parity real (no solo "mismo código", sino "mismo orden de eventos").
- Arquitectura modular limpia: `DataEngine`, `ExecutionEngine`, `RiskEngine`, `Cache`, `MessageBus` separados.
- Releases bi-semanales, mantenedor corporativo (Nautech Systems Pty Ltd) con incentivo de monetizar via servicios.
- Permite escribir estrategias **solo en Python** sin tocar Rust.

**Caveats:**
- LGPL-3.0 es más restrictivo que Apache. Si embebes Nautilus en un SaaS comercial cerrado, debes permitir al usuario reemplazar la librería (típicamente vía dynamic linking). Manejable, pero no tan libre como Apache.
- API "becoming more stable" — admiten breaking changes entre releases. Riesgo para un MVP que quiere estabilidad.
- Comunidad ~10x más pequeña que Lean → menos ejemplos, menos respuestas en Stack Overflow.

**Recomendación:** **Si iguanatrader quiere apostar por el engine "del futuro"**, este es. Para MVP single-user, demasiado overkill; para v2 multi-tenant SaaS, candidato fuerte como engine subyacente.

### 3.3 Lumibot (★ ~2k, Apache-2.0)

**Qué es:** Framework Python de trading creado por Lumiwealth (empresa con educación de pago + bots gestionados). Soporta IBKR, Alpaca, Tradier, crypto. Mismo código backtest↔live. En 2026 añadió "BotSpot": módulo que conecta estrategias a LLMs para sentiment/news en tiempo real.

**Por qué es el más cercano al MVP de iguanatrader:**
- Python puro, ergonómico para dev solo.
- IBKR de primera clase (REST + Legacy).
- AI hooks ya pensados — no rechaza la idea LLM como Lean/Nautilus.
- Modelo de negocio OSS + SaaS comercial **ya validado en este nicho** (Lumiwealth vende bots gestionados, cursos, dashboards).

**Por qué hay que mirarlo con lupa:**
- Comunidad pequeña, código menos pulido que Lean/Nautilus.
- Documentación irregular.
- "BotSpot" parece marketing-driven, no un layer agentic serio (no es LangGraph).
- No hay approval gate explícito.

**Recomendación:** **Lectura obligada antes de escribir una línea de iguanatrader**. Considerar fork o, al menos, copiar literalmente el `Strategy` interface y el `Broker` abstraction. Es el "stand on shoulders of giants" más eficiente.

### 3.4 Freqtrade (★ ~30k, GPL-3.0)

**Qué es:** El bot de cripto OSS más popular del planeta. No aplica directamente a IBKR/equities pero **es el único framework con Telegram + webUI + risk engine maduros y battle-tested para retail**.

**Patrón a robar (literal):**
- Comandos Telegram: `/status`, `/profit`, `/balance`, `/forcebuy`, `/forcesell`, `/stop`, `/reload_config`, `/whitelist`, `/blacklist`. **Esto es exactamente el approval-gate UX que iguanatrader necesita**.
- Modos: `dry-run` (paper), `live`, `backtesting`, `hyperopt` (Optuna). Diseño impecable para iterar.
- FreqAI: módulo de ML opt-in con pipeline reproducible. Modelo a seguir si iguanatrader añade ML.
- FreqUI: dashboard local servido por el propio bot. Pattern: "tu bot es también su propio servidor de UI".

**Caveats:** GPL-3.0 → si forkeas, todo derivado debe ser GPL-3.0 (no SaaS cerrado fácil). Solo cripto, no equity. No usable como base, sí como referencia UX.

**Recomendación:** **Documentar e imitar el set de comandos Telegram, los modos dry/live, y el patrón webUI embebida**. No forkear (licencia + scope incorrecto).

### 3.5 NautilusTrader vs Lean — la decisión arquitectónica

| Eje | Lean | NautilusTrader |
|---|---|---|
| Lenguaje primario | C# (94%) | Rust (core) + Python (control) |
| Madurez | 12+ años, 13k commits, 300+ hedge funds | ~5 años, 2.7k★, growing fast |
| Licencia para SaaS | Apache 2.0 (perfecto) | LGPL-3.0 (manejable) |
| Determinismo backtest↔live | Bueno | Excelente (event time model único) |
| Footprint para dev solo | Pesado | Medio |
| IBKR adapter | Sí, maduro | Sí, completo (con caveat Python 3.14) |
| Ecosistema community | Enorme | Mediano pero creciendo |
| Encaja con LangGraph/LLM | Hay que pegarlo encima | Hay que pegarlo encima |

Ambos son técnicamente correctos. **Lean** es la elección "consensus / no me despiden por elegirlo". **Nautilus** es la apuesta a 3 años. **Ninguno resuelve el approval gate ni la observabilidad de coste LLM** — esos los escribe iguanatrader.

### 3.6 Composer.trade (no OSS, pero benchmark obligado)

**Qué es:** SaaS no-code para crear "symphonies" (estrategias visuales tipo flowchart). Subyacente Alpaca para execution. Subscripción $40/mes para stocks, 0.2% crypto. Lanzaron "Trade With AI" en oct 2025: NL → estrategia. ~$X00M valuation.

**Por qué importa para iguanatrader:**
- **Es el benchmark de pricing y UX del retail-quant SaaS**. $40/mes es el techo psicológico para retail no-pro.
- Su DSL propio + AI generation es exactamente "LLM propone estrategia, humano aprueba". Es el patrón conceptual de iguanatrader, **pero cerrado y sin approval gate por trade**.
- Demuestra que el mercado paga por: (a) backtest visual instantáneo, (b) execution managed (no quieren tocar TWS Gateway), (c) "trade with AI" como hook.

**Lo que iguanatrader puede hacer mejor:**
- Open core (Composer es cerrado total).
- IBKR (Composer solo Alpaca).
- Approval gate **por trade**, no solo por estrategia.
- Cost observability de LLM (Composer no tiene LLMs en el hot path; tampoco los expone como coste).

---

## 4. Sub-grupo: precedentes OSS + SaaS multi-tenant

| Empresa | OSS layer | SaaS layer | Cómo se split | Licencia que lo permite |
|---|---|---|---|---|
| **QuantConnect** | Lean (engine) | QC Cloud (datos, compute, hosting, equipos, marketplace de algos) | OSS = engine + adapters; SaaS = data feeds licenciados, compute managed, colaboración multi-user, alpha streams marketplace, soporte SLA | Apache 2.0 → permite QC monetizar todo el stack alrededor sin obligar a abrir el SaaS |
| **Lumiwealth** | Lumibot | Cursos, bots gestionados, dashboards | OSS = framework; SaaS = "bots-as-a-service" + educación + signals | Apache 2.0 |
| **Hummingbot Foundation** | Hummingbot core + Condor UI | NO hay SaaS; monetizan vía **exchange-fee-share** (los exchanges pagan rebates por volume generado por bots Hummingbot) | OSS 100% gratuito; revenue indirecto vía partnerships | Apache 2.0 |
| **OctoBot** | OctoBot core | OctoBot.cloud (deploy hosted, packs de estrategias) | OSS = engine local; SaaS = hosting + estrategias premium | LGPL/GPL |
| **Jesse** | jesse (core) | JesseGPT, dashboards, datasets premium | OSS = engine + backtest; SaaS = AI strategy assistant + datos | MIT |
| **vectorbt** | vectorbt (research lib) | vectorbt PRO (private repo, Discord, features avanzadas) | OSS = "demo"; PRO = todo lo serio | Apache 2.0 + **Commons Clause** (impide vender el OSS como servicio) |
| **Numerai** | Pequeñas libs python | Tournament + hedge fund | OSS = SDK; el negocio es el hedge fund que opera con la meta-model crowdsourced. Pagan en NMR token. | MIT (libs); el modelo no se replica fácil |

**Patrones repetibles para iguanatrader:**

1. **OSS = engine + SDK; SaaS = todo lo "managed"** (datos, compute, multi-user, hosted dashboard, soporte). QC y Lumiwealth.
2. **License moat**: Apache 2.0 puro permite replicación del SaaS por terceros. **Commons Clause** (vectorbt) o **AGPL** (backtesting.py) bloquean SaaS competidor pero ahuyentan algunos usuarios. Trade-off explícito.
3. **Education-as-revenue** (Lumiwealth, QuantStart, Jesse): cursos y libros generan margen alto y embeden la herramienta.
4. **Marketplace de estrategias** (QC Alpha Streams, Numerai meta-model): network effect raro pero defensible. Largo plazo.
5. **Exchange-fee-share** (Hummingbot): solo aplica a cripto, no a equity. Ignorar para iguanatrader.

---

## 5. Síntesis estratégica

### (a) ¿Hay un OSS tan completo que iguanatrader debería usarlo en vez de construir?

**Respuesta honesta: NO, pero estás cerca.**

- **Lean** cubre engine + brokers + backtest↔live perfectamente. No cubre LLM-orchestrated routines, approval gate, ni cost observability. Si iguanatrader fuera "yet another Python trading framework", la respuesta sería "use Lean y termina". Como NO lo es, Lean es **componente subyacente posible**, no el producto.
- **Lumibot** es lo más cercano funcionalmente al MVP. Si tu objetivo fuese "lanzar mañana en vez de en 3 meses", **forkearías Lumibot y añadirías el approval gate + LLM layer encima**.
- **NautilusTrader** es la apuesta a 3 años para el engine. Para MVP es overkill.

**Conclusión:** No abandonar el proyecto. Sí abandonar la idea de **escribir el engine de execution desde cero**. Wrappear `ib_async` en una capa fina y, cuando llegue el momento, migrar a Lean o Nautilus como engine subyacente.

### (b) Top candidatos para fork

1. **Lumibot** — match más alto del MVP. Python puro, IBKR, backtest↔live, Apache (probable). Pega: comunidad pequeña, código menos pulido. Riesgo de heredar deuda técnica.
2. **NautilusTrader** — apuesta técnica fuerte. Pega: LGPL es un ítem para auditar antes; Rust en el core eleva la barra de contribución externa.
3. **Lean** — opción "industrial". Pega: C#-Python híbrido es pesado para dev solo; productividad penalizada en MVP.

**Recomendación operativa:** **No forkear ninguno en MVP**. Construir capa Python propia con `ib_async` directo. Mantener `BrokerInterface` abstracto desde el día 1 para poder enchufar Lumibot/Nautilus como adapter en v2. Esto es el "embrace pero no acoplar".

### (c) ¿Qué gaps cubre iguanatrader que nadie más cubre?

**Validación de la hipótesis: en gran parte sí.**

| Gap | Cubierto por OSS hoy | Cubierto por SaaS comercial hoy |
|---|---|---|
| LLM-orchestrated routines (pre-market briefing, weekly review) | No (TradingAgents es demo, no production) | Composer "Trade With AI" parcialmente, Architect.co parcialmente |
| Approval gate **por trade** vía Telegram + dashboard | Freqtrade comandos parciales (cripto) | No |
| Backtest↔live parity en Python puro | Sí (Lean, Nautilus, Lumibot) | N/A |
| Cost observability del propio LLM stack en USD | **No, en ningún sitio** | No |
| IBKR retail con approval gate | No | No |
| Risk caps (2%/5%/15%) con kill-switch automatizado | Parcial (Freqtrade, Lean tienen pieces) | Composer no expone esto al usuario |

**El verdadero diferencial es la combinación**: *"LLM propone estrategia y trades → humano aprueba en Telegram → engine determinista ejecuta vía IBKR → cada API call de LLM y broker se loggea con su coste USD → kill-switch automático si excedo 5% diario"*. **Este flujo end-to-end no existe en OSS hoy**.

### (d) Panorama competitivo: ¿saturado, creciente, muriendo, nicho?

- **Mercado total**: $25-32B en 2026, CAGR 13-15%, retail = 38.5% del market share. **Crece fuerte**.
- **Cripto bots OSS**: **saturado** — Freqtrade, Hummingbot, OctoBot, Jesse compiten sobre cripto. Tendencia: consolidación (Freqtrade gana long-tail; Hummingbot gana market-making; OctoBot gana low-code/UI).
- **Equity/multi-asset OSS**: **menos saturado, dominado por Lean**. NautilusTrader y Lumibot son los retadores serios.
- **Quant SaaS retail B2C**: **creciente y oportunista**. Composer ($40/mes, no-code, AI) está creciendo; QuantConnect Cloud cubre prosumer; pero el segmento "retail con cuenta IBKR pequeña/mediana que quiere algo más serio que Composer y menos pesado que QC" está **subatendido**.
- **LLM-agent trading**: **explosión de hype 2025-2026**, mayoría son demos académicos (TradingAgents) o tutoriales Medium. **Ninguno production-grade con risk engine real y approval gate**. Aquí está la ventana.

**Survivors clave y por qué siguen vivos:**
- **Lean / QuantConnect**: efecto red + datos licenciados + financiación corporativa.
- **Freqtrade**: comunidad enorme + maintainer dedicado + nicho cripto con monetización indirecta (cursos, signals).
- **NautilusTrader**: backing corporativo (Nautech Systems Pty Ltd) + diferenciación técnica clara (Rust).
- **Hummingbot**: Foundation con governance + revenue indirecto (exchange fees).

**Tendencia 2026:** **convergencia LLM + trading**. Quien lo haga bien primero (con risk engine serio + approval gate, no full-auto cowboy) define la categoría.

---

## 6. Ideas worth stealing

### UX
- **Freqtrade Telegram commands**: `/status`, `/profit`, `/forcebuy`, `/forcesell`, `/stop`, `/reload_config`. Adaptar para iguanatrader: `/propose`, `/approve <trade_id>`, `/reject <trade_id>`, `/halt`, `/resume`, `/risk_status`, `/cost_today`.
- **Freqtrade `dry-run` mode**: switch entre paper y live con un flag en config. Imitar.
- **Composer "symphony" visual**: aunque iguanatrader no sea no-code, **un visualizador de la estrategia activa en el dashboard es oro**.
- **QC backtest report HTML auto-generado**: imitar formato (equity curve, drawdown, trades, métricas Sharpe/Sortino/Calmar).
- **Lumibot "BotSpot" idea**: módulo opt-in para inyectar señales LLM (sentiment, news). Idem patrón.

### Arquitectura
- **NautilusTrader's `MessageBus` + separated engines** (`DataEngine`, `ExecutionEngine`, `RiskEngine`): replicable en Python con asyncio + queues. Limpieza arquitectónica que iguanatrader debería abrazar desde día 1.
- **Lean's `BrokerageModel`**: abstracción que permite testear con un "ideal broker" en backtest y plug del real en live. Replicable.
- **Freqtrade's strategy interface**: `populate_indicators`, `populate_entry_trend`, `populate_exit_trend` — separación clara de concerns. Adaptar a `propose_signals`, `request_approval`, `execute_approved`.
- **QSTrader's modular schedule-based portfolio construction**: signal → portfolio construction → risk → execution, completamente desacoplado. Bueno como referencia.
- **`ib_async`'s sync+async dual API**: usar async en hot path, sync en research scripts. Patrón a seguir.

### Monetización (visión a largo plazo)
- **Composer's $40/mes flat** = techo psicológico para retail no-pro en este vertical. Pricing inicial sugerido: **$29-49/mes** tier individual, **$199-499/mes** tier "team" (3-5 seats).
- **Freemium tier**: paper trading + 1 estrategia gratis (como QC free). Conversión cuando el usuario quiere live + risk caps + approval flow.
- **Education flywheel** (Lumiwealth, QuantStart, Jesse): blog + curso de pago + bot premium. Margen alto, customer acquisition orgánico.
- **No marketplace de estrategias en v1** — alta complejidad legal y operacional, requiere masa crítica que iguanatrader no tendrá año 1.
- **Cost-pass-through del LLM**: cobrar margen sobre el coste de Anthropic/Perplexity API. iguanatrader tiene cost observability nativa, esto es defensible.

### Community building
- **Discord >> Slack** para retail quant (Freqtrade, NautilusTrader, vectorbt PRO todos en Discord).
- **GitHub Discussions** activo para bug-reports estructurados (NautilusTrader lo hace bien).
- **Newsletter mensual** (Hummingbot lo hace excelente — Substack mensual con métricas, releases, roadmap).
- **Cohort-based course** (estilo Lumiwealth) cada trimestre: high-touch, high-margin, generates content + advocates.
- **Open roadmap público** en GitHub (Freqtrade, NautilusTrader): transparencia atrae contributors.

---

## 7. Riesgos y pitfalls observados

### Por qué murieron proyectos
- **Quantopian (RIP 2020)**: regalar todo y monetizar después con un fondo cuyo alpha falló. **Lección: monetizar pronto y modesto, no apostar la viabilidad a un único alpha**.
- **Backtrader (dormant 2023+)**: **bus factor 1**. Maintainer dejó. Comunidad no organizó takeover. **Lección: bus factor ≥ 2 desde día 1; gobernanza explícita**.
- **PyAlgoTrade (dormant)**: idem bus factor + Python 3 transition no completada a tiempo.
- **Catalyst (Enigma)**: arrastrado por SEC enforcement contra Enigma (ICO ENG no registrado). **Lección: no atar trading platform a esquemas tokenizados/ICO speculative**.
- **bt (abandoned)**: API limpia pero scope demasiado nicho (rebalancing portfolio); falta de live trading lo dejó sin pull commercial.

### Errores arquitectónicos comunes
- **Backtest engine ≠ live engine**: cuando son código distinto cosido, paridad falla en producción. **Lean y Nautilus lo resolvieron usando un único event loop**. Imitar.
- **LLM en el hot path**: latencia + coste + non-determinismo destruyen el risk engine. **Mantener LLM solo en research/orchestration, NUNCA en execution**. iguanatrader ya tiene esto correcto en su arquitectura de 3 capas.
- **Multi-tenancy bolted on después**: imposible refactorizar a multi-tenant si SQLite + filesystem está hardcoded. **Diseñar el `tenant_id` como first-class desde día 1**, aunque MVP sea single-user.
- **Risk engine como afterthought**: en Backtrader y PyAlgoTrade los risk caps eran opt-in y se olvidaban. **Risk engine debe ser obligatorio; estrategias proponen, risk engine aprueba/recorta/rechaza**.
- **No tener `dry-run` desde día 1**: error fatal. Freqtrade lo tiene, y por eso retail no se quema en producción primer día.

### Errores de monetización comunes
- **Free forever sin path a paid**: Quantopian. Drena recursos sin retorno.
- **Pago por feature en vez de por capacidad** (ej. cobrar por "número de estrategias"): retail churnea. Mejor pricing por **AUM gestionado** o **número de cuentas conectadas** o **flat tier con capacidad clara**.
- **Token utility coin** (Numerai NMR, HBOT): sirve a Numerai porque hay un hedge fund detrás. Para iguanatrader sería distracción regulatoria.
- **AGPL puede frenar adoption corporativa**: backtesting.py limita su upside porque corps tienen miedo de AGPL. **Apache 2.0 + Commons Clause es el sweet spot** si quieres bloquear SaaS competidor sin asustar a usuarios.

### Riesgos regulatorios
- **EE.UU. (SEC/FINRA)**: si das señales accionables a múltiples usuarios, puedes caer en "investment advisor". Approval gate por usuario individual mitiga (es el usuario quien decide), pero auditar.
- **EU (MiFID II)**: distribuir software OSS es seguro; ofrecer SaaS gestionado en EU exige cuidado con definición de "investment service".
- **Tax reporting**: si SaaS opera trades en nombre del usuario (incluso vía approval), puede convertirte en "broker" a efectos fiscales. **Mantener arquitectura "el usuario es quien tiene la cuenta IBKR; tú solo orquestas su software"** es defensible.

---

## 8. Recomendación para iguanatrader (veredicto honesto)

### MVP (corto plazo, próximos 3 meses)

**Construir desde cero, NO forkear, pero pararse sobre hombros de gigantes.**

1. **Engine de execution**: wrap fino sobre `ib_async` directamente. NO meter Lean/Nautilus en MVP — la complejidad de su API te frenará. Mantener una `BrokerInterface` abstracta para poder enchufar adapters en v2.
2. **Backtest engine**: escribir uno simple event-driven propio para Donchian + ATR. Validar paridad con un único test: corre la misma estrategia en backtest y en paper trading sobre el mismo periodo, compara fills. Si Lean/Nautilus se sienten necesarios después, plug-in via adapter.
3. **Research sandbox**: usar **vectorbt** (OSS, Apache + Commons Clause es OK para uso interno research) para grid-search de parámetros. Es exactamente para eso.
4. **Telegram + dashboard**: copiar literal el set de comandos de Freqtrade adaptado: `/propose`, `/approve`, `/reject`, `/halt`, `/risk_status`, `/cost_today`. FastAPI local sirve dashboard.
5. **Risk engine**: separado, obligatorio, kill-switch hardcoded a 5% daily / 15% weekly. Estrategias **proponen**, risk engine **filtra/recorta/rechaza** ANTES de que el approval gate vea el trade.
6. **LangGraph orchestration**: para routines (pre-market briefing, weekly review). NO en hot path. Cada node loggea su `provider`, `model`, `tokens_in`, `tokens_out`, `usd_cost` a SQLite.
7. **Cost observability**: tabla `llm_calls` en SQLite append-only. Comando `/cost_today` y `/cost_week` en Telegram.

**Lo que NO hacer en MVP:**
- No multi-asset (solo equity US vía IBKR).
- No multi-strategy (solo Donchian+ATR v0).
- No ML/RL (FinRL es para v3+).
- No marketplace, no community features, no tier free.
- No pre-market scanning del universo entero — solo watchlist manual.

### v2 (6-12 meses)

- Decidir engine subyacente: **Lumibot** si quieres velocidad de feature, **NautilusTrader** si quieres apostar técnico, **Lean** si quieres consensus. Migración con `BrokerInterface` que ya estará lista.
- Multi-tenant readiness: `tenant_id` first-class, postgres en vez de sqlite (o sqlite per-tenant con tenant-router), object storage para parquets.
- Approval gate vía Web (no solo Telegram) para usuarios non-techie.

### v3 / SaaS (12-24 meses)

- Modelo: **OSS Apache-2.0 + Commons Clause** (bloquea SaaS competidor) + tier SaaS hosted ($29 individual / $199 team).
- Education flywheel: blog técnico + curso cohort-based trimestral.
- NO entrar en marketplace de estrategias hasta tener >1000 usuarios pagantes.
- Considerar entrar en EU primero (regulación más clara para "user-owned-account orchestration") antes que US.

### TL;DR del veredicto

> iguanatrader **NO es redundante** con la oferta OSS actual. Su diferencial — **LLM-orchestrated proposals + human approval gate + cost observability + IBKR retail** — no existe en ningún proyecto OSS hoy. Construir el MVP en Python puro sobre `ib_async`, **robar UX de Freqtrade**, **robar arquitectura modular de NautilusTrader**, **robar pricing/positioning de Composer**, y dejar la puerta abierta para que el engine de execution sea reemplazable por Lumibot/Lean/Nautilus en v2. La oportunidad de mercado es real, está creciendo, y la categoría "responsible LLM-orchestrated retail trading" está abierta.

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
