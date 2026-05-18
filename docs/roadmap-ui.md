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

> **Related landed slice** (2026-05-18, PR #213): the citation chip rendering
> now shows `fact_kind · value_excerpt` instead of just `[fact:UUID]` or a
> bare source name, and `factById` is built from the brief's authoritative
> `resolved_citations` so previously-unresolved facts now have provenance.
> The audit-trail viewer slice is the next layer: replace the raw JSON dump
> below the prose with a table-style view.

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

## U5 — Full app English translation

**Status**: proposed
**Estimated**: ~50 visible strings across 20+ files; mechanical work, no design churn.

### What

Today the app mixes Spanish UI prose with English labels (Spanglish). MVP convention: **English by default**. Per-tenant locale switching is out of scope; this slice only removes the Spanish strings.

### Components

- Grep `apps/web/src` for known Spanish phrases (`Nueva`, `Editar`, `Deshabilitar`, `Guardar`, `Cancelar`, `obligatorio`, `inválido`, `Selecciona`, `usa A-Z`, etc.) and translate to canonical English.
- Update the matching test assertions in `apps/web/tests/`.
- Where component help-text or confirm-dialogs reference Spanish, port to English while keeping the meaning.

### Why not now

PR `feat/strategies-form-rewrite-english` (this work) only translated the strategies pages because they were being rewritten anyway. Translating the rest in the same PR would have inflated the diff without solving the underlying UX bug. This slice handles the cleanup pass.

### Files known to contain Spanish strings as of 2026-05-18

- `apps/web/src/routes/(app)/portfolio/**` (some helper copy)
- `apps/web/src/routes/(app)/trades/**`
- `apps/web/src/routes/(app)/approvals/**`
- `apps/web/src/routes/(app)/research/**`
- `apps/web/src/routes/(app)/risk/**`
- `apps/web/src/routes/(app)/costs/**`
- `apps/web/src/routes/(app)/settings/**`
- Confirmation dialogs and error toasts globally.

---

## U6 — Light theme implementation

**Status**: proposed (currently stubbed)
**Estimated**: ~50 LoC CSS, plus contrast-audit pass against the OKLCH tokens.

### What

`apps/web/src/lib/stores/theme.svelte.ts` already toggles `data-theme="light"` on `<html>` and the `TopBar` exposes the moon/sun button. But `apps/web/src/app.css:21-23` declares the *same* dark palette under both `:root[data-theme='dark']` and `:root[data-theme='light']` — the toggle is therefore a visual no-op (documented in `theme.svelte.ts:9-13` and `app.css:14-20`).

This slice unblocks the toggle by defining a real light palette.

### Components

- New `:root[data-theme='light']` block in `app.css` with light-mode OKLCH tokens:
  - `--bg`: light surface (e.g. `oklch(98% 0.005 250)`)
  - `--surface`, `--surface-2`: lighter than bg
  - `--ink`: dark text (e.g. `oklch(20% 0.01 250)`)
  - `--mute`: mid-grey
  - `--border`: subtle line
  - Accents and semantic colours can stay; verify legibility.
- Remove the "render dark regardless" hack so the toggle takes visual effect.
- Update `html { color-scheme: dark; }` to be theme-aware (or drop it, since `data-theme` now drives the palette).
- Run `npm run test` + a manual smoke on every page; capture screenshots in the PR.

### Why not now

This is a design exercise (palette contrast, hover/focus states, badge legibility on light surfaces) on top of the CSS plumbing. Better handled as its own slice with the UX checklist.

---

## U7 — Backend strategies catalogue API

**Status**: proposed
**Estimated**: ~120 LoC backend + ~40 LoC frontend wiring.

### What

The strategy parameter catalogue (display name, description, per-parameter type/default/min/max/help) lives client-side at `apps/web/src/lib/strategies/types.ts`. Defaults are duplicated against the Python `DEFAULT_*` constants in `apps/api/src/iguanatrader/contexts/trading/strategies/*.py`. When a backend param changes, the frontend silently drifts.

This slice moves the catalogue to the backend as the source of truth.

### Components

- Each `Strategy` subclass exposes a `describe()` classmethod returning a Pydantic `StrategyDescriptor` (kind + display_name + description + ParamSpec list).
- `StrategyManager.registry()` returns the list of descriptors.
- `GET /api/v1/strategies/catalogue` route surfaces them.
- Frontend swaps `STRATEGY_CATALOGUE` from the TS module to a server-loaded async value via `+page.server.ts` for `/strategies/new` and `/strategies/[symbol]`.
- The TS catalogue stays as a fallback for SSR + tests where the API isn't reachable.

### Why not now

Frontend catalogue ships the form today; backend catalogue is the right long-term split but isn't blocking any user flow.

---

## How to start a slice

```
git checkout -b feat/u<N>-<slug>
# Open formal proposal:
/opsx:propose u<N>-<slug>
```

Then update this file's row Status from `proposed` to `in-progress` with the branch link.
