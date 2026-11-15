"""The generator compatibility manifest — SGD-2.1 (#4735).

* **Versioned and fixture-tested.** The manifest for a fixture API is pinned in
  ``tests/golden/sdk_compat_manifest/widgets.json`` — the **same** file the apiome-cli and apiome-ui
  tests render, so the dashboard and the CLI are proven to read one document. Regenerate it with
  ``pytest --update-golden`` (or ``UPDATE_SDK_COMPAT_GOLDEN=1``) and review the diff. The committed
  JSON Schema (``schemas/sdk-compat-manifest.v1.json``) must match the model.
* **Actionable.** Every finding carries a stable code and the action for it; nothing a generator
  skipped is dropped.
* **Digests.** Source, options, generator and artifact digests are present, and move exactly when
  their input moves.
* **Semver.** The classified changelog's required bump against what the labels declare.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.canonical_model import Operation, OperationKind, Parameter, ParameterLocation, TypeRef
from app.sdk_compat_manifest import (
    ACTIONS,
    FINDING_CODES,
    SCHEMA_VERSION,
    ChangelogInfo,
    SdkCompatManifest,
    build_compat_manifest,
    classify_bump,
    manifest_etag,
)
from test_sdk_kit import _api, _build, _http_op

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "sdk_compat_manifest" / "widgets.json"
SCHEMA = ROOT / "schemas" / "sdk-compat-manifest.v1.json"


def _fixture_api():
    """The kit fixture plus a paginated list guarded by two security schemes."""
    api = _api()
    listing = _http_op(
        "listWidgets",
        path="/widgets",
        operation_id="listWidgets",
        parameters=[
            Parameter(key="p-limit", name="limit", location=ParameterLocation.QUERY, type=TypeRef(name="integer")),
            Parameter(key="p-cursor", name="cursor", location=ParameterLocation.QUERY, type=TypeRef(name="string")),
        ],
    )
    listing = listing.model_copy(update={"extras": {**listing.extras, "security": ["bearerAuth", "oauth2"]}})
    api.services[0].operations.insert(1, listing)
    return api


def _manifest(api=None, *, changelog=ChangelogInfo("non-breaking", "0.9.0"), **kit_kwargs) -> SdkCompatManifest:
    api = api or _fixture_api()
    kit = _build(api, **kit_kwargs)
    branding = kit_kwargs.get("branding")
    return build_compat_manifest(
        api,
        kit.manifest,
        kit.content,
        source_text=kit_kwargs.get("source_text", '{"openapi": "3.1.0"}'),
        settings_fingerprint=kit_kwargs.get("settings_fingerprint", "sha256:" + "a" * 64),
        package_names=dict(branding.package_names) if branding else {},
        user_agent=branding.user_agent if branding else None,
        license_header=branding.license_header if branding else None,
        changelog=changelog,
    )


def _dump(manifest: SdkCompatManifest) -> Dict[str, Any]:
    return manifest.model_dump(mode="json")


def _update_requested(request) -> bool:
    return bool(request.config.getoption("--update-golden", default=False)) or os.environ.get(
        "UPDATE_SDK_COMPAT_GOLDEN"
    ) == "1"


# ---------------------------------------------------------------------------------------------
# Versioned and fixture-tested
# ---------------------------------------------------------------------------------------------


def test_the_manifest_matches_the_golden_fixture(request) -> None:
    rendered = json.dumps(_dump(_manifest()), indent=2, sort_keys=False) + "\n"
    if _update_requested(request):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(rendered)
    assert GOLDEN.exists(), "run pytest --update-golden to create the golden manifest"
    assert rendered == GOLDEN.read_text(), "the manifest changed; review and run pytest --update-golden"


def test_the_golden_fixture_is_a_valid_manifest() -> None:
    manifest = SdkCompatManifest.model_validate(json.loads(GOLDEN.read_text()))
    assert manifest.schema_version == SCHEMA_VERSION


def test_the_committed_json_schema_matches_the_model(request) -> None:
    schema = SdkCompatManifest.model_json_schema()
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if _update_requested(request):
        SCHEMA.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA.write_text(rendered)
    assert SCHEMA.read_text() == rendered, "regenerate with scripts/generate_sdk_compat_schema.py"


def test_the_manifest_is_deterministic() -> None:
    assert _dump(_manifest()) == _dump(_manifest())
    assert manifest_etag(_manifest()) == manifest_etag(_manifest())


def test_unknown_keys_are_refused() -> None:
    data = _dump(_manifest())
    data["artifacts"][0]["secret"] = "x"
    with pytest.raises(ValueError):
        SdkCompatManifest.model_validate(data)


# ---------------------------------------------------------------------------------------------
# Coverage and constructs
# ---------------------------------------------------------------------------------------------


def test_every_kit_artifact_is_described() -> None:
    ids = [artifact.id for artifact in _manifest().artifacts]
    assert ids == [
        "snippets-ts", "snippets-python", "snippets-curl", "go-client",
        "server-fastapi", "server-express", "terraform-provider", "mcp-server",
    ]


def test_constructs_are_counted_from_the_model() -> None:
    constructs = _manifest().constructs
    assert (constructs.operations, constructs.http_operations) == (3, 2)
    assert constructs.security_schemes == ["bearerAuth", "oauth2"]
    assert constructs.pagination_parameters == ["cursor", "limit"]


def test_coverage_counts_what_each_artifact_carries() -> None:
    by_id = {a.id: a for a in _manifest().artifacts}
    assert (by_id["go-client"].coverage.operations, by_id["go-client"].coverage.of) == (2, 3)
    assert by_id["snippets-ts"].coverage.operations == 2
    assert by_id["mcp-server"].coverage.operations == 2


def test_pagination_is_reported_as_manual() -> None:
    go = next(a for a in _manifest().artifacts if a.id == "go-client")
    assert go.pagination.mode == "manual" and go.pagination.parameters == ["cursor", "limit"]
    single = _manifest(api=_api())
    assert next(a for a in single.artifacts if a.id == "go-client").pagination.mode == "none"


def test_runtime_dependencies_are_read_from_the_generated_files() -> None:
    by_id = {a.id: a for a in _manifest().artifacts}
    assert by_id["go-client"].runtime.language_version == "go 1.21"
    assert by_id["go-client"].runtime.dependencies == []
    assert any(dep.startswith("fastapi") for dep in by_id["server-fastapi"].runtime.dependencies)
    assert by_id["snippets-python"].runtime.dependencies == ["httpx"]


# ---------------------------------------------------------------------------------------------
# Actionable findings
# ---------------------------------------------------------------------------------------------


def test_every_code_has_an_action() -> None:
    assert set(FINDING_CODES) == set(ACTIONS)
    assert all(ACTIONS[code].strip() for code in FINDING_CODES)


def test_every_finding_says_what_to_do() -> None:
    manifest = _manifest()
    findings = [f for a in manifest.artifacts for f in a.findings]
    assert findings and manifest.findings_count == len(findings)
    for finding in findings:
        assert finding.code in FINDING_CODES and finding.action == ACTIONS[finding.code] and finding.reason


def test_an_operation_without_an_http_binding_is_a_finding_everywhere_it_is_dropped() -> None:
    manifest = _manifest()
    for artifact in manifest.artifacts:
        codes = {(f.code, f.subject) for f in artifact.findings}
        assert any(code == "operation-no-http-binding" for code, _ in codes), artifact.id


def test_auth_schemes_an_artifact_cannot_carry_are_findings() -> None:
    by_id = {a.id: a for a in _manifest().artifacts}
    snippet_auth = {f.subject for f in by_id["snippets-ts"].findings if f.code == "auth-scheme-unsupported"}
    assert snippet_auth == {"bearerAuth", "oauth2"}
    assert by_id["snippets-ts"].auth.unsupported == ["bearerAuth", "oauth2"]
    go = by_id["go-client"]
    assert set(go.auth.supported) | set(go.auth.unsupported) == {"bearerAuth", "oauth2"}
    assert {f.subject for f in go.findings if f.code == "auth-scheme-unsupported"} == set(go.auth.unsupported)


def test_a_failed_generator_is_an_error_finding(monkeypatch) -> None:
    from app import sdk_kit

    def boom(*_args, **_kwargs):
        raise RuntimeError("generator exploded")

    monkeypatch.setattr(sdk_kit, "generate_go_client", boom)
    go = next(a for a in _manifest().artifacts if a.id == "go-client")
    assert go.included is False and go.digest is None
    (finding,) = go.findings
    assert (finding.code, finding.severity, finding.element) == ("artifact-not-generated", "error", "artifact")


def test_a_truncated_kit_says_so(monkeypatch) -> None:
    from app import sdk_kit

    monkeypatch.setattr(sdk_kit, "MAX_KIT_OPERATIONS", 1)
    snippets = next(a for a in _manifest().artifacts if a.id == "snippets-ts")
    assert any(f.code == "operations-truncated" for f in snippets.findings)


# ---------------------------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------------------------


def test_every_digest_is_present() -> None:
    manifest = _manifest()
    assert manifest.source.digest.startswith("sha256:")
    assert manifest.options.digest.startswith("sha256:")
    for artifact in manifest.artifacts:
        assert artifact.generator.digest.startswith("sha256:")
        assert artifact.digest and artifact.digest.startswith("sha256:")


def test_the_source_digest_follows_the_source() -> None:
    a, b = _manifest(), _manifest(source_text='{"openapi": "3.1.1"}')
    assert a.source.digest != b.source.digest
    assert a.options.digest == b.options.digest


def test_the_options_digest_follows_the_settings() -> None:
    a, b = _manifest(), _manifest(settings_fingerprint="sha256:" + "b" * 64)
    assert a.options.digest != b.options.digest and a.source.digest == b.source.digest


def test_the_generator_digest_follows_the_apiome_version() -> None:
    a, b = _manifest(), _manifest(apiome_version="2.0.0")
    assert [x.generator.digest for x in a.artifacts] != [x.generator.digest for x in b.artifacts]


def test_an_artifact_digest_follows_its_files() -> None:
    from test_sdk_kit import _BRANDED

    a, b = _manifest(), _manifest(branding=_BRANDED)
    go_a = next(x for x in a.artifacts if x.id == "go-client")
    go_b = next(x for x in b.artifacts if x.id == "go-client")
    assert go_a.digest != go_b.digest


# ---------------------------------------------------------------------------------------------
# Semver
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "baseline", "expected"),
    [
        ("2.0.0", "1.9.3", "major"),
        ("1.10.0", "1.9.3", "minor"),
        ("1.9.4", "1.9.3", "patch"),
        ("v1.9.3", "1.9.3", "none"),
        ("2.0.0-beta.1", "1.9.3", "major"),
        ("latest", "1.9.3", "unknown"),
        (None, "1.0.0", "unknown"),
    ],
)
def test_classify_bump(version, baseline, expected) -> None:
    assert classify_bump(version, baseline) == expected


@pytest.mark.parametrize(
    ("severity", "baseline", "required", "consistent"),
    [
        ("breaking", "0.9.0", "major", True),
        ("breaking", "0.9.9", "major", True),
        ("non-breaking", "0.9.0", "minor", True),
        ("breaking", "1.0.0-rc.0", "major", False),
        ("docs-only", "0.9.0", "patch", True),
    ],
)
def test_semver_compares_the_required_and_declared_bump(severity, baseline, required, consistent) -> None:
    semver = _manifest(changelog=ChangelogInfo(severity, baseline)).semver
    assert semver.classification == severity and semver.required_bump == required
    assert semver.consistent is consistent


def test_a_revision_without_a_changelog_is_unknown() -> None:
    semver = _manifest(changelog=None).semver
    assert semver.classification == "unknown" and semver.required_bump is None and semver.consistent is None
