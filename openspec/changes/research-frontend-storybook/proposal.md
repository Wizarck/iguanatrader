# Proposal: research-frontend-storybook

> **Storybook init + 5 component stories** for the research bounded context. Closes the deliberate scope-deferral from PR #115 (`research-frontend-extras-2`).

## Why

PR #115 deferred Storybook to keep the slice scoped:

> Storybook stories scope-deferred to a future `research-frontend-storybook` slice (rationale: component coverage already provided by Playwright + Vitest; setup adds ~6 devDeps + 2 config files + potentially a new CI job — disproportionate for 3-5 components; the slice is more useful once the frontend surface is wider).

Now the surface is 5 components (MethodologyBadge, CitationLink, BriefHeader, FactTimeline, AuditTrailViewer) and several recent slices touched them — the next round of UI iteration benefits materially from a sandbox where each component renders in isolation with knobs for every prop.

## What

### Dependencies (additive devDeps)

- `storybook@^10` — Storybook core (Vite + framework agnostic).
- `@storybook/sveltekit@^10` — SvelteKit framework adapter (Svelte 5 supported at runtime).
- `@storybook/addon-a11y@^10` — axe-core inline a11y reporter (W1 enforces a11y ≥ 95 in Lighthouse; surface violations during component work, not only at page level).

`@storybook/addon-essentials` is **not** installed — in Storybook 9+ the canonical essentials (controls, actions, viewport, docs) are bundled into the core.

### Configuration

- `.storybook/main.ts` — framework + stories glob (`src/lib/**/*.stories.{js,ts,svelte}`) + a11y addon registration + `typescript.check: false` (avoid running tsc again from the Storybook config layer).
- `.storybook/preview.ts` — global parameters: `controls.matchers` for colour/date pickers + `a11y` parameter pointing at `#storybook-root`.

### Stories (`apps/web/src/lib/components/research/<name>.stories.ts`)

One story file per component, written in the canonical CSF format. Each file:

- Exports a `meta: Meta` (untyped — Storybook 10's `Meta<Component>` generic still references Svelte 4 component shape, blocking strict typecheck with Svelte 5 runes components; using bare `Meta` lets the Storybook runtime validate args via the Controls panel instead).
- Exports 4–8 `StoryObj` instances covering the canonical variants: methodology values, citation states (resolved/scraped/manual/llm/broken), brief-header refresh states, fact-timeline empties/highlights/as-of-mode, audit-trail accordion states.

### Build verification

- `pnpm build-storybook` runs locally + produces a complete `storybook-static/` bundle (verified during development — Vite finishes the build in ~5s).
- `.gitignore` extended with `storybook-static`.
- `tsconfig.json` `exclude` adds `src/**/*.stories.ts` to keep `svelte-check` clean (Storybook's typings have a Svelte 4 / Svelte 5 mismatch that's a known ecosystem gap; the build succeeds — only TypeScript strict typecheck fails on the generic).

## Out of scope (deferred)

- **CI build-storybook job** — could be a third GitHub Actions job alongside the existing lighthouse + tests. Not in this slice; `pnpm build-storybook` is part of the local dev loop. A future `research-frontend-storybook-ci` slice (or just a `.github/workflows/storybook.yml` 1-line addition) can land it.
- **Story interaction tests** (`@storybook/addon-interactions` + `@storybook/test`) — Playwright e2e already covers user-flow assertions. Story files in this slice are visual/contract-only.
- **`.stories.svelte` format** via `@storybook/addon-svelte-csf` — adds a dependency + an extra build step; `.stories.ts` CSF format works fine for component-level stories.
