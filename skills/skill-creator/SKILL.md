---
name: skill-creator
description: >
  Creates new skills, modifies existing skills, and optimizes skill descriptions
  for better triggering accuracy. Adapted from Anthropic's official skill-creator.
  Use when creating a skill from scratch, editing or improving an existing skill,
  or optimizing a skill's description. Also use when /qa-improve identifies that
  a skill needs structural changes, new skills are needed, or descriptions need
  optimization.
argument-hint: "[create|modify|optimize] [skill-name]"
disable-model-invocation: true
model: opus
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

# Skill Creator

Creates new skills and iteratively improves existing ones for the GTM-Helper system.

Adapted from [Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator). For advanced eval infrastructure (automated benchmarking, blind comparison, description optimization scripts), see the original repository.

## Template Edit Protocol

OFFER-000 (Template) files are protected by a hook. When creating or modifying template files:

1. **Before editing**: `touch c:/GTM-Helper/.claude/template-edit-mode`
2. **Edit templates** using Edit/Write tools normally
3. **After all edits**: `rm c:/GTM-Helper/.claude/template-edit-mode`

**CRITICAL**: Always remove the bypass file when done.

## Core Loop

1. Capture what the skill should do and when it should trigger
2. Write a draft SKILL.md following GTM-Helper conventions
3. Test with realistic prompts (2-3 test cases)
4. Evaluate results with the user
5. Improve and repeat until satisfied

## GTM-Helper Skill Conventions

### Directory Structure

Every skill gets its own directory under `.claude/skills/`:

```
.claude/skills/{name}/
├── SKILL.md              (required — YAML frontmatter + instructions)
├── validation-rules.md   (optional — extracted checklist, used by QA skills)
├── validation-scope.md   (optional — detailed scope, used by QA skills)
├── sd-op-workflow.md     (optional — workflow reference, used by /service)
└── architecture-hierarchy.md  (optional — reference doc, used by /qa-improve)
```

### YAML Frontmatter Fields

| Field | Required | Values | Purpose |
|-------|----------|--------|---------|
| `name` | Yes | Matches directory name | Skill identifier |
| `description` | Yes | Free text, max 1024 chars | Triggering mechanism — see Description Optimization |
| `model` | No | `haiku`, `sonnet`, `opus` | AI model routing |
| `context` | No | `fork` | Isolated subagent (no conversation history) |
| `allowed-tools` | No | Comma-separated | Tool restrictions (e.g., `Read, Glob, Grep`) |
| `disable-model-invocation` | No | `true` | User-invoked only (description hidden from Claude) |
| `user-invocable` | No | `false` | Auto-invoked only (hidden from `/` menu) |
| `argument-hint` | No | Free text | Hint shown in `/` menu |

### Skill Categories in GTM-Helper

| Category | Context | Model | Tools | Pattern |
|----------|---------|-------|-------|---------|
| **Worker** | inline | varies | All | Interacts with user, calls paired QA |
| **QA** | `fork` | sonnet | `Read, Glob, Grep` | Read-only validation, returns verdict |
| **Meta-QA** | `fork` | opus | `Read, Glob, Grep, Edit, Write, Bash` | Architecture advisor (/qa-improve) — proposes, implements on approval |
| **Auto** | inline | haiku | `Read, Glob, Grep` | Silent context loader (/intel) |

---

## Creating a Skill

### Step 1: Capture Intent

Understand what the user wants. If the conversation already contains a workflow to capture (e.g., "turn this into a skill"), extract:
- Tools used, sequence of steps, corrections made
- Input/output formats observed
- Edge cases encountered

Key questions:
1. What should this skill enable Claude to do?
2. When should this skill trigger? (user phrases, contexts)
3. What's the expected output format?
4. Which category? (Worker, QA, Meta-QA, Auto)
5. Does it need a paired QA agent?

### Step 2: Write the SKILL.md

Based on the interview, fill in:

**Frontmatter**:
- `name` — matches directory name
- `description` — WHAT + WHEN triggers (see Description Optimization below)
- `model` — haiku for simple/fast, sonnet for most work, opus for complex reasoning
- `context: fork` — if the skill should run isolated (QA agents)
- `allowed-tools` — restrict to minimum needed (QA = `Read, Glob, Grep`)

**Body** (under 500 lines):
- Role and principles
- Caller detection (if applicable — Worker vs User input)
- Source documents to validate against
- Validation checklist or workflow steps
- Output format (structured templates)
- Architectural improvement handoff (if QA — the `/qa-improve` block)

### Step 3: Extract Supporting Files

If the SKILL.md body is approaching 500 lines, extract detailed content to reference files:
- Validation checklists → `validation-rules.md`
- Formula references → `validation-scope.md`
- Workflow details → `{name}-workflow.md`

Reference them from SKILL.md: `See [validation-rules.md](validation-rules.md) for the complete checklist.`

For large reference files (>300 lines), include a table of contents so the skill can selectively read sections.

---

## Skill Writing Guide

### Description Optimization

The `description` field is the **primary triggering mechanism**. Claude reads it to decide whether to invoke the skill. Everything about "when to use" goes here, not in the body.

**Rules**:
- Third-person voice: "Validates..." not "Validate..."
- Include WHAT it does + WHEN to trigger
- Claude undertriggers by default — make descriptions "pushy" with multiple trigger keywords
- Auto-invocable skills (no `disable-model-invocation`) need aggressive trigger phrases
- Max 1024 chars

**Pattern for QA skills**:
```yaml
description: >
  Validates [domain] [what it checks].
  Use after creating or updating [which documents].
```

**Pattern for Worker skills**:
```yaml
description: >
  [Does what] through [how]. Generates [outputs].
  Use when [trigger contexts]. Also use when [additional triggers].
```

**Pattern for auto-invocable skills** (most aggressive):
```yaml
description: >
  [Does what] silently. Use this skill whenever [broad trigger list].
  Also use when [more triggers], [even more triggers].
```

### Writing Style

Explain **WHY**, not just MUST. Today's LLMs are smart — they have good theory of mind and when given reasoning can go beyond rote instructions.

- Bad: "ALWAYS use snake_case for variable names"
- Good: "Use snake_case because the codebase convention is consistent Python style"
- Bad: "NEVER include pricing in OD documents"
- Good: "No pricing in OD — prices belong exclusively in LEAN_BUSINESS_CASE.md because OD is customer-facing catalogue content shared across segments, while pricing varies by deal"

If you find yourself writing ALWAYS or NEVER in all caps, that's a yellow flag — reframe and explain the reasoning so the model understands importance.

### Progressive Disclosure

Skills use a three-level loading system:

| Level | What | When Loaded | Budget |
|-------|------|-------------|--------|
| 1. Metadata | `name` + `description` | Always in context | ~100 words |
| 2. SKILL.md body | Instructions | On skill trigger | <500 lines |
| 3. Bundled references | Detail docs | On-demand (Read) | Unlimited |

Key patterns:
- Keep SKILL.md under 500 lines
- Reference files clearly from SKILL.md with guidance on when to read them
- For large reference files (>300 lines), include a TOC
- Scripts can execute without being loaded into context

### Output Format Templates

QA skills should define structured output for each verdict:

```markdown
### APPROVED
[Success template with verification details]

### ISSUES FOUND
[Numbered issues with Expected/Found/Action]

### CLARIFICATION NEEDED
[Question with Option A/B and implications]
```

### Agent Contract Section

Workers should include a `## Contract` section in their SKILL.md body that consolidates deliverables, acceptance criteria, and escalation rules. This makes expectations explicit and actionable — Claude reads the body as prompt, so the contract directly influences behavior.

```markdown
## Contract

**Deliverables**: SOLUTION_DESIGN.md, SERVICE_DESIGN.md, OPERATIONAL_PLAYBOOK.md, OFFER_DESCRIPTION.md
**Validation**: /qa-sd (SD+OP), /qa-od (OD)
**Acceptance Criteria**:
- All [M] fields populated
- No [TBD] remaining without GAP-XXX reference
- Source traceability 100%
**Escalation Triggers**:
- QA ISSUES FOUND twice on same deliverable → pause, escalate to user
- Required source document missing → log to GAPS.md, ask user
**Max Rework Cycles**: 2
```

Why markdown body instead of YAML frontmatter: the skill system only recognizes 8 frontmatter fields. Custom YAML fields are silently ignored. The markdown body IS the prompt — contracts here are directly actionable.

### Worker→QA Pattern

Every worker that modifies documents should call its paired QA before completing:

```
Worker completes task → calls QA with summary → QA validates →
  if APPROVED → present to user
  if ISSUES FOUND → Worker fixes issues, re-calls QA (max 2 rework cycles) →
    if still failing → escalate to user with issues + fixes attempted
  if CLARIFICATION NEEDED → escalate to user (cannot self-fix)
```

QA skills detect caller via input content:
- Worker call: input contains document names or "Task summary"
- User call: direct invocation via `/qa-name`

### Architectural Improvement Handoff

QA skills should include a handoff block for systemic errors:

```
SYSTEMIC ERROR DETECTED — Recommend /qa-improve

Error Type: [Formula | Terminology | Validation Gap | Template Gap | Process Gap]
Error Description: [What was wrong]
Expected / Found / Correction Applied / Files Affected
```

---

## Improving an Existing Skill

### When Called by /qa-improve

qa-improve may call this skill when it identifies:
- A skill needs structural changes (e.g., missing validation rules)
- A new skill is needed (e.g., gap in agent coverage)
- A description needs optimization (undertriggering or overtriggering)

In this case, qa-improve provides:
- What needs to change and why
- Which files are affected
- Priority (P1 = blocking, P2 = should fix, P3 = nice to have)

### Improvement Principles

1. **Generalize from feedback** — don't overfit to specific examples. Skills are used across many prompts. Avoid fiddly, overly specific changes.

2. **Keep it lean** — remove instructions that aren't pulling their weight. Read transcripts, not just outputs — if the skill makes the model waste time on unproductive steps, trim those parts.

3. **Explain the why** — instead of adding more MUSTs, explain reasoning so the model understands importance and can generalize to edge cases.

4. **Look for repeated work** — if subagents repeatedly write similar code or take the same multi-step approach, bundle that as a script or reference file.

---

## Testing Skills

### Quick Validation

After writing or modifying a skill, test with 2-3 realistic prompts:

1. Draft prompts that a real user would type (specific, with context — not abstract)
2. Run each prompt with the skill active
3. Evaluate: Did the skill trigger? Did it produce correct output? Did it follow conventions?

### What to Check

- Does the description trigger the skill for intended queries?
- Does the description NOT trigger for unrelated queries?
- Does the output follow the expected format?
- Are all source documents read and validated correctly?
- Does the Worker→QA handoff work?

### Description Triggering Test

For skills that should auto-trigger, test with realistic queries:
- Should-trigger: "validate the OD for OFFER-003" → should invoke `/qa-od`
- Should-not-trigger: "what's in the OD file?" → should NOT invoke `/qa-od` (it's a read, not validation)

If triggering is off, adjust the description keywords. For formal optimization with automated benchmarking, see [Anthropic's description optimization scripts](https://github.com/anthropics/skills/tree/main/skills/skill-creator/scripts).

---

## Reference

### Existing GTM-Helper Skills

```
Workers (21):
  /kickoff, /research, /market-intel, /strategy, /customer,
  /catalogue, /service, /pot, /poc, /develop, /use-case-research,
  /enablement, /commercial-playbook, /datasheet, /cpq,
  /bc-to-pptx, /pptx-template, /ideation-deck,
  /intel (auto), /start, /sync-jira

QA (12):
  /qa-research, /qa-strategy, /qa-catalogue, /qa-od,
  /qa-sd, /qa-financial, /qa-consistency, /qa-use-cases, /qa-pot,
  /qa-enablement, /qa-pptx, /qa-poc

Meta-QA (1):
  /qa-improve (AI Architecture Advisor)

Tooling (1):
  /skill-creator
```

### Concordance Update (MANDATORY)

After creating, renaming, or deleting ANY skill, update ALL concordance files so the system stays consistent. This is NOT optional — skipping it causes drift that the user should never have to fix manually.

**Concordance Registry** — files that reference the skill inventory:

| File | What to Update |
|------|---------------|
| `CLAUDE.md` | Worker Agents / QA Agents listing (agent names, models, descriptions) |
| `00_Prompts/agents/README.md` | Agent count, Worker-QA diagram, Quick Reference table, File Structure tree |
| `00_Prompts/analysis.md` | Context Sources section (if skill changes affect which files agents load) |
| `.claude/skills/qa-improve/architecture-hierarchy.md` | Worker Agents list (Step 1, item 5) |
| `.claude/skills/skill-creator/SKILL.md` | "Existing GTM-Helper Skills" reference list (this file) |

**When to run**: After Step 5 (testing), before declaring the skill done.

**How**: Read each concordance file, find the relevant section, update it. If adding a new worker, also check if it should appear in `/develop` Sub-Agent Delegation list.

---

### Advanced Eval Tooling

The full Anthropic skill-creator is available locally at `.claude/vendor/anthropic-skills/skills/skill-creator/` (git submodule). It includes:

- `scripts/run_eval.py` — Run evaluation prompts against skills
- `scripts/run_loop.py` — Automated description optimization loop
- `scripts/aggregate_benchmark.py` — Benchmark aggregation with variance analysis
- `agents/grader.md` — Subagent for grading assertion pass/fail
- `agents/comparator.md` — Blind A/B comparison between skill versions
- `agents/analyzer.md` — Post-hoc analysis of why one version beats another
- `references/schemas.md` — JSON schemas for evals, grading, benchmarks

See `.claude/vendor/SOURCES.md` for update workflow and tracking.

$ARGUMENTS
