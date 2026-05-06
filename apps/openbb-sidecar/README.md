# openbb-sidecar

This sidecar embeds [OpenBB Platform](https://openbb.co/) (AGPL-3.0-or-later) and exposes a small HTTP surface consumed by the **iguanatrader** monolith (Apache-2.0 + Commons Clause). The sidecar runs in its own Docker container with its own LICENSE and dependency tree; the monolith never imports `openbb` at the Python level. This file-system + process boundary is the mechanism by which the AGPL-3.0 obligations of OpenBB are kept inside this sidecar and do not propagate into the rest of the codebase.

See [ADR-015](../../docs/adr/ADR-015-2026-04-28-openbb-sidecar-isolation.md) for the boundary rationale.

## Purpose

- License isolation: keep AGPL-3.0 code out of `apps/api/` (Apache-2.0 + Commons Clause).
- Provide research data (equity fundamentals, ratings, ESG; macro indicators) to the monolith over HTTP.
- Communicate exclusively over loopback inside the docker-compose internal network — the host-port binding is intentionally NOT exposed.

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | Liveness + readiness flag (`openbb_loadable`) |
| GET | `/v1/equity/fundamentals/{symbol}` | P/E, market cap, dividend yield, as-of date |
| GET | `/v1/equity/ratings/{symbol}` | Consensus, target price, analyst count, as-of date |
| GET | `/v1/equity/esg/{symbol}` | ESG score + E/S/G sub-scores, as-of date |
| GET | `/v1/economy/macro/{indicator}` | Macro series (CPI, GDP, etc.), unit, frequency |

## Local development

The sidecar runs standalone for testing without the rest of the iguanatrader stack:

```bash
cd apps/openbb-sidecar
poetry install
poetry run uvicorn openbb_sidecar.main:app --reload --port 8765
curl http://localhost:8765/health
```

In a docker-compose environment the sidecar is reached via service DNS (`http://openbb_sidecar:8765`), not localhost. The host port is not exposed; verify with:

```bash
docker compose port openbb_sidecar 8765
# Should return empty / "<no entry>" — the sidecar is reachable only from inside the compose network.
```

## License

This sidecar is licensed under the [GNU Affero General Public License v3.0 or later](LICENSE) — separate from and independent of the root repository LICENSE (Apache-2.0 + Commons Clause). The AGPL terms apply to this sidecar's source + binaries; the iguanatrader monolith does not derive from this code (no imports, only HTTP) and remains under its own license.

If you redistribute or run a network service derived from this sidecar, you are subject to AGPL §13 — you must offer the corresponding source to all users interacting with the service over a network. The current upstream source is at this repository under `apps/openbb-sidecar/`.

For the boundary rationale (why HTTP-loopback isolation is sufficient to keep the monolith outside the AGPL derivative-work scope), see [ADR-015](../../docs/adr/ADR-015-2026-04-28-openbb-sidecar-isolation.md).
