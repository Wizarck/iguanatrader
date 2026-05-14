# Tasks: approvals-dashboard-ui

- [ ] 1. `apps/web/src/lib/approvals/types.ts` (NEW) — TS mirrors of `ApprovalRequest`, `ApprovalDecision`, `ApprovalCommandResult`, `RejectionRequest`.
- [ ] 2. `apps/web/src/lib/approvals/countdown.ts` (NEW) — pure `formatCountdown(expiresAt: string, now: Date): string`.
- [ ] 3. `apps/web/src/lib/components/ApprovalCard.svelte` (NEW) — pending-card with live countdown ($effect+setInterval), delivered/failure badges, approve + reject (expand-textarea) buttons. Reuses `Badge` + `forms/Textarea`.
- [ ] 4. `apps/web/src/routes/(app)/approvals/+page.server.ts` (NEW) — `load` + `actions = { approve, reject }` with cookie forwarding.
- [ ] 5. `apps/web/src/routes/(app)/approvals/+page.svelte` — replace `PlaceholderCard`: header + count badge + `<ul>` of `ApprovalCard` + EmptyState/error.
- [ ] 6. `apps/web/tests/approvals-page.test.ts` (NEW) — 7 vitest cases (happy / empty / 503 / approve / reject empty / reject with reason / expired countdown).
- [ ] 7. `apps/web/tests/countdown.test.ts` (NEW) — pure test of `formatCountdown` (5 cases).
- [ ] 8. `ApprovalCard.stories.ts` — 3 variants (fresh / expiring-soon / delivery-failures).
- [ ] 9. `pnpm test` + `pnpm check` + `pnpm build` green locally (scoped).
- [ ] 10. Push + open PR with §4.5 self-review.
- [ ] 11. Wait CI all-green (15 checks).
