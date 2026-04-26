# Architecture Discovery Process

### Step 1: Read Architecture Files

**ALWAYS read relevant files first to understand current state**:

```
1. AI Instructions:
   - CLAUDE.md (root)

2. Analysis Framework & Pipeline:
   - 00_Prompts/analysis.md (self-validation gates)
   - 00_Prompts/pipeline.md (38-step pipeline, agent delegation, QA gates, template-to-step mapping)
   - 00_Prompts/analysis_financial_model.md (financial patterns)
   - 00_Prompts/PRICING_FORMULA_REFERENCE.md (pricing formulas)
   - 00_Prompts/analysis_*.md (other analysis modules)

3. Templates:
   - 20_OFFERS/OFFER-000 (Template)/LEAN_BUSINESS_CASE.md
   - 20_OFFERS/OFFER-000 (Template)/*.md (all templates)

4. QA Agents:
   - .claude/skills/qa-financial/SKILL.md
   - .claude/skills/qa-catalogue/SKILL.md
   - .claude/skills/qa-strategy/SKILL.md
   - .claude/skills/qa-consistency/SKILL.md
   - .claude/skills/qa-research/SKILL.md
   - .claude/skills/qa-od/SKILL.md
   - .claude/skills/qa-sd/SKILL.md
   - .claude/skills/qa-pot/SKILL.md
   - .claude/skills/qa-enablement/SKILL.md
   - .claude/skills/qa-poc/SKILL.md
   - .claude/skills/qa-use-cases/SKILL.md
   - .claude/skills/qa-pptx/SKILL.md

5a. PPTX Visual Context:
   - 20_OFFERS/OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/reference/ (reference PNGs from completed offering -- style guide for fill+QA agents)
   - 20_OFFERS/OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/slide_pngs/template/ (template PNGs with {{TAG}} placeholders -- layout guide for fill+QA agents)

5. Worker Agents:
   - .claude/skills/kickoff/SKILL.md
   - .claude/skills/develop/SKILL.md
   - .claude/skills/research/SKILL.md
   - .claude/skills/market-intel/SKILL.md
   - .claude/skills/use-case-research/SKILL.md
   - .claude/skills/pot/SKILL.md
   - .claude/skills/catalogue/SKILL.md
   - .claude/skills/strategy/SKILL.md
   - .claude/skills/customer/SKILL.md
   - .claude/skills/service/SKILL.md
   - .claude/skills/enablement/SKILL.md
   - .claude/skills/poc/SKILL.md
   - .claude/skills/commercial-playbook/SKILL.md
   - .claude/skills/datasheet/SKILL.md
   - .claude/skills/cpq/SKILL.md
   - .claude/skills/ideation-deck/SKILL.md
   - .claude/skills/bc-to-pptx/SKILL.md
   - .claude/skills/pptx-template/SKILL.md
   - .claude/skills/sync-jira/SKILL.md
   - .claude/skills/intel/SKILL.md
   - .claude/skills/start/SKILL.md

5b. PPTX Pipeline Artifacts:
   - 20_OFFERS/OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/semantic_mapping.yaml (tag metadata: type, description, suggestion, max_chars, tag_positions)
   - 20_OFFERS/OFFER-000 (Template)/_int_ai/_int_ai/_pptx_pipeline/filler_spec_BC.md (fill rules: formatting, cross-slide consistency, structural constraints)
   - .claude/skills/pptx-template/guardrails.md (absolute rules for template builder AND fill agent)
   - .claude/skills/bc-to-pptx/SKILL.md (fill agent pipeline: extract → validate → inject → QA)
   - .claude/skills/qa-pptx/SKILL.md (QA agent: PASS/REWORK/STRUCTURAL verdicts)

6. Guidelines:
   - 15_PORTFOLIO/10_Guidelines/*.md

7. Agent Documentation:
   - 00_Prompts/agents/README.md (architecture, model routing & MCP, interaction patterns, data flow, validation hooks)
```

### Step 2: Classify Root Cause (Mode 1) or Impact Area (Mode 2/3)

| Category | Root Cause | Prevention/Impact Layer |
|----------|------------|-------------------------|
| **Formula Error** | Wrong calculation method | PRICING_FORMULA_REFERENCE.md, Templates |
| **Terminology Error** | Inconsistent naming | CLAUDE.md glossary, Guidelines |
| **Validation Gap** | Missing check in workflow | analysis.md gates, QA checklists |
| **Template Gap** | Missing guidance in template | LEAN_BUSINESS_CASE.md |
| **Cross-Reference Error** | Stale or missing links | Templates, analysis.md protocol |
| **Process Gap** | Missing step in workflow | Agent prompts, CLAUDE.md |
| **Documentation Gap** | Missing or outdated docs | README files, CLAUDE.md |
| **Use Case Taxonomy Error** | Capability listed as use case | Use Cases CSV, use-case-research SKILL.md |
| **JTBD Coverage Gap** | Missing user jobs in use cases | Use Cases CSV, OFFER-000 template |
| **PPTX Tag Metadata Error** | Wrong description/suggestion/max_chars in YAML | semantic_mapping.yaml, filler_spec_BC.md |
| **PPTX Layout Mismatch** | Content type vs slide layout conflict | semantic_mapping.yaml (table_layout, tag_positions), guardrails.md |
| **PPTX Overflow Error** | Text exceeds element capacity | semantic_mapping.yaml (max_chars), filler_spec_BC.md |
| **PPTX Guardrail Gap** | Missing rule in template/fill guardrails | pptx-template/guardrails.md, filler_spec_BC.md |
| **PPTX Fill Logic Error** | Wrong extraction/enrichment logic | bc-to-pptx/SKILL.md, filler_spec_BC.md |
| **PPTX Series Duplication** | Paragraph cloning instead of join-based fill | generate_pptx.py, guardrails.md (Series Tag Fill Strategy) |
| **PPTX Tag Inventory Mismatch** | Fill data count != template slot count | bc-to-pptx/SKILL.md (Step 1.5), _int_ai/fill_data.json |
| **PPTX YAML Source Inversion** | YAML generated from classification, not template scan | pptx-template/SKILL.md (STEP 6d), guardrails.md Post-Injection Audit #5 |
| **PPTX Duplicate Tag** | Same `{{TAG}}` appears multiple times in template | guardrails.md (Post-Injection Audit), template PPTX |
| **Boundary Scope Error** | Boundary work treated as registry-only task; cascading file edits omitted | `OFFER_BOUNDARIES.md`, `develop` SKILL.md, `pipeline.md` |
| **Reflection Loop Exhaustion** | Worker exhausts max rework cycles on same deliverable — same QA issue persists across iterations | Worker SKILL.md (rules may need clarification), QA SKILL.md (criteria may be too strict), `## Contract` section (max_rework_cycles) |

### Step 3: Prevention/Impact Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                    ARCHITECTURE HIERARCHY                        │
│                    (Earlier = Higher Impact)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Level 1: CLAUDE.md                                              │
│  └── AI reads this FIRST on every session                        │
│      Impact: Universal - affects ALL operations                  │
│                                                                  │
│  Level 2: 00_Prompts/analysis.md                                 │
│  └── Self-validation gates run BEFORE presenting docs            │
│      Impact: High - catches errors before user sees them         │
│                                                                  │
│  Level 3: 00_Prompts/*_REFERENCE.md                              │
│  └── Detailed reference documents                                │
│      Impact: Medium - provides depth when needed                 │
│                                                                  │
│  Level 4: Templates (OFFER-000)                                  │
│  └── User sees warnings when filling templates                   │
│      Impact: Medium - guides content creation                    │
│                                                                  │
│  Level 5: Agent Prompts (.claude/skills/)                        │
│  └── Define agent behavior and workflows                         │
│      Impact: Varies - affects specific workflows                 │
│                                                                  │
│  Level 5b: PPTX Pipeline Artifacts                               │
│  └── semantic_mapping YAML, filler_spec, guardrails              │
│      Impact: PPTX-specific — affects deck generation quality     │
│      Root cause triage: Tag metadata → fix YAML.                 │
│      Fill logic → fix filler_spec or bc-to-pptx SKILL.           │
│      Missing guardrail → fix guardrails.md.                      │
│      Layout mismatch → may require template rebuild.             │
│                                                                  │
│  Level 6: Guidelines (10_MARLINK/)                               │
│  └── Business rules and taxonomy                                 │
│      Impact: Domain-specific                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Step 4: Skill Modifications

When proposing changes to skills, recommend calling `/skill-creator` — it has the complete skill writing guide, GTM-Helper conventions, description optimization patterns, and testing workflow. Adapted from [Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator).
