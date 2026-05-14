# Proposal: proposals-list-endpoint

> **Wire `GET /api/v1/proposals` — the LAST 501 stub in the API surface.** Body already exists for `GET /{proposal_id}` (T4) + `POST /{id}/approve`. After this slice ships there are zero remaining 501 stubs and the `test_trading_route_stubs.py` parametrized list goes empty.

## Why

Audit on 2026-05-13 (PR #142 retro) identified `GET /api/v1/proposals` as the sole genuinely-unwired endpoint. Closing it now:
- Unblocks the `/approvals` dashboard tab's future "view proposal details" link
- Unblocks any future "Recent proposals" widget on the portfolio dashboard
- Zeros out `STUB_ENDPOINTS` in `test_trading_route_stubs.py` — clean state going into v1.5+

## What

### Route body

`apps/api/src/iguanatrader/api/routes/proposals.py::list_proposals` — replace `raise _stub(...)`:

```python
@router.get("", response_model=ProposalListOut)
async def list_proposals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalListOut:
    """List proposals for the authenticated tenant (FR11)."""
    log.info("api.proposals.list", tenant_id=str(user.tenant_id))
    session_var.set(db)
    repo = TradeProposalRepository()
    rows = await repo.list_for_tenant()
    return ProposalListOut(
        items=[ProposalOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )
```

### Repo addition

`apps/api/src/iguanatrader/contexts/trading/repository.py::TradeProposalRepository`:

```python
async def list_for_tenant(self) -> list[TradeProposal]:
    """List all proposals for the current tenant (slice proposals-list-endpoint).

    Tenant filter automatic via slice-3 ``tenant_listener``. Ordered
    ``created_at DESC`` (most-recent first); pagination v2.
    """
    stmt = select(TradeProposal).order_by(TradeProposal.created_at.desc())
    result = await self.session.execute(stmt)
    return list(result.scalars().all())
```

### Stub-pin test cleanup

`apps/api/tests/integration/test_trading_route_stubs.py::STUB_ENDPOINTS` — empty the list:

```python
STUB_ENDPOINTS: list[tuple[str, str]] = []
```

The `test_trading_stub_returns_501_problem` parametrized test still exists (becomes a no-op when the list is empty). The `test_openapi_surfaces_all_four_trading_route_prefixes` assertion stays — it's a useful smoke check.

### Tests

`apps/api/tests/integration/test_proposals_routes.py` (NEW):
1. `test_list_proposals_empty_tenant` — fresh tenant → `{items: [], total: 0, next_cursor: null}`.
2. `test_list_proposals_returns_tenant_proposals_sorted_desc` — seed 2 proposals at different `created_at` → newest first.
3. `test_list_proposals_isolated_across_tenants` — tenant A's proposals invisible to tenant B (tenant_listener).

### Logs

`api.proposals.list` topical event with `tenant_id` + `count`.

## Out of scope

- **Pagination cursor** — `next_cursor=None` in v1; v2 SaaS slice adds it.
- **Filter params** (by symbol, by date range, by state) — v1.5 (`proposals-filters`).
- **Manual proposal POST** — `ProposalIn` DTO is planted but the endpoint is not wired. T4 explicitly deferred this; v2.
- **Frontend consumer** — no UI uses this yet; will be consumed by future "Recent proposals" widget + approval-detail-view.
