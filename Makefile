# iguanatrader — root Makefile
#
# Per `release-management.md` §5 + slice plan: this is the workspace-level
# entry point. Each subsequent slice owns its `Makefile.includes` under its
# package (apps/api/Makefile.includes, apps/web/Makefile.includes, etc.) and
# this root file `-include`s them lazily so the missing-file case doesn't
# error before those slices land.

SHELL := bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

.PHONY: help bootstrap lint format type test up down clean

# Required tool versions per docs/getting-started.md.
PYTHON_MIN := 3.11
NODE_MIN := 20
PNPM_MIN := 9
POETRY_MIN := 1.8

help:
	@echo "iguanatrader — Makefile targets"
	@echo
	@echo "  bootstrap   Verify toolchain + install Python (poetry) + Node (pnpm) deps + pre-commit hooks"
	@echo "  lint        Run ruff + black --check + eslint"
	@echo "  format      Run black + prettier"
	@echo "  type        Run mypy --strict"
	@echo "  test        Run pytest + (eventually) vitest/playwright via per-package includes"
	@echo "  up          docker compose up dev profile"
	@echo "  down        docker compose down dev profile"
	@echo "  clean       Remove caches (.pytest_cache, .mypy_cache, .ruff_cache, dist, build)"
	@echo
	@echo "Per-package includes (added by subsequent slices):"
	@echo "  apps/api/Makefile.includes (slice 2)"
	@echo "  apps/web/Makefile.includes (slice W1)"

bootstrap:
	@echo "→ Verifying toolchain..."
	@command -v python >/dev/null || { echo "ERROR: python not on PATH"; exit 1; }
	@command -v node   >/dev/null || { echo "ERROR: node not on PATH"; exit 1; }
	@command -v pnpm   >/dev/null || { echo "ERROR: pnpm not on PATH (npm i -g pnpm)"; exit 1; }
	@command -v docker >/dev/null || { echo "ERROR: docker not on PATH"; exit 1; }
	@command -v age    >/dev/null || { echo "ERROR: age not on PATH (https://github.com/FiloSottile/age)"; exit 1; }
	@command -v sops   >/dev/null || { echo "ERROR: sops not on PATH (https://github.com/getsops/sops)"; exit 1; }
	@python -c "import sys; assert sys.version_info >= ($(subst .,$(comma),$(PYTHON_MIN))), f'Python >= $(PYTHON_MIN) required (got {sys.version_info})'"
	@node --version
	@pnpm --version
	@docker --version
	@age --version || true
	@sops --version | head -1
	@echo
	@echo "→ Installing Python dev deps via Poetry..."
	@python -m poetry install --no-interaction
	@echo
	@echo "→ Installing Node deps via pnpm..."
	@pnpm install --frozen-lockfile
	@echo
	@echo "→ Activating pre-commit hooks..."
	@python -m pre_commit install || python -m poetry run pre-commit install
	@echo
	@echo "✓ bootstrap complete"

# These targets defer to per-package includes; root no-op until those land.
lint:
	@echo "(lint: per-package implementations land in slices 2 + W1)"

format:
	@echo "(format: per-package implementations land in slices 2 + W1)"

type:
	@echo "(type: per-package implementations land in slices 2 + W1)"

test:
	@echo "(test: per-package implementations land in slices 2 + W1)"

up:
	docker compose up -d

down:
	docker compose down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info

# Per-package includes — added by subsequent slices. Lowercase `-include` so
# missing files do NOT cause Make to error. Anti-collision pattern per
# release-management.md §6.
-include apps/api/Makefile.includes
-include apps/web/Makefile.includes
-include apps/openbb-sidecar/Makefile.includes

# Helper for the python version check (Make can't use dots inside f-string args).
comma := ,
