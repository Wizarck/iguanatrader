---
type: gotchas
project: iguanatrader
schema_version: 1
created: 2026-04-30
updated: 2026-05-01
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

## 7. CI: `actions/checkout@v4` doesn't init submodules + private submodules need a PAT

**Surfaced**: 2026-05-01 (slice 1 PR #22 CI run).

**Symptom**: pre-commit hook step in CI fails with `FileNotFoundError: '.ai-playbook/scripts/schema_validate.py'`. After enabling `submodules: true`, fails again with `fatal: repository 'https://github.com/Wizarck/ai-playbook.git/' not found`.

**Root cause** (two layers):

1. `actions/checkout@v4` defaults to `submodules: false`. `.ai-playbook` and `.skills-sources/*` are declared as submodules in `.gitmodules`, so they don't get cloned without explicit opt-in.
2. Even with `submodules: true`, the default `GITHUB_TOKEN` is scoped only to the running repo. The submodule URLs point at private sibling repos (`Wizarck/ai-playbook`, `Wizarck/eligia-skills`), which the default token cannot access — clone fails with HTTP 404 (GitHub's deliberate obfuscation of "private" as "not found").

**Workaround**: pass a Personal Access Token with `Contents: read` for the playbook + skills repos via `actions/checkout@v4` `token:` input, AND set `submodules: true`. Token stored as repo secret `ELIGIA_GOD_MODE`.

```yaml
- uses: actions/checkout@v4
  with:
    submodules: true
    token: ${{ secrets.ELIGIA_GOD_MODE }}
```

**Status**: resolved for iguanatrader. **TODO**: codify the secret name + checkout pattern in playbook `release-management.md` so future projects don't rediscover this. Also: investigate using a GitHub App token (org-wide install) instead of per-repo PAT once the playbook moves to an org.

## 8. CI: pre-commit `language: system` hooks need their Python deps installed separately

**Surfaced**: 2026-05-01 (slice 1 PR #22 CI run).

**Symptom**: `schema-validate-agents` hook fails in CI with `❌ jsonschema is required. Install with: pip install jsonschema`. Locally it works.

**Root cause**: pre-commit hooks declared as `language: system` invoke the host Python directly (no managed venv). They depend on imports like `yaml` and `jsonschema` that exist on developer machines (system pip / poetry / conda) but aren't part of the iguanatrader poetry dev group. Adding them to dev group wouldn't help either, because the hook runs `python <script>` outside poetry's venv.

**Workaround**: install the playbook hooks' deps explicitly in the CI step before running pre-commit:

```yaml
- run: pip install jsonschema pyyaml
```

**Status**: resolved for iguanatrader. **TODO**: ai-playbook should ship a `requirements-hooks.txt` that consumer CI can install from, so the dep list is centralized + versioned.

## 9. CI: playbook scripts assume editable install (`pip install -e .ai-playbook`)

**Surfaced**: 2026-05-01 (slice 1 PR #22 CI run).

**Symptom**: After installing `jsonschema`/`pyyaml`, `schema-validate-agents` still fails in CI: `ModuleNotFoundError: No module named 'scripts'`. Locally the same script runs fine.

**Root cause**: `schema_validate.py` imports `from scripts._break_glass import ...`, which assumes the playbook ROOT (containing the `scripts/` package) is on `sys.path`. On developer machines, ai-playbook is `pip install -e`'d at the system Python level (`__editable__.ai_playbook-0.2.1.pth`), so `scripts.` is importable from anywhere. CI doesn't editable-install the submodule, so the import resolves only when the script's own directory is `sys.path[0]` — and that points to `<playbook>/scripts/`, NOT the playbook root, so `from scripts.X` fails.

**Workaround**: prepend the playbook root to `PYTHONPATH` in the CI step:

```yaml
env:
  PYTHONPATH: ${{ github.workspace }}/.ai-playbook
```

**Status**: resolved for iguanatrader. **TODO**: ai-playbook scripts should add `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` at top so they're self-contained and don't rely on editable install. Open a playbook issue.

## 10. CI: `mcp-validate` cannot run cleanly because it needs the personal layer

**Surfaced**: 2026-05-01 (slice 1 PR #22 CI run).

**Symptom**: `mcp-validate` hook reports `❌ mcp-servers.yaml rendered output diverges from committed .mcp.json`. Diff shows ~10 server entries (`atlassian-geeplo`, `camoufox`, `google-workspace-arturo`, `paperclip`, etc.) that exist in the committed `.mcp.json` but not in the CI re-render.

**Root cause**: the hook re-renders `mcp-servers.yaml` from the 3-layer SSOT (base + project + personal) and compares the result to the committed `.mcp.json`. The personal layer lives at `~/.config/mcp-servers.yaml` (or a fallback) on developer machines. CI has no personal layer, so its re-render only contains base + project entries → diverges by design.

**Workaround**: skip the hook in CI via `SKIP=mcp-validate`. The hook still runs locally on every commit by the developer.

```yaml
env:
  SKIP: mcp-validate
```

**Status**: workaround in place. **Architectural question for follow-up**: should `.mcp.json` even be committed? It's a per-developer rendered artifact — different devs would commit different `.mcp.json`s, causing constant churn. Two cleaner options:
1. Gitignore `.mcp.json` + `.gemini/settings.json` (each dev regenerates locally; no CI gate needed).
2. Commit a "skeleton" `.mcp.json` (base + project only, no personal); `mcp-validate` in CI compares against that skeleton.

Tracked as a question for the playbook maintainer.

## 11. CI: `pre-commit run --all-files` re-flags legacy issues + breaks `block-manual-spec-edit`

**Surfaced**: 2026-05-01 (PR #23 — first PR through new branch-protection flow).

**Symptom**: `Pre-commit hooks` job in CI fails on every PR with:
- `fix end of files...........Failed` — auto-fixes legacy files in main that predate the hook
- `Block manual edits to openspec/specs/...........Failed` — flags `openspec/specs/*.md` files even when the PR doesn't touch them

**Root cause**: the CI step ran `pre-commit run --all-files`, which scans every file in the repo on every PR. Two consequences:

1. **Legacy files** (whitespace, missing trailing newlines, etc.) added to main BEFORE the hook config existed get re-flagged on every PR, even when the PR never touches them. Auto-fix triggers a non-zero exit, marking the PR red for an issue it didn't introduce.
2. **`block_manual_spec_edit.py` is buggy under `--all-files`**: it considers a file "edited" if the path matches `openspec/specs/*.md`, regardless of whether the PR's diff actually modifies it. With `--all-files`, every spec file is "checked" — and since the PR's HEAD commit message lacks the `openspec-archive:` marker, the hook fails. The script doesn't know how to distinguish "file exists" from "file modified by this commit".

**Workaround**: change the CI invocation from `--all-files` to `--from-ref <BASE> --to-ref HEAD` so only files changed by THIS PR are checked. PR events use `origin/$GITHUB_BASE_REF` as base; push events use `HEAD~1`.

**Status**: workaround in iguanatrader's `ci.yml`. **Upstream fix queued** for ai-playbook: `block_manual_spec_edit.py` should resolve "file modified vs file exists" via `git diff --name-only HEAD~1 HEAD --` filter instead of relying on the caller to pass only modified files. Phase 1 of multi-AI-dev release-management migration tracks this.

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
