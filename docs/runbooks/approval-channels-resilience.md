---
type: runbook
slice: P1 (approval-channels-multichannel)
audience: ops + on-call
related:
  - docs/gotchas.md#50-approval-bot-looks-dead-to-non-whitelisted-senders-silent-drop
  - docs/gotchas.md#51-approval-channel-transports-are-stub-only-in-slice-p1
  - apps/api/src/iguanatrader/contexts/approval/channels/
---

# Runbook — Approval Channels Resilience

Operator playbook for "the Telegram (or WhatsApp) bot stopped responding to my commands". Covers diagnosis, recovery, and the canonical observability signals to inspect along the way.

## Prerequisites

- API process is running.
- structlog output is being collected (stdout, file, or aggregator).
- DB shell access for `approval_requests`/`approval_decisions` queries.

## 1. Confirm symptom + scope

Ask the reporter:

- **Which channel?** Telegram, WhatsApp, or the dashboard?
- **Which command?** `/approve`, `/reject`, etc.
- **Did the bot ever reply?** A user who has never received an ack is most likely a `D6` silent-drop (gotcha #50) — they're not in `authorized_senders`. If the bot used to reply but stopped, it's a connection drop.

## 2. Inspect heartbeat events

For Telegram:

```
grep "approval.channel.telegram" logs/$(date -u +%F).jsonl
```

For Hermes / WhatsApp:

```
grep "approval.channel.whatsapp" logs/$(date -u +%F).jsonl
```

Healthy state pattern (one of these inside the last minute):

- `approval.channel.<x>.delivered` — outbound delivery succeeded.
- *(absence of `approval.channel.<x>.disconnected` since last `connected`)*.

Disconnected state pattern (a `disconnected` event with no subsequent `mark_connected`):

- `approval.channel.<x>.disconnected` — the heartbeat detected a wire failure.

`HeartbeatMixin.reconnect_loop` is the contract that recovers from this. It walks the canonical backoff schedule `[3, 6, 12, 24, 48]` seconds with ±20% jitter (per slice 2 D7 + NFR-R7). Worst-case time-to-reconnect from a fresh drop: `3+6+12+24+48 = 93s` (un-jittered) — 75-112s with jitter. Anything longer than ~2 minutes warrants investigation.

## 3. Inspect pending requests during the outage

Pending requests live in the database and survive the channel outage. They are **not** modified during the disconnect (the table is append-only).

```sql
SELECT id, proposal_id, expires_at, created_at
FROM approval_requests r
LEFT JOIN approval_decisions d ON d.request_id = r.id
WHERE d.id IS NULL
  AND r.expires_at > CURRENT_TIMESTAMP
ORDER BY r.created_at DESC;
```

If the outage exceeds the request's `timeout_seconds`, the request will auto-timeout via the sweeper:

```bash
iguanatrader approval sweep-expired
```

This records a `timeout` decision row + emits `approval.proposal.timed_out` on the bus. Trading service picks up the event and auto-discards the proposal (FR13).

## 4. Check the underlying transport

Slice P1 ships only stub transports (gotcha #51). Until the follow-up slice `approval-channels-real-clients` lands and is deployed, "the bot stopped responding" can also mean **production has not yet been wired to a real bot**. Check the deployment manifest for the transport implementation:

```bash
grep -E "TelegramTransport|HermesTransport" deploy/*.yaml
```

If you see `FakeTelegramTransport` in production: that's the bug. Stop trading + redeploy with the real client.

## 5. Token rotation procedure (NFR-I6 second clause)

When a Telegram bot token or WhatsApp Cloud API access token is compromised:

1. Rotate the secret in your secrets store (`age` / `SOPS` / vault).
2. Restart the API process so the new token is picked up at app boot.
3. Confirm the channel reconnects cleanly: tail `approval.channel.<x>.connected` events.
4. Send a known-good `/whoami` from a whitelisted sender to confirm round-trip.

The HeartbeatMixin handles the reconnect automatically once the new token is in place; no manual intervention beyond the restart.

## 6. Escalation

If `reconnect_loop` is stuck (>5 minutes of repeated `_send_heartbeat` failures with no recovery):

1. Inspect the transport's `_send_heartbeat` implementation — for Telegram, it calls `getMe`; for Hermes, it probes Meta's `/me` endpoint.
2. Verify network egress to the third-party endpoint (`curl -I https://api.telegram.org/bot<TOKEN>/getMe`).
3. If the third-party returns 401, the token is invalid — go to §5.
4. If the third-party returns 5xx, the third-party is down — wait + monitor.
5. If exhaustive retries continue to fail with no clear cause, file an incident + escalate to the platform engineer who owns the secrets-store rotation policy.

## Related

- `docs/gotchas.md` #50 (silent-drop), #51 (stub-only transports), #52 (registry single source of truth)
- `apps/api/src/iguanatrader/contexts/approval/channels/` (source)
- `apps/api/tests/integration/test_telegram_resilience.py` + `test_hermes_resilience.py` (resilience contract tests)
