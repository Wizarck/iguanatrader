"""Human-readable docs for the IBKR translator vocabulary.

Slice ``ib-translators-full`` ships every contract / order / algo kind
the daemon can route. The UI needs prose that lets a non-broker user
understand each option without leaving the app — bond traders, FX
day-traders, options swing-traders all touch the same selector and
must distinguish e.g. STK vs CFD or TRAIL vs TRAIL LIMIT.

This module is the single source of truth for those explanations.
It exposes:

* :data:`SEC_TYPES` — every contract sec_type with required fields +
  Spanish prose.
* :data:`ORDER_TYPES` — order types with required parameter signature
  + Spanish prose.
* :data:`ALGO_KINDS` — execution algos with their parameter
  vocabulary + Spanish prose.

The API surface at ``GET /api/v1/broker/types`` returns this catalogue
verbatim so the frontend selector can render labels + tooltips
without hard-coding strings.

All prose is in Spanish (Arturo's working language; the rest of the
UI follows the same convention). Translations to other languages would
land as sibling modules consumed by an i18n layer — out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranslatorOption:
    """One entry in the broker-vocabulary catalogue.

    ``code`` is the literal value the daemon expects (e.g. ``"STK"`` or
    ``"TRAIL LIMIT"``); ``label`` is the short UI string; ``description``
    is 1-3 paragraphs of prose explaining the option, its required
    parameters, and the most common use case. ``required_fields`` lists
    the additional :class:`Contract` / :class:`IBOrder` attributes the
    caller MUST populate beyond the always-required ones.
    """

    code: str
    label: str
    description: str
    required_fields: tuple[str, ...] = ()


SEC_TYPES: tuple[TranslatorOption, ...] = (
    TranslatorOption(
        code="STK",
        label="Acción (Stock)",
        description=(
            "Renta variable cotizada — la opción por defecto y la única "
            "soportada en el slice T2 original. Cubre cualquier ticker "
            "negociable en NASDAQ / NYSE / AMEX / LSE, y cualquier mercado "
            "que IBKR enrute mediante SMART.\n\n"
            "Requiere solo símbolo + exchange + currency. Para el operador "
            "USA el default ``exchange='SMART'`` es lo correcto en el 99 % "
            "de casos; IBKR resuelve el venue concreto (Island, ARCA, etc.) "
            "según best-execution."
        ),
    ),
    TranslatorOption(
        code="FUT",
        label="Futuro (Future)",
        description=(
            "Contrato de futuros — apalancamiento + vencimiento explícito. "
            "Pensado para macro (ES, NQ, CL, GC), no para hedging de equity "
            "individual.\n\n"
            'Requiere ``expiry`` con formato YYYYMM (e.g. ``"202612"`` '
            "para el contrato de diciembre 2026) o YYYYMMDD si quieres "
            "fijar el día. El exchange ya no puede ser SMART — usa "
            '``"CME"`` / ``"NYMEX"`` / ``"ECBOT"`` según el producto.\n\n'
            "El multiplicador (``multiplier``) es opcional pero recomendado "
            "para evitar ambigüedad en productos con micro/mini variantes "
            '(``"50"`` para ES, ``"5"`` para MES).'
        ),
        required_fields=("expiry",),
    ),
    TranslatorOption(
        code="OPT",
        label="Opción (Option)",
        description=(
            "Contrato de opciones — calls + puts sobre equity o índice. "
            "Mayor riesgo de gamma y theta; respeta el contract multiplier "
            "(100 para US equity options).\n\n"
            "Requiere TRES campos extra: ``expiry`` (YYYYMMDD obligatorio "
            "al día), ``strike`` (Decimal con el precio de ejercicio) y "
            '``right`` ∈ {``"C"`` call, ``"P"`` put}.\n\n'
            'Exchange suele ser ``"SMART"``; el SDK enrutará entre CBOE / '
            'AMEX / ISE / etc. El multiplicador default es ``"100"`` (US '
            "equity option estándar); ajústalo si tu producto tiene "
            "multiplier no-estándar (mini opciones SPY = 10)."
        ),
        required_fields=("expiry", "strike", "right"),
    ),
    TranslatorOption(
        code="CASH",
        label="Forex (FX spot)",
        description=(
            "Par FX al contado — spot, no forward. IBKR opera 23/5 cubriendo "
            "los mayores + emergentes con suficiente liquidez.\n\n"
            'El símbolo es el PAR completo (``"EUR.USD"``, ``"GBP.JPY"``); '
            "el SDK lo parsea internamente. El exchange canónico es "
            '``"IDEALPRO"`` (banco-de-bancos de IBKR). Tamaño mínimo de '
            "orden 25k unidades de la base currency."
        ),
    ),
    TranslatorOption(
        code="CRYPTO",
        label="Cripto (Crypto spot)",
        description=(
            "Spot crypto via la integración IBKR ↔ Paxos Trust. Lista "
            "actual: BTC, ETH, LTC, BCH (puede expandir).\n\n"
            'Símbolo es solo el ticker (``"BTC"``); exchange '
            '``"PAXOS"`` y currency ``"USD"``. Custodia es de IBKR '
            "(no auto-custodial — no hay withdrawals on-chain)."
        ),
    ),
    TranslatorOption(
        code="CFD",
        label="CFD (Contract for Difference)",
        description=(
            "Contract for Difference — instrumento sintético sobre equity / "
            "FX / commodities. NO disponible para residentes US (regulación "
            "CFTC); IBKR lo bloquea por jurisdicción.\n\n"
            "Útil para residentes UK / EU que quieren exposición apalancada "
            "sin financiar el subyacente. Símbolo = ticker del activo "
            'subyacente; exchange depende del producto (``"SMART"`` para '
            'equity CFD, ``"IDEALPRO"`` para FX CFD).'
        ),
    ),
    TranslatorOption(
        code="IND",
        label="Índice (Index cash)",
        description=(
            "Índice cash NO negociable directamente — sirve para market-data "
            "subscription / referenciar combinaciones de derivados. Si quieres "
            "exposición usa el futuro (FUT) o un ETF (STK).\n\n"
            'Ejemplos: ``"SPX"`` en CBOE, ``"NDX"`` en NASDAQ, '
            '``"DAX"`` en EUREX.'
        ),
    ),
)


ORDER_TYPES: tuple[TranslatorOption, ...] = (
    TranslatorOption(
        code="MKT",
        label="Market (mercado)",
        description=(
            "Orden de mercado — entra al mejor precio disponible "
            "inmediatamente. Garantiza ejecución, NO precio. Apta para "
            "entradas urgentes cuando la calidad del fill es secundaria al "
            "tiempo (e.g. close de un stop manual, exit de pánico).\n\n"
            "Riesgos: slippage en pre/post-market, en tickers ilíquidos, o "
            "durante earnings. Para retail US equity en horario regular el "
            "spread suele ser ínfimo, pero verifícalo en small-caps."
        ),
    ),
    TranslatorOption(
        code="LMT",
        label="Limit (límite)",
        description=(
            "Orden limitada — solo fills al ``limit_price`` o mejor. "
            "Garantiza precio, NO ejecución. Apta para entrada paciente / "
            "salida con take-profit explícito.\n\n"
            "Requiere ``limit_price``. Si el mercado nunca toca tu límite, "
            "la orden queda pending until canceled (revísalo en horario)."
        ),
        required_fields=("limit_price",),
    ),
    TranslatorOption(
        code="STP",
        label="Stop (parada en mercado)",
        description=(
            "Orden stop simple — cuando el precio toca ``aux_price`` "
            "(trigger), la orden se convierte en MKT y fill al mejor "
            "disponible. Es la primitiva clásica de stop-loss.\n\n"
            "Atención: en gaps (overnight, halts, earnings), el fill "
            "puede salir muy por debajo del trigger. Para protección "
            "más estricta, considera STP LMT."
        ),
        required_fields=("aux_price",),
    ),
    TranslatorOption(
        code="STP LMT",
        label="Stop-Limit (parada con límite)",
        description=(
            "Combinación de stop + limit: el trigger ``aux_price`` activa "
            "la orden como LMT al ``limit_price``. Protege contra slippage "
            "extremo a costa de no garantizar fill.\n\n"
            "Caso típico: stop-loss en small-cap con gaps frecuentes — "
            "prefieres quedarte con la posición a venderla a precio "
            "ruinoso. Trade-off vs STP: si el gap rebasa tu limit, no "
            "ejecutas y te quedas con el riesgo."
        ),
        required_fields=("aux_price", "limit_price"),
    ),
    TranslatorOption(
        code="TRAIL",
        label="Trailing Stop (stop dinámico)",
        description=(
            "Stop dinámico — el trigger se reajusta automáticamente "
            "siguiendo al precio (a favor de la posición). Para un long, "
            "el trigger sube cuando el precio sube y se queda fijo cuando "
            "el precio retrocede; en short el comportamiento es espejo.\n\n"
            "Configura EXACTAMENTE UNO de:\n"
            "* ``trail_amount`` — distancia absoluta en USD (e.g. ``5.00`` "
            "  para trailing 5 dólares).\n"
            "* ``trail_percent`` — distancia relativa al precio (e.g. "
            "  ``3.5`` para 3.5 % trailing).\n\n"
            "Si configuras ambos o ninguno la orden se rechaza al "
            "construir."
        ),
        required_fields=("trail_amount OR trail_percent",),
    ),
    TranslatorOption(
        code="TRAIL LIMIT",
        label="Trailing Stop-Limit (stop dinámico con límite)",
        description=(
            "Trailing stop con un offset de limit (slippage protection). "
            "El trigger se mueve igual que TRAIL; cuando se dispara, la "
            "orden entra al book como LMT con precio = trigger + "
            "``limit_price`` (interpretado como offset).\n\n"
            "Útil para take-profit dinámico con tolerancia controlada al "
            "slippage. Mismo trade-off vs TRAIL: precio mejor pero "
            "ejecución no garantizada."
        ),
        required_fields=("trail_amount OR trail_percent", "limit_price"),
    ),
    TranslatorOption(
        code="MOC",
        label="Market-on-Close (cierre de mercado)",
        description=(
            "Orden de mercado garantizada al closing print (16:00 ET para "
            "US equity). No se ejecuta antes del closing auction.\n\n"
            "Ideal para estrategias buy-and-hold rebalancing que quieren "
            "el precio oficial de cierre como benchmark. Submission "
            "cut-off típicamente 15:45 ET (depende del exchange)."
        ),
    ),
    TranslatorOption(
        code="LOC",
        label="Limit-on-Close (límite al cierre)",
        description=(
            "Limit garantizada al closing print: solo fills si el precio "
            "de cierre respeta tu ``limit_price``. Mismo cut-off que MOC.\n\n"
            "Útil cuando quieres el closing print pero no a cualquier "
            "precio. Si el closing print rompe tu limit, no ejecutas y "
            "te quedas con la posición / efectivo."
        ),
        required_fields=("limit_price",),
    ),
)


ALGO_KINDS: tuple[TranslatorOption, ...] = (
    TranslatorOption(
        code="adaptive",
        label="Adaptive (single-order)",
        description=(
            "Algoritmo smart-routing single-shot de IBKR. Toma una orden "
            "(MKT o LMT) y optimiza el venue + timing para minimizar "
            "transaction cost. NO sli­cea la orden — fill rápido contra el "
            "best price disponible.\n\n"
            "Parámetro: ``adaptivePriority`` ∈ {``Patient``, ``Normal``, "
            "``Urgent``}. Patient = más price improvement, más tiempo de "
            "fill; Urgent = lo contrario; Normal = punto medio. Default "
            "``Normal``.\n\n"
            "Apropiado para órdenes de tamaño pequeño/medio donde el "
            "fill rápido a precio decente importa más que minimizar "
            "market impact."
        ),
    ),
    TranslatorOption(
        code="twap",
        label="TWAP (Time-Weighted Average Price)",
        description=(
            "Time-Weighted Average Price — slicea la orden en lotes "
            "iguales a lo largo de una ventana temporal. El benchmark "
            "que minimiza es el precio promedio temporal del intervalo.\n\n"
            "Parámetros:\n"
            "* ``strategyType`` ∈ {``Marketable``, ``Matching Midpoint``, "
            "  ``Matching Same Side``, ``Matching Last``}. ``Marketable`` "
            "  es el más agresivo (fill contra el bid/ask existente). "
            "  Default.\n"
            "* ``startTime`` / ``endTime`` — UTC strings. Vacío = "
            "  ``now`` + ventana razonable según tamaño.\n\n"
            "Apropiado para órdenes grandes donde NO te importa el "
            "volume profile del día, solo distribuir el fill en el tiempo."
        ),
    ),
    TranslatorOption(
        code="vwap",
        label="VWAP (Volume-Weighted Average Price)",
        description=(
            "Volume-Weighted Average Price — slicea la orden siguiendo "
            "la curva de volumen del día (más en la apertura y cierre, "
            "menos en el midday). El benchmark es el VWAP intradiario.\n\n"
            "Parámetro: ``maxPctVol`` — porcentaje máximo del volumen "
            "consolidado en cada slice (default 10). Subirlo acelera fill "
            "pero aumenta market impact.\n\n"
            "Estándar institucional para órdenes large-cap; en small-cap "
            "el volume profile es ruidoso y TWAP suele ser preferible."
        ),
    ),
    TranslatorOption(
        code="arrival_price",
        label="Arrival Price (implementation shortfall)",
        description=(
            "Implementation Shortfall — minimiza la diferencia entre el "
            "precio de submission (arrival) y el precio promedio de fill. "
            "Trade-off entre velocidad (fill rápido = menos exposure "
            "drift) y market impact (fill lento = menos slippage).\n\n"
            "Parámetros:\n"
            "* ``maxPctVol`` — igual que en VWAP, default 10.\n"
            "* ``riskAversion`` ∈ {``Get Done``, ``Aggressive``, "
            "  ``Neutral``, ``Passive``}. ``Get Done`` = prioriza fill "
            "  rápido; ``Passive`` = prioriza precio. Default "
            "  ``Neutral``.\n\n"
            "Apropiado cuando el alpha del trade decae rápido (event-"
            "driven, momentum) y necesitas balancear urgencia vs impact."
        ),
    ),
)


def to_catalogue_dict() -> dict[str, list[dict[str, object]]]:
    """Serialise the three catalogues into a JSON-friendly dict.

    Used by the ``GET /api/v1/broker/types`` route. Keep the shape
    stable; the frontend selector hard-codes ``code`` / ``label`` /
    ``description`` / ``required_fields`` keys.
    """

    def _opts(seq: tuple[TranslatorOption, ...]) -> list[dict[str, object]]:
        return [
            {
                "code": o.code,
                "label": o.label,
                "description": o.description,
                "required_fields": list(o.required_fields),
            }
            for o in seq
        ]

    return {
        "sec_types": _opts(SEC_TYPES),
        "order_types": _opts(ORDER_TYPES),
        "algo_kinds": _opts(ALGO_KINDS),
    }


__all__ = [
    "ALGO_KINDS",
    "ORDER_TYPES",
    "SEC_TYPES",
    "TranslatorOption",
    "to_catalogue_dict",
]
