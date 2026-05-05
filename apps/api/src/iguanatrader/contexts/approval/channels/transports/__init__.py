"""Channel transport package — wire-format facades behind a Port.

Per slice P1 design D8: this slice ships only fakes
(:class:`FakeTelegramTransport`, :class:`FakeHermesTransport`).
Real wire clients (``python-telegram-bot``, Hermes/Meta Cloud API) are
deferred to a follow-up slice that swaps the implementation behind the
same :class:`ChannelTransportPort` Protocol.

This keeps Wave 2 fast: idempotency, audit, and heartbeat contracts
are all exercised end-to-end through the fakes; the real wire clients
are a tightly-scoped 1-2 day follow-up.
"""
