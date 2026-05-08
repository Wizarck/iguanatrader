# Retrospective: research-news-catalysts-adapters (slice R3)

- **Archived**: 2026-05-08 (post-hoc; PR merged 2026-05-06)
- **PR**: [#89](https://github.com/Wizarck/iguanatrader/pull/89)
- **Squash SHA**: `1767483`
- **Archive path**: `openspec/changes/archive/2026-05-06-research-news-catalysts-adapters/`
- **Schema**: spec-driven
- **Tasks**: 100% (5 Tier-1 webfetch adapters + 2 Tier-2 Playwright adapters + 2 bars adapters + scrape-ladder ADR-017 + ESG ban)

## What worked

- **9 source adapters** (Finnhub, GDELT, OpenFDA, World Bank WGI, V-Dem, OpenInsider, Finviz scrape, IBKR bars, yfinance fallback) all implement R1's `SourcePort` Protocol — zero coupling to repository internals.
- **4-tier scrape ladder (ADR-017)**: WebFetch → Playwright → Camoufox MCP → manual. Forms a documented escalation path that R5 + future scrape consumers reuse.
- **Tier-B (snapshot) vs Tier-C (bootstrap) `pit_class` distinction** in `research_sources` drives FR75 feature-availability gating in R5 brief synthesis.
- **ESG/sustainability data explicitly banned** (per ADR-016 research-domain-and-backtest-skip) — keeps the source set tight + the methodology auditable.

## What didn't

- **Post-hoc archive only** (same silent-drift pattern as the other Wave 3 slices; addressed by ai-playbook v0.10.2 propagate-archive workflow).
- **Bars adapters duplicated effort** with what later landed in T4-followup-market-data (`IbAsyncMarketDataIngestor`). The R3 `ibkr_bars.py` adapter targets one-shot research backfill; the T4-followup ingestor targets recurring daemon-driven ingestion. **Both exist** and serve different consumers — but a future cleanup could unify the IBKR historic-bar surface.

## Lessons

- **Tier-1/Tier-2 separation** (webfetch vs Playwright) at the source-adapter layer is a sound abstraction — each adapter knows its own resilience needs without leaking up to the service.
- **`pit_class` as a column** (vs. a per-adapter Boolean) propagates correctly through the synthesis pipeline because it's stored on the row, not on the code path.

## Carry-forward (closed downstream / pending)

- ✅ R5 synthesis consumes facts from all 9 adapters via the unified `ResearchRepository.list_facts(...)` query path.
- (Future) Unify `ibkr_bars.py` (R3 research adapter) with `IbAsyncMarketDataIngestor` (T4-followup-market-data daemon adapter) — both pull from `reqHistoricalDataAsync`; one cache layer would suffice.
- (Future) `research-frontend-components` slice will surface the citation chain from these adapters in the UI.
