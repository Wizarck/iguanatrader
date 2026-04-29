---
type: hitl-gates-log
project: iguanatrader
schema_version: 1
created: 2026-04-28
updated: 2026-04-28
purpose: Append-only record of HITL gate approvals per .ai-playbook/specs/runbook-bmad-openspec.md §5
---

# HITL Gates Log — iguanatrader

Append-only registro de aprobaciones humanas en cada gate del runbook BMAD+OpenSpec. Cada entrada cita el artifact aprobado y la session ID del chat donde se otorgó la aprobación.

Per [`.ai-playbook/specs/runbook-bmad-openspec.md`](../.ai-playbook/specs/runbook-bmad-openspec.md) §5: "Humans may delegate D/E/F to a designated reviewer, but the gate must be **recorded** in the retro. An archived change whose gates have no recorded approver is an audit-fail in the monthly lifecycle check."

## Format

```
### Gate <X> — <name>
- **Date**: YYYY-MM-DD
- **Approved by**: <human name + email>
- **Artefact(s) approved**: <path:line or doc title>
- **Session**: <claude-code session id or git ref>
- **Decision**: ✅ approved / ⚠️ approved-with-conditions / ❌ rejected
- **Conditions / notes**: free-form
- **Retroactive?**: yes / no (if yes, original verbal approval date)
```

---

## Log

### Gate A — Post-PRD

- **Date**: 2026-04-28 (retroactive record)
- **Approved by**: Arturo Ramírez (arturo6ramirez@gmail.com)
- **Artefact(s) approved**: `docs/prd.md` (frontmatter `date: 2026-04-27`, sealed) + `docs/prd-validation-report.md` (status PASS, 4.5/5 holistic)
- **Session**: claude-code session `b55aa492-1810-48dd-9cae-077ed1156884` (rolled into current session via /compact)
- **Decision**: ✅ approved
- **Conditions / notes**:
  - PRD passed bmad-validate-prd 13-check audit (PASS, holistic 4.5/5).
  - Top-3 polish edits applied via bmad-edit-prd (4 cosmetic FR56/NFR-S6/NFR-S7/NFR-O2 fixes; Fraud Prevention consolidated subsection; Journey 3 routine clarification).
  - User responded "E" then "S" to validation summary, then proceeded to /bmad-agent-architect — implicit approval to advance to Phase 2 (architecture).
  - Approval recorded retroactively 2026-04-28 after gap discovered in compliance audit against `.ai-playbook/specs/runbook-bmad-openspec.md` §5.
- **Retroactive?**: yes (original verbal approval ~2026-04-27 during edit/validate workflow)

---

### Gate A amendment — Research & Intelligence Domain addition + Backtest skip

- **Date**: 2026-04-28
- **Approved by**: Arturo Ramírez (arturo6ramirez@gmail.com)
- **Artefact(s) approved**:
  - PRD section "[REMOVED 2026-04-28] Backtest & Research" (FR6-FR10 eliminated)
  - PRD section "Research & Intelligence Domain" (FR57-FR79 added — 23 new FRs)
  - PRD updated NFRs: NFR-P6 + NFR-O6 removed; NFR-P9 + NFR-O8 added
  - `docs/research/data-sources-catalogue.md` (38 sources × 12 categories researched)
  - `AGENTS.md` §7 Override 1 — paper-trading hard rule relaxed to recommendation
- **Session**: claude-code session continuation (current); informed by background research agent task `ad4eeec10a4e727fa`
- **Decision**: ✅ approved
- **Conditions / notes**:
  - Backtest skipped (Camino C). User confirmed "skippeamos y no hace falta gate, quien quiera probar live puede hacerlo, es a riesgo del usuario".
  - Paper trading remains strongly recommended via AGENTS.md §7 Override 1; CLI surface emits WARNING with risk acknowledgment text rather than block when user goes live without paper history.
  - Research domain 7 open questions resolved 2026-04-28:
    1. **OpenBB**: sidecar process from day 1 (HTTP localhost isolation; AGPL boundary preserved).
    2. **Paid tiers**: €0 MVP; escalate to Polygon Stocks Starter $29/mo when yfinance breaks first time.
    3. **PiT policy**: 3-tier system (A native PiT / B snapshot collected / C bootstrap), strategy code MUST handle None gracefully; CI assertion for tier-B usage in queries (FR75).
    4. **Knowledge schema**: bitemporal `effective_from/to × recorded_from/to` (FR68); ADR-014 to be created.
    5. **GDELT BigQuery**: free tier with date+ticker partitioning, target ≤100 GB/mo, accept $5-20/mo if ceiling exceeded.
    6. **Insider sources**: Form 4 EDGAR (authoritative) + OpenInsider scraping (aggregated screens) — both included MVP.
    7. **ESG**: yfinance.sustainability included as best-effort single-source; backtest features ESG prohibited (tier-B per FR75).
  - 4 critical caveats acknowledged: (1) yfinance grey-area + non-PiT, (2) OpenBB AGPL trap → sidecar mitigation, (3) SEC Climate Rule withdrawn 2025-03 → ESG single-source only, (4) captcha solver paid service available.
- **Retroactive?**: no (current decision 2026-04-28)

---

### Gate B — Post-ADRs + Data Model + Project Structure

- **Date**: 2026-04-28
- **Approved by**: Arturo Ramírez (arturo6ramirez@gmail.com)
- **Artefact(s) approved**:
  - `docs/architecture-decisions.md` (final state post Gate A amendment): research bounded context added (~80 archivos en `contexts/research/`), backtest context removed, ADR-014/015/016/017 referenced in tree, OpenBB sidecar topology section added, critical path "research_brief synthesis with Hindsight integration" documented, Hindsight integration row added to External integrations table, settings/ route + cli/settings.py + 2 hindsight adapters + settings web route added
  - `docs/data-model.md` (final state post Gate A amendment): 22 tablas iniciales + 7 nuevas research tables (research_sources cross-tenant, symbol_universe, watchlist_configs, research_facts bitemporal, research_briefs versioned, corporate_events, analyst_ratings); 4 open questions §7 resueltas (audit_log scoped, snapshot_kind drop tick, JSON1 CI verify, trades.state dual storage); 4 open questions §7b resueltas (forever SQL + Hindsight complementary, 3-col polymorphism, hybrid 16KB threshold, per-tenant MVP/ADR-018 v2); `tenants.feature_flags` JSONB column added with `hindsight_recall_enabled` allowlist key
  - `docs/project-structure.md` (created standalone): ~700 lines, 16 sections, full monorepo tree with ~120+ files annotated, boundary summary table, license/Apache+CC vs AGPL/openbb-sidecar isolation documented
  - `docs/prd.md` Research domain extended: FR80 (Hindsight write always-on) + FR81 (Hindsight recall togglable) + NFR-I8 (recall latency p50<500ms p95<2s, graceful degradation) added; total 76 FRs + 52 NFRs
- **Session**: claude-code session continuation; Batch 3 of recovery sequence (Hindsight integration finalized 2026-04-28 evening)
- **Decision**: ✅ approved
- **Conditions / notes**:
  - All 4 §7 open questions resolved with documented decisions in data-model.md
  - All 4 §7b research-domain open questions resolved with documented decisions in data-model.md
  - Hindsight integration final design: write-on day 1 + read-togglable per-tenant via `tenants.feature_flags.hindsight_recall_enabled` (default OFF, recommended ON after ≥12 months operation). Rationale: build narrative history from MVP launch so recall has substance when user enables it; below 12 months recall is sparse and adds noise to LLM context.
  - Hindsight does NOT replace SQL bitemporal storage; both layers operate independently (SQL = structured exact provenance + audit; Hindsight = narrative semantic complement). Archive policy is v3+ concern when storage cost becomes material.
  - 4 new ADRs to be drafted as separate artifacts in `docs/adr/` post-Gate B (ADR-014 bitemporal research_facts, ADR-015 OpenBB sidecar isolation, ADR-016 research domain + backtest skip, ADR-017 scrape ladder 4 tiers); referenced in tree but not yet written. Acceptable per BMAD: ADRs document the decision; the decision itself is captured in architecture-decisions.md with traceability to gate amendment.
- **Retroactive?**: no

---

### Gate C — Post-slicing

- **Date**: 2026-04-28
- **Approved by**: Arturo Ramírez (arturo6ramirez@gmail.com)
- **Artefact(s) approved**:
  - [`docs/openspec-slice.md`](openspec-slice.md) — 20 changes, 4 parallel waves, max 7 simultaneous agents per wave (canonical schema per `.ai-playbook/specs/bmad-openspec-bridge.md` §3.1; renamed from `openspec-slice-plan.md` 2026-04-29 for runbook compliance)
  - Optimization target confirmed: **maximum-parallelism-with-disjoint-write-paths** (over cohesion + reviewability per single-dev assumption)
  - Anti-collision patterns confirmed for slice 5 (`api-foundation-rfc7807`):
    - API routes auto-discovery via `pkgutil.iter_modules` in `routes/__init__.py`
    - SSE auto-discovery same pattern
    - CLI typer auto-discovery in `cli/main.py`
    - Frontend sidebar dynamic enumeration via `import.meta.glob`
    - Pre-commit regenerates `apps/web/src/lib/api/index.ts` from glob
    - Alembic migrations monotonic numbering with no-gap CI validation
    - Makefile includes pattern (`Makefile.includes` per slice)
  - Per-slice workflow confirmed: `git worktree` per slice + `slice/<id>` branch + Agent tool with `isolation: "worktree"` + CI gates + PR + squash-merge
- **Session**: claude-code session continuation; closure of BMAD Discovery (Phase 1-2) and entry into OpenSpec Implementation (Phase 3)
- **Decision**: ✅ approved
- **Conditions / notes**:
  - Each slice name ≤6 words (verified)
  - Each slice has ≤2 directory write_paths principales (with documented exceptions for `bootstrap-monorepo` and `dashboard-svelte-skeleton` which by nature touch many files)
  - Estimated ≤10 acceptance scenarios per slice (final count materializes during `/opsx:propose` per-slice)
  - All 76 FRs + 52 NFRs traced to ≥1 slice in the catalogue
  - `litestream-backup-setup` folded into slice 1 (`bootstrap-monorepo`); `gotchas.md` populated incrementally per slice (NFR-M7)
  - `dependency-graph-validator` script optional, deferred (not blocking)
  - 4 ADRs pending physical drafting (ADR-014/015/016/017) — to be authored in slice 1 (`bootstrap-monorepo`) acceptance criteria
- **Retroactive?**: no

---

### Gate E — Pre-apply (slice 1: bootstrap-monorepo)

- **Date**: 2026-04-29
- **Approved by**: Arturo Ramírez (arturo6ramirez@gmail.com)
- **Artefact(s) approved**:
  - [`openspec/changes/bootstrap-monorepo/proposal.md`](../openspec/changes/bootstrap-monorepo/proposal.md) — 3 New Capabilities (`monorepo-tooling`, `secrets-baseline`, `compliance-baseline`); foundation NFRs (NFR-S1, NFR-S2, NFR-M9)
  - [`openspec/changes/bootstrap-monorepo/design.md`](../openspec/changes/bootstrap-monorepo/design.md) — 8 decisions (Poetry workspaces, pnpm 9, four standalone compose files, SOPS+age, hook ordering gitleaks-first, Makefile + per-package includes, ADR placeholders strategy, LICENSE byte-verified)
  - [`openspec/changes/bootstrap-monorepo/specs/monorepo-tooling/spec.md`](../openspec/changes/bootstrap-monorepo/specs/monorepo-tooling/spec.md) — 6 requirements / 13 scenarios
  - [`openspec/changes/bootstrap-monorepo/specs/secrets-baseline/spec.md`](../openspec/changes/bootstrap-monorepo/specs/secrets-baseline/spec.md) — 3 requirements / 5 scenarios
  - [`openspec/changes/bootstrap-monorepo/specs/compliance-baseline/spec.md`](../openspec/changes/bootstrap-monorepo/specs/compliance-baseline/spec.md) — 6 requirements / 8 scenarios
  - [`openspec/changes/bootstrap-monorepo/tasks.md`](../openspec/changes/bootstrap-monorepo/tasks.md) — 11 task groups, 50 tracked tasks
- **Session**: claude-code session continuation post-compact 2026-04-29; `npx openspec validate bootstrap-monorepo` → valid
- **Decision**: ✅ approved
- **Conditions / notes**:
  - Release management model confirmed: **1 rama = 1 slice = 1 PR**, NOT one branch per task. Tasks live as a checklist inside the slice's PR; reviewer approves once at the end (Gate F).
  - GH Project #2 "iguanatrader" tracks the **20 slices** as items (one per slice), not the 50+ tasks per slice. Status field will be expanded with "Review" and "Blocked" options before items are created.
  - CI verde es prerequisito para que el PR pase de "In Progress" → "Review" en el Project board.
  - Order of merge governed by the dependency graph in `docs/openspec-slice.md`: Wave 0 sequential (1→2→3) → Wave 1 parallel (4║5) → Wave 2 parallel (×6) → Wave 3 parallel (×7) → Wave 4 parallel (×2).
- **Retroactive?**: no

---

## Pending gates

- **Gates D/F** — per-OpenSpec-change (continuing per slice):
  - **Gate D** (per artefact): QA subagent verdict ✅/⚠️/❓ on `proposal.md` → `specs/*.md` || `design.md` → `tasks.md` (deferred for slice 1 since artefacts were authored interactively + validated; will run for slices 2+)
  - **Gate F** (pre-archive): human approves implementation diff + tests + retro draft before `/opsx:archive`
