# Retrospective: research-frontend-extras-2

> **Forward-authored** — fill at archive with squash SHA, CI rounds, and pre-flag candidates.

- **PR**: [#115](https://github.com/Wizarck/iguanatrader/pull/115) (merged 2026-05-11, squash `b81ad10`).
- **Archive path**: `openspec/changes/archive/2026-05-11-research-frontend-extras-2/`
- **Lines shipped**: 1489 insertions / 65 deletions across 17 files. CI 12/12 verde **al primer push** (zero fix rounds).

## What worked

- **Vitest sanitization suite** caught the DOMPurify configuration before any e2e runtime — `<script>`, `onerror` attrs, `javascript:` URLs, and disallowed tags (`<iframe>`) all stripped. 10/10 unit tests passed first run.
- **Mock-fastapi extension** for research routes mirrors the canonical pattern (slice 4): add the route inline, return the same shape the real FastAPI uses. Two Playwright specs landed without backend changes.
- **`refreshDisabled` prop on `BriefHeader`** keeps the read-only audit-trail page reusing the same header component without forking — single source of truth for symbol + version + methodology badge rendering.
- **`?entry=N` deep link on `AuditTrailViewer`** via `$effect` syncing `openIndex` from `deepLinkIndex` — the warning that surfaced ("captures initial value only") forced the correct reactive pattern instead of a one-shot capture.
- **Lighthouse a11y >=95 extension to `/research/AAPL` + `/research/AAPL/audit-trail/1`** was a 2-line config diff (URL list append) — no new CI job needed.

## What didn't

- **Initial `openIndex = $state(deepLinkIndex)` failed svelte-check** with "captures only the initial value" warning. Fix: `let openIndex = $state<number | null>(null); $effect(() => { openIndex = deepLinkIndex; });`. Pre-flag candidate: any `$state` initialized directly from a `$props()` value needs the `$effect` (or `$derived`) sync pattern.
- **Unused CSS selector `h2`** survived from the prior page's "Recent facts" header (removed when FactTimeline replaced the inline list). svelte-check flagged it; trivial fix. Pre-flag: when removing a Svelte block, sweep the `<style>` for orphaned selectors.
- **Per-segment markdown rendering produces multi-paragraph artifacts** between citation chips (each text fragment between `[fact:<uuid>]` markers becomes its own `<p>` element). Captured in pre-flag candidates; cleaner approach (full body → HTML → placeholder hydration) is a `research-citation-renderer-refactor` follow-up.

## Carry-forward

- **`research-frontend-storybook` slice** (deliberately deferred from this slice): set up Storybook (`@storybook/sveltekit` + addons), write stories for `MethodologyBadge`, `CitationLink`, `BriefHeader`, `FactTimeline`, `AuditTrailViewer`. Add `pnpm storybook` / `pnpm build-storybook` scripts. Optionally add a CI job that builds Storybook on PRs. Rationale for deferral: component coverage already provided by Playwright + Vitest; Storybook payoff scales with surface area.
- **`FactTimeline` "as-of" bitemporal mode** — requires a date picker + `?asOf=<iso>` query parameter on `/api/v1/research/facts/{symbol}` (backend doesn't accept it today). Future enhancement.
- **`/briefs/{symbol}/versions/{n}` endpoint** — currently the audit-trail URL's `[brief_version]` parameter is decorative (validated against current version, redirects on mismatch). Adding the backend endpoint + swapping the loader to fetch by version is a small follow-up.

## Pre-flag candidates

- **Markdown body + citation chips: per-segment rendering produces block boundary artifacts.** The current pipeline splits the brief markdown on `[fact:<uuid>]` markers BEFORE running marked, then renders each text fragment via marked+DOMPurify independently. Adjacent fragments lose their shared paragraph context (the text "Strong quarter per [fact:abc] and growing earnings per [fact:def]." renders as 3 separate `<p>` elements instead of one). The cleaner approach (render full body to HTML first, then post-process to replace markers with `<CitationLink>` placeholders) needs either a marked extension or a placeholder hydration step at the page layer. Both are larger lifts; documented as a `research-citation-renderer-refactor` follow-up.
