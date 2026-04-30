# iguanatrader

> Algorithmic trading bot. Paper-first → live IBKR. Single-tenant. Multi-strategy. Self-hosted.

[![License](https://img.shields.io/badge/license-Apache--2.0%20%2B%20Commons%20Clause-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-MVP%20in%20flight-orange.svg)](docs/openspec-slice.md)

iguanatrader is a Python+Svelte single-tenant trading bot that consumes market data from IBKR (and yfinance fallback), runs strategies (Donchian-ATR + extensible), generates research briefs (5 methodologies + bitemporal facts), and executes via paper-trading first / live-trading on operator opt-in. Everything HITL-gated through Telegram or Hermes (WhatsApp).

## Status

Pre-MVP. Wave 0 (`bootstrap-monorepo`, `shared-primitives`, `persistence-tenant-enforcement`) is the sequential foundation; once landed, four parallel waves implement the 20 OpenSpec slices. See [`docs/openspec-slice.md`](docs/openspec-slice.md).

## Quickstart

1. Read [`docs/getting-started.md`](docs/getting-started.md) — prerequisites + bootstrap.
2. `make bootstrap` — installs Python (Poetry) + Node (pnpm) deps, activates pre-commit.
3. `docker compose -f docker-compose.yml up` — dev profile.

Paper-trading rehearsal (`docker compose -f docker-compose.paper.yml up`) is **strongly recommended** before live (`docker compose -f docker-compose.live.yml up`); see AGENTS.md §7 Override 1.

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/prd.md`](docs/prd.md) | Product requirements (Gate A approved) |
| [`docs/architecture-decisions.md`](docs/architecture-decisions.md) | Architecture + ADRs (Gate B approved) |
| [`docs/data-model.md`](docs/data-model.md) | ERD + bitemporal schema |
| [`docs/project-structure.md`](docs/project-structure.md) | Full monorepo tree annotation |
| [`docs/openspec-slice.md`](docs/openspec-slice.md) | 20-slice plan + dependency graph (Gate C approved) |
| [`docs/getting-started.md`](docs/getting-started.md) | Onboarding |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records |
| [`docs/gotchas.md`](docs/gotchas.md) | Non-obvious dev-loop quirks |
| [`docs/hitl-gates-log.md`](docs/hitl-gates-log.md) | Append-only HITL gate approval log |
| [`AGENTS.md`](AGENTS.md) | Project dispatcher (universal norms inherit from `.ai-playbook/specs/`) |

## License

Apache-2.0 + Commons Clause v1.0 — see [LICENSE](LICENSE). The Commons Clause restricts "selling the software itself" but allows building products/SaaS on top.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow. Security issues: [SECURITY.md](SECURITY.md).
