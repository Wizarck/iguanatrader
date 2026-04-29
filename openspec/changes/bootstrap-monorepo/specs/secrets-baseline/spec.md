## ADDED Requirements

### Requirement: Repository declares a SOPS+age secrets layout under `.secrets/`

The system SHALL provide a `.secrets/.sops.yaml` file declaring the age public keys authorised to decrypt repo secrets, and SHALL provide three encrypted env templates: `.secrets/dev.env.enc`, `.secrets/paper.env.enc`, `.secrets/live.env.enc`. Each template SHALL contain placeholder envs (no real secrets) and SHALL be valid SOPS-encrypted YAML or dotenv format readable by `sops -d`.

#### Scenario: .sops.yaml declares the encryption rule for .secrets/*.env

- **WHEN** the contents of `.secrets/.sops.yaml` are read
- **THEN** the file declares a `creation_rules` entry whose `path_regex` matches `.secrets/.*\.env$` and whose `age` recipient list contains at least one valid age public key (Arturo's)

#### Scenario: All three encrypted templates decrypt cleanly with the recipient's age key

- **WHEN** a developer with the matching age private key runs `sops -d .secrets/dev.env.enc`, `sops -d .secrets/paper.env.enc`, and `sops -d .secrets/live.env.enc`
- **THEN** each decryption succeeds and emits a plaintext envfile containing only placeholder values (e.g. `IBKR_HOST=<placeholder>`, `BROKER_API_KEY=<placeholder>`), no real credentials

#### Scenario: Plaintext .env files are gitignored

- **WHEN** the contents of `.gitignore` are read
- **THEN** `.gitignore` includes pattern entries that prevent any unencrypted `.env` files from being committed (e.g. `.secrets/*.env` without `.enc` suffix)

### Requirement: Pre-commit gitleaks hook scans for unencrypted secrets

The system SHALL configure the pre-commit `gitleaks` hook to scan every file in the staging area on commit, with the `.gitleaksignore` safe-list documenting any explicit exemptions. Running `gitleaks` against the bootstrap tree SHALL find zero violations.

#### Scenario: gitleaks finds zero violations on the bootstrap tree

- **WHEN** `gitleaks detect --source . --no-banner` is run after this slice's merge
- **THEN** the command exits 0 with no findings reported

#### Scenario: A planted unencrypted secret would be caught

- **GIVEN** a hypothetical `apps/api/test-leak.txt` containing a recognisable AWS access key
- **WHEN** `pre-commit run --files apps/api/test-leak.txt` is executed
- **THEN** the gitleaks hook fails with a non-zero exit code and reports the leak before any other hook runs (test verifies hook ordering)

### Requirement: AGENTS.md secrets hard rule is enforced by tooling

The system SHALL ensure that the AGENTS.md §4 hard rule "API keys MUST live in SOPS-encrypted env files, never in code or config" is enforceable: any commit that introduces a recognisable API key in plaintext SHALL be blocked at the pre-commit stage.

#### Scenario: A plaintext API key in a Python file is blocked

- **GIVEN** a developer attempts to commit a file containing the literal string `OPENAI_API_KEY = "sk-proj-..."`
- **WHEN** `git commit` runs the pre-commit hook chain
- **THEN** gitleaks rejects the commit before it reaches the index, with a message identifying the leak
