"""Approval bounded context — multichannel approval surface for trade proposals.

Per slice P1 (`approval-channels-multichannel`) — a Wave 2 slice that lands
the missing link between trade-proposal generation (T1/T2) and broker
execution (T2/T4). Composes on top of slice 2's `HeartbeatMixin` +
canonical `[3, 6, 12, 24, 48]` backoff (NFR-R7) and slice 3's
`append_only_listener` + `tenant_listener`.

Public surface:

* :mod:`iguanatrader.contexts.approval.service` — :class:`ApprovalService`
  orchestrates the lifecycle: create_request → fan_out_to_channels →
  resolve_decision → emit_event.
* :mod:`iguanatrader.contexts.approval.repository` — :class:`ApprovalRepository`
  wraps INSERT-only access to `approval_requests` + `approval_decisions`
  + read access to `authorized_senders` (whitelisting).
* :mod:`iguanatrader.contexts.approval.events` — three event-name
  constants (`APPROVAL_PROPOSAL_APPROVED`, `APPROVAL_PROPOSAL_REJECTED`,
  `APPROVAL_PROPOSAL_TIMED_OUT`) + dataclass payloads, consumed via the
  slice-2 :class:`MessageBus`.
* :mod:`iguanatrader.contexts.approval.errors` — slice-local
  :class:`IguanaError` subclasses (`ApprovalNotFoundError`,
  `ApprovalAlreadyDecidedError`, `ApprovalExpiredError`,
  `UnauthorizedSenderError`). Slice-local per cross-slice coordination —
  do not pollute `shared/errors.py`.
* :mod:`iguanatrader.contexts.approval.channels` — three
  :class:`ChannelPort` adapters (Telegram, Hermes/WhatsApp, Dashboard)
  + a :func:`command_handler.dispatch` entrypoint that all three transport
  layers funnel into.

The 17 canonical user-facing commands (per design D2):

    /approve   /reject   /halt      /resume    /status
    /positions /equity   /strategies /risk     /override
    /cost      /budget   /help      /whoami    /lock
    /unlock    /logout

Cross-context event vocabulary (emitted on every `approval_decisions`
INSERT, consumed by trading T2/T4):

    approval.proposal.approved
    approval.proposal.rejected
    approval.proposal.timed_out

Authorized-sender enforcement happens at the channel boundary
(`repository.is_sender_authorized`); non-whitelisted senders are
silent-dropped (no echo) per design D6 + NFR-S3.
"""
