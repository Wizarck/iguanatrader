# Proposal: approvals-dashboard-ui

> **Wire the `/approvals` dashboard tab to consume the pending-list + approve/reject endpoints** — `GET /approvals` + `POST /approvals/{id}/approve` + `POST /approvals/{id}/reject`. Action-bearing read view: operators see pending requests and act from the dashboard.

## Why

Backend shipped in slice P1 (`approval-channels-multichannel`). 3 endpoints + SSE stream. Today UI is `PlaceholderCard`. This slice ships the dashboard approval flow as an alternative to Telegram/WhatsApp — same backend handler, different transport (`decided_via_channel="dashboard"`).

Pattern: extends the read-only tab template (list + actions). Reuses form primitives shipped in [[strategies-config-ui]] (`TextInput`/`Textarea`) for the rejection reason.

## What

### Server load

**`apps/web/src/routes/(app)/approvals/+page.server.ts`** (NEW). Single fetch + actions:
- `load`: `GET ${API_BASE_URL}/api/v1/approvals` → `ApprovalRequest[]`. Returns `{ approvals, loadError }`.
- `actions = { approve, reject }`:
  - `approve(request_id)` → `POST /api/v1/approvals/{request_id}/approve` with empty body; redirect-on-success or `fail(400, {formError})`.
  - `reject(request_id, reason)` → `POST /api/v1/approvals/{request_id}/reject` body `{ reason }`; same redirect/fail pattern.

### Page UI

**`apps/web/src/routes/(app)/approvals/+page.svelte`** — replace `PlaceholderCard`:

- **Header**: `<h1>Approvals</h1>` + count badge ("3 pendientes").
- **Pending list**: NOT a `DataTable` — these are richer cards. Use a `<ul>` of `ApprovalCard` components.
- Per-card content (NEW `ApprovalCard.svelte`):
  - Header: proposal_id (short) + countdown "Expira en N min" computed from `expires_at - now` (live-updates via `$effect` + `setInterval(1000)`).
  - Delivered channels: list of `Badge` `accent` per channel name.
  - Delivery failures (if any): list rendered with `Badge` `destructive`.
  - Actions:
    - "Aprobar" button (green) → submits `approve` action with `request_id` hidden field.
    - "Rechazar" expand-button → on click reveals an inline `Textarea` (reuse from `forms/Textarea.svelte`) + "Confirmar rechazo" submit (`reject` action).
- **Empty state**: when `approvals.length === 0` → `EmptyState` "Sin aprobaciones pendientes."
- **Error state**: `loadError` → red alert.

### New components

- **`apps/web/src/lib/components/ApprovalCard.svelte`** — `{ approval: ApprovalRequest }`. Card with countdown timer (live $effect setInterval), delivered channels badges, action buttons + inline rejection form. Reuses form primitives.
- **`apps/web/src/lib/approvals/countdown.ts`** — pure `formatCountdown(expiresAt: string, now: Date): string` → "5m 12s" or "Expirado". Unit-testable.

### TS types

`apps/web/src/lib/approvals/types.ts` — mirrors of `ApprovalRequest`, `ApprovalDecision`, `ApprovalCommandResult`, `RejectionRequest`.

### Tests

- **`apps/web/tests/approvals-page.test.ts`** (vitest):
  1. Happy path — pending list renders 2 cards with countdown + badges + action buttons.
  2. Empty list → `EmptyState`.
  3. API 503 → `loadError`.
  4. Approve action — click "Aprobar" → POST fired with request_id; redirect-on-success.
  5. Reject expand → reveals Textarea; submitting empty reason still sends `reject` (backend accepts null reason).
  6. Reject with reason → POST fired with `{ reason }`.
  7. Countdown shows "Expirado" when `expires_at < now`.

- **`apps/web/tests/countdown.test.ts`** (vitest, pure): `formatCountdown` for various deltas (-5s / 0 / 30s / 1m30s / 1h / >1h cases).

### Storybook

3 variants for `ApprovalCard.stories.ts` (pending fresh / expiring-soon / with-delivery-failures).

## Out of scope

- **SSE realtime** (`/stream/approvals/events`) — list refreshes only on navigation in v1. `approvals-sse-realtime` adds live push.
- **Approval history view** — `ApprovalDecision` audit table is not surfaced in this slice; v1.5 (`approvals-history-ui`).
- **Approval from `/approvals` itself triggers the trading daemon** — that's backend-already-wired; no UI work.
- **Bulk approve/reject** — single per-row in v1.
- **Time-zone-aware countdown** — `Intl.DateTimeFormat` defaults to browser locale; explicit tenant TZ is v1.5.
