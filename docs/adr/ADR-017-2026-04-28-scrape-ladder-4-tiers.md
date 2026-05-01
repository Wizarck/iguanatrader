---
adr: 017
date: 2026-04-28
status: proposed
decided-by: Arturo Ramírez (arturo6ramirez@gmail.com)
tags: [research, scraping, resilience, anti-bot]
---

# ADR-017 — 4-tier scrape ladder

## Status

**Proposed**. Recorded at Gate B (2026-04-28); full body lands when slice **R3** (`research-news-catalysts-adapters`) implements the ladder — at which point this ADR transitions to `accepted`.

## Stub

Several research data sources (Finviz screener, OpenInsider scraping, certain Finnhub endpoints) require web scraping rather than pure-API access. Anti-bot measures escalate over time: simple rate-limiting → JavaScript rendering → fingerprinting → CAPTCHAs. iguanatrader's research domain needs to gracefully degrade through this escalation rather than hard-fail when one tier breaks.

The ladder, in order of preference (cheapest + simplest first):

1. **Tier 1 — `WebFetch`**: plain HTTPS GET. Works for static HTML + simple `robots.txt`-respecting endpoints.
2. **Tier 2 — Playwright**: full browser automation (Chromium headless). Handles JavaScript-rendered content; user-agent rotation; cookie persistence per session.
3. **Tier 3 — Camoufox**: Firefox fork with anti-fingerprinting (https://github.com/daijro/camoufox). Used when Playwright's Chromium is detected/blocked.
4. **Tier 4 — Camoufox + paid CAPTCHA solver**: e.g. 2Captcha or AntiCaptcha. Used only when (a) the source is critical, (b) tier 3 is blocked, and (c) the per-call cost is justified by the data value (~$0.001-0.003 per CAPTCHA solve).

Each adapter declares its tier-1 default and which fallback tiers it allows. Per-tenant config can opt out of paid tier 4 (`scrape_tier_max: 3`).

## Cross-references

- `docs/architecture-decisions.md` — §"Scrape ladder topology" + 4 critical caveats from Gate A amendment.
- `docs/data-model.md` — `research_facts.tier` column (A/B/C) for point-in-time semantics; the scrape ladder's tier numbering (1-4) is orthogonal — that's about *how* we got the fact, not *whether* it's PiT-correct.
- `docs/hitl-gates-log.md` — Gate A amendment entry, caveat #4 (captcha-solver paid services).
- `docs/openspec-slice.md` row R3 — slice that lands the ladder (`contexts/research/scraping/{tier1_webfetch,tier2_playwright,tier3_camoufox,tier4_captcha,robots_check,user_agent}.py`).

## Full content

Pending. Slice R3's `proposal.md` + `design.md` + spec scenarios will populate this ADR's full Context / Decision / Consequences sections via the OpenSpec lifecycle.
