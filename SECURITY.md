# Security Policy

## Supported versions

iguanatrader is pre-MVP. The `main` branch is the only supported surface; tagged releases inherit `main`'s state at tag time.

| Version | Supported |
|---|---|
| `main` (HEAD) | ✅ |
| Tagged releases (`v*.*.*`) | ✅ — for the most recent tag only |
| Older tags | ❌ |

## Reporting a vulnerability

**Do NOT open a public GitHub issue for security reports.** Public disclosure of unfixed vulnerabilities is forbidden under this policy.

Two private channels:

1. **GitHub Security Advisories** — preferred. Open a draft advisory at
   https://github.com/Wizarck/iguanatrader/security/advisories/new
2. **Email** — `arturo6ramirez@gmail.com` with subject prefix `[iguanatrader-security]`.

## Response SLA

iguanatrader is a single-maintainer project at MVP stage. Best-effort response within **7 calendar days** for triage acknowledgement; fix timeline depends on severity (critical: target 14 days; high: 30 days; medium/low: best-effort).

## Disclosure

After a fix lands on `main` and the tagged release is published, the maintainer will publish a GitHub Security Advisory with a CVE if the issue is publicly reportable.

## Out of scope

- Self-DoS via configured caps in `config/strategies.yaml` or `live.env.enc` — those are operator-side controls, not security boundaries.
- IBKR / broker-side auth flows (TWS/Gateway port exposure) — that is the operator's responsibility per AGENTS.md §4 hard rules; the bot does not authenticate users beyond the FastAPI session it manages itself.
- Issues in `.ai-playbook/` — those are upstream of `iguanatrader`; report to https://github.com/Wizarck/ai-playbook/security/advisories/new
