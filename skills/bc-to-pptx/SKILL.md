---
name: bc-to-pptx
description: >
  Generates a branded PPTX deck from LEAN_BUSINESS_CASE.md using the Marlink template.
  Pipeline: Extract BC data -> validate -> inject into template -> QA swarm.
  Use after LEAN_BUSINESS_CASE.md is approved and ready for presentation.
  Also use when user says "generate deck", "create slides", "make pptx", "presentation".
model: opus
context: inline
allowed-tools: "Read, Glob, Grep, Edit, Write, Bash, Agent, Skill"
---

# BC-to-PPTX Generation Pipeline

You generate branded PPTX decks from LEAN_BUSINESS_CASE.md using the semantic placeholder template.

**Reference documents** (read these before generating):
- `OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/filler_spec_BC.md` -- filling rules, structural constraints, formatting
- `OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/semantic_mapping.yaml` -- tag metadata (type, max_chars, bc_sections, descriptions)
- `.claude/skills/pptx-template/guardrails.md` -- absolute rules

**Visual context** (read alongside YAML for each slide):
- `OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/reference/` -- reference PNGs from a completed offering (style guide -- shows what a filled slide looks like)
- `OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/` -- template PNGs with `{{TAG}}` placeholders visible (shows tag positions and layout)

## Architecture

```
LEAN_BUSINESS_CASE.md ──────────────────────────┐
                                            │
_int_ai/_pptx_pipeline/filler_spec_BC.md ──┤
_int_ai/_pptx_pipeline/semantic_mapping.yaml┤
_int_ai/_pptx_pipeline/slide_pngs/reference/*.png ┤  (visual: completed slide style)
_int_ai/_pptx_pipeline/slide_pngs/template/*.png ─┤  (visual: tag positions)
                                            │
                           [Step 1: Visual-Context Fill] ──> _int_ai/fill_data.json
                                            │
                           [Step 1.5: Tag Inventory Check]
                                            │
                           [Step 2.5: Pilot Generation]
                                            │
TEMPLATE.pptx ──────────> [Step 3: Inject] ──────────────> output PPTX
                            (generate_pptx.py)               │
                                                   [Step 4: Post-flight]
                                                             │
                                                   [Step 5: QA Swarm]
                                                             │
                                                   LEAN_BUSINESS_CASE.pptx
```

## Argument Parsing

When invoked with an argument (e.g., "002", "OFFER-002"):
1. Extract the offer number
2. Find folder: `Glob("20_OFFERS/OFFER-{number}*")`
3. Verify `LEAN_BUSINESS_CASE.md` exists in that folder
4. If NO match or no BC -> error

---

## Step 1: Visual-Context Fill

Read the offering's `LEAN_BUSINESS_CASE.md` and produce `fill_data.json` using visual context + YAML metadata.

**Per fill agent (8 parallel, one per PPTX section):**

Each agent receives:
1. **Full LEAN_BUSINESS_CASE.md** -- complete document for cross-reference
2. **Reference PNGs** (`_int_ai/_pptx_pipeline/slide_pngs/reference/`) -- what completed slides look like (style guide only, NEVER copy data)
3. **Template PNGs** (`_int_ai/_pptx_pipeline/slide_pngs/template/`) -- where `{{TAG}}` placeholders sit
4. **YAML section extract** -- tag names, types, max_chars, visual_roles, bc_sections, descriptions, suggestions
5. **filler_spec_BC.md** -- formatting rules, blacklist, consistency requirements

**Agent instructions:**
1. LOOK at the reference PNG -- understand what KIND of content goes on this slide (density, format, bullet count)
2. LOOK at the template PNG -- see WHERE each `{{TAG}}` sits and how much space it has
3. READ the BC sections listed in `bc_sections` for this slide (scoped extraction)
4. READ the YAML tag metadata (description, suggestion, max_chars) for constraints
5. For each tag: extract BC data, respecting `max_chars` and `visual_role`
6. Fill ALL tags for the section at once -- ensure narrative coherence across slides
7. Financial figures MUST be exact from BC -- never invent
8. Ask user about offering-specific blacklist (filler_spec S2)

**Output**: `OFFER-XXX/_int_ai/fill_data.json` (flat JSON, series expanded as `TAG_1`, `TAG_2`, ...)

**Output**: `OFFER-XXX/_int_ai/slide_data.json`

```json
{
  "meta": {
    "offering_id": "OFFER-002",
    "offering_name": "1EDGE Secure Edge Cloud",
    "iteration_num": "1",
    "iteration_maturity": "Good",
    "generated": "2026-03-22"
  },
  "TITLE_OFFERING": "1EDGE Secure Edge Cloud",
  "TITLE_ITERATION": "Customer VM Hosting",
  "TITLE_PILLAR": "Cloud & IT -- Portfolio and Innovation Strategy",
  "ITERATION_NUM": "1",
  "ITERATION_MATURITY": "Good",
  "CANVAS_REVENUE_1": "VM subscriptions ($30/VM/mo)",
  "CANVAS_REVENUE_2": "Management fee ($31/VM/mo)",
  ...
}
```

**Rules** (from filler_spec S4):
- Every value must be a string
- Bullet lists: `\n`-separated within a single field
- Numbers: $X.XM (millions), $X,XXXK (thousands), X.X%
- No markdown, no em-dashes (use --), max ~200 chars per field
- Auto-fix: CIT -> "Cloud & IT", SKU codes -> service names

---

## Step 1.5: Tag Inventory Check (MANDATORY -- blocks Step 2)

Before validation, reconcile fill data against the actual template:

1. **Count template slots**: open template PPTX, grep `{{TAG}}` across all XML files (slides + diagrams/data + diagrams/drawing). Count unique tag patterns.
2. **Count fill data keys**: count unique keys in fill_data.json
3. **Compare**:
   - Tags in template with no fill data = **unfilled slots** (will show as raw `{{TAG}}` in output)
   - Fill data keys with no template slot = **orphan data** (wasted extraction effort)
4. **Report**: `Template: X slots, Fill data: Y keys, Matched: Z, Unfilled: A, Orphan: B`
5. **Block if**: orphan ratio > 10% (indicates YAML has phantom tags not in template, or fill agents invented tag names)
6. **Warn if**: unfilled slots > 5% (ask user: "X tags have no data. Continue?")

**Why this step exists**: YAML generated from classification (not template scan) once produced 453 tag patterns for a template with 217 actual tags -- 80.9% orphan ratio, 9 STRUCTURAL failures. A 50% threshold failed to catch it. The 10% threshold catches YAML/template drift early.

---

## Step 2: Validate Data

```bash
python 98_Scripts/validate_pptx_data.py \
  --data OFFER-XXX/_int_ai/slide_data.json \
  --template "OFFER-000 (Template)/LEAN_BUSINESS_CASE_TEMPLATE.pptx"
```

Checks (from filler_spec S2, S5, S6):
- Forbidden keywords (CIT, SKU codes, offering blacklist)
- Field length violations (>200 chars)
- Cross-slide consistency (revenue, margin, ARPU across slides)
- Template coverage (every tag in template has a value)
- Fill rate (must be >= 80%)

If violations found: fix data, re-validate. Block on <80% fill rate.

---

## Step 2.5: Pilot Generation (MANDATORY -- blocks Step 3)

Before full generation, test on 3 representative slides:

1. **Pick 3 slides**: 1 SmartArt (e.g., Case Background), 1 table (e.g., CTS Summary), 1 canvas/shapes (e.g., Canvas or Dashboard)
2. **Run generate_pptx.py** on those slides only (or full run, then inspect these 3)
3. **Render to PNG** and visually inspect for the 5 known failure modes:
   - **Duplication**: same content repeated 2-6x in a cell (series join failure)
   - **Missing SmartArt**: raw `{{TAG}}` visible on SmartArt slides (triple-file violation)
   - **Split tags**: partial `{{TAG` visible (tag spans two `<a:r>` runs)
   - **Overflow**: text cut off or wrapping badly (max_chars violated)
   - **Stale content**: original template text still showing (replacement failed)
4. **If any failure**: fix generate script or fill data BEFORE full generation
5. **If clean**: proceed to Step 3

**Why**: full 57-slide generation + QA swarm is expensive. Catching errors on 3 slides saves 80% of rework.

---

## Step 3: Inject Data

```bash
python 98_Scripts/generate_pptx.py \
  "OFFER-000 (Template)/LEAN_BUSINESS_CASE_TEMPLATE.pptx" \
  OFFER-XXX/_int_ai/fill_data.json \
  OFFER-XXX/LEAN_BUSINESS_CASE.pptx
```

The script:
1. Opens template as zip
2. Builds series expansions (`TAG_{n}` -> joined newline string from `TAG_1`, `TAG_2`, ...)
3. Processes ALL XML files: `slides/slide*.xml` + `diagrams/data*.xml` + `diagrams/drawing*.xml`
4. Deduplicates: first occurrence of each tag gets the value, subsequent occurrences emptied
5. Cleans up empty paragraphs left by deduplication
6. Validates XML after modifications (lxml parse test)
7. Reports: replaced/remaining breakdown per file

**Do NOT edit XML manually.** The script handles all text replacement.

---

## Step 4: Post-flight Verification

```bash
python 98_Scripts/postflight_pptx.py \
  --pptx OFFER-XXX/LEAN_BUSINESS_CASE.pptx \
  --template "OFFER-000 (Template)/LEAN_BUSINESS_CASE_TEMPLATE.pptx"
```

Checks:
- Raw `{{tags}}` remaining (target: 0)
- XML validity of every file
- python-pptx open test
- Slide count matches template
- Forbidden keywords scan

---

## Contract

**Deliverables**: Branded PPTX deck from LEAN_BUSINESS_CASE.md
**Validation**: /qa-pptx
**Acceptance Criteria**:
- All template tags filled from BC data (no raw {{TAG}} remaining)
- No placeholder text remaining in output
- Series tags use join strategy (newline-separated, never paragraph cloning)
- SmartArt triple-file compliance (slide + data + drawing XMLs processed)
- Visual QA passed (no duplication, overflow, split tags, or stale content)
- Fill rate >= 80% before generation proceeds
**Escalation Triggers**:
- QA ISSUES FOUND twice on same deliverable → pause, escalate to user
- Orphan ratio > 10% at Tag Inventory Check → stop, reconcile YAML
**Max Rework Cycles**: 2

## Step 5: QA Swarm

Render slides and launch parallel QA agents (3 slides per agent):

```
/qa-pptx --slides 1,2,3 --pptx OFFER-XXX/LEAN_BUSINESS_CASE.pptx
/qa-pptx --slides 4,5,6 --pptx OFFER-XXX/LEAN_BUSINESS_CASE.pptx
...
```

**Launch ALL QA agents in parallel.**

Each returns: PASS or ISSUES (slide_number, issue, fix_instruction).

### Fix Loop
1. Collect all issues
2. Data errors: update _int_ai/slide_data.json, re-inject (Step 3)
3. Re-render affected slides, re-QA
4. Max 2 fix iterations

---

## Protected Slides (NEVER inject)

Authoritative list from `semantic_mapping.yaml` `protected_slides` (67-slide template v4.0):

| Slide (presentation pos) | Content |
|--------------------------|---------|
| 2 | TOC |
| 3 | Branding |
| 4 | Framework |
| 8 | Section separator — Case Background |
| 10 | Section separator — Strategic Fit |
| 14 | Section separator — Customer Problem |
| 16 | Section separator — GTM Offering Overview |
| 20 | Section separator — Commercial Value |
| 26 | Section separator — Finance Credibility Gate |
| 38 | Section separator — Sales Motion Readiness |
| 45 | Section separator — Delivery & Ops |
| 50 | Section separator — Capability & Dependency |
| 57 | Section separator — Risk Assessment |
| 60 | Section separator — Investment Ask |
| 63 | Section separator — Success Metrics |
| 67 | Thank You |

**XML file note**: presentation positions 59-67 map to slide62.xml through slide70.xml
(slide59-61.xml are orphaned — not in presentation, skip these in all operations).

---

## Dynamic Slides (cloned N times during generation)

| Slide (presentation pos) | Logic | BC Source |
|--------------------------|-------|-----------|
| 58 | Risk card — duplicated N times per BC §9.1 risk count. Each copy uses RISK_TITLE, RISK_IMPACT, RISK_LIKELIHOOD, RISK_OVERALL, RISK_ROOT_CAUSE, RISK_INDICATOR_1/2, RISK_OWNER, RISK_CRITERIA_1/2/3 | BC §9.1 |
| 35-36 | SKU forecast table — one per segment (max 2 in template; clone if >2 segments) | BC §4.7 |

**Risk card generation rule**: count Risk N entries in BC §9.1. Insert N-1 additional copies of slide 58 at position 58+k, renaming tags RISK_* with index _k suffix, then inject.

---

## Conditional Slides

| Slide (presentation pos) | Condition | If absent |
|--------------------------|-----------|-----------|
| 13 | BC §2.2 has portfolio evolution/cannibalization detail | Hidden by default, leave as-is |
| 51 | BC §8.3.0 Current State 4P overview exists | Leave empty |
| 34 | BC has wave gates (§9.2) | Leave empty |
| 35-36 | BC has segment-level SKU data | Only populate available segments |

---

## Rules

1. **Read `_int_ai/_pptx_pipeline/filler_spec_BC.md`** before every generation
2. **Never edit XML manually** when generate_pptx.py can handle it
3. **Never use em-dashes** -- use double hyphens (--)
4. **Protected slides are untouchable**
5. **QA is mandatory** -- never skip Step 5
6. **Max 200 chars per field**
7. **No CIT abbreviation** -- always "Cloud & IT"
8. **No SKU codes** -- use descriptive service names
9. **Cross-slide consistency** -- revenue, margin, ARPU must match everywhere
10. **80% minimum fill rate** -- ask user before proceeding if below
11. **Object-grouped fill**: When filling multi-field objects (iterations, milestones, risk cards), extract complete objects from BC then write all fields per object together. Tags are structured `{{OBJECT_{n}_FIELD}}` -- fill by iterating over objects, not over fields. This prevents cross-field misalignment (e.g., iteration 2's year ending up next to iteration 1's label).
    - **Milestone slots**: Each of the 5 milestone slots has exactly 2 fields: `DASH_MILESTONE_{n}_DATE` + `DASH_MILESTONE_{n}_ITEM`. There is NO `_TITLE` field -- do NOT produce one.
12. **Double-index capability tables**: The 4 capability assessment slides (PEOPLE, PROCESS, PLATFORM, PARTNER) use a double-index pattern where M (capability columns) varies per LBC:
    - JSON keys: `PEOPLE_CAP_1_HEADER`, `PEOPLE_CAP_2_HEADER`, ..., `PEOPLE_1_CAP_1`, `PEOPLE_1_CAP_2`, `PEOPLE_2_CAP_1`, etc. Risk column: `PEOPLE_1_RISK`, `PEOPLE_2_RISK`, ...
    - **Extraction order**: iterate columns (m) first, then rows (n). For each BU row n, extract all M capability ratings plus the Risk value.
    - **Pre-fill validation**: count capability columns M in the BC table and compare against M in the template PPTX. If they differ, STOP and ask the user -- the template table structure may need adjustment before injection.
    - Same pattern applies to PROCESS_, PLATFORM_, PARTNER_ prefixes.
