## ADDED Requirements

### Requirement: LICENSE file contains Apache-2.0 + Commons Clause v1.0 verbatim

The system SHALL provide a root `LICENSE` file whose contents are the byte-exact concatenation of the canonical Apache License 2.0 text (from https://www.apache.org/licenses/LICENSE-2.0.txt) and the Commons Clause v1.0 text (from https://commonsclause.com/), separated by a clearly delimited section break. The combined file SHALL be checksum-verifiable by a CI workflow.

#### Scenario: LICENSE matches recorded sha256 checksums

- **WHEN** the `license-boundary-check.yml` workflow's checksum step runs against the `LICENSE` file
- **THEN** the Apache-2.0 segment's sha256 matches the recorded `LICENSE_APACHE2_SHA256` constant and the Commons Clause segment's sha256 matches the recorded `LICENSE_COMMONS_CLAUSE_SHA256` constant

#### Scenario: A tampered LICENSE fails CI

- **GIVEN** the LICENSE file is modified (e.g. a single character changed in the Apache-2.0 text)
- **WHEN** the license-boundary-check workflow runs
- **THEN** the checksum step exits non-zero and the workflow fails with a message identifying which segment's checksum did not match

### Requirement: SECURITY.md declares the vulnerability disclosure policy

The system SHALL provide a root `SECURITY.md` file declaring a vulnerability disclosure policy with: (a) supported versions, (b) reporting channel (private, e.g. GitHub security advisories or a contact email), (c) expected response time, (d) explicit non-disclosure of unfixed vulnerabilities to public channels.

#### Scenario: SECURITY.md is present and contains the four required policy elements

- **WHEN** the contents of `SECURITY.md` are read
- **THEN** the file contains sections covering supported versions, reporting channel, response SLA, and a non-public-disclosure clause

### Requirement: README.md links to canonical project documents

The system SHALL provide a root `README.md` containing: (a) project tagline, (b) link to `docs/prd.md`, (c) link to `docs/architecture-decisions.md`, (d) link to `docs/getting-started.md`, (e) license declaration referencing `LICENSE`, (f) pointer to `CONTRIBUTING.md`.

#### Scenario: README.md links resolve

- **WHEN** the markdown links in `README.md` are followed (relative paths from repo root)
- **THEN** each link resolves to an existing file in the repo (PRD, ADR doc, getting-started, LICENSE, CONTRIBUTING)

### Requirement: getting-started.md provides a runnable onboarding path

The system SHALL provide `docs/getting-started.md` containing: (a) prerequisites list (Python 3.11+, Node 20+, pnpm 9+, Poetry 1.8+, Docker, age, sops, with verification commands), (b) a JSON1 SQLite smoke-test command that confirms the local SQLite has JSON1 extension support, (c) install steps mapped to `make bootstrap`, (d) a "what's next" pointer to `docs/architecture-decisions.md` and to a paper-trading walkthrough placeholder for v1.

#### Scenario: getting-started.md JSON1 verify command runs

- **WHEN** a developer copy-pastes the JSON1 verify command from `docs/getting-started.md` into their shell
- **THEN** the command produces a clear pass/fail signal (e.g. `python -c "import sqlite3; sqlite3.connect(':memory:').execute('SELECT json(\"{}\")');"` exits 0 if JSON1 is present, non-zero otherwise)

### Requirement: Four ADR placeholder files exist in `docs/adr/`

The system SHALL provide four ADR files under `docs/adr/`: `ADR-014-2026-04-28-bitemporal-research-facts.md`, `ADR-015-2026-04-28-openbb-sidecar-isolation.md`, `ADR-016-2026-04-28-research-domain-and-backtest-skip.md`, `ADR-017-2026-04-28-scrape-ladder-4-tiers.md`. Each file SHALL include frontmatter (`status: proposed`, `date: 2026-04-28`, `decided-by: Arturo Ramírez`) and a one-paragraph stub citing where the decision is recorded in `docs/architecture-decisions.md` and `docs/hitl-gates-log.md`. ADR-016 (research domain + backtest skip) MAY be filled out fully in this slice since the decision is self-contained at Gate A amendment.

#### Scenario: All four ADR files exist with correct frontmatter

- **WHEN** the contents of `docs/adr/ADR-014-*.md`, `ADR-015-*.md`, `ADR-016-*.md`, `ADR-017-*.md` are read
- **THEN** each file's frontmatter contains `status: proposed`, `date: 2026-04-28`, and `decided-by: Arturo Ramírez (arturo6ramirez@gmail.com)`

#### Scenario: ADR-016 is fully populated, others are stubs

- **WHEN** the body of each ADR is inspected
- **THEN** ADR-016 contains the full Context / Decision / Consequences sections describing the research domain addition + backtest skip; ADRs 014, 015, 017 contain a stub paragraph plus a "Full content pending" marker pointing to the slice that owns the decision (R1 for 014, R4 for 015, R3 for 017)

### Requirement: CONTRIBUTING.md and CHANGELOG.md and THIRD_PARTY_NOTICES.md exist as placeholders

The system SHALL provide root `CONTRIBUTING.md` (placeholder for v1, noting that contribution guidelines will be fleshed out post-MVP), `CHANGELOG.md` (with an initial `## [0.0.0] — 2026-04-29 — bootstrap` entry), and `THIRD_PARTY_NOTICES.md` (initially empty body, populated when external code is copied with attribution).

#### Scenario: All three files exist and are non-empty

- **WHEN** the repo root is inspected after this slice's merge
- **THEN** `CONTRIBUTING.md`, `CHANGELOG.md`, and `THIRD_PARTY_NOTICES.md` each exist and contain at minimum a heading and one explanatory paragraph (no zero-byte files)
