# Retrospective: auth-jwt-cookie

- **Archived**: 2026-05-05
- **Archive path**: openspec/changes/archive/2026-05-05-auth-jwt-cookie/
- **Schema**: spec-driven
- **PR**: #66 (squash-merged 2026-05-05T13:08:38Z, commit `9737e88`)
- **Branch**: `slice/auth-jwt-cookie` (deleted post-merge)
- **Commits on branch**: 14 (excluding the squash)

## What worked

The "foundation pre-pattern" approach saved the slice twice. When poetry.lock turned out to lack FastAPI/argon2/slowapi/pyjwt — and slice 5 (api-foundation-rfc7807) was supposed to land those at the same dep level — Option C (slice 4 ships the full backend stack + minimal `app.py`, slice 5 layers RFC 7807 / dynamic discovery on top without removing) avoided slice reordering. The same pattern worked again on the frontend side: slice 1 left `apps/web/src/` empty for slice W1, but slice 4 plant the SvelteKit scaffold (package.json + svelte.config.js + vite.config.ts + tsconfig + minimal `(app)/(auth)/+layout` stubs) for the auth surface to render. Slice W1 will extend, not replace.

The Sally pass UX baseline (locked the day before this slice started) made implementing the login surface feel mechanical rather than design-coupled — every visual decision was already mock-validated, the PRs against the locked tokens were obvious. Playwright e2e screenshots give a clean visual regression net for slice W1+ to diff against.

The mid-slice "actually run a smoke" reflex caught the migration 0002 constraint-name double-prefix bug BEFORE Arturo had to discover it post-merge. The pattern of "run the alembic upgrade in a fresh DB + curl /login + /me" should be a Gate-F default for any slice that ships Alembic migrations.

The vitest/Playwright dual-test strategy — vitest for fast logic regressions on form action / hook / allow-list (50× faster), Playwright for browser-real cookie + redirect + DOM rendering — was the right call. Arturo's pushback ("Playwright gives richer visual feedback, why ship vitest-only?") forced the right outcome over my initial too-conservative bias.

## What didn't

The slice-3 listener latent design was a footgun. Slice-4 design.md D7 cited "absent ContextVar = no filter" as slice-3's behaviour; the actual slice-3 implementation **raises** `TenantContextMissingError` for any ORM SELECT (including queries against non-scoped tables) when `tenant_id_var` is unset. This was a mis-read at design time, not a slice-3 bug per se — but it triggered three cascading fixes during CI:

1. ORM `Mapped[UUID]` requirement (slice-3 listener compares `instance.tenant_id != tenant_id_var.get()` directly; both sides MUST be UUID instances).
2. Bootstrap-path raw-SQL helpers (`bootstrap_load_user_by_id`, `bootstrap_load_user_by_email`) using `text()` to bypass the listener entirely per gotcha #23 contract.
3. SA `Uuid` SQLite storage shape — 32-char hex without hyphens; raw-SQL helpers must use `user_id.hex` not `str(user_id)`.

Each fix surfaced only when CI tests exercised the path. Local smoke caught the migration constraint-name bug; CI caught the cookie-flag case-sensitivity, the lint/pytest collection SyntaxError from `\``, and the B008 FastAPI Depends pattern. Lesson: design-doc claims about another slice's behaviour need a cross-reference grep, not just a re-read of that slice's design — the implementation is the truth.

CodeRabbit primary returned rate-limited on every L1 poll (free-tier consumed by the v0.9.x consumer-bump cascade earlier the same day). Profile B fallback per release-management.md §4.5.1 worked correctly — L2 detected my §4.5 self-review as populated and set `ai-self-review-required` to success — but the "richer cross-pair-of-eyes" aspect of CodeRabbit was effectively absent for this PR. The self-review caught the issues I already knew about; an independent reviewer might have caught more.

The `client.cookies.set(name, value, domain="test")` debugging detour cost ~30 minutes. httpx's RFC 6265 cookie domain matching doesn't accept arbitrary single-label domains for non-real hosts. Should have started with the simplest form (no domain arg) and added complexity only if needed.

## Lessons

- **Design D7-style citations of other slices' behaviour need a grep-verify step**, not just a re-read. Mis-reading slice-3 cost three cascading fixes.
- **`batch_alter_table` re-applies the naming convention to constraint names** — pass the bare name (`"role_allowed"`), never the rendered name (`"ck_users_role_allowed"`). Add this to gotchas if anyone else hits it.
- **SQLAlchemy `Uuid` on SQLite stores as 32-char hex without hyphens.** Raw-SQL bypasses use `.hex`; ORM-mapped lookups handle conversion automatically.
- **Run a fresh-DB smoke (alembic upgrade head + login curl) before declaring any migration-bearing slice "done"**. Catches things test fixtures (which create schema via `Base.metadata.create_all`) miss.
- **Playwright pays for itself on the first UI-bearing slice** because the visual baseline is the only credible defence against tokens.css/typography drift. Vitest is necessary but not sufficient.
- **Mock requirement is durable feedback** (Arturo, Sally pass): "sin un mock no puedo darte feedback". Visual decisions need a renderable artefact before approval — applies to e2e screenshots as a follow-on artefact too.
- **Profile B self-review must be specific.** Generic "no issues found" defeats the purpose. Cite file paths + behaviours + scenarios. The §4.5 in PR #66 worked because it called out the body-buffering middleware State-vs-dict bug (already fixed pre-push), the dummy-hash one-import-time computation, the regex-only `iguana_session` extraction with W1 follow-up note, etc.

## Carry-forward to next change

- **Slice O1 follow-up**: fix slice-3 `tenant_listener._inject_tenant_filter` to skip filter injection for queries that touch ONLY non-scoped tables. After that, the bootstrap raw-SQL helpers can collapse — Tenant count goes back to ORM. User-by-email/id stays raw-SQL (still no tenant context to filter on; chicken-and-egg).
- **Slice O1 follow-up**: boot-time guard that refuses `IGUANATRADER_DEV_INSECURE_COOKIE=1` when `IGUANATRADER_ENV=production`. Currently a docs-only gotcha #25 mitigation.
- **Slice O1 follow-up**: linter rule (ruff custom or simple grep) flagging ORM SELECT inside `get_current_user` (per gotcha #28 — bootstrap path must stay text()-only).
- **Slice O1 follow-up**: auto-rehash on login when stored Argon2 hash params are below current `IGUANATRADER_ARGON2_*` env (per gotcha #24).
- **Slice 5 (api-foundation-rfc7807) takes over**: dynamic router discovery via `pkgutil.iter_modules` over `iguanatrader.api.routes` (replacing the manual `app.include_router(auth_router)` in `app.py`); RFC 7807 exception handler for any `IguanaError` raised by routes (currently only the manual JSONResponse Problem Detail in `routes/auth.py` returns the right shape); OpenAPI typegen wiring.
- **Slice W1 (dashboard-svelte-skeleton) takes over**: plant `tokens.css`, install Lucide cherry-picked icon set, mount the `(app)` dashboard skeleton + Sidebar + KillSwitch, render `+error.svelte` for 404/500/401 surfaces, theme-toggle UI. The Inline-style block in `(auth)/login/+page.svelte` will move to `tokens.css` reference.
- **Slice T4 (trading-routes-and-daemon) takes over**: ship the `iguanatrader admin bootstrap-tenant <slug>` CLI that replaces the manual SQL snippet in `apps/api/README.md` Option B; mount the real `/portfolio` surface (currently a stub showing email + role). Add `iguanatrader admin rotate-jwt-secret` CLI per `docs/runbooks/auth-secret-rotation.md` §6.
- **CodeRabbit free-tier rate-limit pattern**: the playbook v0.9.x consumer-bump cascade burned the quota for the day; future Profile-A slices opening on the same day after a playbook release should expect L1 rate-limited and budget time for L2 fallback + self-review accordingly.
