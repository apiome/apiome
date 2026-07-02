"""httpx-mocked integration tests for import commands and the async wait loop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")


def test_import_openapi_sync_200_completes(
    httpx_mock: object,
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    write_openapi_spec: Callable[[Path], Path],
    import_result: dict,
    job_id: str,
) -> None:
    """A 202 upload that polls straight to a completed job emits the ImportResult."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    spec_path = write_openapi_spec(tmp_path / "petstore.json")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        status_code=202,
        json={"job_id": job_id, "state": "pending"},
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/acme-corp/imports/{job_id}",
        json={"state": "completed", "job_id": job_id, "result": import_result},
    )

    result = runner.invoke(app, ["--no-progress", "import", "openapi", str(spec_path)])

    assert result.exit_code == 0
    assert "Import completed: " in result.stdout
    assert "Integration Pet Store" in result.stdout
    assert len(httpx_mock.get_requests()) == 2


def test_import_openapi_async_202_polls_running_to_completed(
    httpx_mock: object,
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    write_openapi_spec: Callable[[Path], Path],
    import_result: dict,
    job_id: str,
) -> None:
    """202 accept polls GET /v1/tenants/{slug}/imports/{job_id} through running until completed."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    spec_path = write_openapi_spec(tmp_path / "petstore.json")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        status_code=202,
        json={"job_id": job_id, "state": "pending"},
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/acme-corp/imports/{job_id}",
        json={"state": "running", "job_id": job_id},
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/acme-corp/imports/{job_id}",
        json={"state": "completed", "job_id": job_id, "result": import_result},
    )

    result = runner.invoke(
        app,
        ["--no-progress", "import", "openapi", str(spec_path)],
    )

    assert result.exit_code == 0
    assert "Import completed: " in result.stdout
    assert len(httpx_mock.get_requests()) == 3
    methods = [request.method for request in httpx_mock.get_requests()]
    assert methods == ["POST", "GET", "GET"]


def test_import_openapi_post_422_exits_usage(
    httpx_mock: object,
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    write_openapi_spec: Callable[[Path], Path],
) -> None:
    """422 validation on upload maps to EXIT_USAGE and prints field details."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    spec_path = write_openapi_spec(tmp_path / "petstore.json")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        status_code=422,
        json={
            "code": 422,
            "message": "OpenAPI import validation failed",
            "details": [
                {
                    "code": "invalid_openapi",
                    "message": "At /info: 'version' is a required property",
                    "path": "/info",
                },
            ],
        },
    )

    result = runner.invoke(app, ["import", "openapi", str(spec_path)])

    assert result.exit_code == EXIT_USAGE
    assert "HTTP 422" in result.stderr
    assert "[invalid_openapi]" in result.stderr
    assert "'version' is a required property" in result.stderr
    assert "at /info" in result.stderr
    assert result.stdout == ""
    assert len(httpx_mock.get_requests()) == 1


def test_import_openapi_async_failed_job_exits_error(
    httpx_mock: object,
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    write_openapi_spec: Callable[[Path], Path],
    strip_ansi: Callable[[str], str],
    job_id: str,
) -> None:
    """Terminal failed job state exits EXIT_ERROR without printing Import completed."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    spec_path = write_openapi_spec(tmp_path / "petstore.json")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        status_code=202,
        json={"job_id": job_id, "state": "pending"},
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/acme-corp/imports/{job_id}",
        json={
            "state": "failed",
            "job_id": job_id,
            "summary": {"message": "OpenAPI parse error at paths./pets"},
        },
    )

    result = runner.invoke(
        app,
        ["--no-progress", "import", "openapi", str(spec_path)],
    )

    assert result.exit_code == EXIT_ERROR
    assert "Import completed: " not in result.stdout
    assert "OpenAPI parse error" in strip_ansi(result.stderr)


def test_import_openapi_async_timeout_exits_error(
    httpx_mock: object,
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    write_openapi_spec: Callable[[Path], Path],
    strip_ansi: Callable[[str], str],
    job_id: str,
) -> None:
    """Poll loop timeout exits EXIT_ERROR when the job never completes."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    spec_path = write_openapi_spec(tmp_path / "petstore.json")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        status_code=202,
        json={"job_id": job_id, "state": "pending"},
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/acme-corp/imports/{job_id}",
        method="GET",
        json={"state": "running", "job_id": job_id},
    )

    result = runner.invoke(
        app,
        ["--timeout", "1", "--no-progress", "import", "openapi", str(spec_path)],
    )

    assert result.exit_code == EXIT_ERROR
    assert "Import timed out after 1 second." in strip_ansi(result.stderr)


def test_import_openapi_no_wait_skips_poll(
    httpx_mock: object,
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    write_openapi_spec: Callable[[Path], Path],
    job_id: str,
) -> None:
    """--no-wait returns the 202 accept body without polling the job endpoint."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    spec_path = write_openapi_spec(tmp_path / "petstore.json")
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        status_code=202,
        json={"job_id": job_id, "state": "pending"},
    )

    result = runner.invoke(
        app,
        ["import", "openapi", "--no-wait", str(spec_path)],
    )

    assert result.exit_code == 0
    assert "Import accepted." in result.stdout
    assert job_id in result.stdout
    assert len(httpx_mock.get_requests()) == 1
