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

**Status**: workaround in iguanatrader's `ci.yml`. **Upstream fix shipped** in ai-playbook v0.8.0-rc7 (`block_manual_spec_edit.py` now intersects input candidates with the actual diff before applying the archive-marker check).

## 12. `bootstrap_gh_project.py --profile auto` overwrites project-specific required checks

**Surfaced**: 2026-05-01 (first idempotent re-run on iguanatrader after v0.8.0-rc7 bump).

**Symptom**: Re-running `bootstrap_gh_project.py --owner X --project-number N --repo Y --profile auto` reduces the project's required status checks from project-specific (e.g. 7 for iguanatrader: 5 universal + AGPL boundary + LICENSE checksums) to the script's default (5 universal). Branch protection PUT replaces the entire `required_status_checks.contexts` array.

**Root cause**: `apply_branch_protection()` in v0.8.0-rc7 sends the full payload via `gh api PUT`. GitHub's `PUT /repos/{owner}/{repo}/branches/{branch}/protection` is REPLACE semantics, not MERGE. The `--required-checks` flag accepts a comma-separated list and the default ships only the 5 universal checks. Project-specific checks (AGPL boundary, LICENSE checksums, lighthouse-perf, contract tests, etc.) get silently dropped.

**Workaround**: pass `--required-checks` explicitly with the FULL list every time:

```bash
python -m scripts.bootstrap_gh_project \
    --owner Wizarck --project-number 2 \
    --repo Wizarck/iguanatrader \
    --profile auto \
    --required-checks "Lint (ruff + black --check),Type check (mypy --strict),Test (pytest),Secrets scan (gitleaks),Pre-commit hooks,AGPL boundary check (apps/api/ vs apps/openbb-sidecar/),Verify LICENSE checksums"
```

Per-consumer the right invocation lives somewhere durable (Makefile target, runbook, etc.) — NOT in operator memory.

**Status**: workaround documented per-consumer. **Upstream fix queued**: `apply_branch_protection` should READ existing protection first and UNION the user-provided checks with what's already there; OR accept `--required-checks-add` (additive) as an alternative to `--required-checks` (replace). Track for v0.8.1.

## 13. `bootstrap_gh_project.py apply_branch_protection` hardcodes `main` as default branch

**Surfaced**: 2026-05-01 (v0.8.0 rollout to openTrattOS, which uses `master`).

**Symptom**: `bootstrap_gh_project.py --profile auto` against openTrattOS errors with `branch protection PUT failed: gh: Branch not found (HTTP 404)`. Repo settings + project schema steps complete fine; only the branch protection step fails.

**Root cause**: `apply_branch_protection()` in v0.8.0 hardcodes the URL path `repos/{repo}/branches/main/protection`. openTrattOS's default branch is `master` (legacy from before GitHub's 2020 rename guidance). The PUT against `/branches/main/` 404s because no such branch exists.

**Workaround**: skip Profile A branch protection on `master`-default repos for now. Repo settings + auto-merge + project schema still apply correctly. Apply branch protection manually via UI or via `gh api PUT repos/<r>/branches/master/protection --input <json>` when needed.

**Status**: **Upstream fix queued** for ai-playbook v0.8.1: `apply_branch_protection` should query `gh repo view --json defaultBranchRef` (or the equivalent GraphQL field) and use the actual default branch name. Until then, consumer projects on non-`main` defaults need manual protection setup.

---

## 14. Submodule untracked content trips `opsx_apply_companion` clean-tree check

**Surfaced**: 2026-05-01 (slice 2, setup).

**Symptom**: `python -m scripts.opsx_apply_companion --change-id <id> ...` exits 2 with `error: working tree is dirty. … M .ai-playbook` even though the consumer (iguanatrader) has no real changes. `cd .ai-playbook && git status` reveals the leaks: `?? hindsight-queue.jsonl` + `?? notifications.jsonl`.

**Root cause**: The playbook submodule's operational scripts (`notify.py`, `retain_memory.py`) append to JSONL queues inside the submodule path. The playbook upstream `.gitignore` does not yet ignore `*.jsonl`, so those files show as untracked. By default `git status --porcelain` in the parent repo flags submodules with untracked content as `M`, which the companion's clean-tree gate rejects.

**Workaround**: add `ignore = untracked` to every `[submodule …]` block in `.gitmodules` (committed in `slice/shared-primitives` infra commit `chore: ignore untracked content in submodules`). The submodule itself still tracks its committed content; only its operational scratch files become invisible to the parent.

**Status**: ⚠️ active — `ignore = untracked` is the workaround. Permanent fix requires the playbook upstream to gitignore `*.jsonl`. Filed as upstream follow-up.

## 15. mypy + Enum literal narrowing across method-driven state mutations

**Surfaced**: 2026-05-01 (slice 2, group 4 — HeartbeatMixin tests).

**Symptom**: A linear test that calls `mark_connected()` → `await mark_disconnected()` → `mark_reconnecting()` and asserts `a.state == ConnectionState.X` after each step trips `mypy --strict` with `Non-overlapping equality check (left operand: Literal[ConnectionState.CONNECTED], right operand: Literal[ConnectionState.DISCONNECTED]) [comparison-overlap]` on the second assertion onward.

**Root cause**: After `mark_connected()`, mypy narrows `a.state` to `Literal[ConnectionState.CONNECTED]` (because the method body assigns that exact literal). It does NOT widen the narrow back when later methods mutate `_state`. Subsequent comparisons against a different literal therefore become non-overlapping in mypy's eyes — a documented limitation, not an mypy bug.

**Workaround**: in tests that exercise multi-step state machines, suppress per-line with `# type: ignore[comparison-overlap]` on the assertions that follow the first transition. (For one or two lines this is cleaner than refactoring the test or using `cast`.) Better: split the test into smaller methods that don't span multiple transitions, when feasible.

**Status**: ⚠️ active — known mypy limitation. Don't bother widening the type with `cast(ConnectionState, a.state)` — mypy re-narrows immediately.

## 16. ruff `from datetime import timezone` → `from datetime import UTC` collides with mypy `no_implicit_reexport`

**Surfaced**: 2026-05-01 (slice 2, group 2 — `shared/time.py`).

**Symptom**: ruff's `UP` (pyupgrade) rule auto-rewrites `from datetime import timezone; UTC = timezone.utc` to `from datetime import UTC; UTC = UTC` (the second line is dead). Cleaning up by removing the dead alias and re-exporting the stdlib `UTC` via `__all__` then trips mypy's `no_implicit_reexport` rule because the import is not aliased explicitly.

**Root cause**: With `[tool.mypy].no_implicit_reexport = true`, names imported into a module are NOT considered part of that module's public surface unless aliased like `from X import Y as Y`. Ruff's auto-fix doesn't add the alias.

**Workaround**: write the import as `from datetime import UTC as UTC` (the explicit re-export form). Combine with a separate `from datetime import datetime, timedelta` line if needed (ruff's `I001` import-sorting rule is fine with two lines from the same module when one of them uses an alias).

**Status**: ⚠️ active — small footgun whenever a public symbol is re-exported from stdlib.

## 17. Hypothesis + `asyncio.run` on Windows leaks ProactorEventLoop FDs → ResourceWarning

**Surfaced**: 2026-05-01 (slice 2, groups 4 & 5 — `test_heartbeat_idempotency.py`, `test_message_ordering.py`).

**Symptom**: A property test that calls `asyncio.run(_run(...))` inside `@given` and runs hundreds of examples emits `ResourceWarning: unclosed event loop <ProactorEventLoop ...>` at process teardown. With `[tool.pytest.ini_options].filterwarnings = ["error"]` (slice 1 default), this turns into a test failure.

**Root cause**: On Windows, asyncio defaults to `ProactorEventLoop` since Python 3.8. Each `asyncio.run()` creates and closes a fresh loop; the proactor implementation leaks a small number of FDs / GC-tracked objects per cycle. Across hundreds of Hypothesis examples this snowballs into a visible warning at GC time.

**Workaround**: at the top of any property-test module that uses `asyncio.run` heavily, force the selector loop policy: `if sys.platform == "win32": asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`. Selector loops are leak-free for our usage.

**Status**: ⚠️ active — Windows-only quirk. Not a problem on CI's Ubuntu runner. Linux/macOS devs can ignore.

## 18. `Money(amount=..., currency=...)` strict input typing requires `init=False` on the dataclass

**Surfaced**: 2026-05-01 (slice 2, group 3 — `shared/types.py`).

**Symptom**: A frozen dataclass declared as `Money(amount: Decimal, currency: str)` cannot accept `Money("100.00", "USD")` (str) or `Money(100, "USD")` (int) under `mypy --strict`. Loosening the field annotation to `Decimal | int | str` then makes every read of `m.amount` typed as the union — even though at runtime the constructor coerces to `Decimal`.

**Root cause**: `@dataclass`'s auto-generated `__init__` mirrors the field annotations. There's no built-in way to have wide-input + narrow-storage type semantics with the auto-init. `dataclasses.field(default=...)` doesn't help either.

**Workaround**: declare the dataclass with `@dataclass(frozen=True, slots=True, init=False)` and provide a custom `__init__(self, amount: Decimal | int | str, currency: str)` that coerces and stores via `object.__setattr__(self, "amount", Decimal(amount))`. The field annotation stays `Decimal`, so reads are correctly typed.

**Status**: ⚠️ active — works fine but is not the obvious-first solution; document on the Money class.

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
