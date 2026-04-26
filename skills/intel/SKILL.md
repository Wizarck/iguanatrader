---
name: intel
description: >
  Loads strategic and market intelligence context silently. Use this
  skill whenever working on offerings, business strategy, market analysis,
  competitive positioning, customer segments, personas, or value propositions.
  Also use when the user mentions ABC Goals, CIT OKRs, Marlink strategy,
  target segments, or any offering in 20_OFFERS/.
disable-model-invocation: true
model: haiku
allowed-tools: Read, Glob
---

# Intelligence Context Loader

Load strategic and market intelligence into context. Silent operation - no output required.

## Instructions

Read ALL the following files silently to load context. After reading, respond only with:

```
Context loaded.
```

---

## Files to Read

### 1. Strategy (Corporate Goals & OKRs)
- `10_MARLINK/10_Strategy/10_GOALS.md`
- `10_MARLINK/10_Strategy/11_CIT_STRATEGY.md`
- `10_MARLINK/10_Strategy/12_CIT_OKRS.md`
- `10_MARLINK/10_Strategy/30_VALUE_PROPOSITION.md`

### 2. Master Intelligence Indices (consolidated — replaces 16 segment/persona files)
- `10_MARLINK/40_Market/21_SEGMENTS.md` — ALL segments: fleet, crew, connectivity, regulations, pain points
- `10_MARLINK/40_Market/22_PERSONAS.md` — ALL persona archetypes: pain points, decision criteria, pillar interest
- `10_MARLINK/50_Competitive/00_COMPETITIVE_LANDSCAPE.md` — Competitor master index: portfolio overlap, segment presence

### 3. Offering-Specific (load only if an offering ID is mentioned)
If the user mentions a specific offering (e.g., OFFER-002), also load:
- `20_OFFERS/OFFER-XXX/00_Research/market.md`
- `20_OFFERS/OFFER-XXX/00_Research/competitive.md`
- `20_OFFERS/OFFER-XXX/00_Research/customer.md`
- `20_OFFERS/OFFER-XXX/00_Research/technical.md`
- `20_OFFERS/OFFER-XXX/GAPS.md`
- `20_OFFERS/OFFER-XXX/PROGRESS.md`

---

## User Request

$ARGUMENTS
