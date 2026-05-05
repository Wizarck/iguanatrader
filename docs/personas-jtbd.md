---
type: personas-jtbd
project: iguanatrader
schema_version: 1
scope: mvp-single-user
created: 2026-04-28
updated: 2026-04-28
status: draft-pending-gate-b
sources:
  - docs/prd.md
  - docs/architecture-decisions.md
  - .ai-playbook/specs/runbook-bmad-openspec.md
---

# Personas & JTBD — iguanatrader

Per [`.ai-playbook/specs/runbook-bmad-openspec.md`](../.ai-playbook/specs/runbook-bmad-openspec.md) §2.1, this artefact captures **roles + JTBD + RBAC matrix** for the MVP scope. Multi-tenant v2/v3 personas explicitly deferred (see §Future Personas).

---

## Persona — "Arturo, the algorithmic trader"

### Identity

| Field | Value |
|---|---|
| Name | Arturo Ramírez |
| Email | arturo6ramirez@gmail.com |
| Role | Sole user, operator, developer, beneficiary |
| Bus factor | 1 (explicit constraint, see PRD §Project Scoping) |
| Time budget | 3-4 calendar months for MVP |

### Demographic / context

- Senior-level developer with deep distributed systems, infra, and AI tooling experience (ELIGIA architecture maintainer; openTrattOS, palafito-b2b, eligia-rag concurrent projects).
- Trades discretionary equity intraday in his own account at IBKR (paper-tested to live transition gate).
- Capital-conscious: ≤50€/mes LLM budget cap (NFR-O); per-trade risk ≤2% of capital default.
- Operates from Windows 11 Pro host; mobile-secondary via dashboard PWA-ready architecture.
- Workflow: morning premarket briefing → midday check → postmarket summary → weekly review (hybrid scheduled + on-demand).

### Technical fluency

- Python 3.11+ first language; production async + typing strict.
- Comfortable with Docker, SOPS+age, structlog, Pydantic, SQLAlchemy.
- Familiar with LangGraph (uses it in ELIGIA infra) — knows when LLMs add value vs noise.
- Reads research papers; backtests on parquet data; has prior experience evaluating Lumibot, NautilusTrader, Lean, Freqtrade landscape.
- Strong opinions on legal/compliance hygiene (SECURITY.md, license attribution, gitleaks pre-commit non-bypassable).

### Quality bar

- Refuses to ship without: backtest↔live parity tests, property tests on RiskEngine, append-only audit, ≥10 ADRs at MVP close, ≥20 gotchas.md entries.
- Pushes back on architectural shortcuts (e.g. forced HTMX→Svelte 5 migration for v3 trajectory; rejected dual date format in favor of ISO 8601 single source of truth).

---

## Jobs To Be Done (JTBD)

JTBD frame: **"When [situation], I want to [motivation], so I can [expected outcome]"**.

### Primary jobs

#### JTBD-1 — Hands-off proposal pipeline with veto power

> **When** the market is open and my strategies are armed, **I want** the bot to autonomously detect setups, evaluate them against risk caps, and surface qualified proposals via Telegram or WhatsApp with a tight approval window, **so I can** focus on my day job and only intervene when there is a real trade to act on — without missing setups or executing trades I would regret.

- **Functional outcome**: 5-20 trades/week with ≥80% of the work delegated to the system.
- **Emotional outcome**: confidence that nothing slipped through silently; calm during market hours.
- **Social outcome**: not relevant (single-user MVP).
- **Maps to**: FR1-FR5, FR11-FR18, FR31-FR38; NFR-P1, NFR-P5.

#### JTBD-2 — Programmatic enforcement of risk policy

> **When** trading is active, **I want** the system to enforce daily / weekly loss caps and per-trade risk limits programmatically, with kill-switch triggers wired to declarative protections, **so I can** rely on policy as code rather than discretionary intervention.

- **Functional outcome**: zero cap breaches beyond configured limits; every breach produces an auditable event.
- **Operational outcome**: risk policy versioned in `config/risk.yaml` and property-tested in CI.
- **Maps to**: FR19-FR30; NFR-R5, NFR-R6.

#### JTBD-3 — Audit & reflection pipeline that compounds over years

> **When** I review my performance weekly or quarterly, **I want** the system to surface what worked, what failed, and what I can learn from each setup, with full provenance back to the LLM prompts, broker fills, and risk events, **so I can** improve as a trader compounding lessons across years rather than re-learning the same mistakes.

- **Functional outcome**: every trade has a reviewable journal entry; weekly review PDF auto-generated.
- **Emotional outcome**: progress visible; mistakes feel like fuel, not regret.
- **Maps to**: FR43-FR44, FR46-FR51; NFR-O1, NFR-O5.

#### JTBD-4 — Research-driven decisions with full provenance and show-your-work

> **When** the system proposes a trade or I review a symbol manually, **I want** every numeric claim to cite its source (URL + retrieval timestamp + method) and every calculated metric to expose its formula + inputs + intermediate steps, **so I can** trust the system's reasoning rather than treat its outputs as opaque LLM hallucinations.

- **Functional outcome**: 100% of `research_facts` carry complete provenance (source_id, source_url, retrieval_method, retrieved_at — DB CHECK + CI test enforce); 100% of calculations in `research_briefs` carry `audit_trail` JSON with formula + inputs cited + steps + output.
- **Operational outcome**: bitemporal storage allows replay of "what did we know about symbol X at time T" for trade audit and post-hoc analysis.
- **Anti-hallucination outcome**: LLM cannot invent values — every numeric assertion in a brief must cite a fact; broken citations fail render in CI.
- **Maps to**: FR57-FR79 (Research & Intelligence Domain); NFR-P9, NFR-O8.

> **Note on backtest** (deferred from MVP per Gate A amendment 2026-04-28): the original "backtest research compounding into live confidence" JTBD has been replaced by paper trading 30-90 days as the validation discipline. Backtest may return in v1.5+ if paper-trading evidence demonstrates clear value beyond the cost.

### Secondary jobs

#### JTBD-5 — Multi-instrument awareness without information overload

> **When** I want broader market context beyond my watchlist, **I want** Tier 2 LLM-filtered alerts and Tier 3 scheduled briefings to surface relevant signals from a wider universe (SP500/R2000 watchlist secondary), **so I can** spot opportunities I would otherwise miss without drowning in noise.

- **Maps to**: FR33-FR35.

#### JTBD-6 — System trustworthy enough to leave running unattended

> **When** I am asleep, traveling, or focused on other work, **I want** the system to handle broker disconnects, LLM outages, and component failures gracefully with reconnect logic + kill-switch escalation, **so I can** trust that nothing catastrophic happens while I am away.

- **Maps to**: FR16, FR29, FR30; NFR-R1, NFR-R2, NFR-R7, NFR-P8.

### Latent / aspirational jobs (deferred to roadmap)

- **JTBD-7** — Open-source the kernel, run a paid multi-tenant SaaS variant: explicitly side-effect; scoped out of MVP per PRD §Project Scoping.
- **JTBD-8** — Onboard another user (friend, family member): v2 SaaS feature; deferred.

---

## RBAC Matrix (MVP + v2 baseline)

Refined 2026-05-05 (Arturo): the model is **2-level, single-seat-per-tenant**. v3 SaaS may introduce multi-user-per-tenant + finer roles (Risk Officer, Auditor) only if real demand emerges.

| Level | Role | Holder MVP | v2 SaaS | Capabilities |
|---|---|---|---|---|
| **Platform** | `god_admin` (cross-tenant) | Arturo (running his own instance) | iguanatrader operator | Manages platform config: pricing tiers, broker allowlist, plan-level feature flags, tenant onboarding/offboarding, billing pipeline. **Can impersonate any tenant user for support/debugging** — impersonation surfaces a banner on the dashboard and writes an audit row. NO regular UI surface exposed to tenant users. |
| **Tenant** | `tenant_user` (1 per tenant) | Arturo | One per tenant (single-seat) | Functionally admin of their own tenant. Full operational autonomy: launch research refreshes, override risk-rejected proposals, force-exit / force-create, kill-switch, edit strategies, edit risk policy, toggle feature flags (Hindsight), manage authorized senders, export everything. Cannot edit platform config. |

### What changed from earlier draft

- The previous matrix had a `user` role meaning "secondary tenant member, read-only". **That role no longer exists** in v2 — v2 is single-seat-per-tenant; the tenant user IS the admin of their tenant. v3 may reintroduce a multi-user model under "Solo / Team / Pro" tiers (see [PRD §Phase 3 Expansion](prd.md)).
- `god_admin` is platform-level only. It surfaces as an internal CLI / hidden ops dashboard; tenant users never see god-admin operations except the impersonation banner if active.

### Authorization enforcement (architectural)

- **Single user MVP** = Arturo is `tenant_user` (and also operates god-admin functions out-of-band via CLI). Auth claim `role: tenant_user` in JWT.
- **`tenant_id` in JWT claim** propagated via `contextvars.ContextVar` to all queries and structlog (NFR-SC1). `role` and (when impersonating) `impersonating_god_admin: <god_id>` claims propagated alongside.
- **`authorized_phones` + `authorized_telegram_ids`** whitelist in encrypted config (NFR-S3, NFR-S4) — sender authentication for messaging channels. Whitelist is per-tenant; `tenant_user` manages it.
- **Permission middleware on `/api/v1/...`**: route-level `requires_role` decorator. All operational mutating endpoints accept `tenant_user`. Platform mutating endpoints (`/api/v1/platform/...` — tenant CRUD, pricing tiers, broker allowlist) accept `god_admin` only and are NOT exposed in the SvelteKit dashboard (separate ops tooling).
- **No hard quotas in MVP/v2**. Anti-abuse via **rate-limits** only (e.g. `slowapi 5/min` on `/auth/login`, `/research/refresh`). Cost observability (NFR-O2) writes per-action cost to the ledger; v2 SaaS analyses patterns and decides if a billing tier with quotas is justified.
- **No fine-grained RBAC** in MVP/v2. v3 may introduce finer roles only after evidence of real demand.

---

## Anti-personas (out-of-scope explicit)

To avoid scope creep into v2/v3 prematurely, the MVP **explicitly does not serve**:

- **Casual retail traders** — UX assumes Python literacy + CLI comfort.
- **High-frequency traders** — daily-bar / minute-bar cadence; not microsecond.
- **Discretionary chart traders** — bot proposes via signals, not a charting GUI for manual entry (charting is read-only post-trade).
- **Compliance officers / regulated entities** — no SEC/FINRA/MiFID compliance modules; private use only.
- **Crypto-only or forex-only users** — deferred to v3. MVP and v2 scoped to US equities via IBKR. FR mention of "crypto / forex" stays only as broker-abstraction north star validated in v3.

---

## Future Personas (deferred — v2 / v3 SaaS)

Listed for traceability only. **NOT** developed for MVP.

| Persona | Phase | Expected JTBD anchor |
|---|---|---|
| Beta tester (paying friend) | v2 | Variant of Arturo's JTBDs, less Python-fluent — needs onboarding wizard. |
| SaaS subscriber individual | v3 | Plug-and-play: register → connect IBKR → pick preset strategies → approve trades. |
| SaaS team (multi-seat per tenant) | v3 | Reintroduces a `tenant_member` role (read-only or limited) under a "Team / Pro" pricing tier. Requires re-opening the RBAC matrix. |
| Compliance auditor | v3+ | Read-only access to trade book + risk overrides + cost ledger; if needed, may justify a third role split from `user`. |

These personas trigger v2/v3 architectural milestones documented in [`docs/backlog.md`](backlog.md). No code changes in MVP justified by these personas.

---

## Cross-references

- [docs/prd.md](prd.md) — User Journeys 1-5 are concrete instantiations of JTBD-1..6 above.
- [docs/architecture-decisions.md](architecture-decisions.md) §Multi-tenant context propagation — RBAC enforcement architecture preserves v2 path without MVP overhead.
- [docs/backlog.md](backlog.md) — v2/v3 personas anchor specific roadmap items.
- [.ai-playbook/specs/runbook-bmad-openspec.md](../.ai-playbook/specs/runbook-bmad-openspec.md) §2.1 — artefact requirement.
