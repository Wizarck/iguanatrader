---
type: roadmap
project: iguanatrader
schema_version: 1
created: 2026-05-17
updated: 2026-05-17
purpose: Forward-looking slice plan for the iguanatrader web frontend (apps/web). Lean — each row points at a future slice; when work starts, open an OpenSpec change and link it back here.
---

# Roadmap — Web UI track

Single source of truth for UX / frontend improvements that don't fit the LLM-features roadmap. Each row is a candidate slice; status reflects implementation state, not priority.

**Track owner**: Arturo Ramírez.
**Scope**: Anything visible inside `apps/web/` (research, portfolio, approvals, risk, costs, settings pages).

## Status legend

- `proposed` — described here, no implementation work yet
- `in-progress` — branch open, OpenSpec change exists
- `merged` — code on main
- `deployed` — running in production on the VPS
- `parked` — descoped or deferred indefinitely

---

## U1 — Symbol search autocomplete (research landing page)

**Status**: proposed
**Where**: [apps/web/src/routes/(app)/research/+page.svelte](../apps/web/src/routes/(app)/research/+page.svelte) ("Buscar brief" form).
**Estimated**: ~250 LoC + 1 new API route (read-only).

### What

When the user types in the symbol search bar (currently a plain `<input>` with a "Buscar brief" submit button), open a dropdown listing matching symbols with both **ticker** and **company name**:

```
NV|
┌─────────────────────────────────────┐
│  NVDA  NVIDIA Corporation           │
│  NVTS  Navitas Semiconductor Corp.  │
│  NVMI  Nova Ltd.                    │
└─────────────────────────────────────┘
```

Keyboard navigation (`↑/↓` to highlight, `Enter` to select, `Esc` to close), debounced server lookup (~150 ms), capped at ~10 results.

### Why

Today the user has to know the ticker by heart. The current input only accepts uppercase + digits but offers no help discovering what to type. With autocomplete the same field becomes a discovery tool for the operator's whole `symbol_universe` (per-tenant) AND a fall-back to a public ticker index for symbols not yet registered.

### Components

- **API**: new route `GET /api/v1/symbols/search?q=<prefix>&limit=10` returning `[{symbol, name, exchange, registered: bool}]`. Two sources, concatenated + de-duplicated by symbol:
  1. The tenant's own `symbol_universe` rows (highest priority — operator already cares about these).
  2. A small bundled snapshot of NASDAQ / NYSE listings (~10k rows) for discovery. Considered: pull from SEC EDGAR company tickers JSON (already used by R2 EDGAR adapter), shipped as a static asset under `apps/web/static/` or fetched once at api boot and cached in-memory.
- **Component**: new `apps/web/src/lib/components/research/SymbolSearch.svelte` with a debounced `$effect` driving `fetch`. Replace the plain input in the research landing page with this component.
- **Behaviour**: if the user submits a symbol that's NOT in their `symbol_universe`, the existing flow already 404s with a registration hint. The autocomplete should add a "+ Register …" entry at the bottom when the prefix doesn't match anything, linking to `iguanatrader admin register-symbol` docs (or, future, an in-UI registration modal).

### Open questions

- Bundled ticker list size vs accuracy trade-off — 10k US-listed common stocks covers the realistic universe but bumps the web image by ~500 KB. Worth gating behind a CDN-loaded JSON?
- Should we also surface non-equity symbols (ETFs like SPY, futures)? SPY is already needed as the relative-strength benchmark — the autocomplete is a natural place to make that registration visible.

---

## U2 — Audit-trail viewer (replace raw JSON dump)

**Status**: proposed
**Where**: `apps/web/src/lib/components/research/AuditTrailViewer.svelte` already exists; needs to be wired into the brief detail page and the LLM prompt must stop bleeding raw JSON into the body.

### What

The brief detail page used to show the audit-trail entries as a raw JSON code block under the prose body. PR (in flight) fixes the synthesizer so the JSON is stripped from the body — this slice exposes the same data through `AuditTrailViewer` instead.

### Components

- Brief load fn fetches `/api/v1/research/audit-trail/{brief_version}` (route already exists).
- The detail page renders a collapsible `<details>` block under the prose with one table-style row per metric: metric · formula · inputs (with citation chips) · final_output.

---

## U3 — Investment recommendation styling

**Status**: proposed (partial — backend prompt emits the section, frontend just renders markdown)
**Where**: `apps/web/src/lib/components/research/BriefHeader.svelte` or a new `RecommendationCard.svelte`.

### What

The brief now contains a mandatory `## Recommendation` section with Action / Target / Horizon / Key risks. Promote it from inline markdown to a distinct card above the pillar prose — coloured chip for Action (green BUY / amber HOLD / red AVOID), bold target price, bulleted risks. Composite score migrates into the same card.

---

## U4 — Search highlight + recent symbols deduplication

**Status**: proposed
**Where**: `apps/web/src/lib/research/recent.ts` + the recent-symbols chips on the research landing page.

### What

Today the recent-symbols list dedupes case-insensitively (good) but doesn't reorder when an existing symbol is re-visited. Minor: bump the visited symbol to the front on each visit, capping at 5.

---

## How to start a slice

```
git checkout -b feat/u<N>-<slug>
# Open formal proposal:
/opsx:propose u<N>-<slug>
```

Then update this file's row Status from `proposed` to `in-progress` with the branch link.
