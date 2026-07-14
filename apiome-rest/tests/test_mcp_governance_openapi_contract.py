"""OpenAPI version + schema contract snapshots for MTG governance (MTG-3.5, #4779).

Locks the Rest surface shipped by MTG-3.1–3.4:

* ``info.version`` after the MTG REST release-train bump
* Path / HTTP method presence for mcp-policy and mcp-keys(/capabilities)
* Structural snapshots of policy and key-capability component schemas

Enrichment noise (examples, decorative titles) is stripped so fixtures stay
stable under cosmetic OpenAPI enrichment churn while still catching property,
type, enum, required, and $ref regressions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Set

import pytest

from app.config import settings
from app.main import app

_FIXTURE_DIR = (
    Path(__file__).resolve().parent / "fixtures" / "mtg_governance_openapi"
)

# Closeout semver for the MTG EPIC-3 REST train (AGENTS.md: bump when contract lands).
_MTG_REST_OPENAPI_VERSION = "1.0.75"

_GOVERNANCE_PATHS: Mapping[str, Set[str]] = {
    "/v1/tenants/{tenant_slug}/mcp-policy": {"get", "put"},
    "/v1/tenants/{tenant_slug}/mcp-keys": {"get", "post"},
    "/v1/tenants/{tenant_slug}/mcp-keys/{key_id}": {"get", "patch", "delete"},
    "/v1/tenants/{tenant_slug}/mcp-keys/{key_id}/capabilities": {"put"},
    "/v1/tenants/{tenant_slug}/mcp-keys/{key_id}/capabilities/preview": {"post"},
}

_POLICY_SCHEMAS = (
    "TenantMcpPolicyTool",
    "TenantMcpPolicyPutRequest",
    "TenantMcpPolicyResponse",
)

_KEY_CAPABILITY_SCHEMAS = (
    "McpKeyCapabilitiesRequest",
    "McpKeyCapabilitiesResponse",
    "McpKeyCapabilitiesPreviewResponse",
    "McpKeyEffectiveToolRow",
)

_SCHEMA_NAMES = _POLICY_SCHEMAS + _KEY_CAPABILITY_SCHEMAS

# Fields that enrich_openapi_spec / FastAPI vary without changing the contract.
_STRIP_KEYS = frozenset(
    {
        "example",
        "examples",
        "title",
        "description",
        "default",
        "maxItems",
        "minLength",
        "maxLength",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }
)


def _live_spec() -> Dict[str, Any]:
    """Return the enriched app OpenAPI document (rate limit irrelevant)."""
    settings.rate_limit_enabled = False
    app.openapi_schema = None
    return app.openapi()


def _structural(node: Any) -> Any:
    """Reduce an OpenAPI JSON node to type / required / $ref / enum structure."""
    if isinstance(node, list):
        return [_structural(item) for item in node]
    if not isinstance(node, dict):
        return node
    out: MutableMapping[str, Any] = {}
    for key, value in node.items():
        if key in _STRIP_KEYS:
            continue
        out[key] = _structural(value)
    return dict(out)


def _fixture_path(name: str) -> Path:
    return _FIXTURE_DIR / f"{name}.json"


def _load_fixture(name: str) -> Dict[str, Any]:
    path = _fixture_path(name)
    assert path.is_file(), f"Missing contract fixture {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_mtg_rest_openapi_version_is_bumped():
    """Release-train bump: one OpenAPI version covers the landed MTG REST surface."""
    assert app.version == _MTG_REST_OPENAPI_VERSION
    assert _live_spec()["info"]["version"] == _MTG_REST_OPENAPI_VERSION


@pytest.mark.parametrize(
    "path,methods",
    [(p, m) for p, m in _GOVERNANCE_PATHS.items()],
    ids=[p for p in _GOVERNANCE_PATHS],
)
def test_governance_path_exposes_expected_methods(path: str, methods: Set[str]):
    paths = _live_spec()["paths"]
    assert path in paths, f"Missing governance path {path} from OpenAPI"
    # FastAPI maps operation keys lower-case.
    present_lower = {
        m.lower()
        for m in paths[path]
        if m.lower() in {"get", "put", "post", "patch", "delete"}
    }
    assert methods <= present_lower, (
        f"{path}: expected methods {sorted(methods)}, found {sorted(present_lower)}"
    )


@pytest.mark.parametrize("schema_name", _SCHEMA_NAMES)
def test_governance_schema_structural_snapshot(schema_name: str):
    schemas = _live_spec()["components"]["schemas"]
    assert schema_name in schemas, f"Missing component schema {schema_name}"
    actual = _structural(schemas[schema_name])
    expected = _load_fixture(schema_name)
    assert actual == expected, (
        f"OpenAPI schema {schema_name} drifted from contract fixture. "
        f"If intentional, refresh tests/fixtures/mtg_governance_openapi/{schema_name}.json"
    )


def test_policy_and_capability_schemas_are_all_fixture_covered():
    """Fixture directory must cover every schema this suite locks."""
    on_disk = {p.stem for p in _FIXTURE_DIR.glob("*.json")}
    assert on_disk == set(_SCHEMA_NAMES)


def write_fixtures(spec: Optional[Dict[str, Any]] = None) -> List[Path]:
    """Regen golden structural schemas (used by the local helper script)."""
    _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    schemas = (spec or _live_spec())["components"]["schemas"]
    written: List[Path] = []
    for name in _SCHEMA_NAMES:
        path = _fixture_path(name)
        path.write_text(
            json.dumps(_structural(schemas[name]), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
