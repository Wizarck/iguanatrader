# Tasks: property-tests-bus-bridge-handlers

- [ ] 1. `tests/property/test_risk_proposal_created_handler.py` — 3 Hypothesis properties (proposal-exists, kill-switch, missing-proposal)
- [ ] 2. `tests/property/test_approval_requested_handler.py` — 4 Hypothesis properties (create_request count, dispatcher invocation, dispatcher isolation, no-dispatcher path)
- [ ] 3. Local lint + format: `ruff check` + `black --check`
- [ ] 4. Push branch + open PR + wait CI green
- [ ] 5. Merge + archive openspec + fill retro
