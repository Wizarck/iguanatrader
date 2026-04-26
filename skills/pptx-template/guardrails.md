# PPTX Template Guardrails

These rules are ABSOLUTE. They override all other instructions, heuristics, or shortcuts.

## Duplicate Detection (ABSOLUTE -- STEP 2-3)

After structural changes (slide removal/reorder), BEFORE proceeding to STEP 4:
1. Render ALL slides to PNGs
2. Scan for slides with identical or near-identical titles
3. For each pair with the same title, **visually compare the PNGs** -- read both images
4. If two slides are visually identical or near-identical (same layout, same data, only minor text differences):
   - **STOP and ASK the user**: "Slides N and M look like duplicates. Should I remove one? Which one to keep?"
   - Do NOT silently keep both or silently remove one
   - The user decides which version to keep (e.g., the one with updated pricing)
5. Only proceed to STEP 4 after confirming zero visual duplicates

This rule exists because the source PPTX may contain iterative versions of the same slide (e.g., v1 pricing and v2 pricing) that the alignment matrix classified as separate slides but are actually the same content with minor updates.

## USER GATES (ABSOLUTE -- never skip)

Every STEP with a USER GATE in the SKILL.md MUST stop and wait for user approval before proceeding. Specifically:
- **STEP 5 Classification**: present EVERY classified slide to the user with PNG + tag table. Do NOT proceed to STEP 6 until ALL slides are reviewed and approved. Agent output is a DRAFT -- the user is the approver.
- **STEP 3 Structure**: user must confirm in PowerPoint before audit
- **STEP 6 Template**: user must verify template + mapping before filler spec
- **STEP 7 Filler spec**: user must approve rules before pipeline updates

If agents complete classification in background, their output MUST be presented to the user slide-by-slide before any injection happens. Never treat agent output as approved. The user decides what is FIXED, what is DATA, and what each tag name should be.

## Tool Ordering (ABSOLUTE)

- python-pptx FIRST (structure) -> save -> lxml SECOND (content)
- NEVER the reverse. NEVER interleaved.
- After STEP 3 completes, python-pptx must NEVER be used on that file again

## XML Safety

- ONLY lxml for text modifications (never regex on raw XML)
- ONLY replace `<a:t>` / `<dgm:t>` text content -- never modify tag attributes or structure
- NEVER copy XML files between PPTX files
- ALWAYS validate XML after modification using `lxml.etree.fromstring()`
- lxml handles XML escaping automatically -- do NOT manually escape `&`, `<`, `>` in text content passed to lxml

## Indices

- Positional indices are ONLY valid within the SAME file version
- ALWAYS re-audit (STEP 4) after any structural change (STEP 3)
- NEVER use indices from version A on version B
- The `element_audit.json` from STEP 4 is the single source of truth

## SmartArt (ABSOLUTE -- template AND generation)

- SmartArt has 3 files: `data{N}.xml` + `drawing{N}.xml` + `slide{N}.xml`
- MUST edit ALL THREE when changing content
- Use text-match (not index) for drawing and slide files because their element order differs from data files
- **Generation script MUST process all 3 file types**: `slides/slide*.xml` + `diagrams/data*.xml` + `diagrams/drawing*.xml`. A script that only processes `slides/` is a BUG.
- **Post-generation verification**: grep for `{{` in ALL three file types. If unreplaced tags remain only in `drawing*.xml`, the triple-file rule was violated.
- **Why this is absolute**: SmartArt slides render from drawing XML, NOT from data XML. If you only replace in data, PowerPoint shows the OLD drawing content until the user manually opens and refreshes the diagram. The generation script cannot rely on PowerPoint auto-refresh.

## Protected Slides (SKIP ENTIRELY)

Some slides are 100% static and must NEVER be audited, classified, or tagged. They are invisible to STEPs 4-6 and to `--update` mode.

Protected slide categories:
- **Branding/Framework**: Corporate imagery, methodology diagrams, strategy visuals (e.g., "Intelligent Innovation", "GTM Offering Creation Blueprint Framework")
- **TOC**: Table of contents -- structure is fixed, content does not vary per offering
- **Section Separators**: Kill-gate dividers ("Detailed Business Case", "Strategic Context & Portfolio Fit", "Commercial Model", "Financial Model", "Execution Readiness", "Risk Assessment & Governance")
- **Thank You / Closing**: Static closing slides

Each template type defines its protected list in `semantic_mapping.yaml` under a `protected_slides` key:

```yaml
protected_slides:
  - slide: 2
    title: "Lean Business Case Structure"
    reason: "TOC -- static structure"
  - slide: 3
    title: "Intelligent Innovation"
    reason: "Corporate branding -- never varies"
  - slide: 4
    title: "GTM Offering Creation Blueprint Framework"
    reason: "Framework diagram -- never varies"
  - slide: 9
    title: "Thank You"
    reason: "Closing slide -- static"
  # ... all separator slides
```

Rules:
- In CREATE mode: skip protected slides in STEP 4 audit, STEP 5 classification, STEP 6 injection
- In UPDATE mode: if a new slide is detected adjacent to a protected slide, do NOT suggest tags for the protected one
- If user explicitly asks to tag a protected slide, warn them and require double confirmation
- The filler skill (`/bc-to-pptx`) must also skip protected slides during generation

## Dual-Source Classification (ABSOLUTE -- STEP 5)

Classification agents MUST receive TWO sources per slide:

1. **XML audit (`deep_audit.json`)**: exact `<a:t>` texts from slide XML + diagram XML. This is the element source -- every classified item maps 1:1 to an actual XML element.
2. **Slide PNG**: rendered image showing visual layout, positioning, hierarchy, reading order. This is the context source -- tells the agent WHERE each element sits and WHAT PURPOSE it serves.

**Rules**:
- Agent classifies EACH `<a:t>` element from the XML audit individually (not visual blocks from PNG)
- PNG is used ONLY to understand purpose, position, and visual context
- Every classified DATA element MUST have its `text` field matching an exact XML `<a:t>` text from the audit
- The `file` field MUST record which XML file contains the element (slide vs diagram)
- Injection is then exact-match: `t.text.strip() == classified_text.strip()` → 100% accuracy

**Why this rule exists**: PNG-only classification produced text BLOCKS that didn't match individual XML elements. Example: agent saw "M365 breaks in satellite sites / Unsustainable bandwidth costs / Compliance exposure" as ONE block, but XML has 3 separate `<a:t>` elements. Result: 54% injection rate, unusable template.

**Never do**: classify from PNG alone, describe content as visual blocks, concatenate texts that are separate XML elements.

## Classification

### Always FIXED (never tag)
- Slide titles and section headings ("Business Model Canvas", "Case Background")
- Cell/card/column labels ("Key Partners", "Revenue Streams", "Adoption Targets")
- Table column/row headers ("Year 1", "Revenue", "Cost", "Margin")
- Section numbers, circled emoji numbers, numbering badges
- Metric labels ("TAM", "SAM", "SOM", "ARPU", "ARR")
- Decorative symbols and punctuation used as layout ("*", ":", "->", bullet chars)
- Sub-headers within dashboard/summary slides ("Sales Productivity", "Technical", "TCO")

### Always DATA (always tag)
- Financial figures ($X.XM, X%, X sites, X years)
- Descriptions and body text (value propositions, problem statements, risk text)
- Segment names and counts
- Names (offering name, iteration name, partner names, platform names)
- Dates and year ranges (including years inside headers like "Goals (2026-2028)")
- Status indicators (Go/No-Go, Green/Yellow/Red)

### Auto-Fields (SKIP entirely)
- Elements with parent tag `<a:fld>` are PowerPoint auto-fields (slide number, date, footer)
- These are managed by PowerPoint itself -- exclude them from the audit, classification, and injection
- If an auto-field appears in element_audit.json, remove it before classification

### DATA Patterns: Series vs Cluster
Two types of variable data groups:

**DATA SERIES** (`{n}`): A repeating list where each item has the same structure, and N varies per offering.
- Pattern: `{{PREFIX_{n}}}` or `{{PREFIX_{n}_FIELD}}`
- Examples: `{{CANVAS_PARTNER_{n}}}`, `{{PROBLEM_PAIN_{n}_TITLE}}` + `{{PROBLEM_PAIN_{n}_DESC}}`
- Rule: ANY list of bullets, items, risks, segments, etc. MUST use series -- never assume a fixed count
- The filler skill determines N by reading the BC

**DATA CLUSTER**: A fixed set of named fields that always appear together on a slide. The field names are known and constant, but the values change per offering.
- Pattern: `{{PREFIX_FIELD1}}`, `{{PREFIX_FIELD2}}`, etc.
- Examples: `{{EXEC_MARGIN}}`, `{{EXEC_ARPU}}`, `{{EXEC_REVENUE_3Y}}` (these 3 always exist on the dashboard)
- Rule: use clusters for single-value fields that are structurally guaranteed by the BC template

**DATA CONDITIONAL**: A series or cluster that only appears if a specific BC section/concept exists.
- Mark with "(conditional)" in the classification table
- The filler skill checks the BC for the triggering concept before populating
- If absent, the elements are left empty or hidden
- Examples: pricing tiers (only if BC defines tiers), capability matrix (only if BC has POT), migration paths (only if portfolio evolution)

**How to decide**: If you can answer "how many?" with a fixed number regardless of offering, it is a cluster. If the count depends on the BC content, it is a series. If the entire group may not exist at all for some offerings, it is conditional.

### Sub-label + Bullets Pattern
When a panel or cell contains one or more **bold sub-labels** (category headers within a panel) each followed by N bullet points, classify them as a label + series group:

**Pattern**:
```
{{PREFIX_SUBLABEL_LABEL}}   ← the sub-label text (DATA tag if varies per offering, FIXED if generic)
{{PREFIX_SUBLABEL_{n}}}     ← the bullets beneath it (always series, even if only 1 bullet today)
```
Where PREFIX encodes the panel/slide context and SUBLABEL is replaced by the actual sub-label identity (e.g., MONITORING, PROVISIONING, REQUIRED).

**Examples**:
- "Monitoring Layer:" (FIXED) + 1 bullet → FIXED label + `{{ITSM_MONITORING_{n}}}` n=1
- "Provisioning Workflow:" (FIXED) + 1 bullet → FIXED label + `{{ITSM_PROVISIONING_{n}}}` n=1
- "A. Renewal & Hardware-Led Motion" (FIXED) + 3 bullets → FIXED label + `{{ENTRY_TRIGGER_A_{n}}}`
- "Required:" (FIXED) + 4 bullets → FIXED label + `{{ENABLE_REQUIRED_{n}}}`

**Rules**:
- Always use `{n}` series for bullets, even when the current slide has only 1 bullet — this avoids template changes if a second bullet is added later
- FIXED sub-labels: generic enough to reuse across offerings (e.g., "Required:", "RACI Model:", "Escalation Model:") — leave the label text as-is
- DATA sub-labels: vary per offering — tag the label itself as `{{PREFIX_SUBLABEL_LABEL}}` and the bullets as `{{PREFIX_SUBLABEL_{n}}}`
- Sub-label with zero bullets (pure divider): classify as plain FIXED label — this pattern does not apply
- **Double-variable case** (N variable sub-labels, each with M variable bullets): do NOT attempt double-index series (`{{PREFIX_{n}_BULLET_{m}}}`). Escalate to user — this requires explicit structural decision before proceeding
- This pattern applies to sub-labels **within a panel or cell**, not to slide-level section headers (which are always FIXED per the "Always FIXED" list above)

### Shared Metadata Tags
- Some tags appear across multiple slides (titles, dashboards, canvas). These use a common prefix:
  - `{{ITERATION_NUM}}` -- iteration number (1, 2, 3), used in canvas title, dashboard title, scope
  - `{{ITERATION_MATURITY}}` -- maturity level ("Good", "Better", "Best"), same locations
  - `{{TITLE_OFFERING}}` -- offering name, used in cover + anywhere the offering is referenced
  - `{{TITLE_ITERATION}}` -- descriptive iteration name (e.g., "Customer VM Hosting"), cover slide
  - `{{TITLE_PILLAR}}` -- pillar context line, cover slide
- When a title contains "Iteration 1 'Good'", split into FIXED text + `{{ITERATION_NUM}}` + `{{ITERATION_MATURITY}}`
- When a header contains year ranges like "(2026-2028)", the years are DATA tags

### Mixed Elements
- Some text elements mix FIXED and DATA in the same string (e.g., "Iteration 1" where "Iteration " is fixed and "1" is data)
- In these cases, the entire element gets a composite tag or the element is split if the XML structure allows it
- Preferred: if the XML has separate `<a:r>` runs for each part, tag only the DATA run
- Fallback: if it is one run, use a single tag for the variable portion and document the fixed prefix in the mapping

### Double-Variable Tables ({n} x {m})
Some tables have a variable number of ROWS (BU entries) AND a variable number of COLUMNS (capabilities). This produces a double-index pattern:

- **Column headers**: `{{PREFIX_CAP_{m}_HEADER}}` (m = 1..M, one per capability column)
- **Body cells**: `{{PREFIX_{n}_CAP_{m}}}` (n = row, m = capability column)
- **Fixed-position final column** (e.g., Risk): `{{PREFIX_{n}_RISK}}` -- uses only `{n}`, NEVER `{m}`, because this column always exists regardless of M

This pattern applies to the 4 capability assessment slides, each with its own prefix:
- `PEOPLE_`, `PROCESS_`, `PLATFORM_`, `PARTNER_`

**Rules**:
- M (number of capability columns) is fixed in the template at STEP 6. If a different LBC needs a different M, the table structure is adjusted at that time.
- The filler iterates m first (columns), then n (rows) when extracting data from the BC capability tables.
- The final column (Risk, Status, etc.) is structurally guaranteed -- it is NOT a capability column, so it uses single-index `{n}` only.
- Object-grouped naming applies: `{n}` groups by row (BU), `{m}` groups by column (capability). This keeps cross-dimensional alignment explicit.

**Example** (PEOPLE slide, M=3 capabilities, N=4 BUs):
```
Headers:  {{PEOPLE_CAP_1_HEADER}}  {{PEOPLE_CAP_2_HEADER}}  {{PEOPLE_CAP_3_HEADER}}  (Risk is FIXED label)
Row 1:    {{PEOPLE_1_CAP_1}}       {{PEOPLE_1_CAP_2}}       {{PEOPLE_1_CAP_3}}       {{PEOPLE_1_RISK}}
Row 2:    {{PEOPLE_2_CAP_1}}       {{PEOPLE_2_CAP_2}}       {{PEOPLE_2_CAP_3}}       {{PEOPLE_2_RISK}}
Row 3:    {{PEOPLE_3_CAP_1}}       {{PEOPLE_3_CAP_2}}       {{PEOPLE_3_CAP_3}}       {{PEOPLE_3_RISK}}
Row 4:    {{PEOPLE_4_CAP_1}}       {{PEOPLE_4_CAP_2}}       {{PEOPLE_4_CAP_3}}       {{PEOPLE_4_RISK}}
```

### Split-Run Words (PowerPoint formatting artifacts)
- PowerPoint sometimes splits a single word across multiple `<a:r>` runs due to formatting changes mid-word (e.g., bold "Itera" + normal "tion 1", or "Iter" + "ation" due to spell-check history)
- These are NOT separate elements — they are fragments of one word broken by formatting boundaries
- **Rule**: place the `{{TAG}}` in the FIRST run of the split word. Clear the text of all subsequent runs that belong to the same word. The injector writes the full replacement value to the first run; the empty subsequent runs are invisible.
- Detection: during STEP 5 audit, look for adjacent `<a:r>` elements where concatenation forms a recognizable word or phrase. Flag these as split-run candidates.
- Do NOT create separate tags for word fragments — this produces broken tags like `{{ITER_LABEL_PART1}}` + `{{ITER_LABEL_PART2}}`

### Label Genericization
- FIXED labels must be generic enough to work for ANY offering (BC, BS, OS)
- During STEP 5, for every FIXED label that contains offering-specific or narrow language, propose a generic alternative
- Slide titles are excluded from genericization (they are structural)
- Examples of labels that need genericization:
  - "Into standardized managed pathways:" -> "Migration targets:"
  - "M365 market share" -> "Platform market share"
  - "Productivity Backup (Veeam for M365)" -> should be DATA, not FIXED
- Generic labels are applied in STEP 6 alongside placeholder injection (lxml text replacement on FIXED elements)

### Structural Element Detection (ABSOLUTE -- STEP 5)

Before assigning any tag, identify FIXED structural elements by checking the ACTUAL `<a:t>` text from the audit JSON (never from memory or slide description):

**Heuristics -- treat as FIXED unless there is explicit reason to tag:**
- Text starts with an emoji (🧱 🔐 🚨 ① ② ③ ✅ etc.) → panel header → FIXED
- Text ends with `:` → sub-label (category divider within a panel) → FIXED
- Text is a single structural word ("Marlink", "NOC", "Otherwise:", "Trigger:") → FIXED inline label

**Panel boundary verification (multi-panel SmartArt):**
- List ALL idx values in the panel with their exact text BEFORE assigning any tags
- Identify: header idx (emoji → FIXED), sub-label idx (ends in `:` → FIXED), then count content items starting from the NEXT idx
- Off-by-one errors come from assuming content starts at header+1 when a sub-label sits at header+1 and content starts at header+2

**Source rule (ABSOLUTE):**
- ALWAYS classify from the `element_audit.json` / `deep_audit.json` text at each idx
- NEVER classify from memory, slide screenshots alone, or descriptions of what a slide "should" contain
- The audit JSON has the actual text -- reading it takes 2 minutes per slide and prevents 90% of classification errors

**Coverage check:**
- After classifying a slide, verify: `max(classified_idx)` ≈ total element count for that slide
- Any gap of ≥2 consecutive unclassified idx is a warning — check the audit JSON to confirm they are FIXED (not missed DATA)

### Visual Position vs Document Order (ABSOLUTE -- STEP 5)

For slides with **free-floating shapes** (dashboard cards, milestone timelines, summary boxes positioned by x,y coordinates), document order (shape insertion sequence) does NOT match visual top-to-bottom, left-to-right order.

**Detection**: when a slide contains multiple shapes of the same type (e.g., 6 milestone boxes, 4 KPI cards), their visual positions MUST be verified before numbering tags sequentially.

**Verification procedure** (run before numbering any multi-shape object tags):
```python
import zipfile
from lxml import etree
EMU_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PML_NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'
SPPR_NS = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'

with zipfile.ZipFile(pptx_path) as z:
    xml = z.read(f'ppt/slides/slide{N}.xml')
tree = etree.fromstring(xml)
for sp in tree.findall('.//{http://schemas.openxmlformats.org/presentationml/2006/main}sp'):
    off = sp.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}off')
    txBody = sp.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}txBody')
    if off is not None and txBody is not None:
        first_t = txBody.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}t')
        x, y = int(off.get('x', 0)), int(off.get('y', 0))
        print(f"y={y:>12} x={x:>12}  text='{(first_t.text or '')[:40]}'")
```
Sort output by `y` (then `x` for same row) to get true visual reading order. Number tags by this order, not by document order.

**Rule**: milestone, KPI card, and summary box tags MUST use visual-position numbering (top→bottom, left→right). Tags like `{{SUMMARY_MS_1_DATE}}` must refer to the top slot visually, not the first shape in document XML.

### Default Behavior
- When in doubt, classify as FIXED (safer -- user can flip to DATA)
- ALWAYS ask user to verify classification before proceeding
- Present in batches of ~3 slides for manageable review

## Placeholder Naming

- UPPER_SNAKE_CASE: `{{CANVAS_UVP_{n}}}`
- Prefix with slide context for uniqueness
- Series patterns use `{n}`: `{{CANVAS_COST_{n}}}`, `{{EXEC_MILESTONE_{n}_DATE}}`
- Compound series use `{n}` + suffix: `{{EXEC_MILESTONE_{n}_DATE}}`, `{{EXEC_MILESTONE_{n}_DESC}}`
- Category-grouped series: `{{EXEC_RISK_{category}_{n}}}` or `{{EXEC_ASSUMPTION_{category}_{n}}}`
- Self-documenting names -- anyone reading the template should understand what goes there
- **Object-grouped tags (ABSOLUTE)**: When a slide has N repetitions of a multi-field object (iterations, risk cards, milestones, comparison columns, etc.), tags MUST be structured as `{{OBJECT_{n}_FIELD}}` — index groups by object, not by field. This ensures the filler writes complete objects (one per repetition), making cross-field misalignment impossible.
  - CORRECT: `{{ITER_1_LABEL}}`, `{{ITER_1_YEAR}}`, `{{ITER_1_Q}}` / `{{ITER_2_LABEL}}`, `{{ITER_2_YEAR}}`, `{{ITER_2_Q}}`
  - WRONG: `{{ITER_LABEL_1}}`, `{{ITER_LABEL_2}}` / `{{ITER_YEAR_1}}`, `{{ITER_YEAR_2}}` (parallel lists — fragile implicit dependency, misalignment possible)
  - Exception: single-field homogeneous lists (bullet points with only one field each) may use `{{FIELD_{n}}}` series

## Injection Engine Rules (STEP 6)

The injection script MUST implement these mechanisms:

### FIXED Set
- MUST be a Python list (never parsed from free text -- double-space splitting breaks multi-word items)
- Includes BOTH original and genericized forms of every label
- Updated after every label genericization decision
- **Short text classification rules** (len <= 2):
  - Has digit or `$`: **DATA** always ("7", "90", "$0" are table values)
  - Pure symbols/punctuation (not alpha): **FIXED** ("*", ":", "->")
  - Pure letters: check FIXED set, otherwise DATA (covers edge cases)
  - **Split-word merging**: if a short letter element is followed by a run starting lowercase, they form one word split by formatting (e.g., bold "F" + normal "or remote..." = "For remote..."). The engine MUST merge these into a single element BEFORE classification. Do not create separate tags for word fragments.
  - **Label-tag spacing**: when a DATA tag immediately follows a FIXED label in the same paragraph (no space between runs), insert a leading space in the tag: `" {{TAG}}"` not `"{{TAG}}"`. Prevents visual concatenation like `Delivery Model{{TAG}}`.
  - **Cluster vs series in cell_map**: cell_map entries can be marked as cluster (single value, no `_N` suffix) vs series (incrementing `_N`). Headers and single-value fields use cluster: `{{CANVAS_HEADER}}`. Multi-item cells use series: `{{CANVAS_COST_1}}`, `{{CANVAS_COST_2}}`.
  - **Dynamic milestone detection**: shapes whose first text matches a date pattern (`Q[1-4] YYYY`, `H[1-2] YYYY`, `YYYY`) are automatically grouped as `EXEC_MS{n}` -- no hardcoded dates in cell_map. This ensures any offering with different milestone dates works automatically.
  - Financial figures ($X,XXX, X%, ~X%) are ALWAYS DATA regardless of length
  - WRONG: `re.match(r'^\d{1,3}$', text)` matches "342" (RGU count) -- BUG
  - WRONG: `len(t) <= 2` without digit check -- catches "90", "$0" as FIXED -- BUG
  - WRONG: blanket `not t.isalpha()` -- catches "F" (split word fragment) as FIXED -- BUG

### Four Assignment Modes (per slide)
Every slide config has four mechanisms:

1. **pre_fields**: positional names for the first N DATA elements (e.g., `["TITLE_OFFERING", "TITLE_ITERATION"]`)
2. **groups**: `{label_text: tag_prefix}` -- delimiter-based grouping for sequential content
3. **table_cols**: `["NAME", "REVENUE", "COST", "MARGIN"]` -- column-cycling for table rows
4. **shape_aware**: for slides where each `<p:sp>` shape is a self-contained cell (e.g., Business Model Canvas). In this mode:
   - Each shape is processed independently
   - The first text element in the shape determines the semantic group (via a `cell_map`)
   - Remaining elements in the shape are tagged with that group prefix
   - This prevents cross-cell contamination when XML element order differs from visual layout
   - IMPORTANT: `<txBody>` may use `p:` namespace (presentationml) not `a:` (drawingml) -- check BOTH

Every slide MUST have a config. NO slide may use a bare default prefix without groups -- that produces generic sequential tags.

### Classification & Enrichment Agent Batch Size
- **Maximum 10 slides per agent** (classification or enrichment)
- This provides headroom for large source documents and dense slides
- Measured: ~8K tokens/slide average, but dense slides (Canvas, Dashboard, Assumptions) can reach 12K+
- With 100K input budget, 10 slides keeps a comfortable margin for system prompt + output

### NEW Slides (created in STEP 3)
- New slides added in STEP 3 arrive with only a title placeholder
- **Title color**: separators (dark bg) use white text (#FFFFFF), content slides (light bg) use navy (#1B2A4A). NEVER set all new slides to the same color -- check the layout background first.
- During STEP 6, the engine must add text boxes with predefined `{{TAGS}}` to these slides so the filler has elements to replace
- The tags for new slides come from the classification (STEP 5) -- if no content exists yet, create a single body text box with the primary tag pattern (e.g., `{{DECISION_VERDICT}}` for Executive Decision)
- **QA check**: render ALL new slides and verify titles are visible (not white-on-white)

### Table Layout Maps (MANDATORY for positional tables)
Tables with sequential positional tags (CONSOL_CELL_1..N, FORECAST_W1_SKU_1..N, CAP_CELL_1..N) MUST have a **table_layout** section in `semantic_mapping.yaml` that documents:
- Number of rows and columns
- Which cells are FIXED headers (not tags)
- Which cells are FIXED labels ("Wave 1", "TOTAL")
- The meaning of each tag by position: `CONSOL_CELL_5 = row2_col0 = segment_name`

Without a layout map, sequential tags are meaningless -- the filler cannot know that CONSOL_CELL_53 is "Wave 1 subtotal RGUs" vs "row 6 col 1". The layout map is the contract between the template builder and the filler skill.

**Critical table pitfalls discovered:**
- **Tag offset**: Tags in tables are often shifted by one or more cell positions from what their name suggests (e.g., CTS_SEG_N_REVENUE is in the visual "Segment" column, not "Revenue"). This happens because the STEP 6 injection engine assigned tags sequentially through `<a:t>` elements, which may not align with visual columns due to merged cells, spanning, or XML element order. **RULE**: During STEP 1 (extraction) and Step 1.5 (enrichment), ALWAYS run an XML audit of the template to build the actual cell-to-tag mapping. NEVER assume tag names match visual column headers. The layout map in semantic_mapping.yaml is the only source of truth.
- **Multi-tag cells**: Some cells contain multiple `<a:r>` runs with different tags (e.g., R2C0 has SEG_8_COST + SEG_8_CONTRIBUTION + SEG_8_MARGIN). If only the first tag has content and the rest are empty, they concatenate as "value1value2". Fix: audit for multi-run cells and document them in the layout map.
- **Shapes outside tables**: Slides with tables may also have shapes (subtitle, detail line) that are tagged separately (e.g., FORECAST_W1_SKU_34 is a subtitle shape, not a table cell). The layout map must distinguish table tags from shape tags.
- **Visual QA after every table fill**: After filling any positional table, ALWAYS render the slide and verify visually before proceeding. Table cell misalignment is invisible to postflight (it passes XML validation).

**Template builder** (STEP 5-6): generates the layout map during classification.
**Filler skill** (Step 1): reads the layout map to know which BC data goes in which cell position.
**Enrichment** (Step 1.5): uses the layout map to verify cell-content alignment.

Format in semantic_mapping.yaml:
```yaml
slide_33:
  table_layout:
    rows: 11
    cols: 12
    fixed_cells:
      row_0: "Year headers (FIXED)"
      row_1_col_0: "Segment (FIXED)"
      row_6_col_0: "Wave 1 (FIXED)"
      row_9_col_0: "Wave 2 (FIXED)"
      row_10_col_0: "TOTAL (FIXED)"
    cell_map:
      CONSOL_CELL_1: {row: 1, col: 1, meaning: "RGUs sub-header"}
      CONSOL_CELL_5: {row: 2, col: 0, meaning: "Segment 1 name"}
      CONSOL_CELL_6: {row: 2, col: 1, meaning: "Segment 1 RGUs"}
      # ... etc
```

### No Generic Tags Rule
- After injection, scan ALL tags in the output file
- Any tag matching `{{PREFIX_\d+}}` where PREFIX is a bare slide-level default (no semantic group) is a BUG
- Acceptable: `{{CANVAS_PARTNER_1}}`, `{{RISK_1_ROOT_CAUSE_1}}`, `{{CTS_SEG_1_NAME}}`
- Unacceptable: `{{CANVAS_1}}`, `{{S39_1}}`, `{{REVQ_1}}`
- Exception: truly positional tables (CAP_CELL, CONSOL_CELL, ROAD_ITEM) where column-cycling is impractical due to complex layout -- these MUST be documented in semantic_mapping.yaml with column order

### Per-Tag Character Limits (max_chars)
Tags can have a `max_chars` field in the YAML that overrides the global max from filler_spec S4:
```yaml
CANVAS_PROBLEM_{n}:
  type: series
  description: Problem statement bullet
  suggestion: §4 Customer Problem
  max_chars: 35
```
- When present, `max_chars` overrides the global limit for that tag
- The filler MUST respect per-tag limits — rephrase for brevity, never truncate mid-word
- `/qa-pptx` checks for visual overflow against these limits
- Default guidelines when `max_chars` is not set:
  - SmartArt cells: 40-80 chars
  - Table cells: 20-40 chars
  - Full-width paragraphs: up to 200 chars
  - Bullet items: 60-100 chars
  - Dashboard metrics: 30-50 chars
- Phase A.5 (Visual Enrichment) populates `max_chars` for every tag based on measured element widths

### semantic_mapping.yaml Generation (mandatory)
- STEP 6 MUST generate `semantic_mapping.yaml` as part of the same step -- not as a separate step or afterthought
- This is the **authoritative** mapping file. If older versions exist (v1, v2), overwrite them.
- The tag list MUST come from scanning the injected template (checkpoint_06), NOT from the classification output. Classification metadata enriches the tag list, but the list itself = template inventory. See Post-Injection Audit rule #5.
- The YAML documents every tag: name, type, description, suggestion, example, max_chars, tag_positions
- Per slide: slide_objective, slide_analysis, slide_notes, layout_type
- Per table slide: table_layout with cell_map
- Protected slides, prototype (sequential) slides, and the complete tag inventory are all in this file
- This file is the SINGLE source of truth for fill agents — it must be self-sufficient (no PNG required to understand a slide's layout and tag positions)
- This file is the reference documentation for what was approved during the classification debate

## Post-Injection Audit (MANDATORY -- after STEP 6, blocks GATE)

After injecting tags into the template, run these 4 checks before presenting to user:

1. **Tag count per slide**: count `{{TAG}}` occurrences in each slide XML + its diagram data/drawing files. Compare against classification count. Mismatch = injection bug.
2. **Tag uniqueness per file**: within each XML file, every `{{TAG_PATTERN}}` should appear the expected number of times. If `{{CANVAS_COST_{n}}}` appears 6 times but the slide only has 1 cost cell, the injection duplicated the tag into multiple paragraphs. Fix: keep 1 instance per semantic slot, remove extras.
3. **No split tags**: grep for `{{` that doesn't have a matching `}}` in the same `<a:t>` element. Split tags (tag spanning two `<a:r>` runs) will not be replaced by the generate script. Fix: consolidate runs within the paragraph.
4. **Tag inventory reconciliation**: extract all unique tag patterns from the template PPTX. Compare against the YAML `tags` section. Report orphans in both directions. If the template has tags not in YAML, or YAML defines tags not in the template, the injection was incomplete.

**Block the USER GATE if**: any tag is split across runs, or tag count mismatch exceeds 10%.

5. **YAML source = template inventory (ABSOLUTE)**: The `semantic_mapping.yaml` MUST be generated by scanning the template PPTX for `{{TAG}}` patterns, then enriching each found tag with classification metadata (description, suggestion, max_chars). Classification data for tags NOT found in the template MUST be discarded -- they are phantom tags. The YAML `total_tags` count MUST equal the unique tag count from the template scan. If they differ, the YAML is invalid and MUST be regenerated from the template.

## Generate Script Contract (MANDATORY -- design in Phase A, not Phase B)

The `generate_pptx.py` interface contract MUST be defined during Phase A (alongside the filler spec in STEP 7), not after the first fill attempt. The contract specifies:

1. **Input format**: flat JSON with `TAG_NAME: "value"` for static tags and `PREFIX_N_SUFFIX: "value"` for series
2. **Series handling**: join-based replacement -- all values for a `{n}` pattern joined with `\n` into the first occurrence. NEVER paragraph cloning (causes duplication in SmartArt and multi-paragraph shapes).
3. **Dedup strategy**: track `seen_tags` per XML file. First occurrence of each tag gets the value, subsequent occurrences are emptied. Empty paragraphs are cleaned up.
4. **SmartArt file list**: script processes `slides/slide*.xml` + `diagrams/data*.xml` + `diagrams/drawing*.xml`
5. **Pilot test plan**: before full generation, test on 3 representative slides (1 SmartArt, 1 table, 1 canvas/shapes)

**Why this rule exists**: designing the script reactively (after injection) caused 6 broken iterations before producing a working output. The injection format and the generation consumption format must be aligned from the start.

## Series Tag Fill Strategy (ABSOLUTE -- generation time)

Series tags (`{{TAG_{n}}}`) MUST be filled using **sequential per-occurrence replacement**:
1. Collect all values: `TAG_1`, `TAG_2`, `TAG_3` ... from fill data, sorted by index
2. Each occurrence of `{{TAG_{n}}}` in the XML file gets the NEXT value from the sorted list
3. Occurrence #0 gets value_1, occurrence #1 gets value_2, etc.
4. If values are exhausted, remaining occurrences get empty string
5. Occurrence counters are **per-file** (SmartArt data/drawing/slide get independent counters)
6. Clean up empty `<a:p>` paragraphs left behind
7. Double `{n}` tags (e.g., `INVEST_PHASE_{n}_PEOPLE_{n}`): values flattened in (outer, inner) sorted order

**Static tags**: ALL occurrences get the SAME value. No deduplication — if `{{TITLE_OFFERING}}` appears in 3 `<a:t>` elements, all 3 get the offering name.

**NEVER use join-with-newline** (collapsing all values into first occurrence). This crammed all table data into first row.
**NEVER use paragraph cloning** (copying `<a:p>` elements). This caused 4-6x content duplication.
**NEVER use seen_tags dedup** (emptying subsequent occurrences). This emptied table rows and Canvas cells.

## Verification

- python-pptx open test after EVERY checkpoint
- lxml parse test after EVERY XML modification
- Count `{{` occurrences to verify placeholder count matches classification
- **Post-injection scan for generic tags** (see No Generic Tags Rule above)
- **Visual QA via LibreOffice**: at every checkpoint, render PPTX to PDF via LibreOffice (`soffice --headless --convert-to pdf`), then render ALL pages as PNG (pymupdf) and inspect EVERY slide. Specific checks:
  1. Are section headers (emoji numbered, circled) showing as FIXED text or as tags? → Headers must be FIXED
  2. Are labels concatenated with tags without space? (e.g., "Label{{TAG}}") → Must have space
  3. Are there stray single characters next to tags? (split-word fragments) → Must be merged or removed
  4. Do mixed-content headers show both FIXED prefix and DATA tags? (e.g., "Title - Iteration {{NUM}} '{{MATURITY}}'") → Must be split correctly
  5. Are canvas/dashboard cell contents in the correct cells? (not cross-contaminated) → Verify shape-aware
- **Programmatic QA**: after injection, scan all tag mappings for:
  - Tags whose original text starts with emoji numbers (1️⃣-9️⃣, ①-⑥) → BUG: section header tagged
  - Tags whose original text matches known header patterns → WARN: possible header
  - Tags that contain `{{` in their original text → BUG: double-tagging
- Ask user to open in PowerPoint at every gate (triple validation: programmatic + visual + user)

## Recovery

- Checkpoint before each destructive step (STEPs 0, 3, 6)
- If any step fails -> restore previous checkpoint -> report failure -> retry
- Never proceed past a failed verification

## Notes Slides Cleanup
- During STEP 6, scan ALL notesSlides for forbidden content (M365, SkyFile, etc.) and clear them
- Notes inherit from the original template and may contain offering-specific text that was never tagged
- The postflight script checks notesSlides too -- if forbidden content is found there, it's a template bug

## Enrichment Rules (Step 1.5)

### Title-Based Slide Matching (ABSOLUTE)
When comparing slides between original/template/output PNGs, NEVER match by page number. Always match by reading the slide title text from the PDF/PNG. This prevents silent misalignment when LibreOffice omits or reorders pages during PDF conversion.

Procedure:
1. Extract first meaningful text line from each PDF page
2. Match original page to output page by title similarity
3. If a title appears multiple times (e.g., "Bottom-Up Financial Logic"), use the subtitle or slide number badge as disambiguator
4. Log the mapping and verify before enrichment agents start

### Table Rating Cells Must Be Tags
Rating indicators (emojis, icons, color codes) in comparison tables are DATA, not decoration. They MUST be semantic tags (e.g., `{{CAP_R_1_2}}`) so the filler can change them per offering. Never leave ratings as hardcoded emojis from the original offering's template.

### 3-Layer Context (MANDATORY for enrichment AND fill agents)
Every enrichment agent AND fill agent MUST receive visual context:
1. **Reference PNG** (`_int_ai/_pptx_pipeline/slide_pngs/reference/`) -- shows what a completed slide looks like (style guide only, NEVER copy data -- different offering)
2. **Template PNG** (`_int_ai/_pptx_pipeline/slide_pngs/template/`) -- shows `{{TAG}}` positions and FIXED labels
3. **YAML metadata** -- tag constraints (type, max_chars, visual_role, description, suggestion, bc_sections)

For **enrichment agents**: all 3 layers inform tag metadata quality.
For **fill agents**: reference PNG shows expected text density/style, template PNG shows tag positions, YAML provides precise constraints. The `bc_sections` field scopes which BC sections to read per slide.

Without all 3 layers, the agent cannot know what type of content fits each tag position.

### Enrichment Hard Rules
- NEVER invent numbers, percentages, or financial figures
- NEVER invent information not present in the BC
- NEVER change the meaning of existing content
- OK to rephrase for clarity, brevity, and presentation style
- OK to fill empty tags with content that IS in the BC but wasn't extracted
- Empty series slots stay empty when BC genuinely has no more items
- The original (other offering) is a STYLE GUIDE -- never copy its data

### Checkpoint System
- `_int_ai/slide_data_raw.json` = literal BC extraction (Step 1 output, rollback point)
- `_int_ai/slide_data.json` = enriched presentation-ready data (Step 1.5 output)
- If enrichment goes wrong, restore from `_int_ai/slide_data_raw.json` and re-enrich

## PNG Directory Management (ABSOLUTE -- STEP 6e)

Before and after copying PNGs to `_int_ai/_pptx_pipeline/slide_pngs/template/` or `_int_ai/_pptx_pipeline/slide_pngs/reference/`, the validation script MUST be run to prevent naming convention duplication.

**Naming conventions**:
- **Current (v4+)**: `page_NN.png` (zero-padded, 2 digits) -- produced by pymupdf PDF-to-PNG rendering
- **Legacy (pre-v4)**: `slide_N.png` (no zero-padding) -- produced by older pipeline runs

These MUST NOT coexist in the same directory. Mixed files cause confusion about which PNGs are current and inflate the directory (e.g., 122 files instead of 65).

**Mandatory procedure**:

1. **Before copying new PNGs**: run validation to detect existing naming convention
   ```bash
   python 98_Scripts/validate_slide_pngs.py "OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/"
   ```
2. **If mixed files detected**: STOP. Clean up old-convention files first, then re-validate:
   ```bash
   cd "OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/" && rm -f slide_*.png
   python 98_Scripts/validate_slide_pngs.py "OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/"
   ```
3. **After copying new PNGs**: re-run validation with expected count to confirm single naming convention and correct file count:
   ```bash
   python 98_Scripts/validate_slide_pngs.py "OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/" --expected-count 65
   ```
4. **If validation fails after copy**: do NOT proceed to the next step. Fix the directory first.

**Rules**:
- The `_int_ai/_pptx_pipeline/slide_pngs/template/` naming convention is `page_NN.png`. Never introduce `slide_N.png` files.
- The `_int_ai/_pptx_pipeline/slide_pngs/reference/` directory follows the same rule -- when regenerated, old files must be cleaned first.
- The `--expected-count` value should match the slide count of the source PPTX.
- Validation exit code 0 = safe to proceed. Exit code 1 = STOP and fix.

## Content Rules (for filler skills, not template builder)

- No "CIT" abbreviation -- always "Cloud & IT" in presentations
- No SKU codes (CIT-MS-*, LABOR-*) -- use descriptive service names
- No product-specific keywords from other offerings (M365, SkyFile, etc.)
- Max ~200 chars per field (longer text overflows slide elements)
- No markdown formatting (no **, no ##) -- plain text only
- No em-dashes -- use double hyphens (--)
