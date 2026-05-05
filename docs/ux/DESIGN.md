---
title: iguanatrader — Design tokens (canonical)
status: LOCKED v1
date: 2026-05-05
parent: docs/ux/
related:
  - components.md
  - j1.md
  - j2.md
  - j3.md
  - ../architecture-decisions.md
---

# iguanatrader — Design tokens (canonical)

> Source: [components.md](components.md) §0.3 (canonical reference), [Architecture Decisions](../architecture-decisions.md) §Frontend Architecture (Tailwind 4.x + dark mode + system preference desde MVP), persona Arturo (single-user MVP, Windows localhost).

This file is the **single canonical source of truth** for design tokens. Tailwind config (`apps/web/tailwind.config.ts`) and `apps/web/src/lib/styles/tokens.css` derive from this doc — if a Svelte story does not match the token names + OKLCH values here, the doc is wrong only if Sally + Arturo say so; otherwise the implementation is wrong.

The catalogue ([components.md](components.md)) references token names without committing values; this file owns the values.

---

## 0. Conventions

- Color space: **OKLCH** (Tailwind 4.x native). Hex/HSL fallbacks not maintained — modern browsers only (per Architecture Decisions §Frontend stack).
- Naming: kebab-case CSS custom properties scoped under `:root` (dark) and `:root.light` (light, deferred to slice W1).
- Numerals: `oklch(L% C H)` literal; never relative `from`/`color-mix` in token definitions (allowed in component scope only).
- Contrast: WCAG-AA targeted (4.5:1 body, 3:1 large/interactive); recorded inline.

---

## 1. Color tokens (dark, MVP-locked)

### 1.1 Surface

| Token | OKLCH | Use |
|---|---|---|
| `--bg` | `oklch(18% 0.02 250)` | app background |
| `--surface` | `oklch(22% 0.02 250)` | cards, side panels, ApprovalCard, EmptyState container |
| `--surface-2` | `oklch(26% 0.02 250)` | popovers, drawers, modal, Toast |

### 1.2 Ink

| Token | OKLCH | Use | Contrast on `--bg` |
|---|---|---|---|
| `--ink` | `oklch(95% 0.005 250)` | body text, headings | 12.6:1 (AAA) |
| `--mute` | `oklch(70% 0.012 250)` | secondary text, helper, placeholder | 6.5:1 (AA) |
| `--border` | `oklch(32% 0.02 250)` | Input border resting, table dividers | — |

### 1.3 Brand & semantic

| Token | OKLCH | Use | Contrast on `--bg` |
|---|---|---|---|
| `--accent` | `oklch(72% 0.14 195)` | iguana teal — primary CTA, focus ring, brand surface, active nav | 4.7:1 (AA) |
| `--accent-fg` | `oklch(15% 0.02 250)` | text on accent fills (Button primary label) | — |
| `--success` | `oklch(72% 0.16 145)` | P&L positive, Badge "Open"/"Approved", success Toast | 5.4:1 (AA) |
| `--destructive` | `oklch(64% 0.20 25)` | P&L negative, KillSwitchButton, "Reject" CTA, error Toast, Input error border | 4.6:1 (AA) |
| `--warn-bg` | `oklch(78% 0.14 80)` | Tier-2 cap banner background, T-10s countdown background | — |

### 1.4 Interaction

| Token | OKLCH | Use |
|---|---|---|
| `--focus-ring` | `oklch(72% 0.14 195)` | 2px outline on `:focus-visible` (= `--accent`) |
| `--accent-hover` | `oklch(76% 0.14 195)` | Button primary hover (1-step lift) |
| `--accent-active` | `oklch(68% 0.14 195)` | Button primary mousedown |

---

## 2. Typography

### 2.1 Font families

```css
--font-sans: 'Inter Variable', system-ui, -apple-system, 'Segoe UI', sans-serif;
--font-mono: 'JetBrains Mono Variable', 'SF Mono', Consolas, 'Liberation Mono', monospace;
```

- **Inter Variable**: single woff2 covers all weights (`100`–`900`). Self-hosted at `apps/web/static/fonts/InterVariable.woff2` (license: SIL OFL 1.1).
- **JetBrains Mono Variable**: same approach, at `apps/web/static/fonts/JetBrainsMono[wght].woff2` (license: SIL OFL 1.1).
- No serif. Operational software, not editorial.

### 2.2 OpenType features

- Body: `font-feature-settings: 'cv11', 'ss01';` (single-storey `a`, alternate `g` — improves at-glance reading of strategy params and tickers).
- Monetary cells: `font-variant-numeric: tabular-nums;` always (P&L columns, equity, prices, sizing).

### 2.3 Type scale (Tailwind defaults)

| Class | Size / Line | Use |
|---|---|---|
| `text-xs` | 12px / 16px | Badge, Toast small, Tooltip |
| `text-sm` | 14px / 20px | helper text, table dense rows, EmptyState body |
| `text-base` | 16px / 24px | body default |
| `text-lg` | 18px / 28px | card heading |
| `text-xl` | 20px / 28px | page H1 |
| `text-2xl` | 24px / 32px | dashboard equity headline |

---

## 3. Spacing & layout

- **Spacing scale**: Tailwind 4.x defaults (4px grid; `space-1` = 4px through `space-24` = 96px). No custom values.
- **Container max-width**: `1280px` (`max-w-screen-xl`); narrower for forms (`max-w-md`).
- **Touch target floor**: ≥48×48 CSS px on `pointer:coarse`. Button `sm` (36px) is desktop-only and forbidden as the sole confirmation control.

---

## 4. Border radius

| Token | Value | Use |
|---|---|---|
| `--r-1` | `4px` | Input sm, Badge sm |
| `--r-2` | `8px` | Button, Input default, Toast |
| `--r-3` | `12px` | Card, Drawer, modal panel |
| `--r-pill` | `9999px` | Badge default, Tag |

---

## 5. Motion

- Duration: `--motion-fast: 120ms` (hover, focus); `--motion-base: 200ms` (toast slide, drawer open); `--motion-slow: 320ms` (modal enter).
- Easing: `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)`; `--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)`.
- **`prefers-reduced-motion: reduce`**: durations clamped to `0ms`; only opacity transitions allowed.

---

## 6. Light mode (deferred to slice W1)

Light tokens not yet defined. Slice 4 ships dark-only. When slice W1 (`dashboard-svelte-skeleton`) authors the system-preference toggle, the light derivation will land here under `:root.light` selectors. Anchor reserved.

---

## 7. Implementation contract

When slice 4 authors `apps/web/src/lib/styles/tokens.css`, every entry above must appear there verbatim. CI gate (Storybook visual regression, slice W1 onward) will diff against this doc — if values diverge, the doc is the source of truth unless Sally + Arturo amend this file first.

The Tailwind config's `theme.extend.colors` aliases to the CSS custom properties (`bg: 'var(--bg)'`) so component code reads `class="bg-bg text-ink"` not raw OKLCH.

---

Status: **LOCKED v1** — refinements (light derivation, motion easing variants for charts, additional warn/info tokens) land via a new revision row at the top of this file with date + scope.
