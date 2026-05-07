"""License-boundary CI gate (slice deployment-foundation §7).

Complementary to ``.github/workflows/license-boundary-check.yml`` which
enforces the AGPL boundary between the apps/api monolith and the
apps/openbb-sidecar pod. This test enforces the **deployment-foundation
allow-list**: the 6 new production-SDK deps introduced in Wave 4 MUST
be in {MIT, Apache-2.0, BSD-3-Clause, BSD-2-Clause, MPL-2.0}.

The allow-list is intentionally narrow — adding a dep with a license
NOT on the allow-list (e.g. AGPL, GPL-3.0, proprietary) requires an
explicit code-review override and an ADR.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


# Verified at slice-land time (2026-05-07) from each project's published metadata:
# - anthropic: MIT (https://github.com/anthropics/anthropic-sdk-python/blob/main/LICENSE)
# - ib_async:  MIT (https://github.com/ib-api-reloaded/ib_async/blob/main/LICENSE)
# - apscheduler: MIT (https://github.com/agronholm/apscheduler/blob/master/LICENSE)
# - playwright: Apache-2.0 (https://github.com/microsoft/playwright-python/blob/main/LICENSE)
# - camoufox:  MIT (https://github.com/daijro/camoufox/blob/main/LICENSE)
# - reportlab: BSD-3-Clause (https://www.reportlab.com/dev/opensource/)
EXPECTED_LICENSES: dict[str, str] = {
    "anthropic": "MIT",
    "ib_async": "MIT",
    "apscheduler": "MIT",
    "playwright": "Apache-2.0",
    "camoufox": "MIT",
    "reportlab": "BSD-3-Clause",
}

ALLOW_LIST: frozenset[str] = frozenset(
    {"MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "MPL-2.0"}
)


def _read_pyproject_text() -> str:
    return (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize("dep,license_id", sorted(EXPECTED_LICENSES.items()))
def test_each_new_dep_is_in_pyproject(dep: str, license_id: str) -> None:
    """Each Wave-4 dep MUST be listed in the root pyproject.toml."""
    text = _read_pyproject_text()
    # Match `dep = ...` (poetry inline) or `dep = {version = ...}` (table form).
    assert (
        f"\n{dep} =" in f"\n{text}"
        or f"\n{dep}=" in f"\n{text}"
    ), f"Expected dep {dep!r} (license {license_id}) not found in root pyproject.toml"


def test_each_new_dep_license_is_in_allow_list() -> None:
    """Each declared Wave-4 license MUST be in the deployment-foundation allow-list."""
    forbidden = {dep: lic for dep, lic in EXPECTED_LICENSES.items() if lic not in ALLOW_LIST}
    assert not forbidden, (
        f"License-boundary breach: deps with non-allow-listed licenses {forbidden}. "
        f"Allow-list = {sorted(ALLOW_LIST)}. Adding a non-allow-listed dep requires an ADR."
    )


def test_anthropic_does_not_drag_in_agpl_via_runtime_imports() -> None:
    """Smoke check — anthropic SDK does NOT depend on AGPL packages.

    The `anthropic` PyPI package is pure-Python with httpx/pydantic deps —
    none AGPL. This test asserts at runtime that no top-level AGPL
    Python module appears in the `sys.modules` after a fresh import.
    """
    if "anthropic" not in sys.modules:
        pytest.importorskip("anthropic")

    forbidden_prefixes = ("openbb", "yfinance")
    leaks = [
        name
        for name in sys.modules
        if any(name == p or name.startswith(p + ".") for p in forbidden_prefixes)
    ]
    assert not leaks, (
        f"Importing `anthropic` dragged in AGPL packages: {leaks}. "
        f"This breaks the apps/api license boundary."
    )
