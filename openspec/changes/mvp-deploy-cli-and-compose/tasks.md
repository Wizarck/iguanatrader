# Tasks: mvp-deploy-cli-and-compose

- [ ] 1. `apps/api/src/iguanatrader/cli/admin.py` — `bootstrap-tenant` Typer command with `--email`, `--password`, `--force-reset`
- [ ] 2. `apps/api/tests/integration/test_admin_bootstrap_tenant.py` — 3 cases (happy, duplicate, force-reset)
- [ ] 3. `apps/api/Dockerfile` — multi-stage Python 3.11 + Poetry → uvicorn runtime
- [ ] 4. `apps/web/Dockerfile` — multi-stage Node 20 + pnpm → adapter-node runtime
- [ ] 5. `docker-compose.mvp.yml` — minimal 2-service stack + named volume
- [ ] 6. `docs/mvp-deploy.md` — 7-step VPS deploy playbook + ops commands + troubleshooting
- [ ] 7. `.github/workflows/build-images.yml` restructure — config validation + per-image build jobs + path-filtered PR trigger
- [ ] 8. Local lint + black verde; svelte-check verde
- [ ] 9. Push + open PR + wait CI green (now includes Docker build)
- [ ] 10. Merge + archive + retro fill
