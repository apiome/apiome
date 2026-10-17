"""``apiome projects export`` (CLI 3.6, #3207).

Against a mocked REST API holding two versions, classes with properties, paths with operations,
class and version tags and a migration plan, these pin the issue's acceptance criteria:

* the output is deterministic byte-for-byte across runs (JSON, gzip and YAML), and the streamed
  JSON is exactly ``json.dumps(document, sort_keys=True, separators=(",", ":"))`` + newline;
* the document is written section by section and one version at a time
  (:class:`~apiome_cli.project_export.ExportWriter`), and nothing reaches stdout when the export
  fails before its first section;
* summary counts and the SHA-256 go to stderr, so stdout carries only the document;
* ``--include`` / ``--exclude`` / ``--versions`` select what is exported; ``data`` is refused
  (the API cannot list data records yet).

The export → import round trip waits for the future import command.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.project_export import (
    DEFAULT_SECTIONS,
    ExportError,
    ExportWriter,
    human_size,
    resolve_sections,
    select_versions,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme-corp",
}
_HOST = "http://localhost:8000/v1"
_P = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V1 = "11111111-1111-4111-8111-111111111111"
_V2 = "22222222-2222-4222-8222-222222222222"
_PATH = "33333333-3333-4333-8333-333333333333"

_PROJECT = {"id": _P, "slug": "payments-api", "name": "Payments API", "updated_at": "2026-10-16T12:00:00Z"}
# Listed newest first, as the API returns them; the export orders them oldest first.
_VERSIONS = [
    {"id": _V2, "version_id": "2.0.0", "published": True, "created_at": "2026-10-02T00:00:00Z"},
    {"id": _V1, "version_id": "1.0.0", "published": False, "created_at": "2026-10-01T00:00:00Z"},
]
_CLASSES = {
    _V1: [{"id": "c1", "name": "Order", "properties": [{"name": "id"}], "tags": []}],
    _V2: [
        {"id": "c2", "name": "Order", "properties": [{"name": "id"}, {"name": "total"}], "tags": [{"tag_name": "core"}]},
        {"id": "c3", "name": "Refund", "properties": [], "tags": []},
    ],
}
_PATHS = {_V1: [], _V2: [{"id": _PATH, "pathname": "/orders"}]}
_PATH_FULL = {"id": _PATH, "pathname": "/orders", "operations": [{"operation": "get"}, {"operation": "post"}]}
_PROPERTIES = [{"id": "lp1", "name": "id"}, {"id": "lp2", "name": "total"}]
_CLASS_TAGS = [{"id": "t1", "name": "core"}]
_VERSION_TAGS = [
    {"id": "vt1", "name": "stable", "version_id": _V1},
    {"id": "vt2", "name": "latest", "version_id": _V2},
]
_PLANS = {
    "plans": [
        {
            "id": "mp1",
            "from_version_id": _V1,
            "to_version_id": _V2,
            "rules": [{"class_name": "Order", "source_property": "id", "rule": {"ruleType": "simple"}}],
        }
    ]
}


def _mock_api(httpx_mock, *, reusable: bool = True) -> None:
    """Serve every read the export makes (reusable, so two runs can share it)."""
    routes = {
        f"{_HOST}/projects/acme-corp/by-slug/payments-api": _PROJECT,
        f"{_HOST}/projects/acme-corp/{_P}": _PROJECT,
        f"{_HOST}/versions/acme-corp/{_P}": _VERSIONS,
        f"{_HOST}/properties/acme-corp/{_P}": _PROPERTIES,
        f"{_HOST}/project-tags/acme-corp/{_P}": _CLASS_TAGS,
        f"{_HOST}/version-tags/acme-corp/{_P}": _VERSION_TAGS,
        f"{_HOST}/migration-plans/acme-corp/projects/{_P}": _PLANS,
        f"{_HOST}/paths/acme-corp/{_V2}/{_PATH}/full": _PATH_FULL,
    }
    for version_id in (_V1, _V2):
        routes[f"{_HOST}/classes/acme-corp/version/{version_id}/with-properties-tags"] = _CLASSES[version_id]
        routes[f"{_HOST}/paths/acme-corp/{version_id}"] = _PATHS[version_id]
    for url, payload in routes.items():
        httpx_mock.add_response(url=url, json=payload, is_reusable=reusable, is_optional=True)


def _export(*args: str) -> object:
    return runner.invoke(app, ["projects", "export", "payments-api", *args], env=_ENV)


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def test_export_holds_every_section_and_is_canonical_json(httpx_mock) -> None:
    _mock_api(httpx_mock)
    result = _export()
    assert result.exit_code == EXIT_SUCCESS, result.output
    raw = result.stdout_bytes
    document = json.loads(raw)
    # Byte-for-byte the canonical serialization of the parsed document.
    assert raw == (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    assert document["exporterVersion"] == 1
    assert document["format"] == "apiome.project-export"
    assert document["sections"] == list(DEFAULT_SECTIONS)
    assert document["project"]["slug"] == "payments-api"
    # Oldest version first, each carrying its classes and full paths.
    assert [v["version"]["version_id"] for v in document["versions"]] == ["1.0.0", "2.0.0"]
    assert [c["name"] for c in document["versions"][1]["classes"]] == ["Order", "Refund"]
    assert document["versions"][1]["paths"][0]["operations"] == [{"operation": "get"}, {"operation": "post"}]
    assert document["properties"] == _PROPERTIES
    assert document["tags"] == {"classTags": _CLASS_TAGS, "versionTags": _VERSION_TAGS}
    assert document["migrations"] == _PLANS["plans"]
    assert "exportedAt" not in document


def test_two_runs_are_byte_identical(httpx_mock) -> None:
    _mock_api(httpx_mock)
    first, second = _export(), _export()
    assert first.stdout_bytes == second.stdout_bytes


def test_summary_goes_to_stderr_with_the_document_sha(httpx_mock) -> None:
    _mock_api(httpx_mock)
    result = _export()
    sha = hashlib.sha256(result.stdout_bytes).hexdigest()
    assert "✔ Exported 2 versions, 3 classes, 2 properties, 1 path, 3 tags, 1 migration plan" in result.stderr
    assert f"deterministic SHA-256: {sha}" in result.stderr
    assert "Exported" not in result.stdout


def test_output_file_is_written_whole_and_named_only_when_complete(httpx_mock, tmp_path) -> None:
    _mock_api(httpx_mock)
    target = tmp_path / "backups" / "payments-api.json"
    target.parent.mkdir()
    result = _export("--output", str(target))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(target.read_text(encoding="utf-8"))["format"] == "apiome.project-export"
    assert not list(target.parent.glob(".*.partial"))
    assert result.stdout == ""
    assert f"→ {target}" in result.stderr


def test_gzip_is_reproducible_and_decompresses_to_the_json(httpx_mock) -> None:
    _mock_api(httpx_mock)
    plain = _export().stdout_bytes
    first, second = _export("--gzip").stdout_bytes, _export("--gzip").stdout_bytes
    assert first == second
    assert gzip.decompress(first) == plain


def test_yaml_is_the_same_document(httpx_mock) -> None:
    from yaml12 import parse_yaml

    _mock_api(httpx_mock)
    as_json = json.loads(_export().stdout_bytes)
    first = _export("--format", "yaml")
    assert first.exit_code == EXIT_SUCCESS, first.output
    assert parse_yaml(first.stdout) == as_json
    assert _export("--format", "yaml").stdout_bytes == first.stdout_bytes


def test_no_deterministic_adds_exported_at(httpx_mock) -> None:
    _mock_api(httpx_mock)
    document = json.loads(_export("--no-deterministic").stdout_bytes)
    assert "exportedAt" in document


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_include_and_exclude_select_sections(httpx_mock) -> None:
    _mock_api(httpx_mock)
    document = json.loads(_export("--include", "versions,classes", "--exclude", "classes").stdout_bytes)
    assert document["sections"] == ["versions"]
    assert "classes" not in document["versions"][0]
    assert "tags" not in document and "migrations" not in document


def test_versions_filter_matches_labels_with_or_without_v(httpx_mock) -> None:
    _mock_api(httpx_mock)
    document = json.loads(_export("--versions", "v2.0.0").stdout_bytes)
    assert [v["version"]["version_id"] for v in document["versions"]] == ["2.0.0"]
    assert document["versionsFilter"] == ["2.0.0"]
    # Tags and plans that point outside the selection are left out.
    assert [t["name"] for t in document["tags"]["versionTags"]] == ["latest"]
    assert document["migrations"] == []


def test_an_unknown_version_writes_nothing(httpx_mock) -> None:
    _mock_api(httpx_mock)
    result = _export("--versions", "9.9.9")
    assert result.exit_code == EXIT_USAGE
    assert "No version labelled '9.9.9'" in result.stderr
    assert result.stdout_bytes == b""


@pytest.mark.parametrize(
    "args,fragment",
    [
        (["--include", "data"], "cannot be exported yet"),
        (["--include", "bogus"], "Unknown section"),
        (["--include", "classes"], "include 'versions' too"),
        (["--format", "xml"], "--format must be json or yaml"),
    ],
    ids=["data", "unknown-section", "classes-without-versions", "bad-format"],
)
def test_bad_options_are_usage_errors_before_any_request(httpx_mock, args, fragment) -> None:
    result = _export(*args)
    assert result.exit_code == EXIT_USAGE
    assert fragment in result.stderr
    assert httpx_mock.get_requests() == []


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def test_writer_streams_the_canonical_bytes() -> None:
    document = {"b": [{"z": 1, "a": None}], "a": {"y": "é", "x": [3, 1]}}
    buffer = io.BytesIO()
    writer = ExportWriter(buffer, deterministic=True)
    writer.member("a", document["a"])
    writer.begin_array("b")
    writer.element(document["b"][0])
    writer.end_array()
    writer.finish()
    expected = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    assert buffer.getvalue() == expected.encode("utf-8")
    assert writer.sha256 == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert writer.size == len(expected.encode("utf-8"))


def test_an_empty_writer_still_writes_a_valid_object() -> None:
    buffer = io.BytesIO()
    writer = ExportWriter(buffer)
    writer.finish()
    assert buffer.getvalue() == b"{}\n"


def test_section_rules() -> None:
    assert resolve_sections(None, None) == DEFAULT_SECTIONS
    assert resolve_sections(None, "migrations,tags") == ("versions", "classes", "properties", "paths")
    assert resolve_sections("Properties, Tags", None) == ("properties", "tags")
    with pytest.raises(ExportError, match="cannot be exported yet"):
        resolve_sections("versions,data", None)
    # `--exclude data` is accepted (it is the default anyway).
    assert resolve_sections(None, "data") == DEFAULT_SECTIONS


def test_version_selection_orders_oldest_first() -> None:
    assert [v["version_id"] for v in select_versions(_VERSIONS, None)] == ["1.0.0", "2.0.0"]
    assert [v["version_id"] for v in select_versions(_VERSIONS, " 1.0.0 , V2.0.0")] == ["1.0.0", "2.0.0"]


def test_human_size() -> None:
    assert human_size(512) == "512 B"
    assert human_size(4_404_019) == "4.2 MiB"
