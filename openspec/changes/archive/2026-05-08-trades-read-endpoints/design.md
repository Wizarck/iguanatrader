# Design — trades-read-endpoints

> 3 GET route bodies + 2 repository methods. Trivial; design.md exists for gate symmetry.

## 1. Routes (`apps/api/src/iguanatrader/api/routes/trades.py`)

```python
@router.get("", response_model=TradeListOut)
async def list_trades(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradeListOut:
    log.info("api.trades.list", tenant_id=str(user.tenant_id))
    session_var.set(db)
    repo = TradeRepository()
    rows = await repo.list_for_tenant()
    return TradeListOut(
        items=[TradeOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )

@router.get("/{trade_id}", response_model=TradeOut)
async def get_trade(
    trade_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradeOut:
    log.info("api.trades.get", trade_id=str(trade_id))
    session_var.set(db)
    repo = TradeRepository()
    row = await repo.get_by_id(trade_id)
    if row is None:
        raise NotFoundError(detail=f"Trade {trade_id} not found.")
    return TradeOut.model_validate(row)

@router.get("/{trade_id}/fills", response_model=FillListOut)
async def list_trade_fills(
    trade_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FillListOut:
    log.info("api.trades.fills", trade_id=str(trade_id))
    session_var.set(db)
    repo = FillRepository()
    rows = await repo.list_for_trade(trade_id)
    return FillListOut(
        items=[FillOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )
```

`session_var.set(db)` mirrors `proposals.py:get_proposal` (same shape).

## 2. Repository additions

### `TradeRepository.list_for_tenant() -> list[Trade]` (`contexts/trading/repository.py`)

```python
async def list_for_tenant(self) -> list[Trade]:
    stmt = select(Trade).order_by(Trade.created_at.desc())
    result = await self.session.execute(stmt)
    return list(result.scalars().all())
```

Tenant filter is automatic via slice-3 `tenant_listener`.

### `FillRepository.list_for_trade(trade_id: UUID) -> list[Fill]`

```python
async def list_for_trade(self, trade_id: UUID) -> list[Fill]:
    stmt = (
        select(Fill)
        .join(Order, Fill.order_id == Order.id)
        .where(Order.trade_id == trade_id)
        .order_by(Fill.filled_at.asc())
    )
    result = await self.session.execute(stmt)
    return list(result.scalars().all())
```

JOIN via `Order.trade_id` because `Fill` has `order_id` (not `trade_id`) — same shape as `OrderRepository.get_by_proposal_id`.

## 3. Tests (`apps/api/tests/integration/test_trade_routes.py` NEW)

Mirror the shape of `test_approval_routes.py`:

| # | Test | Assert |
|---|---|---|
| 1 | `test_list_trades_returns_tenant_trades_sorted_desc` | 200 + `TradeListOut.items` ordered `created_at DESC` |
| 2 | `test_list_trades_empty_for_new_tenant` | 200 + `items == []` + `total == 0` |
| 3 | `test_get_trade_returns_200_on_hit` | 200 + `TradeOut.id == trade_id` |
| 4 | `test_get_trade_returns_404_on_miss` | 404 RFC 7807 with `type=urn:iguanatrader:error:not-found` |
| 5 | `test_list_trade_fills_joins_via_orders` | 200 + fills filtered to the requested trade |

## 4. Anti-patterns

- Do NOT add pagination (cursor) in this slice — v1 trade volume trivial; v2 SaaS adds.
- Do NOT add filter/sort query params — same v2 deferral.
- Do NOT touch portfolio.py or strategies.py — separate slices.
