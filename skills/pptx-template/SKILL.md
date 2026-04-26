---
name: pptx-template
description: >
  Interactive PPTX template builder and maintainer. Two modes:
  CREATE: converts any base .pptx into a semantic placeholder template through a gated process.
  UPDATE: maintains an existing template after user changes (add/remove/modify slides).
  Use when preparing a new PPTX template, converting a presentation to a template,
  or updating an existing template after changes.
  Also use when user says "template pptx", "prepare template", "build pptx template",
  "convert pptx to template", "update template", "sync template".
model: opus
context: inline
argument-hint: "[--update] <path-to-template.pptx>"
disable-model-invocation: true
---

# PPTX Template Builder

You convert any base .pptx into a semantic placeholder template through a safe, gated process.
The core safety invariant: **python-pptx (structure) -> save -> lxml (content) -> never touch again**.

See [guardrails.md](guardrails.md) for absolute rules that override all other instructions.

## Argument Parsing

The user provides a path to a base .pptx file:
- `/pptx-template path/to/deck.pptx`
- If no argument, ask: "Which .pptx file should I convert to a template?"

---

## STEP 0: Input + Backup

1. Verify the .pptx exists and can be opened by python-pptx
2. Copy to a working directory (never modify the original)
3. Save checkpoint: `_int_ai/checkpoint_00_original.pptx`
4. Report slide count
5. Ask user:
   - "This PPTX has X slides. What type? (BC / BS / OS)"
   - "Where is the corresponding markdown file (e.g., LEAN_BUSINESS_CASE.md)?"

**GATE**: User provides type and markdown path before proceeding.

---

## STEP 1: Content Alignment Audit (PPTX vs Markdown)

1. Read the base .pptx slide titles and content summaries (python-pptx, read-only)
2. Read the markdown file section structure (H1, H2, H3 headings)
3. Compare: which sections exist in both? Which are in markdown but not PPTX? Which are in PPTX but not markdown?
4. Present alignment table:

```
PPTX Slide              | Markdown Section       | Match
Canvas (slide 5)        | Executive Summary      | YES
Wave Gates (slide 12)   | S9.2 Wave Gates        | YES
(missing)               | S6 Key Assumptions     | NO -- PPTX missing
Roadmap (slide 36)      | (not in markdown)      | NO -- MD missing
```

5. Ask: "Here is how the PPTX aligns with the markdown. Should we add/remove slides to match? Should we reorder to follow the markdown structure?"

**GATE**: User decides the target structure.

---

## STEP 2: Structural Inventory (read-only)

1. Catalog all slides: number, title, layout name, SmartArt yes/no
2. Present list alongside the STEP 1 alignment
3. Ask: "Based on the alignment, do you need to add, remove, or reorder slides? Or is the structure final?"

If user says structure is final -> skip to STEP 4.

---

## STEP 3: Structural Changes (python-pptx -- ONE save)

1. Collect ALL operations the user wants (add, remove, reorder)
2. Execute ALL in ONE python-pptx session (add + reorder + save)
3. Save checkpoint: `_int_ai/checkpoint_03_structured.pptx`
4. Ask: "Open in PowerPoint. Is the structure correct?"

**GATE**: User must confirm before proceeding. If not correct, repeat STEP 3.

---

## STEP 4: Deep Audit (lxml -- on the FINAL structure)

1. **Identify protected slides first.** Read the filler skill spec (e.g., `_int_ai/_pptx_pipeline/filler_spec_BC.md`) or ask the user which slides are fully static. Protected slides are: branding/framework visuals, TOC, section separators, thank-you/closing. These slides are SKIPPED entirely in STEPs 4-6.
2. Present the protected list to the user for confirmation:
   ```
   PROTECTED (will NOT be audited or tagged):
     Slide 2: "Lean Business Case Structure" (TOC)
     Slide 3: "Intelligent Innovation" (branding)
     Slide 4: "GTM Offering Creation Blueprint" (framework)
     Slide 9: "Thank You" (closing)
     Slides 10,12,19,23,36,42: Section separators
   ```
3. Parse EVERY `<a:t>` and `<dgm:t>` element with lxml across all XML files in the PPTX zip, **excluding protected slides**
4. Record for each element: file path, element index, text content, parent context
5. Output: `_int_ai/element_audit.json` (protected slides are absent from this file)
6. Save the protected list to `semantic_mapping.yaml` under `protected_slides`

**GATE**: User confirms the protected slide list before proceeding.

**IMPORTANT**: After STEP 3 completes, NEVER use python-pptx again on this file. All subsequent operations use lxml only.

---

## STEP 5: Classify Elements (AI + user review)

Classification rules are defined in [guardrails.md](guardrails.md) under "Classification". Key principles:

1. **FIXED**: titles, headers, labels, sub-headers, section numbers, decorative symbols, metric labels
2. **DATA**: financial figures, descriptions, names, dates, year ranges, status indicators
3. **Series Pattern Rule**: ANY list of items (bullets, costs, partners, risks, segments, etc.) MUST use `{n}` pattern -- never assume a fixed count. The filler skill determines N from the markdown.
4. **Object-Grouped Tags**: When a slide has N repetitions of a multi-field object (iterations, milestones, risk cards), tags MUST group by object index: `{{OBJECT_{n}_FIELD}}`, NOT `{{OBJECT_FIELD_{n}}}`. The filler writes complete objects, not parallel lists. See [guardrails.md](guardrails.md) "Placeholder Naming" for the full rule and examples.
5. **Shared Metadata Tags**: iteration number, maturity level, offering name appear across multiple slides -- use consistent tag names (`{{ITERATION_NUM}}`, `{{ITERATION_MATURITY}}`, `{{TITLE_OFFERING}}`)
6. **Mixed Elements**: when a single text element contains both fixed and variable parts (e.g., "Iteration 1" where "Iteration " is fixed), split at the `<a:r>` run level if possible, or document the fixed prefix in the mapping
7. **Split-Run Words**: PowerPoint may split a word across runs (e.g., "Itera" + "tion 1"). Place `{{TAG}}` in the first run, clear subsequent fragment runs. See [guardrails.md](guardrails.md) "Split-Run Words" for details.
8. **Sub-label + Bullets**: When a panel has bold sub-labels followed by bullet points, encode the sub-label identity into the series prefix: `{{PREFIX_SUBLABEL_{n}}}`. Always use `{n}` series even for single bullets today. See [guardrails.md](guardrails.md) "Sub-label + Bullets Pattern" for full rule and edge cases.

9. **Double-Variable Tables**: When a table has variable rows (BUs, {n}) AND variable columns (capabilities, {m}), use double-index tags: headers as `{{PREFIX_CAP_{m}_HEADER}}`, body cells as `{{PREFIX_{n}_CAP_{m}}}`, and fixed final column (Risk) as `{{PREFIX_{n}_RISK}}` (single index only). Applies to PEOPLE, PROCESS, PLATFORM, PARTNER capability slides. See [guardrails.md](guardrails.md) "Double-Variable Tables" for full pattern and example.

Assign semantic `{{TAG}}` names following [guardrails.md](guardrails.md) "Placeholder Naming":
- UPPER_SNAKE_CASE with slide context prefix
- Series: `{{CANVAS_COST_{n}}}`, `{{EXEC_MILESTONE_{n}_DATE}}`
- Compound series: `{{EXEC_RISK_{category}_{n}}}`

Present to user in batches of ~3 slides, element by element, using this format:

```
=== Slide 12 — Customer Problem (32 elements) ===

| # | Text | Class | Tag / Reason |
|---|------|-------|--------------|
| 0 | "Customer Problem & Use-Case Validation" | FIXED | Slide title |
| 1 | (auto-field) | SKIP | PowerPoint slide number |
| 2-8 | "Remote customers operating..." | DATA cluster | {{PROBLEM_STATEMENT}} |
| 9 | "Key Data Highlights:" | FIXED | Section label |
| 10 | "High Latency Friction:" | DATA series | {{PROBLEM_PAIN_{n}_TITLE}} — pain point name varies per offering |
| 11-13 | "Standard M365 fails... 600-800ms..." | DATA series | {{PROBLEM_PAIN_{n}_DESC}} — pain point description |
| 26 | "Observable Business Impact:" | FIXED | Section label |
| 27 | "End-user productivity is unreliable..." | DATA cluster | {{PROBLEM_IMPACT}} |
```

Key distinctions in the table:
- **FIXED**: titles, labels, decorative — no tag
- **SKIP**: auto-fields (`<a:fld>`) — invisible to the pipeline
- **DATA series**: repeating items with `{n}` — N determined by BC content
- **DATA cluster**: named fields with fixed structure — always present

### Label Genericization (inline with classification)

FIXED labels must work for ANY offering, not just the current one. When presenting each batch:
- For every FIXED label that contains offering-specific or overly narrow language, propose a generic alternative inline
- Use a separate column or note: `Original: "Into standardized managed pathways:" -> Proposed: "Migration targets:"`
- Slide titles are EXCLUDED from this review (they are structural and already generic)
- The user approves or adjusts each label change in the same review pass
- Approved generic labels are applied during STEP 6 (lxml injection) alongside placeholder insertion

Ask: "Review the classification and label proposals. Flip any FIXED <-> DATA and adjust labels as needed."

**GATE**: User must approve the full classification before proceeding.
Output: `_int_ai/classification.json`

---

## STEP 6: Insert Placeholders + Generate Mapping (lxml -- SINGLE pass)

See [guardrails.md](guardrails.md) "Injection Engine Rules" for the mandatory mechanisms.

### 6a. Build the injection script

Write a Python script with per-slide configs. Each slide MUST have:
- `pre_fields`: positional tag names for the first N DATA elements (before any group delimiter)
- `groups`: `{label: prefix}` dict using FIXED labels as delimiters for semantic groups
- `default`: fallback prefix (should only apply to truly positional tables)
- `table_cols`: column names for table-structured slides (column cycling)

The FIXED set MUST be a Python list literal (never parsed from free text).

### 6b. Execute: Label genericization + tag injection in one pass

1. Open checkpoint_03 as zip
2. For each non-protected slide and its associated diagram files:
   - Apply label genericizations (old text -> new generic text)
   - Skip auto-fields (`<a:fld>`)
   - Skip FIXED elements
   - Assign semantic `{{TAG}}` to DATA elements using pre_fields -> groups -> table_cols -> default
3. For SmartArt: process data{N}.xml AND drawing{N}.xml with the same config
4. Validate XML after each file modification
5. Save: `_int_ai/checkpoint_06_with_placeholders.pptx`

### 6c. Post-injection verification (mandatory, blocks GATE)

1. python-pptx open test
2. Count all `{{TAG}}` occurrences
3. **Scan for generic tags**: any `{{PREFIX_N}}` where PREFIX is a bare default (no semantic group) is a BUG -- fix before proceeding
4. Report: total tags, tags per slide, any generic tag violations

### 6d. Generate semantic_mapping.yaml (mandatory, same step)

The YAML is generated from the **template tag inventory**, NOT from the classification.

**Procedure**:
1. **Scan the injected template** (checkpoint_06): grep all `{{TAG}}` patterns across ALL XML files (slides + diagrams/data + diagrams/drawing)
2. **Deduplicate**: build the canonical tag list (unique tag patterns found in the template)
3. **Enrich**: for each tag in the inventory, add classification metadata (description, suggestion, example, max_chars, type) from the STEP 5 classification output
4. **Discard phantom tags**: tags in classification but NOT in the template = classification artifacts. Do NOT include them in the YAML.
5. **Report injection gaps**: tags in the template but NOT in classification = injection bugs. Fix before proceeding.

**Invariant**: `meta.total_tags` MUST equal the count of unique tag patterns found in the template PPTX. If these numbers diverge, the YAML is wrong.

**Why**: Classification defines what SHOULD be tagged. The template defines what IS tagged. The YAML must reflect reality (template), enriched with intent (classification). Previous approach generated YAML from classification (453 patterns) for a template with only 217 actual tags -- causing 80.9% orphan ratio and 9 STRUCTURAL failures during generation.

7. Ask: "Template has X semantic tags. Opens OK? Check in PowerPoint. Mapping saved to semantic_mapping.yaml."

**GATE**: User confirms template + mapping are correct.

---

### 6e. Generate PNG sets (mandatory, same step)

Render the template to two PNG sets for use by fill and QA agents:

1. **Template PNGs** (`OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/`): Render checkpoint_06 to PDF via LibreOffice, then to PNG via pymupdf. Shows `{{TAG}}` placeholders in situ.
2. **Reference PNGs** (`OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/reference/`): If a completed offering exists (e.g., OFFER-001), render its LEAN_BUSINESS_CASE.pptx. If none exists yet, skip -- reference PNGs will be generated after the first successful fill.

Both PNG sets are stored in `OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/`. They serve as visual context for the 3-Layer Context rule (guardrails.md).

**PNG validation (mandatory before and after copy)**:

Before copying new PNGs to either directory, validate existing state:
```bash
python 98_Scripts/validate_slide_pngs.py "OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/"
```

If mixed naming is detected (old `slide_N.png` + new `page_NN.png`), clean up first:
```bash
cd "OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/" && rm -f slide_*.png
```

After copying PNGs, re-validate with expected count:
```bash
python 98_Scripts/validate_slide_pngs.py "OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/" --expected-count 65
```

Do NOT proceed past this step if validation fails. See guardrails.md "PNG Directory Management" for full rules.

---

## STEP 7: Filler Spec + Guardrails Debate
Tags are NOT hardcoded counts -- the filler skill determines how many based on the markdown content.

### B) filler_spec_{type}.md

A reference document for the corresponding filler skill (`/bc-to-pptx`, etc.) that defines:

1. For each slide: what markdown section feeds it, what data type (text, table, list, number)
2. For iterative elements: how to determine the count from the markdown
3. For conditional elements: when to include/exclude
4. Content rules (no CIT, no SKU codes, max chars per field)
5. Validation checks: cross-slide consistency (revenue Y1 must match everywhere)
6. **Filler skill guardrails** (see debate below)

### C) Generate Script Contract (mandatory, same step)

During the filler spec debate, also define the `generate_pptx.py` interface contract:

1. **Input format**: flat JSON with static tags + expanded series (TAG_1, TAG_2, ...)
2. **Series handling**: join-based (all values joined with `\n`), NEVER paragraph cloning
3. **Dedup strategy**: seen_tags set per file, first occurrence kept, rest emptied
4. **SmartArt file list**: slides + data + drawing (triple-file mandatory)
5. **Pilot test plan**: 3 representative slides (1 SmartArt, 1 table, 1 canvas) before full run

This contract becomes Section 9 of the filler_spec. It ensures the injection format and the generation consumption format are aligned from the start.

**Why this is mandatory in STEP 7**: designing the script reactively (after first fill attempt) caused 6 broken iterations. The contract must exist before any fill agent runs.

### C) Filler Skill Guardrails Debate

Structured conversation with the user to define the rules the filler skill must follow for THIS specific template. Walk through each category, suggest defaults, and let the user override.

**1. Protected slides** (carried forward from STEP 4):
- "These slides are protected and the filler skill will skip them: [list]. Anything to add or remove?"

**2. Content vocabulary**:
- "What terms are forbidden in this template?" (suggest defaults: CIT→Cloud & IT, SKU codes→service names)
- "Are there any product/brand names that should NOT appear because they belong to a different offering?" (DO NOT assume -- ask. e.g., M365 is forbidden in a 1EDGE deck, but perfectly valid in an EUP deck)
- "Should the filler skill auto-fix these or just block and report?"

**3. Structural constraints**:
- "The BC has 7 risks. The template risk heat map has 4 slots. Expand to 7 or summarize to 4?"
- "The BC has 6 segments but the template market table has 5 rows. How to handle?"
- "The SKU breakdown has N services. Does this match the template table rows?"
- For each mismatch: decide expand template, truncate data, or flag for user.

**4. Field formatting**:
- "Max characters per field type?" (suggest: title=60, body=200, table cell=80, bullet=150)
- "Number format?" (suggest: $X.XM for millions, $X,XXXK for thousands, X.X% for percentages)
- "How to handle bullet lists?" (suggest: `\n`-separated within a single field)

**5. Cross-slide consistency**:
- "Which values must be identical across slides?" (suggest: Revenue Y1, fleet/site count, target margin)
- "How strict? Block on mismatch, or warn and continue?"

**6. Data completeness**:
- "If a markdown section is empty, what should the filler skill do?" (suggest: leave {{TAG}} visible so QA catches it, vs. insert placeholder text like "TBD")
- "Minimum fill rate before generation proceeds?" (suggest: 90% of tags must have values)

All decisions are recorded in `filler_spec_{type}.md` under a "Guardrails" section. These become the enforceable rules for the filler skill.

**GATE**: User approves the mapping, filler spec, AND guardrails before proceeding.

---

## STEP 8: Build/Update the Filler Skill

Based on the filler spec, update the corresponding skill:
- BC templates -> update `.claude/skills/bc-to-pptx/SKILL.md`
- BS templates -> create `.claude/skills/bs-to-pptx/SKILL.md`
- OS templates -> create `.claude/skills/os-to-pptx/SKILL.md`

The filler skill MUST reference:
- The `semantic_mapping.yaml` (what tags exist)
- The `filler_spec_{type}.md` (how to fill them)
- The guardrails (what NOT to do)

Ask: "Here is the filler skill spec. Does this capture how data flows from markdown to PPTX?"

**GATE**: User approves.

---

## STEP 9: Extract Data (per offering, using the filler skill)

This step is performed by the filler skill (e.g., `/bc-to-pptx`), not by `/pptx-template`.
The filler skill:
1. Reads the BC/BS/OS markdown
2. For fixed-count tags: extracts directly
3. For iterative tags: counts rows in markdown tables, expands pattern, extracts each
4. For conditional tags: checks if markdown section exists
5. Validates: no CIT, no SKU codes, no M365, cross-slide consistency
6. Reports: "X of Y tags filled. Z empty. W iterative patterns expanded."

---

## STEP 10: Generate + QA (reuses existing Worker -> QA pattern)

This step reuses the existing pipeline -- no duplication:

```
/bc-to-pptx (worker, already exists)
    | Extract data (STEP 9) -> validate -> generate_pptx.py
    | Render slides -> launch QA swarm
/qa-pptx (QA, already exists)
    | Returns: APPROVED / ISSUES FOUND / CLARIFICATION
    |
ISSUES -> Fix slide_data -> regenerate -> re-QA (max 2 iterations)
APPROVED -> Ask user to open in PowerPoint -> GATE -> Done
```

| Concern | Existing Tool | NOT duplicated |
|---------|--------------|----------------|
| Slide visual QA | `/qa-pptx` | NOT in /pptx-template |
| Error recovery | `/qa-improve Mode 1` | NOT in /pptx-template |
| Data extraction | filler skill (STEP 8) | NOT in /qa-pptx |
| Data validation | `validate_pptx_data.py` | NOT in filler skill |
| PPTX generation | `generate_pptx.py` | NOT duplicated anywhere |
| Template prep | `/pptx-template` (this skill) | NOT in filler skills |

---

## Checkpoints and Recovery

| Checkpoint | Created At | Purpose |
|-----------|------------|---------|
| `_int_ai/checkpoint_00_original.pptx` | STEP 0 | Pristine copy of input |
| `_int_ai/checkpoint_03_structured.pptx` | STEP 3 | After structural changes |
| `_int_ai/checkpoint_06_with_placeholders.pptx` | STEP 6 | Final template |

If any step fails, restore the previous checkpoint and retry.

---

## Contract

**Deliverables**: Semantic PPTX template with {{TAG}} placeholders, semantic_mapping.yaml, filler_spec_{type}.md, template PNGs
**Validation**: none (interactive gated builder, user approves at each step)
**Acceptance Criteria**:
- All tags have description + suggestion + max_chars in semantic_mapping.yaml
- Template PNGs generated and validated (no mixed naming)
- SmartArt triple-file rule followed (slide + data + drawing)
- No orphan tags (tags in YAML but absent from template)
- meta.total_tags matches unique tag count in template PPTX
**Escalation Triggers**:
- PPTX fails python-pptx open test → restore checkpoint, ask user
- Orphan tag ratio > 10% → stop, reconcile YAML against template
**Max Rework Cycles**: 2

## Output Files

When complete, the skill produces:
1. **Template PPTX** -- the .pptx with `{{TAG}}` placeholders
2. **_int_ai/element_audit.json** -- full element inventory
3. **_int_ai/classification.json** -- FIXED/DATA classification
4. **semantic_mapping.yaml** -- tag-to-slide contract
5. **filler_spec_{type}.md** -- how to fill the template

---

## Update Mode: `/pptx-template --update path/to/template.pptx`

For maintaining an EXISTING template after the user makes changes in PowerPoint.

### Argument Parsing

When invoked with `--update`:
1. Read the template PPTX (the modified version the user just saved)
2. Read the last checkpoint (`_int_ai/checkpoint_06_with_placeholders.pptx`) as the baseline
3. Read the associated markdown file (from semantic_mapping.yaml or ask user)
4. Compare: detect added slides, removed slides, modified content

### When User ADDS a Slide

1. Detect new slide(s) by comparing current template vs checkpoint
2. Check if the new slide matches a protected category (branding, TOC, separator, closing). If so, add it to `protected_slides` in semantic_mapping.yaml and report: "New slide 'X' classified as protected (reason). No tags will be created. OK?"
3. For each new NON-protected slide:
   - Read its content (titles, text boxes, tables)
   - Read the associated markdown file (BC.md, BS.md, OS.md)
   - Search markdown for sections/data that could match the new slide content
   - Present mapping suggestion to user:
     ```
     NEW SLIDE: "Marketing Intelligence" (pos 15)

     Markdown matches found in LEAN_BUSINESS_CASE.md:
       §3.2 Key Market Drivers → could map to slide body
       §3.4 Competitive Landscape → could map to table

     Suggested tags:
       {{MARKET_DRIVERS}} → §3.2 bullet list
       {{COMP_LANDSCAPE}} → §3.4 table data

     Accept these? [Y/n/edit]
     ```
3. User approves/edits the tag suggestions
4. Insert approved `{{TAGS}}` into the template with lxml
5. Add entries to slide_data with extracted values from markdown
6. Update semantic_mapping.yaml
7. Save new checkpoint

### When User REMOVES a Slide

1. Detect removed slide(s) by comparing vs checkpoint
2. Identify ORPHANED tags: tags in slide_data that no longer appear anywhere in the template
3. Present cleanup report:
   ```
   REMOVED SLIDE: "Marketing Intelligence" (was pos 15)

   Orphaned tags (in slide_data but no longer in template):
     {{MARKET_DRIVERS}} → value: "CAPEX to OPEX shift..."
     {{COMP_LANDSCAPE}} → value: "Speedcast, Navarino..."

   Remove from slide_data? [Y/n]
   ```
4. User approves → remove orphaned entries from slide_data and semantic_mapping.yaml
5. Save new checkpoint

### When User MODIFIES a Slide

1. Detect changed text elements by comparing vs checkpoint
2. If new text was added that needs a tag → suggest it (with markdown lookup)
3. If existing tags were removed from the slide → identify as orphans
4. If text around tags changed → no action needed (tags are still in place)

### Core Principle: Tags Are Demand-Driven

- Tags exist ONLY because the template needs them
- The markdown file is the SOURCE of values, not the source of tags
- When a slide needs variable data → skill proposes tags by searching the markdown
- When a slide is removed → skill cleans up orphaned tags
- NEVER create tags "just in case" — only when the template demands it
- **Protected slides are invisible** — never audit, classify, tag, or suggest tags for them
- The `protected_slides` list in semantic_mapping.yaml is the authority on which slides are off-limits
