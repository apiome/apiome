"""End-to-end tests for ``objectified import openapi`` with mocked REST."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from objectified_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from objectified_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_VALID_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "paths": {},
}

_IMPORT_RESULT = {
    "project_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "version_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "project": {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "name": "Pet Store",
        "slug": "pet-store",
        "source": "import",
        "enabled": True,
    },
    "version": {
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "project_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "version": "1.0.0",
        "slug": "1.0.0",
        "source": "import",
        "enabled": True,
    },
    "created": {
        "schemas": 0,
        "properties": 0,
        "project_properties": 0,
        "version_schemas": 0,
    },
    "warnings": [],
    "errors": [],
}

_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_UPLOAD_URL = "http://localhost:8000/v1/tenants/acme-corp/imports/upload"
_JSON_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"


def _mock_accept(httpx_mock: object, *, url: str = _UPLOAD_URL) -> None:
    """Register the 202 ``accepted`` response for a spec import POST."""
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=url,
        method="POST",
        status_code=202,
        json={"job_id": _JOB_ID, "state": "pending"},
    )


def _mock_job_completed(
    httpx_mock: object,
    *,
    result: dict[str, object] | None = None,
) -> None:
    """Register a terminal ``completed`` job-status poll response."""
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={
            "state": "completed",
            "job_id": _JOB_ID,
            "result": _IMPORT_RESULT if result is None else result,
        },
    )


def _mock_import_completed(
    httpx_mock: object,
    *,
    url: str = _UPLOAD_URL,
    result: dict[str, object] | None = None,
) -> None:
    """Register the full async import flow: 202 accept then completed poll."""
    _mock_accept(httpx_mock, url=url)
    _mock_job_completed(httpx_mock, result=result)


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key."""
    monkeypatch.setenv("OBJECTIFIED_API_KEY", "test-import-key")
    monkeypatch.setenv("OBJECTIFIED_TENANT_ID", "acme-corp")


def _write_spec(path: Path) -> None:
    path.write_text(json.dumps(_VALID_SPEC), encoding="utf-8")


def _json_object_from_multipart(content: str, *, anchor: str) -> dict[str, object]:
    """Extract a balanced JSON object containing *anchor* from multipart text."""
    anchor_idx = content.find(anchor)
    assert anchor_idx >= 0, f"multipart body missing {anchor!r}"
    start = content.rfind("{", 0, anchor_idx)
    assert start >= 0
    depth = 0
    end = start
    for index, char in enumerate(content[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    return json.loads(content[start:end])


def _import_request_payload(request: object) -> dict[str, object]:
    """Normalize a spec-import POST (multipart upload or JSON body) for assertions.

    The REST surface receives a ``metadata`` object plus the document. This
    helper flattens both encodings into a comparable dict exposing the uploaded
    document under ``spec`` and the parsed import ``metadata``.
    """
    content = request.content.decode("utf-8")  # type: ignore[attr-defined]
    content_type = request.headers.get("content-type", "")  # type: ignore[attr-defined]

    if content_type.startswith("application/json") or content.lstrip().startswith("{"):
        body = json.loads(content)
        spec = json.loads(base64.b64decode(body["document_base64"]).decode("utf-8"))
        metadata = body["metadata"]
        return {"spec": spec, "metadata": metadata}

    # multipart/form-data upload: ``metadata`` JSON field + uploaded ``file``.
    metadata = _json_object_from_multipart(content, anchor='"source_kind"')
    spec = _json_object_from_multipart(content, anchor='"openapi"')
    return {"spec": spec, "metadata": metadata}


def test_import_openapi_sync_success(httpx_mock: object, tmp_path: Path) -> None:
    """Successful sync import prints result on stdout and exits 0."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "openapi", str(spec_path)])

    assert result.exit_code == 0
    assert "Import completed." in result.stdout
    assert "Pet Store" in result.stdout
    assert "pet-store" in result.stdout
    assert "Uploading OpenAPI document petstore.json" in result.stderr


def test_import_openapi_lists_local_schema_coercion_warnings(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """Local schema default coercion warnings are listed in human import output."""
    spec_path = tmp_path / "coerced-default.json"
    spec_path.write_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "Demo", "version": "1.0.0"},
                "paths": {},
                "components": {
                    "parameters": {
                        "limit": {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "default": "100"},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "openapi", str(spec_path)])

    assert result.exit_code == 0
    assert "Warnings (1):" in result.stdout
    assert "[schema_default_type_coercion]" in result.stdout
    assert "Schema default '100' was coerced" in result.stdout


def test_import_openapi_from_url(httpx_mock: object) -> None:
    """OpenAPI import accepts an HTTP(S) URL as the document source."""
    spec_url = "https://example.com/petstore.json"
    httpx_mock.add_response(url=spec_url, text=json.dumps(_VALID_SPEC))
    _mock_import_completed(httpx_mock, url=_JSON_IMPORT_URL)

    result = runner.invoke(app, ["import", "openapi", spec_url])

    assert result.exit_code == 0
    assert "Import completed." in result.stdout
    assert "Fetching OpenAPI document petstore.json" in result.stderr


def test_import_openapi_url_fetch_failure_exits_usage(httpx_mock: object) -> None:
    """Unreachable or failing document URLs exit with usage code."""
    spec_url = "https://example.com/missing.json"
    httpx_mock.add_response(url=spec_url, status_code=404)

    result = runner.invoke(app, ["import", "openapi", spec_url])

    assert result.exit_code == EXIT_USAGE
    assert "HTTP 404" in result.stderr


def test_import_openapi_json_output(httpx_mock: object, tmp_path: Path) -> None:
    """``--json`` emits the raw ImportResult on stdout."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["--json", "import", "openapi", str(spec_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["project_id"] == _IMPORT_RESULT["project_id"]


def test_import_openapi_async_polls_until_completed(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """202 responses poll GET /imports/{job_id} until completed."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_accept(httpx_mock)
    httpx_mock.add_response(
        url=_JOB_URL,
        method="GET",
        json={"state": "running", "job_id": _JOB_ID},
    )
    httpx_mock.add_response(
        url=_JOB_URL,
        method="GET",
        json={
            "state": "completed",
            "job_id": _JOB_ID,
            "result": _IMPORT_RESULT,
        },
    )

    result = runner.invoke(app, ["import", "openapi", str(spec_path)])

    assert result.exit_code == 0
    assert "Import completed." in result.stdout
    stderr = strip_ansi(result.stderr)
    assert "Import running" in stderr or "Uploading" in stderr


def test_import_openapi_invalid_spec_exits_usage(tmp_path: Path) -> None:
    """Structural validation failures exit 2 before any REST call."""
    spec_path = tmp_path / "bad.json"
    spec_path.write_text('{"openapi": "3.1.0", "paths": {}}', encoding="utf-8")

    result = runner.invoke(app, ["import", "openapi", str(spec_path)])

    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""


def test_import_openapi_rejects_json_schema_file(tmp_path: Path) -> None:
    """JSON Schema files suggest ``import json-schema`` instead."""
    spec_path = tmp_path / "schema.json"
    spec_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"id": {"type": "string"}},
            },
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["import", "openapi", str(spec_path)])

    assert result.exit_code == EXIT_USAGE
    assert "import json-schema" in result.stderr
    assert "Use: objectified import json-schema" in result.stderr
    assert result.stdout == ""


def test_import_openapi_errors_in_result_exit_error(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """Non-empty ImportResult.errors exits 1 after printing the result."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    payload = {
        **_IMPORT_RESULT,
        "errors": [{"code": "E1", "message": "partial failure"}],
    }
    _mock_import_completed(httpx_mock, result=payload)

    result = runner.invoke(app, ["import", "openapi", str(spec_path)])

    assert result.exit_code == EXIT_ERROR
    assert "Import completed." in result.stdout
    assert "Errors: 1" in result.stdout


def test_import_openapi_uses_import_timeout(tmp_path: Path) -> None:
    """``--timeout`` applies to the REST client for upload and polling."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)

    with patch("objectified_cli.commands.import_.RestClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        accept = instance.post.return_value
        accept.status_code = 202
        accept.json.return_value = {"job_id": _JOB_ID, "state": "pending"}
        status = instance.get.return_value
        status.json.return_value = {
            "state": "completed",
            "job_id": _JOB_ID,
            "result": _IMPORT_RESULT,
        }

        result = runner.invoke(
            app,
            ["--timeout", "90", "import", "openapi", str(spec_path)],
        )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once()
    assert mock_client_cls.call_args.kwargs["timeout"] == 90.0


def test_import_openapi_dry_run_passes_flag(httpx_mock: object, tmp_path: Path) -> None:
    """``--dry-run`` is forwarded in the import metadata and prints a planned summary."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "openapi", "--dry-run", str(spec_path)])

    assert result.exit_code == 0
    request = httpx_mock.get_requests()[0]
    body = _import_request_payload(request)
    assert body["metadata"]["options"]["dry_run"] is True
    assert "Dry run completed (no changes written)." in result.stdout
    assert "Pet Store" in result.stdout
    assert "Planning OpenAPI import (dry run)" in result.stderr
    assert "Uploading OpenAPI document" not in result.stderr


def test_import_openapi_no_wait_returns_job_without_polling(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """``--no-wait`` prints the 202 accept body and does not poll GET /imports."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_accept(httpx_mock)

    result = runner.invoke(
        app,
        ["import", "openapi", "--no-wait", str(spec_path)],
    )

    assert result.exit_code == 0
    assert "Import accepted." in result.stdout
    assert _JOB_ID in result.stdout
    assert len(httpx_mock.get_requests()) == 1


def test_import_openapi_custom_poll_interval(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """``--poll-interval`` is forwarded to the job poll loop."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_accept(httpx_mock)

    with patch(
        "objectified_cli.import_.upload.wait_for_import_job",
    ) as mock_wait:
        mock_wait.return_value = {
            "state": "completed",
            "result": _IMPORT_RESULT,
        }
        result = runner.invoke(
            app,
            ["import", "openapi", "--poll-interval", "2.5", str(spec_path)],
        )

    assert result.exit_code == 0
    mock_wait.assert_called_once()
    assert mock_wait.call_args.kwargs["poll_interval"] == 2.5


def test_import_openapi_async_timeout_exits_error(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """Async poll loop timeout exits with code 1 and writes timeout message."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_accept(httpx_mock)
    httpx_mock.add_response(
        url=_JOB_URL,
        method="GET",
        json={"state": "running", "job_id": _JOB_ID},
        is_reusable=True,
        is_optional=True,
    )

    result = runner.invoke(
        app,
        ["--timeout", "1", "--no-progress", "import", "openapi", str(spec_path)],
    )

    assert result.exit_code == EXIT_ERROR
    assert "Import timed out after 1 second." in strip_ansi(result.stderr)


def test_import_openapi_help_lists_flags() -> None:
    """Subcommand documents PATH and import-specific options."""
    result = runner.invoke(app, ["import", "openapi", "--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "PATH" in help_text
    assert "--dry-run" in help_text
    assert "--project-name" in help_text
    assert "--version" in help_text
    assert "--project-slug" in help_text
    assert "--version-slug" in help_text
    assert "--project-id" in help_text
    assert "--publish" in help_text
    assert "--visibility" in help_text
    assert "--wait" in help_text
    assert "--poll-interval" in help_text


_PUBLISH_URL = (
    "http://localhost:8000/v1/versions/acme-corp/"
    f"{_IMPORT_RESULT['project_id']}/{_IMPORT_RESULT['version_id']}/publish"
)


def _mock_publish(httpx_mock: object, *, visibility: str) -> None:
    """Register the follow-up publish POST issued after a completed import."""
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_PUBLISH_URL,
        method="POST",
        json={
            "id": _IMPORT_RESULT["version_id"],
            "project_id": _IMPORT_RESULT["project_id"],
            "version": "1.0.0",
            "publish_visibility": visibility,
        },
    )


def test_import_openapi_publish_private_maps_to_protected(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """``--publish private`` publishes the imported version as ``protected``."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_import_completed(httpx_mock)
    _mock_publish(httpx_mock, visibility="protected")

    result = runner.invoke(
        app,
        ["import", "openapi", "--publish", "private", str(spec_path)],
    )

    assert result.exit_code == 0
    requests = httpx_mock.get_requests()
    # The /v1 spec-import surface carries no visibility field in its metadata.
    body = _import_request_payload(requests[0])
    assert "visibility" not in body["metadata"]
    # Publishing is realized as a follow-up publish POST (private -> protected).
    publish_request = requests[-1]
    assert publish_request.method == "POST"
    assert str(publish_request.url) == _PUBLISH_URL
    assert json.loads(publish_request.content) == {"visibility": "protected"}
    assert "Published imported version as private." in result.stderr


def test_import_openapi_publish_public_accepted(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """``--publish public`` publishes the imported version as ``public``."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_import_completed(httpx_mock)
    _mock_publish(httpx_mock, visibility="public")

    result = runner.invoke(
        app,
        ["import", "openapi", "--publish", "public", str(spec_path)],
    )

    assert result.exit_code == 0
    requests = httpx_mock.get_requests()
    body = _import_request_payload(requests[0])
    assert "visibility" not in body["metadata"]
    publish_request = requests[-1]
    assert publish_request.method == "POST"
    assert str(publish_request.url) == _PUBLISH_URL
    assert json.loads(publish_request.content) == {"visibility": "public"}
    assert "Published imported version as public." in result.stderr


def test_import_openapi_override_flags_in_request_body(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    """CLI overrides land in the uploaded document and import metadata."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)
    _mock_import_completed(httpx_mock)
    project_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    result = runner.invoke(
        app,
        [
            "import",
            "openapi",
            "--project-name",
            "Custom Name",
            "--version",
            "9.0.0",
            "--project-slug",
            "custom-slug",
            "--version-slug",
            "9.0.0",
            "--project-id",
            project_id,
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    request = httpx_mock.get_requests()[0]
    body = _import_request_payload(request)
    info = body["spec"]["info"]
    assert info["title"] == "Custom Name"
    assert info["version"] == "9.0.0"
    assert info["x-objectified-project-slug"] == "custom-slug"
    assert info["x-objectified-version-slug"] == "9.0.0"
    assert body["metadata"]["existing_project_id"] == project_id


def test_import_openapi_project_name_field_in_request_body(
    httpx_mock: object,
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "petstore.json"
    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "Ignored",
            "version": "1.0.0",
            "summary": "Summary Name",
        },
        "paths": {},
    }
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    _mock_import_completed(httpx_mock)

    result = runner.invoke(
        app,
        [
            "import",
            "openapi",
            "--project-name-field",
            "info.summary",
            str(spec_path),
        ],
    )

    assert result.exit_code == 0
    request = httpx_mock.get_requests()[0]
    body = _import_request_payload(request)
    assert body["spec"]["info"]["x-objectified-project-name-field"] == "info.summary"


def test_import_openapi_invalid_project_slug_exits_usage(tmp_path: Path) -> None:
    """Invalid --project-slug exits 2 before any REST call."""
    spec_path = tmp_path / "petstore.json"
    _write_spec(spec_path)

    result = runner.invoke(
        app,
        ["import", "openapi", "--project-slug", "INVALID SLUG", str(spec_path)],
    )

    assert result.exit_code == EXIT_USAGE
    assert "Project slug" in result.stderr
