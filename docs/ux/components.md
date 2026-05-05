---
title: iguanatrader — Components catalogue
status: DRAFT v1
date: 2026-05-01
parent: docs/ux/
related:
  - j1.md
  - j2.md
  - j3.md
  - ../prd.md
  - ../architecture-decisions.md
  - ../personas-jtbd.md
  - ../openspec-slice.md
---

# iguanatrader — Components catalogue (DRAFT v1)

> Source: FR54-FR56 (web dashboard), FR12-FR18 (proposals/approval), FR58 + FR71-FR75 (research briefs), FR42-FR44 (weekly review PDF), FR81 (Hindsight toggle), Arturo persona ([personas-jtbd.md](../personas-jtbd.md)), Architecture Decisions §Frontend stack rationale + §Frontend Architecture (Svelte 5 + SvelteKit + Tailwind 4.x + TypeScript strict), [openspec-slice.md](../openspec-slice.md) rows 4 / W1 / R5 / R6 / P1 / T4.

This file is the **single canonical components catalogue** for `apps/web`. It is the contract between design and engineering: if a Svelte story does not match the doc here, the doc is wrong — fix it.

The frontend stack is **Svelte 5 + SvelteKit + Tailwind CSS 4.x + TypeScript strict** (canonical per Architecture Decisions §Frontend stack rationale; HTMX option from earlier discovery rounds was explicitly rejected after architect roundtable). All component prop shapes are written as TypeScript-ish interfaces consumed by Svelte 5 runes (`$props()`).

---

## 0. Conventions

### 0.1 File layout

- Primitives + dashboard atoms: `apps/web/src/lib/components/<Name>.svelte`.
- Navigation atoms: `apps/web/src/lib/components/nav/<Name>.svelte`.
- Research-domain atoms (BriefHeader, FactTimeline, CitationLink, AuditTrailViewer, MethodologyBadge): `apps/web/src/lib/components/research/<Name>.svelte`.
- Approval-domain atoms (ApprovalCard, ApprovalList, OverrideForm): `apps/web/src/lib/components/approvals/<Name>.svelte`.

### 0.2 Universal states

Every interactive component honours these eight states (per `docs/ux/DESIGN.md` §4 — to be authored by Sally before slice 4 starts):

| State | Trigger | Visual contract |
|---|---|---|
| `default` | resting | base tokens |
| `hover` | pointer:fine over | `--accent-hover` or 1-step lift |
| `focus` | keyboard tab-in | 2px outline using `--focus-ring` |
| `active` | mousedown / Enter | `--accent-active` |
| `disabled` | `disabled` prop / loading | `opacity: 0.45`, `cursor: not-allowed`, no pointer events |
| `loading` | async work in flight | inline `Spinner` slot, label preserved |
| `error` | failed validation / async error | `--destructive` border + inline message |
| `empty` | data array length 0 | `EmptyState` component or inline copy |

Hover-only affordances are forbidden on `pointer:coarse` (mobile/tablet). All touch targets ≥48×48 CSS px. Reduced motion respected per `prefers-reduced-motion: reduce`.

### 0.3 Design tokens

Locked 2026-05-05 (Sally + Arturo). Canonical values live in [`DESIGN.md`](DESIGN.md) §1; the catalogue references token names only.

**Philosophy**: dark-first (Bloomberg/TradingView lineage; trading software is read in low-light operational sessions); P&L semantics are **dual-channel** (color + sign + icon) so red/green never carry the load alone (color-blind safety). Tailwind 4.x native OKLCH.

| Token | OKLCH | Use | Contrast on `--bg` |
|---|---|---|---|
| `--bg` | `oklch(18% 0.02 250)` | app background | base |
| `--surface` | `oklch(22% 0.02 250)` | cards, panels | — |
| `--surface-2` | `oklch(26% 0.02 250)` | popovers, drawers, modal | — |
| `--ink` | `oklch(95% 0.005 250)` | body text | 12.6:1 (AAA) |
| `--mute` | `oklch(70% 0.012 250)` | secondary text, helper | 6.5:1 (AA) |
| `--border` | `oklch(32% 0.02 250)` | dividers, Input border resting | — |
| `--accent` | `oklch(72% 0.14 195)` | iguana teal — primary CTA, focus, brand | 4.7:1 (AA) |
| `--accent-fg` | `oklch(15% 0.02 250)` | text on accent fills | — |
| `--success` | `oklch(72% 0.16 145)` | P&L positive, "Open" Badge | 5.4:1 (AA) |
| `--destructive` | `oklch(64% 0.20 25)` | P&L negative, kill-switch, "Reject" CTA | 4.6:1 (AA) |
| `--warn-bg` | `oklch(78% 0.14 80)` | Tier-2 cap banner, T-10s countdown | — |
| `--focus-ring` | `oklch(72% 0.14 195)` | 2px outline (= `--accent`) | — |

**Typography**:

- Body: **Inter Variable** with `font-feature-settings: 'cv11', 'ss01'`; fallback chain `system-ui, -apple-system, sans-serif`. Single variable woff2 covers all weights.
- Mono: **JetBrains Mono Variable** for monetary values, equity, prices, JSON audit, YAML editor. Monetary cells always carry `font-variant-numeric: tabular-nums`.
- No serif (operational software).

**Spacing**: Tailwind 4.x defaults (4px grid). No custom scale.

**Border radius**: `--r-1: 4px` (Input sm, Badge sm) · `--r-2: 8px` (Button, Input default) · `--r-3: 12px` (Card, Drawer) · `--r-pill: 9999px` (Badge variant).

**Light mode**: deferred non-blocker. Slice 4 ships dark-only; light derivation lands in slice W1 alongside the system-preference toggle (per Architecture Decisions §Frontend Architecture line 382: "Tailwind dark mode + system preference desde MVP" — *availability* is MVP, but the *toggle UI surface* lives in W1).

### 0.4 Accessibility floor (MVP)

Per Architecture Decisions §Frontend Architecture: WCAG 2.1 AA target is v3 SaaS; **MVP catches low-hanging via `eslint-plugin-svelte` a11y rules**. The catalogue still records the AA-friendly choice for every component so Sally's pass to v3 is incremental, not a rewrite. WCAG-AA contrast ratios are recorded per token pair in [`DESIGN.md`](DESIGN.md) §1.2 + §1.3 (locked 2026-05-05).

### 0.4b Modal-route pattern (drawers + modals carry URL state)

Locked 2026-05-05 (Sally + Arturo, validated against [variants/mock-j1-3-trade-detail.html](variants/mock-j1-3-trade-detail.html)).

Drawers and modals that show a specific entity (a trade, an audit-trail version, an override audit row) **MUST carry the entity ID as a URL query param** (e.g. `?detail=<id>`, `?audit=<version>`, `?override=<id>`). The pattern:

- Opening the drawer pushes the param via `goto({ keepFocus: true })` (SvelteKit) — preserves the parent page's filters, scroll position, and active SSE connections.
- Closing the drawer (Esc / X / backdrop click) drops the param via `goto` again.
- Reload re-mounts the drawer over the current filtered view.
- Browser back button closes the drawer first; second Back leaves the filtered page.

Forbidden: drawers backed by purely local component state (not deep-linkable, breaks back-button, defeats the bridge between J1 trade rows and J3 audit-trail / brief versions). Inspired by Linear / Notion / GitHub Issues. First consumer = J1 §3 trade detail (slice T4).

### 0.5 Iconography

Locked 2026-05-05 (Sally + Arturo, validated against [mock-c4-icons.html](variants/mock-c4-icons.html)).

- **Library**: [Lucide](https://lucide.dev/) — cherry-picked imports via `lucide-svelte` (ISC licence; tree-shakeable). Every icon ships as a Svelte component using `currentColor` for fill/stroke — colour is owned by the surrounding component (`color: var(--accent)` etc.), never hard-coded in the icon import.
- **Stroke**: `1.5px` for 24px icons, `1.25px` for ≤16px (auto via `stroke-width` prop). Avoid `2px` outside hover-pulse animations — clashes with the operational/Bloomberg lineage chosen for surface tokens.
- **Sizing**: `16px` inside Button slots, `18px` in Sidebar nav rows, `24px` standalone, `48px` in EmptyState. No other sizes.
- **Naming**: components reference Lucide names verbatim (e.g. `octagon-x` for KillSwitchButton, `gauge` for Risk Cockpit nav, `arrow-trending-up`/`-down` for P&L cells, `shield-check` for RBAC indicators, `briefcase` for Portfolio nav, `bell` for Approvals nav).
- **Forbidden**: emoji or unicode symbols as iconography (accessibility + cross-platform rendering risk). Inline SVG paths invented in component files (must come from Lucide).
- **Audit**: a slice that needs an icon Lucide does not ship MUST file an entry in §7 *Open questions* + propose either (a) a Lucide community icon by name OR (b) a one-off custom icon to vet with Sally before merge.

---

## 1. Primitives

### 1.1 `Button.svelte`

- **Purpose**: single canonical button primitive used by every CTA, form submit, and toolbar action.
- **Status**: canonical (MVP).
- **Used by**: every page; explicitly cited by ApprovalCard, OverrideForm, KillSwitchButton (specialised wrapper), Settings toggle row.
- **Capability**: foundation — all FRs that surface a user-triggered action.
- **Data shape**:
  ```ts
  interface ButtonProps {
    variant?: 'primary' | 'secondary' | 'ghost' | 'destructive' | 'success';
    size?: 'sm' | 'md' | 'lg';
    type?: 'button' | 'submit' | 'reset';
    disabled?: boolean;
    loading?: boolean;          // shows Spinner + sets aria-busy
    icon?: 'left' | 'right';    // slot position
    fullWidth?: boolean;
    href?: string;              // if set, renders <a> instead of <button>
    onclick?: (e: MouseEvent) => void;
    'aria-label'?: string;      // required when icon-only
  }
  ```
- **Component-specific states**: none beyond the universal 8.
- **Tokens used**: `--accent` / `--accent-fg` (primary); `--surface` / `--ink` (secondary); transparent / `--ink` (ghost); `--destructive` / `--destructive-fg` (destructive); `--success` / `--success-fg` (success).
- **Behaviour**:
  - Keyboard: `Tab` to focus, `Enter` or `Space` to activate.
  - Loading: `loading=true` swaps label for `Spinner` and sets `aria-busy="true"`; preserves width to avoid layout shift.
  - Disabled: blocks click + sets `aria-disabled="true"`.
  - Destructive variant pairs with mandatory confirm dialog at the call site (KillSwitchButton, force-exit) — never one-click.
- **Edge cases**: long labels truncate with `text-ellipsis` + tooltip via native `title`. Icon-only buttons require `aria-label` (lint rule enforced).
- **Storybook stories**: default (each variant × each size), loading, disabled, icon-left, icon-right, icon-only, full-width.

### 1.2 `Card.svelte`

- **Purpose**: surface container for grouped content (positions panel, brief section, approval card body, settings row group).
- **Status**: canonical (MVP).
- **Used by**: dashboard `/`, approvals, research, costs, risk, settings — every page.
- **Capability**: foundation.
- **Data shape**:
  ```ts
  interface CardProps {
    elevation?: 'flat' | 'raised';
    padding?: 'sm' | 'md' | 'lg' | 'none';
    interactive?: boolean;          // adds hover/focus affordance + role="button" when href/onclick set
    href?: string;
    onclick?: (e: MouseEvent) => void;
  }
  ```
- **Component-specific states**: `interactive=true` adds the universal hover/focus/active states.
- **Tokens used**: `--surface` background, `--surface-border` 1px border (flat) or `--shadow-sm` (raised).
- **Behaviour**: when `interactive`, renders as button-equivalent semantics; when not, renders as `<section>`.
- **Edge cases**: nested cards forbidden (per anti-patterns checklist). The catalogue review rejects any usage that would nest a Card inside a Card.
- **Storybook stories**: default, interactive (default / hover / focus / active), padding variants, with header slot, with footer slot.

### 1.3 `Badge.svelte`

- **Purpose**: status pill — strategy state, methodology label, tier indicator, severity tag.
- **Status**: canonical (MVP).
- **Used by**: PositionsTable, ApprovalCard (timeout indicator), MethodologyBadge (specialised wrapper), TradesTable (override marker), Settings (feature flag state).
- **Capability**: foundation; specialised consumers tie to FR58 (methodology), FR75 (tier), FR15 (order state), FR48 (override marker).
- **Data shape**:
  ```ts
  interface BadgeProps {
    variant?: 'neutral' | 'success' | 'warn' | 'destructive' | 'info';
    size?: 'sm' | 'md';
    icon?: boolean;       // reserve leading icon slot
  }
  ```
- **Component-specific states**: none.
- **Tokens used**: per-variant background + `*-fg` foreground; AA-verified pair recorded in `DESIGN.md` §15.
- **Behaviour**: text-only, non-interactive; if status is interactive (e.g. clickable to open the underlying entity), wrap in `Button variant="ghost"` instead.
- **Edge cases**: reserve `destructive` for actual blocked / failed / risk-rejected states — not for warnings.
- **Storybook stories**: each variant × each size; with-icon; long-label truncation.

### 1.4 `Input.svelte`

- **Purpose**: single canonical text input — login, override reason, settings text field, search.
- **Status**: canonical (MVP).
- **Used by**: login form (`/login`), OverrideForm, Settings, future search box.
- **Capability**: foundation; underpins FR31 (login), FR25 (override reason ≥20 chars).
- **Data shape**:
  ```ts
  interface InputProps {
    type?: 'text' | 'email' | 'password' | 'number' | 'search';
    label: string;                  // visible or sr-only
    labelVisible?: boolean;         // default true
    name: string;
    value?: string;
    placeholder?: string;
    required?: boolean;
    minLength?: number;
    maxLength?: number;
    pattern?: string;
    autocomplete?: string;
    error?: string;                 // shown inline below; sets aria-invalid
    helper?: string;                // shown below when no error
    disabled?: boolean;
    readonly?: boolean;
    oninput?: (e: InputEvent) => void;
  }
  ```
- **Component-specific states**: `error` (inline message + red border), `success` (green check after validation pass — used by OverrideForm at ≥20 chars).
- **Tokens used**: `--surface` background, `--ink` text, `--mute` placeholder, `--focus-ring` focus, `--destructive` error, `--success` success.
- **Behaviour**:
  - Label always exists in DOM (never placeholder-as-label).
  - `aria-describedby` wires to helper / error message when present.
  - Password type ships with show/hide toggle (icon button slot).
  - Number type uses `inputmode="numeric"` and a real `<input type="number">` to surface the OS keypad on mobile.
- **Edge cases**: autofill colour clash → reset via `:autofill` selector matched to `--surface`. Cannot rely on `pattern` alone for security — server-side validation also required.
- **Storybook stories**: default, focused, with helper, with error, disabled, readonly, password (toggle), email (with autocomplete), long-text overflow.

### 1.5 `Spinner.svelte`

- **Purpose**: indeterminate loading indicator inline or block-level.
- **Status**: canonical (MVP).
- **Used by**: Button (loading state), `+page.svelte` async load fallback, SSE reconnect indicator (composed inside ConnectionIndicator).
- **Capability**: foundation; satisfies the "loading" universal state.
- **Data shape**:
  ```ts
  interface SpinnerProps {
    size?: 'xs' | 'sm' | 'md' | 'lg';
    color?: 'inherit' | 'accent' | 'mute';
    label?: string;        // sr-only; defaults to "Loading"
  }
  ```
- **Component-specific states**: none.
- **Tokens used**: `currentColor` by default; `--accent` / `--mute` overrides.
- **Behaviour**:
  - Renders an SVG with `role="status"` + `aria-live="polite"` + sr-only label.
  - Respects `prefers-reduced-motion`: replaces rotating arc with a static three-dot pulse at 1.5s interval.
- **Edge cases**: must not be used as a primary loading affordance for >5s waits — pair with `SkeletonLoader` or `EmptyState` with helper copy.
- **Storybook stories**: each size, each colour, reduced-motion variant.

### 1.6 `EmptyState.svelte`

- **Purpose**: placeholder shown when a list / table / chart has zero rows or zero data points.
- **Status**: canonical (MVP).
- **Used by**: ApprovalList (no pending), TradesTable (no trades in range), PositionsTable (no open positions), FactTimeline (no facts ingested for symbol), AuditTrailViewer (no audit entry for version).
- **Capability**: foundation; the "empty" universal state.
- **Data shape**:
  ```ts
  interface EmptyStateProps {
    title: string;                       // short headline, e.g. "No pending approvals"
    description?: string;                // one sentence
    icon?: 'inbox' | 'chart' | 'document' | 'shield' | 'database' | null;
    cta?: { label: string; href?: string; onclick?: () => void };
  }
  ```
- **Component-specific states**: none.
- **Tokens used**: `--mute` text, `--surface` background card, `--accent` CTA button.
- **Behaviour**: centred within its container; `cta` renders a `Button variant="primary" size="sm"`.
- **Edge cases**: no emoji icons (per anti-pattern `emoji icons in critical paths`); use the curated icon set only.
- **Storybook stories**: minimal (title only), with-description, with-icon, with-cta, all-three.

### 1.7 `Switch.svelte`

- **Purpose**: binary on/off toggle primitive — the canonical control for boolean state. Replaces the temptation to use a Checkbox or paired buttons for "is it on?" UX.
- **Status**: canonical (MVP).
- **Used by**: `FeatureFlagToggle` (composes), `/strategies` per-symbol enable/disable rows, settings rows that don't need helper text or warnings.
- **Capability**: foundation — generic boolean affordance.
- **Data shape**:
  ```ts
  interface SwitchProps {
    checked: boolean;
    onchange: (next: boolean) => void;
    disabled?: boolean;
    size?: 'sm' | 'md';                    // default 'md'
    'aria-label'?: string;                 // required when no visible label sibling
    'aria-describedby'?: string;           // wires to helper / warning text
  }
  ```
- **Component-specific states**: `checked` / `unchecked`, plus universal `disabled` and `focus`.
- **Tokens used**: `--surface-2` track unchecked, `--accent` track checked, `--mute` thumb unchecked, `--accent-fg` thumb checked, `--focus-ring` outline.
- **Behaviour**: keyboard `Space` toggles; click target ≥48×48 CSS px (the visible track is smaller; padding extends the hitbox); transitions clamped to 0ms under `prefers-reduced-motion: reduce`.
- **Edge cases**: never use as the sole control of a destructive action (kill-switch is a Button, not a Switch — Switches imply a low-stakes binary).
- **Storybook stories**: unchecked, checked, disabled-unchecked, disabled-checked, sm, md, with-aria-describedby.

### 1.8 `FeatureFlagToggle.svelte`

- **Purpose**: canonical surface for a tenant-scoped feature flag — composes `Switch` with a label, helper paragraph, optional "Experimental" Badge, and optional destructive warning row.
- **Status**: canonical (MVP).
- **Used by**: `/settings` Feature flags section. First consumer = slice R6 (`hindsight-integration`) for FR81 Hindsight bias guard; future flags (e.g. paper-trading-only, verbose-audit-mode) reuse the same shape.
- **Capability**: FR81 (Hindsight toggle) + any future tenant-scoped boolean flag.
- **Data shape**:
  ```ts
  interface FeatureFlagToggleProps {
    flagKey: string;                       // server identifier, e.g. 'hindsight_bias_guard'
    label: string;                         // visible label, e.g. 'Hindsight bias guard'
    helper: string;                        // one-paragraph description; may include inline <code>
    checked: boolean;
    onchange: (next: boolean) => Promise<void>;   // server-bound; component shows loading state
    experimental?: boolean;                // renders the warn-bg "Experimental" Badge
    sideEffectWarning?: string;            // renders a destructive-tinted row with alert-triangle icon
    disabled?: boolean;                    // e.g. while RBAC is loading
  }
  ```
- **Component-specific states**:
  - `default` (resting at current value).
  - `loading` (during `onchange` promise — Switch shows inline Spinner; full card non-interactive).
  - `error` (onchange rejected — Toast emits + Switch reverts; the card itself returns to `default`).
  - `disabled` (RBAC mismatch or feature-locked).
- **Tokens used**: `--surface` card background, `--border`, `--ink` label, `--mute` helper, `--warn-bg` Experimental Badge, `--destructive` side-effect warning row, plus all Switch tokens.
- **Behaviour**:
  - The card is NOT a `<button>`; the Switch is the only interactive control. Click on label / helper does NOT toggle (avoids accidental flips on read).
  - Helper paragraph supports inline `<code>` for technical terms; no other inline markup (no links — would compete with the Switch as the primary action).
  - `experimental` Badge uses the warn-bg accent (Lucide icon optional; prefer label-only).
  - `sideEffectWarning` row uses `alert-triangle` Lucide icon + destructive-tinted background; surfaces below the Switch row, not inline with helper.
  - `aria-describedby` on the inner Switch references both helper text id and (if present) warning row id.
- **Edge cases**:
  - Optimistic toggle is forbidden — the Switch waits on the server promise; rejection reverts atomically. Reason: feature flags affect tenant-wide behaviour; lying about state is dangerous.
  - If `onchange` rejects, emit a Toast with the correlation ID; do NOT add error copy inside the card (avoids permanent error surface for transient failures).
  - The card NEVER mutates its own helper / warning copy at runtime — those are static per flag definition. Dynamic per-state messaging belongs in a Toast.
- **Storybook stories**: default-off, default-on, experimental-off, experimental-on, with-side-effect-warning, with-side-effect-warning-on, loading, disabled-rbac.

### 1.9 `Alert.svelte`

- **Purpose**: canonical inline alert surface — title + body + optional dismiss action, with semantic variant. Replaces the temptation for each slice to invent its own banner HTML (per §6 stewardship clause).
- **Status**: canonical (MVP).
- **Used by**: at least 4 sites identified at lock time (2026-05-05) — `/risk` Tier-2 cap warning ([j2.md](j2.md) §7), `/risk` Tier-1 cap exhaustion ([j2.md](j2.md) §7), J1 §3 SSE stale-data alert ([j1.md](j1.md) §3 Step 1), J0 Step 1 rate-limit banner ([j0.md](j0.md)).
- **Capability**: foundation — any non-Toast, non-error-boundary inline alert surface.
- **Data shape**:
  ```ts
  interface AlertProps {
    variant: 'warn' | 'destructive' | 'info';
    title: string;                         // short, sentence case
    body?: string;                         // one paragraph; may include inline <code>
    dismissible?: boolean;                 // shows the dismiss Button
    onDismiss?: () => void;                // called when dismiss is clicked
    icon?: string;                         // Lucide icon name; defaults per variant (see Behaviour)
    role?: 'alert' | 'status';             // aria role; defaults per variant (see Behaviour)
  }
  ```
- **Component-specific states**:
  - `default` (visible, resting).
  - `dismissed` (component is unmounted by the parent — Alert itself does NOT manage the dismissed state, only emits `onDismiss`).
- **Tokens used per variant**:
  - `warn`: `oklch(78% 0.14 80 / 0.14)` background tint, `--warn-bg` border + icon, `--ink` title, `--mute` body.
  - `destructive`: `oklch(64% 0.20 25 / 0.14)` background tint, `--destructive` border + icon, `--ink` title, `--destructive` body (when copy IS the alert), else `--mute`.
  - `info`: `oklch(72% 0.14 195 / 0.14)` background tint, `--accent` border + icon, `--ink` title, `--mute` body.
- **Behaviour**:
  - Default Lucide icons per variant: `warn` → `alert-triangle`, `destructive` → `octagon-alert`, `info` → `info`. Override via `icon` prop only when justified (e.g. J0 rate-limit uses `alert-triangle` even though variant is destructive — context-specific).
  - Default `role`: `warn` and `destructive` → `role="alert"` (assertive announcement); `info` → `role="status"` (polite). Override only with explicit a11y reason.
  - **Alert is presentational only**. Auto-clear semantics, dismiss persistence, session memory — all owned by the parent (e.g. /risk page logic clears the Tier-2 banner when `daily_pct < 0.80`; Alert itself is unmounted, never self-times-out).
  - Dismissible variant has a `Button variant="ghost" size="sm"` labelled "dismiss" or an X icon-only Button with `aria-label="Dismiss"`.
- **Edge cases**:
  - Multiple Alerts stacked: parent wraps in a flex column with `gap: 8px`; Alert itself does NOT manage stacking.
  - Body with very long copy: NO truncation in the primitive — alert messages should be short by contract; if a slice needs collapsible alert bodies, it's a different component.
  - Inline links inside body: forbidden in MVP. If a slice needs a CTA, use a separate `Button` outside Alert (or compose into a `Card`-shaped surface, not Alert).
- **Storybook stories**: warn-default, warn-with-body, warn-dismissible, destructive-default, destructive-with-body, destructive-dismissible, info-default, info-dismissible, custom-icon.

### 1.10 `YAMLEditor.svelte`

- **Purpose**: lazy-loaded CodeMirror 6 wrapper for editing structured YAML config (strategy params, risk policy, methodology profile). Replaces the temptation to either ship Monaco (~600 KB) or fall back to a plain textarea (YAML indentation breaks too easily).
- **Status**: canonical (MVP).
- **Used by**: J1 §3 Step 4 strategy edit modal (first consumer, slice T4); future surfaces — risk policy editor (slice K1), methodology config editor (slice R5), feature-flag config editor (slice R6 if structured).
- **Capability**: FR3 (per-symbol YAML params) + any future YAML editing surface.
- **Data shape**:
  ```ts
  interface YAMLEditorProps {
    value: string;                                // YAML source text
    onChange: (next: string) => void;
    readonly?: boolean;
    schema?: object;                              // optional JSON Schema for client-side lint
    height?: string;                              // CSS height; default '320px'
    'aria-label'?: string;                        // required when no visible label
  }
  ```
- **Component-specific states**:
  - `default` (editing).
  - `readonly` (display-only; no caret; gutter still visible).
  - `lint-error` (inline squiggle on offending line; `Toast` is NOT raised — server-side validation is the canonical authority and shows on submit).
- **Tokens used**: gutter background `--surface`, content background `--bg`, line-numbers `--mute`, indent guides `--border`. Syntax mapping: `--accent` for keys, `--success` for strings, `--warn-bg` for numbers, `--destructive` for booleans, `--mute` for comments, `--ink` for raw values. Custom theme exported as `iguanaDarkTheme`.
- **Behaviour**:
  - **Lazy-loaded**: the CodeMirror bundle (`codemirror` + `@codemirror/lang-yaml` + theme) is dynamically imported when the component first mounts. Parent renders a `Spinner` for ≤300ms before swapping in.
  - **Client-side lint is convenience only**: server-side schema validation is canonical. Inline squiggles flag obvious issues (unquoted strings starting with `*`, mixed tabs/spaces); the server is the source of truth on save.
  - **Theme is dark-only at MVP**: light derivation lands alongside the slice W1 theme toggle (deferred non-blocker).
  - **No autosave**. Parent owns the dirty state and the save action; `YAMLEditor` is a controlled component.
- **Edge cases**:
  - Very large YAML (>500 lines): not supported. Throw a friendly error from the parent if the source exceeds 500 lines (config files for iguanatrader strategies / risk / methodology are bounded; if a slice needs more, the surface is wrong).
  - Mobile: editing on touch devices is acceptable but not promoted; the strategy modal closes back to a read-only view on `pointer:coarse` with "Edit YAML on desktop" copy if width <600px.
  - Bundle never available offline (localhost dev only): CodeMirror is bundled by Vite into the app, not loaded from a CDN.
- **Storybook stories**: default, readonly, with-schema, lint-error, dirty-state, lazy-loading.

---

## 2. Layout & navigation

### 2.1 `+layout.svelte` (root) and `(app)/+layout.svelte` (authenticated)

- **Purpose**: SvelteKit root + authenticated-group layouts. Root layout renders `<svelte:head>` defaults, theme attribute, global toast outlet. Authenticated layout adds the `Sidebar` + main content region + ConnectionIndicator strip.
- **Status**: canonical (MVP).
- **Used by**: every route.
- **Capability**: FR54 (dashboard surface), FR55 (kill-switch button accessible from any page).
- **Data shape**:
  - Root: no props; reads `themeStore` to set `data-theme` attribute on `<html>`.
  - Authenticated: receives `tenant` + `user` from `+layout.server.ts` load function; passes `user.role` to children via context.
- **Component-specific states**:
  - Root: `theme=light | dark | system` (controlled by `themeStore`).
  - Authenticated: `sidebar=collapsed | expanded` (mobile drawer; persisted to `localStorage`).
- **Tokens used**: `--bg` page background, `--surface` sidebar.
- **Behaviour**:
  - Root layout reads JWT cookie via `hooks.server.ts`; redirects to `/login` if absent on any `(app)/*` route.
  - Authenticated layout shows `KillSwitchButton` (compact form) in the top-right region of every page — wired to global `riskStore` so the button reflects current state without per-page wiring.
  - `prefers-reduced-motion` respected for sidebar drawer transition.
- **Edge cases**:
  - Tenant context **must** be set before any child renders — guarded via `+layout.server.ts` redirect to `/login` if `tenant_id` claim missing.
  - SSE connection failure surfaces as a banner at top of main region (composed from `ConnectionIndicator`) — never as a toast (toasts are per-action, banners are persistent).
- **Storybook stories**: not applicable (route layouts); covered by Playwright E2E.

### 2.2 `Sidebar.svelte`

- **Purpose**: primary navigation. Uses **dynamic enumeration** via `import.meta.glob('/src/routes/(app)/*/+page.svelte')` so each new slice that adds a route is picked up automatically without editing `Sidebar.svelte` (anti-collision pattern, per [openspec-slice.md](../openspec-slice.md) §Anti-collision patterns).
- **Status**: canonical (MVP).
- **Used by**: `(app)/+layout.svelte`.
- **Capability**: FR54 (dashboard navigation surface).
- **Data shape**:
  ```ts
  interface SidebarItem {
    href: string;                  // /portfolio, /trades, /research, ...
    label: string;                 // human title pulled from a per-route metadata export
    icon: keyof IconRegistry;      // from a curated icon set (see §0.4)
    badge?: { count: number; variant: 'neutral' | 'warn' | 'destructive' };
    requiresRole?: 'admin' | 'user';
  }

  interface SidebarProps {
    collapsed?: boolean;
    onToggle?: () => void;
    activeHref: string;            // SvelteKit's $page.url.pathname
    user: { role: 'admin' | 'user'; email: string };
  }
  ```
- **Component-specific states**:
  - `collapsed` (icon-only, ≥1024 px) vs `expanded` (icon + label).
  - `mobile-drawer` (<1024 px): hidden by default, opened by hamburger button in top bar.
- **Tokens used**: `--surface` background, `--surface-border` divider, `--accent` active state, `--ink` / `--mute` text.
- **Behaviour**:
  - Each item resolves the active state via prefix-match against `$page.url.pathname` so deep routes (e.g. `/research/AAPL/audit-trail/3`) keep "Research" highlighted.
  - Items with `requiresRole='admin'` are hidden when `user.role !== 'admin'`.
  - Badge slot (e.g. pending approval count) reads from `approvalsStore` / `alertsStore` — wired in the parent layout, not inside Sidebar (separation of concerns).
  - Keyboard: `Tab` cycles items; `Enter` navigates; `Esc` closes mobile drawer.
- **Edge cases**:
  - Mobile drawer must trap focus while open + close on outside click + close on route change.
  - Glob enumeration order is alphabetical by route path; per-route metadata exports an `order: number` to override (default 100). New routes from later slices declare their own order to land in the right slot.
- **Storybook stories**: expanded, collapsed, mobile-drawer-open, with-badges (each variant), with-impersonation-banner (god-admin context — see [personas-jtbd.md](../personas-jtbd.md) §RBAC Matrix).

### 2.3 `+error.svelte`

- **Purpose**: global error boundary at every route level + root. Renders RFC 7807 problem body (per Architecture Decisions §API & Communication Patterns) when an `error()` is thrown server-side or load function rejects.
- **Status**: canonical (MVP).
- **Used by**: SvelteKit framework picks it up at every route directory; root `+error.svelte` is the catch-all.
- **Capability**: FR54 (graceful degradation), NFR-O8 (audit trail must include error context).
- **Data shape**: Reads `$page.error` (SvelteKit-provided). Expected shape extends RFC 7807:
  ```ts
  interface AppError {
    type: string;                  // RFC 7807 type URI
    title: string;
    status: number;
    detail?: string;
    instance?: string;
    correlation_id?: string;       // ai-playbook structlog correlation ID; surfaced for support
  }
  ```
- **Component-specific states**:
  - `recoverable` (status < 500 and the route can retry, e.g. 401 → login link, 403 → "switch tenant" hint, 404 → "go home" link).
  - `unrecoverable` (status ≥ 500 — copy + correlation ID + "report" button).
- **Tokens used**: `--bg`, `--surface`, `--ink`, `--mute`, `--destructive`.
- **Behaviour**:
  - Reports to `hooks.client.ts` global error handler → OTel collector (per Architecture Decisions §Infrastructure).
  - Always shows the correlation ID with a copy-to-clipboard button so Arturo can grep structlog.
  - Never echoes raw stack traces to the user — server logs only.
- **Edge cases**:
  - 401 from `(app)/*` → redirect to `/login?redirect_to=<current>` instead of rendering error.
  - SSE disconnects DO NOT trigger `+error.svelte` (those are surfaced via `ConnectionIndicator` banner).
- **Storybook stories**: 401 (login redirect — story shows pre-redirect state), 403, 404, 500, 503 maintenance.

---

## 3. Approval-flow components (Journey 2)

### 3.1 `ApprovalCard.svelte`

- **Purpose**: single proposal as a Card with reasoning, sizing, risk impact, countdown, and approve/reject/modify actions. The web equivalent of the Telegram/WhatsApp message in Journey 1 / Journey 2.
- **Status**: canonical (MVP).
- **Used by**: `/approvals` page, dashboard `/` (top-3 pending preview).
- **Capability**: FR12, FR13, FR14, FR17, FR18, FR25 (override surface composes ApprovalCard + OverrideForm), FR48 (decision logged), FR74 (`research_brief_id` link surfaced inline).
- **Data shape**:
  ```ts
  interface Proposal {
    id: string;
    symbol: string;
    side: 'BUY' | 'SELL';
    strategy: string;                // 'DonchianATR'
    quantity: number;
    estimatedPrice: number;          // Decimal as string, formatted via decimal.js
    notional: number;
    pctOfCapital: number;
    stopPrice: number;
    riskAtStopPct: number;
    confidenceScore?: number;        // 0..1
    estimatedLLMCostUSD: number;
    timeoutAt: string;               // ISO 8601 UTC
    state: 'pending' | 'approving' | 'approved' | 'rejected' | 'timed-out' | 'risk-rejected';
    riskRejectionReason?: string;    // populated when state = 'risk-rejected'
    researchBriefId?: string;        // FR74; click to open /research/[symbol]
    reasoningSummary: string;        // ≤2 sentences; full reasoning JSON behind details/summary
  }

  interface ApprovalCardProps {
    proposal: Proposal;
    onApprove: (id: string) => Promise<void>;
    onReject: (id: string, reason?: string) => Promise<void>;
    onOverrideRequest: (id: string) => void;   // opens OverrideForm flow
    compact?: boolean;                         // compact mode for dashboard preview
  }
  ```
- **Component-specific states**:
  - `pending` (default): countdown + 3 buttons.
  - `approving` / `rejecting` (optimistic): button shows Spinner; card border pulses with `--accent`.
  - `approved` / `rejected` / `timed-out`: card collapses to a one-line summary with a chevron to expand.
  - `risk-rejected` (FR24): red border, rejection reason in `Badge variant="destructive"`, "Override" button replaces "Approve".
- **Tokens used**: `--surface`, `--ink`, `--accent` for primary CTA, `--destructive` for reject, `--success` for approve, `--warn-bg` for countdown <10s, `--mute` for secondary metadata.
- **Behaviour**:
  - Countdown driven by `useCountdown` composable; updates every 250 ms; turns to `--warn-bg` when ≤10 s remaining; auto-fires `onTimeout` callback (which transitions card to `timed-out` state — server is canonical via SSE).
  - Approve / Reject buttons are `Button variant="success" / variant="destructive"` and confirmation pattern depends on size (compact: single click; full: confirmation popover).
  - Reasoning details hidden by default behind `<details>` with `summary` "Full reasoning" — keyboard accessible.
  - Click on `researchBriefId` chip opens `/research/[symbol]` in a new tab (preserves the approval context).
  - Keyboard: `A` approves focused card, `R` rejects focused card, `O` opens override flow (hint surfaced in tooltip; no global hijack — only when card has focus).
- **Edge cases**:
  - Network failure on approve/reject: surfaces inline error and reverts optimistic state. Card is not removed until SSE confirms terminal state.
  - SSE-driven update arrives mid-action: server state wins; user sees a brief toast "Decision already recorded by another channel" if user beat themselves to it via Telegram.
  - Long symbols / long reasoning: card height grows; never horizontal scroll.
- **Storybook stories**: pending (full + compact), approving, approved, rejected, timed-out, risk-rejected (with override CTA), countdown <10s, long-symbol, long-reasoning, no-research-brief.

### 3.2 `ApprovalList.svelte`

- **Purpose**: virtualised list of `ApprovalCard` instances for the `/approvals` page.
- **Status**: canonical (MVP).
- **Used by**: `/approvals/+page.svelte`.
- **Capability**: FR12, FR13, FR48.
- **Data shape**:
  ```ts
  interface ApprovalListProps {
    pending: Proposal[];
    history: Proposal[];                       // last N decided
    historyLimit?: number;                     // default 50
    filter?: { symbol?: string; state?: Proposal['state'][] };
    onApprove: ApprovalCardProps['onApprove'];
    onReject: ApprovalCardProps['onReject'];
    onOverrideRequest: ApprovalCardProps['onOverrideRequest'];
  }
  ```
- **Component-specific states**: `empty` (uses `EmptyState` with copy "No pending approvals — system is watching").
- **Tokens used**: inherited from `Card` + `Badge`.
- **Behaviour**:
  - Two sections: "Pending" (live, SSE-fed via `approvalsStore`) and "History" (paginated, lazy-loaded on scroll).
  - Filter bar at top (symbol search + state multi-select via `Badge`-as-checkbox pattern).
  - Pending section auto-sorts: shortest countdown first.
- **Edge cases**: when pending count > 20 (unlikely MVP — rate is 5-20 trades/week per persona JTBD-1) the list virtualises via `<svelte:component>` only-rendering above-fold.
- **Storybook stories**: empty, 1-pending, 5-pending mixed states, with-history, with-filter applied, very-long-history.

### 3.3 `OverrideForm.svelte`

- **Purpose**: form to override a `risk-rejected` proposal — written reason ≥20 chars + double confirmation, per FR25.
- **Status**: canonical (MVP).
- **Used by**: `/approvals` page (modal triggered from ApprovalCard), `/risk` page (override risk-rejected entry).
- **Capability**: FR25, FR26, FR48.
- **Data shape**:
  ```ts
  interface OverrideFormProps {
    proposal: Proposal;
    onConfirm: (input: { proposalId: string; reason: string; modifiedStop?: number }) => Promise<void>;
    onCancel: () => void;
  }
  ```
- **Component-specific states**:
  - `step-1-reason` (Input + character counter + helper "min 20 chars"; submit disabled until ≥20).
  - `step-2-preview` (read-only summary of modified trade + projected risk impact — Journey 2 climax; "Confirm override" button).
  - `submitting` (Spinner inline; both step buttons disabled).
  - `error` (inline RFC 7807 detail).
- **Tokens used**: `--surface` modal, `--destructive` warning band, `--accent` confirm button, `--mute` reason helper.
- **Behaviour**:
  - Step 2 explicitly displays "Daily projected: X% (cap: Y%)" — copies the Telegram/WhatsApp Journey 2 framing.
  - Confirm button intentionally placed AFTER the destructive context, with a 1s minimum visibility before becoming clickable (anti-mis-click).
  - Reason text is committed to `risk_overrides` table (FR26) with `recorded_by`, `reason`, `risk_state_snapshot`.
  - Keyboard: `Esc` cancels; `Cmd/Ctrl+Enter` submits step.
- **Edge cases**:
  - User edits the stop in step 2 → recompute risk impact client-side via shared decimal helper; final authoritative value comes from server response.
  - Network timeout: form stays open, error inline, retry button.
- **Storybook stories**: step-1-empty, step-1-typing-15-chars (counter warning), step-1-valid, step-2-preview, step-2-with-modified-stop, submitting, error.

### 3.4 `KillSwitchButton.svelte`

- **Purpose**: single button to activate the kill-switch from anywhere in the dashboard — global affordance present in every page header (per FR55).
- **Status**: canonical (MVP).
- **Used by**: `(app)/+layout.svelte` top bar, `/risk/+page.svelte` (large variant), `/portfolio/+page.svelte` (large variant on alert).
- **Capability**: FR29 (activation channel: dashboard button), FR55, FR30 (post-activation refuses execution).
- **Data shape**:
  ```ts
  interface KillSwitchButtonProps {
    state: 'armed' | 'active';            // armed = ready to activate, active = already triggered
    size?: 'compact' | 'large';
    onActivate: () => Promise<void>;
    onResume: () => Promise<void>;        // only when state='active' and user is admin
    user: { role: 'admin' | 'user' };
  }
  ```
- **Component-specific states**:
  - `armed-default` (red Button, copy "Halt trading").
  - `armed-confirm` (after first click, replaces with confirmation dialog "Type HALT to confirm" — anti-mis-click).
  - `activating` (Spinner; button disabled).
  - `active` (button replaced by amber "Trading halted — Resume" — Resume gated by admin role + reverse confirmation).
- **Tokens used**: `--destructive` (armed), `--warn-bg` (active state strip), `--success` (Resume action).
- **Behaviour**:
  - Compact variant in the top bar shows only the icon + tooltip; large variant on `/risk` shows full label + state copy.
  - Activation is optimistic — UI flips to `active` immediately; server SSE confirms. If server rejects, revert + toast.
  - Resume requires typing "RESUME" (mirrors HALT).
- **Edge cases**:
  - State arrives via `riskStore` SSE — kill-switch fired from CLI / Telegram propagates to UI within the SSE round-trip.
  - Network failure during activation: state stays `armed-confirm` with inline error and a retry CTA.
- **Storybook stories**: armed (compact, large), armed-confirm (typing HALT), activating, active, error.

---

## 4. Research-domain components (Journey 3)

### 4.1 `BriefHeader.svelte`

- **Purpose**: header band of a `research_brief` page — symbol, methodology, version, freshness, refresh CTA.
- **Status**: canonical (MVP).
- **Used by**: `/research/[symbol]/+page.svelte`, top of `/research/[symbol]/audit-trail/[brief_version]/+page.svelte`.
- **Capability**: FR58 (methodology profile selection), FR71 (synthesised brief), FR72 (refresh on schedule + on-trigger), FR73 (immutable per version).
- **Data shape**:
  ```ts
  interface BriefHeaderProps {
    symbol: string;
    methodology: '3-pillar' | 'CANSLIM' | 'Magic Formula' | 'QARP' | 'Multi-factor';
    version: number;                       // monotonic FR73
    synthesizedAt: string;                 // ISO 8601 UTC
    lastFactRecordedAt: string;            // ISO 8601 UTC; freshness signal
    nextScheduledRefreshAt?: string;       // ISO 8601 UTC; null if manual-only
    refreshing: boolean;
    onRefresh: () => Promise<void>;
    onMethodologyChange?: (m: BriefHeaderProps['methodology']) => void;   // tenant_user; v3 multi-seat may gate
    onOpenAuditTrail: () => void;          // navigates to /audit-trail/[version]
  }
  ```
- **Component-specific states**:
  - `default` (info display + actions).
  - `refreshing` (Refresh button shows Spinner + "Synthesising…" copy; the rest of the header is non-interactive but visible).
  - `stale` (when `synthesizedAt` is older than methodology's threshold — surface a `Badge variant="warn"` "Brief stale, refresh recommended").
- **Tokens used**: `--surface` band, `--ink`, `--mute` for timestamps, `--accent` for refresh CTA, `--warn-bg` for stale badge.
- **Behaviour**:
  - Version badge composed from `Badge variant="info"` + `MethodologyBadge`.
  - Methodology change is exposed to the tenant user (single-seat MVP/v2 model — see [personas-jtbd.md](../personas-jtbd.md) §RBAC Matrix). The read-only `Badge` fallback is preserved as a v3 multi-seat hook (when `tenant_member` role lands, the dropdown becomes a Badge).
  - Refresh CTA disabled while refreshing; cancel option after 30s (per Architecture Decisions §Frontend Architecture loading-states rule).
  - Timestamps formatted via `useFormatPrice`-equivalent date helper — display always pairs absolute ISO 8601 with relative ("3h ago"), never relative-only.
- **Edge cases**:
  - Refresh fails mid-flight: header reverts to previous version's header (the brief is immutable) + toast with the correlation ID.
  - Methodology change creates a new brief version (FR73) — header transitions from version N to version N+1 only after the new brief synthesises.
- **Storybook stories**: default, fresh-brief, stale-brief, refreshing, admin-with-methodology-edit, user-readonly-methodology, no-scheduled-refresh.

### 4.2 `FactTimeline.svelte`

- **Purpose**: bitemporal timeline of `research_facts` for a symbol — the visual surface for FR68's `effective_from/to × recorded_from/to`.
- **Status**: canonical (MVP).
- **Used by**: `/research/[symbol]/+page.svelte` (compact mode below the brief), `/research/[symbol]/audit-trail/[brief_version]/+page.svelte` (full mode anchored to a calculation's input).
- **Capability**: FR68 (bitemporal storage), FR69 (provenance), FR75 (tier-based availability surfaced visually).
- **Data shape**:
  ```ts
  interface ResearchFact {
    id: string;
    sourceId: string;
    sourceUrl: string;                   // FR69
    retrievalMethod: 'api' | 'scrape' | 'manual' | 'llm';
    retrievedAt: string;                 // ISO 8601 UTC
    effectiveFrom: string;
    effectiveTo: string | null;
    recordedFrom: string;
    recordedTo: string | null;
    factType: string;                    // 'earnings_per_share' | 'analyst_rating' | 'insider_buy' | …
    rawValue: string;                    // canonical string form
    tier: 'A' | 'B' | 'C';               // FR75
  }

  interface FactTimelineProps {
    symbol: string;
    facts: ResearchFact[];
    mode?: 'compact' | 'full';
    asOf?: string;                       // ISO 8601 UTC; if set, shows what was known at that knowledge-time
    onFactClick?: (fact: ResearchFact) => void;
    filter?: { factType?: string[]; tier?: ('A' | 'B' | 'C')[]; sourceId?: string[] };
  }
  ```
- **Component-specific states**:
  - `compact` (vertical list, latest 10 facts, collapse older).
  - `full` (horizontal axis = effective time; vertical lanes = fact type; bitemporal indicator dots show recorded vs effective offset).
  - `as-of-mode` (when `asOf` is set, dims facts not yet known at that time + adds an "as of YYYY-MM-DD HH:mm UTC" header).
  - `empty` (uses `EmptyState` "No facts recorded for this symbol").
- **Tokens used**: `--surface`, `--ink`, `--mute`, `--accent` for currently-effective, `--mute` (50% alpha) for superseded, tier colour map per `DESIGN.md` §Iconography (TBD).
- **Behaviour**:
  - Each fact row shows: factType, value, source (`Badge` with `sourceId`), tier badge (composes to `MethodologyBadge`-style atom), recorded-vs-effective offset, and a `CitationLink`.
  - Click fact → `onFactClick` (used by AuditTrailViewer to highlight which fact a calculation cited).
  - Reduced-motion: removes the timeline-axis-pan animation; static layout still legible.
- **Edge cases**:
  - When two facts have overlapping `effective_from/to`, render both with offset indicator + tooltip explaining bitemporal semantics ("Fact recorded after the period it describes").
  - When `tier='C'`, show a tooltip explaining the bootstrap-only constraint (FR75).
- **Storybook stories**: empty, compact-10-facts, full-mode-mixed-types, as-of-mode, with-tier-filter, with-superseded-facts, narrow-viewport.

### 4.3 `CitationLink.svelte`

- **Purpose**: inline citation chip linking a brief assertion or audit input back to its `research_fact` (or original source URL).
- **Status**: canonical (MVP).
- **Used by**: BriefHeader (sources used count), brief body prose (every numeric assertion), AuditTrailViewer (input rows).
- **Capability**: FR69 (provenance), FR70 (audit trail input citation), FR74 (proposal reasoning preserves citations).
- **Data shape**:
  ```ts
  interface CitationLinkProps {
    factId?: string;                  // optional; clicks scroll to FactTimeline + highlight
    sourceUrl: string;                // FR69
    sourceLabel: string;              // 'SEC EDGAR · 10-K 2026-01-12' or 'Finnhub'
    retrievedAt: string;              // ISO 8601 UTC
    method: ResearchFact['retrievalMethod'];
    inline?: boolean;                 // default true; renders as superscript chip
    onClickFact?: (factId: string) => void;
  }
  ```
- **Component-specific states**: `default`, `hover` (tooltip with full retrievedAt + method), `visited` (subtle de-emphasis after first click).
- **Tokens used**: `--accent` chip background, `--accent-fg` text, `--mute` for visited.
- **Behaviour**:
  - When `factId` set, primary click invokes `onClickFact` (scrolls FactTimeline and highlights the fact).
  - Secondary action: opens `sourceUrl` in new tab (`target="_blank" rel="noopener noreferrer"`).
  - `aria-label` always describes "Citation: <sourceLabel> retrieved <retrievedAt>".
- **Edge cases**:
  - Broken link (404 at fetch time): surfaced as `Badge variant="warn"` instead — does not silently degrade. Per FR75 + audit-trail principle.
  - Per FR78, the link goes to the public source URL, not to a local cached copy.
- **Storybook stories**: default-inline, with-fact-link, with-broken-link-warning, very-long-source-label, visited, dark-mode.

### 4.4 `AuditTrailViewer.svelte`

- **Purpose**: show-your-work view per calculation in a `research_brief` — formula + inputs (each cited) + intermediate steps + final output (FR70).
- **Status**: canonical (MVP).
- **Used by**: `/research/[symbol]/audit-trail/[brief_version]/+page.svelte`.
- **Capability**: FR70, FR71 (audit_trail accompanies any computed metric), JTBD-4 (anti-hallucination guarantee).
- **Data shape**:
  ```ts
  interface AuditEntry {
    metric: string;                            // 'forward_pe', 'eps_growth_yoy', …
    formula: string;                           // 'price / forward_eps'
    inputs: {
      name: string;
      value: string;                           // canonical decimal string
      factCitation: CitationLinkProps;
    }[];
    steps: { description: string; intermediate: string }[];
    finalOutput: string;
    methodology: BriefHeaderProps['methodology'];
  }

  interface AuditTrailViewerProps {
    briefVersion: number;
    entries: AuditEntry[];
    activeMetric?: string;                     // deep-link via #metric=forward_pe
  }
  ```
- **Component-specific states**: `default` (collapsed entries), `expanded` (one entry open at a time; like an accordion — keyboard-friendly), `empty` (uses `EmptyState`).
- **Tokens used**: `--surface` entry card, `--mute` for formula text, `--accent` for cited inputs, `--ink` for output.
- **Behaviour**:
  - Each entry is a `Card` with header (metric + final output + `MethodologyBadge`) and an expandable body (formula + input list with `CitationLink` per input + step list).
  - Deep-linkable via URL hash; on mount, scrolls to + opens the active entry.
  - "Copy as markdown" button per entry — exports the audit content for retro / journal use.
  - Keyboard: `↑/↓` to navigate entries; `Enter` to expand; `Esc` to collapse.
- **Edge cases**:
  - Entry with zero `steps` (one-shot lookup, e.g. `analyst_consensus`) renders without the steps section — formula collapses to "lookup".
  - Broken citation (per CitationLink edge case) surfaces inline; CI integration test (FR75 spirit) blocks rendering of an audit entry where `inputs[].factCitation` does not resolve.
- **Storybook stories**: empty, single-entry-collapsed, single-entry-expanded, multi-entry, broken-citation-entry, deep-linked, very-long-formula.

### 4.5 `MethodologyBadge.svelte`

- **Purpose**: specialised `Badge` for the 5 research methodologies (FR58) — fixed icon + colour per methodology so the same methodology is recognisable across BriefHeader, FactTimeline filter, AuditTrailViewer entry header, and `/research` overview list.
- **Status**: canonical (MVP).
- **Used by**: BriefHeader, AuditTrailViewer, `/research/+page.svelte` watchlist row.
- **Capability**: FR58.
- **Data shape**:
  ```ts
  interface MethodologyBadgeProps {
    methodology: BriefHeaderProps['methodology'];
    size?: 'sm' | 'md';
    showLabel?: boolean;                       // false = icon-only with aria-label
  }
  ```
- **Component-specific states**: none.
- **Tokens used**: per-methodology colour map (TBD in `DESIGN.md`):
  - 3-pillar — `--methodology-three-pillar`
  - CANSLIM — `--methodology-canslim`
  - Magic Formula — `--methodology-magic`
  - QARP — `--methodology-qarp`
  - Multi-factor — `--methodology-multi`
- **Behaviour**: pure visual; non-interactive by default. When wrapped in a Button by parent (e.g. AuditTrailViewer entry click target) inherits the Button's interaction model.
- **Edge cases**:
  - Unknown methodology string → falls back to `Badge variant="neutral"` with the raw string (fail-safe; lint rule warns on unmapped methodology).
- **Storybook stories**: each of 5 methodologies × each size × showLabel true/false.

---

## 5. Already-defined dashboard atoms (referenced for completeness)

The following components are inventoried in [architecture-decisions.md](../architecture-decisions.md) §Project Structure under `apps/web/src/lib/components/` and are **not redefined here** — they will get full entries in this catalogue when their consuming slices (T4 mostly) bring them online. Listed here so OpenSpec proposals can reference them by stable name.

| Component | Slice | Notes |
|---|---|---|
| `EquityCurve.svelte` | T4 | TradingView Lightweight Charts wrapper — equity curve + drawdown overlay. |
| `DrawdownGauge.svelte` | T4 | Gauge for max drawdown. |
| `PositionsTable.svelte` | T4 | Live table with `animate:flip` for stock reordering. |
| `TradesTable.svelte` | T4 | Filterable history table; columns include override marker (FR48). |
| `CostBreakdownChart.svelte` | O1 / O2 | ApexCharts USD/day per provider/node. |
| `RiskCapsBar.svelte` | K1 / W1 | Cap consumption visual (per-trade / daily / weekly / drawdown). |
| `StockRow.svelte` | T4 | Streaming row with `animate:flip`. |
| `ConnectionIndicator.svelte` | W1 | SSE connection state strip (green/red); composes `Spinner`. |
| `SkeletonLoader.svelte` | W1 | Skeleton placeholder for async load. |
| `Toast.svelte` | W1 | Per-action notification outlet. |

---

## 6. Stewardship clause

The components catalogue is the contract between design and engineering. If a Svelte story does not match the doc here, the doc is wrong — fix it.

For tokens (`--bg`, `--accent`, etc.), the canonical source is [`docs/ux/DESIGN.md`](DESIGN.md) (locked 2026-05-05). For component visuals once mounted, Storybook is canonical. The catalogue's role is to enforce that no two slices invent two ways to express the same idea.

---

## 7. Open questions for Sally

Resolved 2026-05-05:

- ✅ **Tokens** locked — see §0.3 + [`DESIGN.md`](DESIGN.md) §1.
- ✅ **Dark mode** — on from MVP day 1 (dark-only at slice 4; toggle UI lands in slice W1 per [openspec-slice.md](../openspec-slice.md)).
- ✅ **Iconography** — Lucide cherry-picked via `lucide-svelte`; spec in §0.5 + validated mock at [variants/mock-c4-icons.html](variants/mock-c4-icons.html).
- ✅ **Auth + error surfaces** — promoted to a dedicated [`j0.md`](j0.md) (split from J1 §0); validated mock at [variants/mock-c3-auth-surfaces.html](variants/mock-c3-auth-surfaces.html). Slice 4 (`auth-jwt-cookie`) cites `j0.md`; slice W1 owns `+error.svelte`.
- ✅ **Feature flag toggle** — dedicated `FeatureFlagToggle.svelte` (composes Switch + label + helper + optional Experimental Badge + optional side-effect warning); spec in §1.8 + validated mock at [variants/mock-c6-feature-flag-toggle.html](variants/mock-c6-feature-flag-toggle.html). Switch primitive added at §1.7. First consumer: slice R6 (FR81 Hindsight); future flags reuse the shape.

Still open:

- (none open at this layer; remaining TBDs live in journey docs J1/J2/J3.)

---

Status: **REFINED v1** (locked 2026-05-05 by Sally + Arturo). All TBDs closed; mocks validated in [variants/](variants/). Catalogue is canonical for slice 4 (`auth-jwt-cookie`) and onward; updates land via revision rows at the top of this file.
