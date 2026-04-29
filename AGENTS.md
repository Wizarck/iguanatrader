---
schema: agents-md/v1
version: 0.1.0
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.7.1
skills_sources:
  - Wizarck/ai-playbook@v0.7.1
  - Wizarck/eligia-skills@v0.3.0
updated: 2026-04-26
project: iguanatrader
owner: arturo6ramirez@gmail.com
capabilities_map: true
---

# iguanatrader — AGENTS.md

> Project dispatcher. Lean file. Universal norms inherit from `.ai-playbook/specs/*` (pinned via `inherits_from` above).

## 0 Bootstrap directive

Before responding to ANY task:

1. Read `.ai-playbook/specs/dispatcher-chain.md` — universal norms inherited from the pinned playbook tag.
2. Consult `.claude/injected-context.md` — populated by the SessionStart hook from `hindsight.recall(query="iguanatrader <topic>")` against bank `iguanatrader`. If absent or showing `DEGRADED_CONTEXT`, announce + proceed without prior recall.
3. Check `openspec/changes/*/` for active work on the topic. If a change is live, extend it — don't start parallel work.
4. Only then respond.

## 1 Project identity

Iguanatrader — algorithmic trading bot. Estrategias automatizadas para crypto / stocks / forex, ejecución vía exchange APIs y backtesting con datos históricos. Stack y exchanges concretos por definir en la primera OpenSpec change.

## 2 Dispatcher index

| Topic | Pointer |
|---|---|
| Daily-dev runbook | [docs/runbook.md](docs/runbook.md) |
| Architecture decisions | `docs/architecture-decisions.md` *(create when first ADR lands)* |
| PRD | `docs/prd.md` *(create when product brief lands)* |
| Universal playbook norms | [.ai-playbook/specs/](.ai-playbook/specs/) |
| Verdict + severity contract | [.ai-playbook/specs/verdict-contract.md](.ai-playbook/specs/verdict-contract.md) |
| Memory hierarchy + retain CLI | [.ai-playbook/specs/memory-hierarchy.md](.ai-playbook/specs/memory-hierarchy.md) |
| Hindsight retain runbook | [.ai-playbook/runbooks/hindsight-retain.md](.ai-playbook/runbooks/hindsight-retain.md) |

## 3 Active work

none — proyecto recién bootstrapped. Primera change se creará vía `/opsx:propose` cuando se defina la estrategia inicial (probable orden: data ingest → backtesting framework → paper trading → live execution).

## 4 Project hard rules (project-specific, NOT duplicating playbook)

- **API keys de exchange NUNCA en commits**. Viven en SOPS o keystore local. Pre-commit `gitleaks` debe pasar siempre.
- **Sandbox / paper-trading antes que live**. Toda nueva estrategia se valida primero contra paper trading del exchange (Binance Testnet, Alpaca paper, etc.) o backtesting histórico. Ningún despliegue a producción sin un período mínimo de paper-trading documentado en la OpenSpec change.
- **Capital máximo por trade explícito en config**. Nunca hardcoded. Default conservador (≤1% del capital) hasta confirmación del usuario.
- **Kill-switch obligatorio**. Toda estrategia live debe exponer un mecanismo trivial para detener ejecución (env var, file flag, endpoint) sin requerir despliegue.
- **Logs de ejecución inmutables**. Cada trade live se loggea con timestamp, exchange, instrumento, side, qty, price, order_id antes y después de la confirmación del exchange. No se borran logs históricos.

## 5 Capability map

| Need | Tool / skill | Where |
|---|---|---|
| Recall prior decisions | `python .ai-playbook/scripts/inject_context.py --bank-id iguanatrader` (auto-fired by SessionStart hook) | playbook |
| Retain a lesson / decision / gotcha | `python .ai-playbook/scripts/retain_memory.py --bank iguanatrader --kind <kind> --content "..." --why "..."` | playbook |
| OpenSpec ops | `/opsx:propose | apply | archive | explore` | `.claude/commands/` |
| Validate OpenSpec change | `python .ai-playbook/scripts/openspec_validate.py` | playbook |
| Validate this AGENTS.md | `python .ai-playbook/scripts/schema_validate.py AGENTS.md` | playbook |
| Render MCP configs | `python .ai-playbook/scripts/mcp/render.py --project iguanatrader` | playbook |
| Secrets scan | `python .ai-playbook/scripts/secrets_scan.py` | playbook |
| Check for legacy↔v1 mcp-servers drift | `python .ai-playbook/scripts/check_mcp_drift.py` | playbook |

## 6 MCP sources (SSOT pointer)

3-layer SSOT per [.ai-playbook/specs/mcp-servers-schema.md](.ai-playbook/specs/mcp-servers-schema.md):

1. **Base** — `.ai-playbook/mcp-servers-base.yaml` (universal templates).
2. **Project** — [`mcp-servers.project.yaml`](mcp-servers.project.yaml) (this project's overrides + Hindsight bank `iguanatrader`).
3. **Personal** — `~/.config/mcp-servers.yaml` (per-dev tenant instances; never committed).

Rendered to [`.mcp.json`](.mcp.json) + [`.gemini/settings.json`](.gemini/settings.json) via `scripts/mcp/render.py`. Regenerate after editing the project layer.

## 7 Overrides inherited from playbook

### Override 1 (2026-04-28) — §4 hard rule "paper-trading antes que live" relaxed to recommendation

**What is overridden**: AGENTS.md §4 hard rule "Sandbox / paper-trading antes que live. Toda nueva estrategia se valida primero contra paper trading del exchange ... o backtesting histórico. Ningún despliegue a producción sin un período mínimo de paper-trading documentado en la OpenSpec change."

**New behavior**: paper trading remains the **strongly recommended** path before live trading. It is **no longer mandatory**. The user retains final authority on whether to skip paper and go directly to live. CLI surface MUST require explicit `--confirm-live --i-understand-the-risks` flag for live deployment without prior paper history; absence of paper-trading record in `audit_log` → CLI emits **WARNING with risk acknowledgment text**, not block.

**Rationale**: Arturo (sole MVP user) is a discretionary trader with full risk authority and accepts the consequences of skipping paper. v3 SaaS retains the same authority via per-user setting. Bus factor 1 + 3-4 month MVP budget makes mandatory paper period a misaligned friction. Backtest gate was also evaluated and explicitly skipped from MVP scope (decision 2026-04-28); paper trading remains the only validation discipline available, recommended but not enforced.

**Recommendation invariant**: The system ALWAYS recommends paper trading. The user can override per-strategy. `audit_log` records the override decision with timestamp, strategy reference, and the literal risk acknowledgment text typed by the user.

**Reverts to default**: If/when v3 SaaS exposes the system to non-Arturo users with potentially less risk literacy, this override may need to be narrowed to `admin`-role users only, with §4 behavior restored as mandatory for `user`-role accounts. The decision is logged in `docs/hitl-gates-log.md` Gate A amendment 2026-04-28.

## 8 Gotchas

_Vacío. Se rellena con uso real — entradas dated YYYY-MM-DD según el formato de abajo._

Append one-line dated entries when a project gotcha is discovered:

```
- YYYY-MM-DD — <what went wrong>. <rule to apply next time>.
```

Promote recurring gotchas to Hindsight via `retain_memory.py --kind gotcha` so other sessions and projects benefit.
