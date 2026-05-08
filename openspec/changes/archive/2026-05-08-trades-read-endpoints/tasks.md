# tasks — trades-read-endpoints

## 1. Repository additions (`apps/api/src/iguanatrader/contexts/trading/repository.py`)

- [ ] **1.1** `TradeRepository.list_for_tenant()` — ~6 LoC.
- [ ] **1.2** `FillRepository.list_for_trade(trade_id)` — ~10 LoC (JOIN via `Order.trade_id`).

## 2. Route bodies (`apps/api/src/iguanatrader/api/routes/trades.py`)

- [ ] **2.1** Replace `list_trades` 501 stub with body per design §1. ~15 LoC + imports.
- [ ] **2.2** Replace `get_trade` 501 stub with body. ~12 LoC.
- [ ] **2.3** Replace `list_trade_fills` 501 stub with body. ~13 LoC.
- [ ] **2.4** Drop the now-unused `_stub` helper if no remaining 501 routes (likely keep — list_proposals etc. still 501 elsewhere).

## 3. Tests (`apps/api/tests/integration/test_trade_routes.py` NEW)

- [ ] **3.1** 5 tests per design §3.

## 4. Lint + mypy + commit

- [ ] **4.1** ruff + black + mypy --strict locally.
- [ ] **4.2** Branch `slice/trades-read-endpoints` → push → PR → admin merge → archive + retro fill.

## Estimated effort

| Group | Files | Effort | LoC |
|---|---|---|---|
| 1 Repo methods | repository.py (+~16) | 0.25h | ~16 |
| 2 Route bodies | trades.py (~+45 net) | 0.5h | ~45 |
| 3 Tests | test_trade_routes.py NEW | 1h | ~140 |
| 4 Lint + commit | — | 0.25h | – |

**Total**: ~2h, ~200 LoC.
