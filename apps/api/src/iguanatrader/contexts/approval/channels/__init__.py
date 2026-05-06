"""Channel adapters package.

Three :class:`ChannelPort` subclasses (Telegram, Hermes/WhatsApp,
Dashboard) all funnel inbound user input through a single
:func:`command_handler.dispatch` so the 17-command surface cannot
drift across transports (FR37).

Real wire clients are stubbed via the
:class:`ChannelTransportPort` Protocol (per design D8) so this slice
ships zero new external Python dependencies. The follow-up slice
``approval-channels-real-clients`` swaps the stub for real
``python-telegram-bot`` + Hermes implementations behind the same Port.
"""
