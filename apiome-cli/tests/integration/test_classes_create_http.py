"""httpx-mocked end-to-end flow for ``apiome classes create`` (CLI 7.3, #3231).

Creates a class in a fixture **draft** version from a YAML class spec and follows every request
the command makes, in order: resolve the project and version, check the version is a draft and not
frozen, read the version's classes and the project's properties, create the class, attach its
properties, create the missing project tag and tag the class.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_DRAFT = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_CLASS = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def test_create_a_class_in_a_fixture_draft(
    httpx_mock: object, tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The YAML spec becomes a class with two properties and a new tag, in one ordered sequence."""
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    spec = tmp_path / "refund.yaml"
    spec.write_text(
        "name: Refund\ndescription: Reversal of a charge.\ntags: [financial]\n"
        "properties:\n  - amount:required\n  - reason\n",
        encoding="utf-8",
    )
    t = "acme-corp"
    httpx_mock.add_response(url=f"{_HOST}/projects/{t}/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/version-tags/{t}/{_PROJECT}", json=[])
    httpx_mock.add_response(
        url=f"{_HOST}/versions/{t}/{_PROJECT}", json=[{"id": _DRAFT, "version_id": "2.2.0-rc.1", "published": False}]
    )
    httpx_mock.add_response(url=f"{_HOST}/versions/{t}/{_PROJECT}/{_DRAFT}/freeze-schema", json={"frozen": False})
    httpx_mock.add_response(url=f"{_HOST}/classes/{t}?version_id={_DRAFT}", json=[{"name": "Charge"}])
    httpx_mock.add_response(
        url=f"{_HOST}/properties/{t}/{_PROJECT}",
        json=[
            {"id": "p-amount", "name": "amount", "data": {"type": "number"}},
            {"id": "p-reason", "name": "reason", "data": {"type": "string"}},
        ],
    )
    httpx_mock.add_response(url=f"{_HOST}/classes/{t}", method="POST", json={"id": _CLASS, "name": "Refund"})
    httpx_mock.add_response(url=f"{_HOST}/classes/{t}/{_CLASS}/properties", method="POST", json={"id": "cp"}, is_reusable=True)
    httpx_mock.add_response(url=f"{_HOST}/project-tags/{t}/{_PROJECT}", method="GET", json=[])
    httpx_mock.add_response(url=f"{_HOST}/project-tags/{t}/{_PROJECT}", method="POST", json={"id": "t1", "name": "financial"})
    httpx_mock.add_response(url=f"{_HOST}/project-tags/{t}/classes/{_CLASS}", method="POST", json={"id": "ct1"})

    result = runner.invoke(app, ["classes", "create", "payments-api", "2.2.0-rc.1", "--from-file", str(spec), "--yes"])

    assert result.exit_code == 0, result.output
    assert "✔ Created class 'Refund' with 2 properties." in result.stdout
    calls = [(r.method, str(r.url).removeprefix(_HOST)) for r in httpx_mock.get_requests()]
    assert calls[-6:] == [
        ("POST", f"/classes/{t}"),
        ("POST", f"/classes/{t}/{_CLASS}/properties"),
        ("POST", f"/classes/{t}/{_CLASS}/properties"),
        ("GET", f"/project-tags/{t}/{_PROJECT}"),
        ("POST", f"/project-tags/{t}/{_PROJECT}"),
        ("POST", f"/project-tags/{t}/classes/{_CLASS}"),
    ]
    attached = [json.loads(r.content) for r in httpx_mock.get_requests() if r.url.path.endswith("/properties") and r.method == "POST"]
    assert [(a["name"], a["data"]["required"]) for a in attached] == [("amount", True), ("reason", False)]
