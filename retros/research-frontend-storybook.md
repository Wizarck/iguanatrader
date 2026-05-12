# Retrospective: research-frontend-storybook

> **Forward-authored** — fill at archive.

- **PR**: TBD (merged TBD, squash `TBD`).
- **Archive path**: `openspec/changes/archive/2026-05-12-research-frontend-storybook/`
- **Lines shipped**: TBD insertions / TBD deletions across TBD files. CI TBD.

## What worked

- TBD

## What didn't

- TBD

## Carry-forward

- **CI `build-storybook` job** — 1-line GitHub Actions step that runs `pnpm build-storybook` on PR. Catches story breakage before merge.
- **`@storybook/addon-svelte-csf`** for `.stories.svelte` files — co-locates story scaffolding with the component's native template syntax. Adds a small dependency but improves DX.
- **`@storybook/test` + interaction tests** — once stories accumulate, interactive flow tests (click, fill, assert) could replace some Playwright assertions. Trade-off: Storybook test runner adds CI weight.

## Pattern usage

- **First Storybook slice in iguanatrader** — sets the precedent for component-level documentation. Future slices that touch UI can add stories alongside the component edit for free.
- **Untyped `Meta` over `satisfies Meta<Component>`** — known Svelte 5 / Storybook 10 typing gap; documented in story files inline so contributors don't waste time trying to "fix" it.
- **`tsconfig.json` exclude for `*.stories.ts`** rather than fighting the type mismatch — pragmatic; Storybook runtime validates the args via Controls.
