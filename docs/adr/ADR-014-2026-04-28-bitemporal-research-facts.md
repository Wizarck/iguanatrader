---
adr: 014
date: 2026-04-28
status: proposed
decided-by: Arturo Ramírez (arturo6ramirez@gmail.com)
tags: [research, data-model, bitemporal, audit]
---

# ADR-014 — Bitemporal `research_facts` schema

## Status

**Proposed**. Recorded at Gate B (2026-04-28); full body lands when slice **R1** (`research-bitemporal-schema`) implements the table — at which point this ADR transitions to `accepted`.

## Stub

The Research bounded context stores facts (corporate filings, macro indicators, news catalysts, analyst ratings, etc.) in a single `research_facts` table with **two time dimensions**:

- `effective_from` / `effective_to` — when the fact is *true in the world* (e.g. the quarter the financial result covers).
- `recorded_from` / `recorded_to` — when the system *learned* the fact (the snapshot ingestion timestamp).

This bitemporal schema is required because methodology backtests, audit trails, and citation chains (NFR-O8) all need to answer "what did the system *know* on date X about period Y", not just "what was true on date Y".

## Cross-references

- `docs/architecture-decisions.md` — Step 4 "Research bounded context", §"Bitemporal facts table".
- `docs/data-model.md` §6 (Research domain tables) — schema definition.
- `docs/data-model.md` §7b Q2 — open-question resolution citing this ADR.
- `docs/hitl-gates-log.md` — Gate B amendment 2026-04-28 (research domain addition).
- `docs/openspec-slice.md` row R1 — slice that lands this schema.

## Full content

Pending. Slice R1's `proposal.md` + `design.md` + spec scenarios will populate this ADR's full Context / Decision / Consequences sections via the OpenSpec lifecycle.
