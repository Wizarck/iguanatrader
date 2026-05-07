"""Helm chart lint CI gate (slice deployment-foundation §7).

Shells out to ``helm lint helm/iguanatrader-stack/`` and asserts exit 0.
Skipped when the ``helm`` binary is not on the runner ``PATH`` —
the GitHub workflow installs it via ``azure/setup-helm`` before running
this test.

The chart's `litestream.s3.bucket` is REQUIRED in production but blank
by default (Fleet bundle override populates it per env). For lint we
inject a placeholder via ``--set`` so the chart renders fully.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
CHART_DIR = REPO_ROOT / "helm" / "iguanatrader-stack"


@pytest.fixture(scope="module")
def helm_bin() -> str:
    binary = shutil.which("helm")
    if binary is None:
        pytest.skip("helm CLI not on PATH; install via azure/setup-helm in CI")
    return binary


def test_chart_lint_exits_clean(helm_bin: str) -> None:
    assert CHART_DIR.exists(), f"Chart directory missing: {CHART_DIR}"

    result = subprocess.run(
        [helm_bin, "lint", str(CHART_DIR), "--set", "litestream.s3.bucket=ci-placeholder"],
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert (
        result.returncode == 0
    ), f"`helm lint` failed (exit {result.returncode}). Output:\n{output}"


def test_chart_template_renders_valid_yaml(helm_bin: str) -> None:
    """`helm template` must produce parseable Kubernetes manifests."""
    yaml = pytest.importorskip("yaml")  # PyYAML — already a dev dep transitively.

    result = subprocess.run(
        [
            helm_bin,
            "template",
            "iguanatrader",
            str(CHART_DIR),
            "--set",
            "litestream.s3.bucket=ci-placeholder",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0
    ), f"`helm template` failed (exit {result.returncode}):\n{result.stderr}"

    docs = list(yaml.safe_load_all(result.stdout))
    assert len(docs) >= 5, f"Expected ≥5 K8s resources, got {len(docs)}"
    for doc in docs:
        if doc is None:
            continue
        assert "kind" in doc, f"Resource missing kind: {doc}"
        assert "apiVersion" in doc, f"Resource missing apiVersion: {doc}"
