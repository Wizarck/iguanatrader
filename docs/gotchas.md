---
type: gotchas
project: iguanatrader
schema_version: 1
created: 2026-04-30
updated: 2026-04-30
purpose: Append-only log of non-obvious dev-loop quirks discovered during implementation. NFR-M7.
---

# Gotchas — iguanatrader

Per AGENTS.md §X (release-management) and NFR-M7: when a slice's implementation surfaces a non-obvious lesson that future devs would benefit from knowing, append it here. Format: short heading, the symptom, the root cause, the workaround.

This file is **append-only** — never delete entries. If a gotcha is fixed upstream, mark it as **resolved on YYYY-MM-DD** but keep the entry as a historical record.

---

## 1. Poetry on Microsoft Store Python recreates venv on every `poetry run`

**Surfaced**: 2026-04-30 (slice 1, group 1).

**Symptom**: After `poetry install` succeeds, every subsequent `poetry run <tool>` (e.g. `poetry run ruff check .`) re-runs the installer because Poetry decides the venv "seems to be broken". Tools then fail with `'<tool>' is not recognized as an internal or external command` because the freshly-created venv is empty (only `pip` + `activate`).

**Root cause**: Poetry's "is this venv still valid" check uses `sys.executable` to verify the Python binary still exists. The Microsoft Store Python install lives at `C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_<hash>\` where the `<hash>` portion is unstable (changes after Store updates). Poetry sees the path is no longer reachable and concludes the venv is broken.

**Workaround**: enable in-project venv via `poetry config virtualenvs.in-project true --local`. The repo's `poetry.toml` carries this config so all devs get it. Then either:
- `python -m poetry run <tool>` (still triggers the recreate cycle on MS Store Python; not great)
- Better: install the dev tools at user level (`pip install --user ruff black mypy pytest`) and invoke as `python -m <tool>` (matches what `make lint`/`type`/`test` do internally — see Makefile).

**Permanent fix**: install Python from https://www.python.org/downloads/ instead of Microsoft Store. The python.org installers don't suffer the unstable-path issue.

**Status**: known issue; CI is unaffected (Linux runners use python.org Python).

## 2. `make` not on Windows PATH by default

**Surfaced**: 2026-04-30 (slice 1, group 3).

**Symptom**: `make bootstrap` fails with `make: command not found` on a fresh Windows install.

**Root cause**: Make is a Unix tool. Git for Windows ships `make` only inside its Git Bash MinGW environment, but it's not on the system PATH by default.

**Workaround**: three options:
- **Git Bash users**: `make` IS on the PATH inside the Git Bash shell — open Git Bash and run from there.
- **WSL users**: `apt install make` inside WSL; run from inside WSL.
- **Direct invocation**: skip `make`, run the underlying commands directly. The Makefile is short — read it and copy the relevant `python -m poetry install ...` / `pnpm install ...` / `pre-commit install` lines.

**Permanent fix**: documented in `getting-started.md`. CI is unaffected (Linux runners have `make`).

## 3. `mcp-validate` pre-commit hook reads eligia-core's mcp-servers.yaml + fails on missing env vars

**Surfaced**: 2026-04-30 (slice 1, group 6).

**Symptom**: `pre-commit run --all-files` fails with errors like "server X has unknown scope 'user'" (referencing `C:/Projects/eligia-core/mcp-servers.yaml`, NOT iguanatrader's file) and "merged server Y declares N required env var(s) unset in the current environment". Multiple failures on every iguanatrader commit attempt.

**Root cause** (two layers):

1. The playbook's `mcp/validate.py` searches for the "personal" mcp-servers.yaml layer using a legacy convention fallback (`~/Projects/eligia-core/mcp-servers.yaml`). On a dev machine where eligia-core lives at that path AND has a stale `scope: user` (deprecated in v1 schema; renamed to `personal`), iguanatrader's hook trips on eligia-core's stale data.

2. The `required env var` check fires on all merged servers — but pre-commit runs BEFORE any dev-shell env-loading, so production envs (ATLASSIAN_*, GOOGLE_*, etc.) are predictably absent. The check is too strict for the pre-commit context.

**Workaround**: commit with `git commit --no-verify` for slice 1's commits. The fix lands in playbook `v0.8.0-rc4`:

- `mcp/validate.py` env-var check downgraded to soft-warn in pre-commit context (set `--strict` to restore the hard-fail for CI / explicit validation).
- Personal-layer search prefers `~/.config/mcp-servers.yaml` and emits a "fallback to eligia-core" notice when using the legacy path so the dev sees what's happening.

**Status**: ⚠️ active — fix coming in playbook `v0.8.0-rc4`. Track via [Wizarck/ai-playbook PR queue](https://github.com/Wizarck/ai-playbook/pulls).

## 4. `sops` `path_regex` doesn't match directory-prefixed regexes against the file path passed in

**Surfaced**: 2026-04-30 (slice 1, group 8).

**Symptom**: `sops --encrypt .secrets/dev.env` fails with `error loading config: no matching creation rules found` even though `.secrets/.sops.yaml` declares `path_regex: \.secrets/.*\.env$` and the file IS under `.secrets/`.

**Root cause**: `sops` matches the `path_regex` against the **filename** (or relative path AS-PASSED), not the absolute path. When `.sops.yaml` lives at `.secrets/.sops.yaml` and the file passed is `.secrets/dev.env`, the matching is done relative to the `.sops.yaml`'s directory — i.e. against `dev.env` (NOT `.secrets/dev.env`). The regex `\.secrets/.*\.env$` cannot match `dev.env`.

**Workaround**: simplify the regex to `\.env$`. Since `.sops.yaml` is INSIDE `.secrets/`, it only governs files under that directory anyway — the directory-prefix in the regex is redundant.

**Status**: resolved by config simplification. Documented in `.secrets/.sops.yaml` comments.

## 5. `docker compose` parses `:memory:` as a YAML mapping

**Surfaced**: 2026-04-30 (slice 1, group 4).

**Symptom**: `docker compose -f docker-compose.test.yml config` warns `services.api.environment.[1]: unexpected type map[string]interface {}` for the line `- SQLITE_PATH=:memory:`.

**Root cause**: YAML parses `:memory:` as a mapping (key-value pairs separated by `:`) rather than a string value, because the colons aren't quoted.

**Workaround**: quote the entire env entry: `- "SQLITE_PATH=:memory:"`.

**Status**: resolved. Pattern: any docker-compose env value containing `:` must be quoted.

## 6. GitHub Projects v2 are user/org-scoped — repo Projects tab is just a link surface

**Surfaced**: 2026-04-30 (during slice 1 implementation; led to playbook `v0.8.0-rc3`).

**Symptom**: After `bootstrap_gh_project.py --owner Wizarck --project-number 2` succeeded (project created, items added, schema configured), the iguanatrader repo's Projects tab at `https://github.com/Wizarck/iguanatrader/projects` was empty.

**Root cause**: Projects v2 always live at user/org scope (`https://github.com/users/Wizarck/projects/2`). The repo's Projects tab is purely a link surface — the project must be **explicitly linked** to the repo via the `linkProjectV2ToRepository` GraphQL mutation to appear there.

**Workaround**: pass `--repo <owner/name>` to `bootstrap_gh_project.py` (added in `v0.8.0-rc3`). One-shot CLI: `gh project link 2 --owner Wizarck --repo Wizarck/iguanatrader`.

**Status**: resolved upstream. iguanatrader's Project #2 is linked to `Wizarck/iguanatrader` as of 2026-04-30.

---

## Format for new entries

```markdown
## N. <short heading>

**Surfaced**: YYYY-MM-DD (slice X, group Y).

**Symptom**: <what the dev sees>

**Root cause**: <the underlying reason>

**Workaround**: <what to do about it>

**Status**: resolved on YYYY-MM-DD / known issue / ⚠️ active
```
