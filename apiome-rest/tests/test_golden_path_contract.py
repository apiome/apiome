"""Golden-path UI <-> REST contract: the REST side (RC1-3.1, #3616).

The product's golden path (``docs/GOLDEN_PATH.md``) depends on a small, stable set of REST operations.
This test asserts every operation in the shared contract (``scripts/golden_path/contract.json``) is
present in the live REST OpenAPI surface with the expected HTTP method. If a router is renamed, moved,
or has its method changed, this goes red — which is exactly the regression signal RC1-3.1 wants the CI
gate to carry. The matching UI-side check lives in
``apiome-ui/tests/contract/rest-golden-path-contract.test.ts``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.config import settings
from app.main import app

_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "golden_path" / "contract.json"
)


def _load_contract() -> List[Dict[str, Any]]:
    data = json.loads(_CONTRACT_PATH.read_text())
    return data["operations"]


def _openapi_paths() -> Dict[str, Any]:
    # The OpenAPI schema is independent of rate limiting; disable it so generating the schema never
    # depends on middleware configuration.
    settings.rate_limit_enabled = False
    return app.openapi()["paths"]


def test_contract_file_is_present_and_non_empty():
    ops = _load_contract()
    assert ops, "golden-path contract defines no operations"


@pytest.mark.parametrize("op", _load_contract(), ids=lambda o: f"{o['method']} {o['path']}")
def test_rest_exposes_golden_path_operation(op: Dict[str, Any]):
    """Every golden-path operation must exist in the REST OpenAPI surface with its method."""
    paths = _openapi_paths()
    path = op["path"]
    method = op["method"].lower()

    assert path in paths, (
        f"Golden-path step {op['step']!r} expects REST endpoint {op['method']} {path}, "
        f"but it is absent from the OpenAPI surface. If the route was intentionally changed, update "
        f"scripts/golden_path/contract.json and docs/GOLDEN_PATH.md together."
    )
    assert method in paths[path], (
        f"Golden-path step {op['step']!r} expects method {op['method']} on {path}, "
        f"but only {sorted(m.upper() for m in paths[path])} are defined."
    )
