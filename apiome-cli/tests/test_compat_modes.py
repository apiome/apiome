"""Compatibility mode flags on ``apiome diff`` and ``apiome compat`` (XPC-4.5 / #5749)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from apiome_cli.compat_modes import describe_evaluated_under, mode_request_fields, normalize_category, normalize_mode
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_SPEC_FILE = Path(__file__).resolve().parent / "fixtures" / "diff-property-removed.yaml"
_DIFF_URL = "http://localhost:8000/v1/diff/acme-corp/classified"
_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_BASE_VERSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_NATIVE_URL = f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/compatibility"

_EVALUATED = {
    "mode": "FORWARD",
    "transitive": False,
    "category": None,
    "formats": ["avro"],
    "modeApplied": True,
    "categoryApplied": False,
    "ruleset": "avro-compatibility",
    "source": {"mode": "request", "transitive": "policy", "category": "policy"},
    "comparedRevisions": [{"revisionId": "r2", "versionLabel": "2.0.0", "role": "base"}],
    "comparedRevisionsTruncated": False,
}

_AVRO_DIFF = {
    "changes": [
        {
            "ruleId": "avro-compatibility.reader-field-missing-default-value",
            "severity": "breaking",
            "pointer": "/field/com.example.User.email",
            "unclassified": False,
            "changeKind": "removed",
            "consumers": None,
            "grade": "breaking",
            "rationale": "[FORWARD] breaks FORWARD and FULL: the old schema cannot read data written with the new",
            "against": {"revisionId": "r1", "versionLabel": "1.0.0"},
        }
    ],
    "counts": {"breaking": 1, "non-breaking": 0, "docs-only": 0, "unclassified": 0, "total": 1},
    "maxSeverity": "breaking",
    "base": {"projectId": "p", "projectSlug": "orders", "versionRecordId": "r2", "versionLabel": "2.0.0"},
    "head": {"source": "inline", "projectId": None, "projectSlug": None, "versionRecordId": None, "versionLabel": None},
    "evaluatedUnder": {
        **_EVALUATED,
        "transitive": True,
        "comparedRevisions": [
            {"revisionId": "r2", "versionLabel": "2.0.0", "role": "base"},
            {"revisionId": "r1", "versionLabel": "1.0.0", "role": "prior"},
        ],
    },
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _body(httpx_mock: Any, index: int = 0) -> dict[str, Any]:
    return json.loads(httpx_mock.get_requests()[index].content)


# ===========================================================================
# The shared helpers
# ===========================================================================


@pytest.mark.parametrize(
    "raw, expected",
    [("forward", "FORWARD"), ("Full_Transitive", "FULL_TRANSITIVE"), ("full-transitive", "FULL_TRANSITIVE"), (None, None), ("  ", None)],
)
def test_normalize_mode(raw: Any, expected: Any) -> None:
    assert normalize_mode(raw) == expected


@pytest.mark.parametrize("raw", ["sideways", "none_transitive", "backwards"])
def test_normalize_mode_rejects_unknown(raw: str) -> None:
    with pytest.raises(typer.BadParameter):
        normalize_mode(raw)


def test_normalize_category() -> None:
    assert normalize_category("wire_json") == "WIRE_JSON"
    assert normalize_category(None) is None
    with pytest.raises(typer.BadParameter):
        normalize_category("bytes")


def test_mode_request_fields_sends_only_what_was_given() -> None:
    assert mode_request_fields(None, None, None) == {}
    assert mode_request_fields("full", False, "file") == {"mode": "FULL", "transitive": False, "category": "FILE"}
    assert mode_request_fields(None, True, None) == {"transitive": True}


def test_describe_evaluated_under() -> None:
    assert describe_evaluated_under(None) is None
    assert describe_evaluated_under(_EVALUATED) == "Evaluated under FORWARD (avro-compatibility; avro)"
    assert describe_evaluated_under(_AVRO_DIFF["evaluatedUnder"]) == (
        "Evaluated under FORWARD_TRANSITIVE (avro-compatibility; avro) against 2.0.0, 1.0.0"
    )
    not_applied = {**_EVALUATED, "modeApplied": False, "ruleset": "ctg", "formats": ["openapi"]}
    assert describe_evaluated_under(not_applied) == "Evaluated under FORWARD — mode not applied: graded by ctg; openapi"
    proto = {**_EVALUATED, "modeApplied": False, "categoryApplied": True, "category": "WIRE", "ruleset": "buf-breaking", "formats": ["protobuf"]}
    assert describe_evaluated_under(proto).endswith("Protobuf category WIRE")


# ===========================================================================
# apiome diff
# ===========================================================================


@pytest.mark.usefixtures("api_key_env")
def test_diff_passes_mode_flags_through(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_AVRO_DIFF)
    result = runner.invoke(
        app,
        ["diff", str(_SPEC_FILE), "--against", "orders@2.0.0", "--mode", "forward", "--transitive", "--category", "wire"],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    body = _body(httpx_mock)
    assert (body["mode"], body["transitive"], body["category"]) == ("FORWARD", True, "WIRE")
    assert "Evaluated under FORWARD_TRANSITIVE" in result.stdout
    assert "(against 1.0.0)" in result.stdout
    assert "[FORWARD] breaks FORWARD and FULL" in result.stdout


@pytest.mark.usefixtures("api_key_env")
def test_diff_without_flags_leaves_the_policy_to_the_server(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_AVRO_DIFF)
    runner.invoke(app, ["diff", str(_SPEC_FILE), "--against", "orders@2.0.0"])
    body = _body(httpx_mock)
    assert not {"mode", "transitive", "category"} & set(body)


@pytest.mark.usefixtures("api_key_env")
def test_diff_rejects_an_unknown_mode_before_calling_the_server(httpx_mock: Any) -> None:
    result = runner.invoke(app, ["diff", str(_SPEC_FILE), "--against", "orders@2.0.0", "--mode", "sideways"])
    assert result.exit_code == EXIT_USAGE
    assert httpx_mock.get_requests() == []


@pytest.mark.usefixtures("api_key_env")
def test_diff_json_keeps_evaluated_under(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_AVRO_DIFF)
    result = runner.invoke(app, ["diff", str(_SPEC_FILE), "--against", "orders@2.0.0", "--format", "json"])
    payload = json.loads(result.stdout)
    assert payload["evaluatedUnder"]["mode"] == "FORWARD"
    schema = json.loads((Path(__file__).parent / "fixtures" / "diff-classified-response.schema.json").read_text())
    import jsonschema

    jsonschema.validate(instance=payload, schema=schema)


@pytest.mark.usefixtures("api_key_env")
def test_diff_md_sends_the_mode_on_both_calls(httpx_mock: Any) -> None:
    httpx_mock.add_response(url=_DIFF_URL, method="POST", json=_AVRO_DIFF)
    httpx_mock.add_response(url=_DIFF_URL, method="POST", text="# Changelog\n", headers={"content-type": "text/markdown"})
    runner.invoke(app, ["diff", str(_SPEC_FILE), "--against", "orders@2.0.0", "--format", "md", "--mode", "full"])
    assert _body(httpx_mock, 0)["mode"] == "FULL"
    assert _body(httpx_mock, 1)["mode"] == "FULL"


# ===========================================================================
# apiome compat
# ===========================================================================


def _mock_scope(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/orders",
        json={"id": _PROJECT_ID, "slug": "orders", "name": "Orders", "enabled": True},
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/2.1.0",
        json={"id": _VERSION_ID, "project_id": _PROJECT_ID, "version": "2.1.0", "enabled": True},
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/2.0.0",
        json={"id": _BASE_VERSION_ID, "project_id": _PROJECT_ID, "version": "2.0.0", "enabled": True},
    )


def _native(overall: str, category: str) -> dict[str, Any]:
    return {
        "overall": overall,
        "baseRevisionId": _BASE_VERSION_ID,
        "headRevisionId": _VERSION_ID,
        "findings": [
            {
                "id": "cmp-1",
                "path": "/field/com.example.User.email",
                "category": category,
                "rule": "avro-compatibility.reader-field-missing-default-value",
                "ruleId": "avro-compatibility.reader-field-missing-default-value",
                "message": "[FULL] breaks FORWARD and FULL",
                "against": {"revisionId": "r1", "versionLabel": "1.0.0"},
            }
        ],
        "ruleHits": {},
        "reportFingerprint": "fp",
        "evaluatedUnder": {**_EVALUATED, "mode": "FULL"},
    }


_COMPAT_ARGS = ["compat", "--project", "orders", "--version", "2.1.0", "--base-version", "2.0.0"]


@pytest.mark.usefixtures("api_key_env")
def test_compat_with_a_mode_uses_the_native_check(httpx_mock: Any) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_NATIVE_URL, method="POST", json=_native("breaking", "breaking"))
    result = runner.invoke(app, [*_COMPAT_ARGS, "--mode", "full", "--transitive"])
    assert result.exit_code == EXIT_ERROR, result.output
    posted = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    assert [str(r.url) for r in posted] == [_NATIVE_URL]
    body = json.loads(posted[0].content)
    assert body == {
        "baseRevisionId": _BASE_VERSION_ID,
        "headRevisionId": _VERSION_ID,
        "mode": "FULL",
        "transitive": True,
    }
    assert "Compatibility overall: breaking" in result.stdout
    assert "Evaluated under FULL" in result.stdout
    assert "(against 1.0.0)" in result.stdout


@pytest.mark.usefixtures("api_key_env")
@pytest.mark.parametrize("fail_on, expected", [("breaking", EXIT_SUCCESS), ("dangerous", EXIT_ERROR)])
def test_compat_native_fail_on_reads_the_finding_category(httpx_mock: Any, fail_on: str, expected: int) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_NATIVE_URL, method="POST", json=_native("unknown", "unknown"))
    result = runner.invoke(app, [*_COMPAT_ARGS, "--mode", "backward", "--fail-on", fail_on])
    assert result.exit_code == expected, result.output


@pytest.mark.usefixtures("api_key_env")
def test_compat_native_json(httpx_mock: Any) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_NATIVE_URL, method="POST", json=_native("safe", "safe"))
    result = runner.invoke(app, ["--json", *_COMPAT_ARGS, "--category", "wire"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["evaluatedUnder"]["mode"] == "FULL"


@pytest.mark.usefixtures("api_key_env")
def test_compat_native_refuses_sarif(httpx_mock: Any) -> None:
    result = runner.invoke(app, [*_COMPAT_ARGS, "--mode", "full", "--format", "sarif"])
    assert result.exit_code == EXIT_USAGE
    assert httpx_mock.get_requests() == []
