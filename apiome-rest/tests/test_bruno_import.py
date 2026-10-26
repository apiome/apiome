"""Bruno collection import — MFI-32.4 (#4406).

Covers the ``.bru`` lexer (:mod:`app.bru_lang`), the reader (:mod:`app.bruno_parser`), the normalizer
(:mod:`app.bruno_normalizer`) and the adapter (:mod:`app.bruno_import_source`) against the acceptance
criteria:

* a Bruno repository imports **via archive and via git intake with identical fingerprints** — run
  through the real import pipeline both ways;
* ``.bru`` grammar edge cases are handled: multipart bodies, multi-line values, quoted keys, disabled
  entries, unknown blocks, and **script blocks ignored with a note** in the coverage ledger;
* the folder tree becomes tags and environments become server variables and parameter defaults;
  secrets never reach the model, the ledger or the stored source.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

from app import import_source_pipeline
from app.bru_lang import BruSyntaxError, parse_bru
from app.bruno_normalizer import AUTH_EXTRAS_KEY, BRUNO_EXTRAS_KEY
from app.bruno_parser import BrunoParseError, detect_bruno, parse_bruno_fileset, parse_bruno_text
from app.canonical_model import CanonicalApi, MessageRole, ParameterLocation
from app.fileset import IntakeFileset
from app.git_intake import pack_fileset_zip
from app.import_preview_manifest import build_import_preview_manifest
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    canonical_fingerprint,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
)
from app.import_source_pipeline import ImportRunArtifacts, _ResolvedIntake, scrub_intake_source
from app.inference_provenance import INFERRED, provenance_of
from app.intake_secret_scrub import scrub_document_text

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "bruno"
#: The nested collection, committed zipped (its tree is deeper than a corpus set directory allows).
_COLLECTION_ZIP = _EXAMPLES / "03-users-collection.zip"
_ZIP_PREFIX = "03-users-collection/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adapter():
    return get_import_source("bruno")


def _example(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _members(prefix: str = "") -> Dict[str, str]:
    """The fixture collection, keyed as an archive (``prefix``) or a git selection (no prefix)."""
    with zipfile.ZipFile(_COLLECTION_ZIP) as archive:
        return {
            prefix + name[len(_ZIP_PREFIX) :]: archive.read(name).decode("utf-8")
            for name in sorted(archive.namelist())
            if not name.endswith("/")
        }


def _member(path: str) -> str:
    return _members()[path]


def _import_set(members: Dict[str, str], root: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root=root)))


def _collection() -> CanonicalApi:
    return _import_set(_members(), "bruno.json")


def _import(text: str, label: str = "request.bru") -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=label))


def _operations(api: CanonicalApi) -> Dict[str, Any]:
    return {op.key: op for service in api.services for op in service.operations}


def _bru(method: str = "get", url: str = "https://a.example.com/x", extra: str = "", auth: str = "none") -> str:
    return (
        "meta {\n  name: R\n  type: http\n  seq: 1\n}\n\n"
        f"{method} {{\n  url: {url}\n  body: none\n  auth: {auth}\n}}\n\n{extra}"
    )


# ---------------------------------------------------------------------------
# The .bru lexer
# ---------------------------------------------------------------------------


def test_lexer_reads_dict_text_and_list_blocks() -> None:
    blocks = parse_bru(_example("04-stress-every-block.bru"))
    by_name = {block.name: block for block in blocks}
    query = by_name["params:query"]
    assert [(e.key, e.value, e.enabled) for e in query.entries] == [
        ("dry_run", "false", True),
        ("verbose", "1", False),
        ("quoted key", "a value: with a colon", True),
    ]
    assert by_name["vars:pre-request"].values()["note"] == "a multi-line\nvalue"
    assert by_name["docs"].kind == "text"
    assert "A brace on an indented line does not close the block." in by_name["docs"].text
    assert by_name["body:json"].text.startswith('{\n  "kept"')
    secret = parse_bru(_member("environments/staging.bru"))[1]
    assert (secret.kind, [e.key for e in secret.entries]) == ("list", ["accessToken", "adminPassword"])


def test_an_unknown_block_with_free_text_is_kept_as_text() -> None:
    example = {block.name: block for block in parse_bru(_example("04-stress-every-block.bru"))}["example"]
    assert example.kind == "text" and "and a line with no colon" in example.text


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("url: x\n", "INPUT_MALFORMED"),
        ("headers {\n  no colon here\n}\n", "INPUT_MALFORMED"),
        ("meta {\n  name: x\n", "INPUT_TRUNCATED"),
        ("vars {\n  note: '''\n    open\n}\n", "INPUT_TRUNCATED"),
        ('headers {\n  "unterminated: x\n}\n', "INPUT_MALFORMED"),
    ],
)
def test_lexer_errors(text: str, code: str) -> None:
    with pytest.raises(BruSyntaxError) as excinfo:
        parse_bru(text)
    assert excinfo.value.code == code


def test_crlf_line_endings_are_read() -> None:
    blocks = parse_bru(_example("01-minimal-get.bru").replace("\n", "\r\n"))
    assert [block.name for block in blocks] == ["meta", "get"]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_claims_bruno_json_and_request_files() -> None:
    manifest = detect_bruno(_member("bruno.json"))
    request = detect_bruno(_example("01-minimal-get.bru"))
    assert manifest is not None and manifest[1] >= 0.98
    assert request is not None and request[1] >= 0.95


@pytest.mark.parametrize("name", ["environments/local.bru", "users/folder.bru"])
def test_detect_claims_settings_and_environment_files_only_weakly(name: str) -> None:
    found = detect_bruno(_member(name))
    assert found is not None and found[1] <= 0.4


@pytest.mark.parametrize(
    "text",
    [
        "just text",
        json.dumps({"type": "collection"}),
        json.dumps({"info": {}, "item": []}),
        "GET https://a.example.com\n",
    ],
)
def test_detect_ignores_other_documents(text: str) -> None:
    assert not _adapter().detect(DetectionInput(text=text)).matched


def test_registry_detection_picks_bruno_for_requests_and_the_manifest() -> None:
    for path in sorted(_EXAMPLES.glob("0*.bru")) + [_EXAMPLES / "07-flat-orders-collection" / "bruno.json"]:
        adapter, _ = detect_import_source(DetectionInput(text=path.read_text(encoding="utf-8"), filename=path.name))
        assert adapter is not None and adapter.key == "bruno", path.name


def test_descriptor() -> None:
    descriptor = _adapter().descriptor()
    assert descriptor.label == "Bruno collection"
    assert ".bru" in descriptor.file_extensions and ".zip" in descriptor.file_extensions


# ---------------------------------------------------------------------------
# Acceptance: archive and git intake give identical fingerprints
# ---------------------------------------------------------------------------


def test_the_committed_zip_parses_as_bytes_like_an_archive() -> None:
    adapter = _adapter()
    assert adapter.detect(DetectionInput(data=_COLLECTION_ZIP.read_bytes(), filename="c.zip")).matched
    from_bytes = adapter.normalize(adapter.parse_bytes(_COLLECTION_ZIP.read_bytes(), source_label="c.zip"))
    assert canonical_fingerprint(from_bytes) == canonical_fingerprint(_collection())


def test_bytes_that_are_not_a_zip_are_an_archive_error() -> None:
    with pytest.raises(ImportSourceError):
        _adapter().parse_bytes(b"PK\x03\x04 not really", source_label="broken.zip")


def test_the_flat_collection_set_imports() -> None:
    folder = _EXAMPLES / "07-flat-orders-collection"
    members = {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir()}
    api = _import_set(members, "bruno.json")
    operations = _operations(api)
    assert set(operations) == {"GET /v2/orders", "GET /v2/orders/{orderId}"}
    assert operations["GET /v2/orders"].extras["security"] == ["apiKey"]
    assert api.servers[0].variables[0].default == "https://orders.example.com"  # collection variable


def test_archive_and_git_member_keys_give_the_same_model() -> None:
    """An archive wraps the collection in a folder; a git selection strips its prefix."""
    archive = _members("users-api/")
    archive["README.md"] = "# notes beside the collection"
    archive["other/unrelated.bru"] = _bru()  # outside the collection folder: ignored
    from_archive = _import_set(archive, "users-api/bruno.json")
    from_git = _import_set(_members(), "bruno.json")
    assert canonical_fingerprint(from_archive) == canonical_fingerprint(from_git)
    assert from_archive.model_dump_json() == from_git.model_dump_json()


def _zip(members: Dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(members):
            info = zipfile.ZipInfo(path, date_time=(2026, 10, 25, 0, 0, 0))
            archive.writestr(info, members[path])
    return buffer.getvalue()


async def _run(document: bytes, filename: str, options: Dict[str, Any]) -> ImportRunArtifacts:
    payload = {
        "rest_job_id": f"bruno-{filename}",
        "metadata": {
            "source_kind": "bruno",
            "project": {"name": "Users API", "slug": "users-api"},
            "version": {"version_id": "0.0.1"},
            "options": {"dry_run": True, "input_kind": "fileset", **options},
        },
        "document_base64": base64.standard_b64encode(document).decode("ascii"),
        "filename": filename,
    }
    artifacts = ImportRunArtifacts()
    final = await import_source_pipeline.run_adapter_import_job(
        get_import_source("bruno"), payload, artifacts=artifacts
    )
    assert final.state == "completed", final.error
    return artifacts


async def test_archive_and_git_intake_through_the_pipeline_fingerprint_identically() -> None:
    archive = await _run(_zip(_members("users-api/")), "users-api.zip", {})
    git = await _run(
        pack_fileset_zip(_members()),
        "users-api.zip",
        {
            "archive_root": "bruno.json",
            "git_source": {
                "repo_url": "https://github.com/example/users-api",
                "ref": "main",
                "commit_sha": "0" * 40,
                "path": "api/bruno",
            },
        },
    )
    assert archive.fingerprint and archive.fingerprint == git.fingerprint
    assert archive.model is not None and set(_operations(archive.model)) == set(_operations(git.model))


# ---------------------------------------------------------------------------
# The collection: folders, auth, variables
# ---------------------------------------------------------------------------


def test_folder_tree_becomes_tags_with_folder_bru_names() -> None:
    operations = _operations(_collection())
    assert operations["GET /health"].tags == []
    assert operations["GET /v1/users"].tags == ["Users"]
    assert operations["DELETE /v1/users/{id}"].tags == ["Users / Admin"]
    assert _collection().extras[BRUNO_EXTRAS_KEY]["folders"] == ["Users", "Users / Admin"]


def test_auth_inherits_request_folder_collection() -> None:
    operations = _operations(_collection())
    assert operations["GET /v1/users"].extras["security"] == ["bearer"]
    assert operations["GET /v1/users"].extras[AUTH_EXTRAS_KEY] == [
        {"type": "bearer", "scheme": "bearer", "declared_at": "collection"}
    ]
    assert operations["DELETE /v1/users/{id}"].extras[AUTH_EXTRAS_KEY][0]["declared_at"] == "Users / Admin"
    assert "security" not in operations["GET /health"].extras  # `auth: none`


def test_environment_variables_become_server_variables_and_defaults() -> None:
    api = _collection()
    [server] = api.servers
    assert (server.url, server.variables[0].default) == ("{baseUrl}", "http://localhost:3000")  # first env
    listing = {(p.location, p.name): p for p in _operations(api)["GET /v1/users"].parameters}
    assert listing[(ParameterLocation.QUERY, "limit")].default == "20"
    assert listing[(ParameterLocation.QUERY, "page")].default is None
    assert listing[(ParameterLocation.HEADER, "x-tenant")].default == "acme"  # folder header, env value
    assert (ParameterLocation.QUERY, "debug") not in listing  # disabled


def test_secret_variables_are_listed_and_never_defaults() -> None:
    record = {(v["name"], v["source"]): v["secret"] for v in _collection().extras[BRUNO_EXTRAS_KEY]["variables"]}
    assert record[("accessToken", "environment:local")] is True
    assert record[("adminPassword", "environment:staging")] is True
    assert record[("tenant", "environment:local")] is False
    assert record[("apiVersion", "collection")] is False


def test_request_variables_beat_environment_and_collection() -> None:
    """Bruno's precedence: request > folder > environment > collection."""
    members = _members()
    members["users/override.bru"] = _bru(
        url="{{baseUrl}}/v1/paged",
        extra="params:query {\n  limit: {{pageSize}}\n  version: {{apiVersion}}\n}\n\n"
        "vars:pre-request {\n  pageSize: 50\n}\n",
    )
    members["environments/local.bru"] = members["environments/local.bru"].replace(
        "  pageSize: 20\n", "  pageSize: 20\n  apiVersion: v9\n"
    )
    api = _import_set(members, "bruno.json")
    params = {p.name: p.default for p in _operations(api)["GET /v1/paged"].parameters}
    assert params["limit"] == "50"  # the request's own variable beats the environment's 20
    assert params["version"] == "v9"  # the environment beats collection.bru's apiVersion: v1
    listing = {p.name: p.default for p in _operations(api)["GET /v1/users"].parameters}
    assert listing["limit"] == "20"


def test_path_parameters_and_bodies() -> None:
    api = _collection()
    operations = _operations(api)
    path = {p.name for p in operations["GET /v1/users/{id}"].parameters if p.location is ParameterLocation.PATH}
    assert path == {"id"}
    create = [m for m in operations["POST /v1/users"].messages if m.role is MessageRole.REQUEST][0]
    assert create.content_types == ["application/json"]
    types = {t.name: t for t in api.types}
    assert {f.name for f in types[create.payload.name].fields} == {"name", "email", "roles", "active"}
    upload = [m for m in operations["POST /v1/users/{id}/avatar"].messages if m.role is MessageRole.REQUEST][0]
    assert upload.content_types == ["multipart/form-data"]
    assert {f.name for f in types[upload.payload.name].fields} == {"caption", "file"}  # disabled part left out


def test_bruno_json_ignore_list_is_honoured() -> None:
    members = _members()
    members["node_modules/pkg/noise.bru"] = _bru(url="https://noise.example.com/x")
    assert "GET /x" not in _operations(_import_set(members, "bruno.json"))


def test_non_http_requests_are_left_out_with_a_note() -> None:
    members = _members()
    members["grpc-hello.bru"] = "meta {\n  name: Hello gRPC\n  type: grpc\n  seq: 9\n}\n"
    api = _import_set(members, "bruno.json")
    limits = {limit["construct"]: limit for limit in api.extras[BRUNO_EXTRAS_KEY]["capability_limits"]}
    assert limits["bruno.grpc_request"]["locations"] == ["Hello gRPC"]


def test_import_is_deterministic_and_inferred() -> None:
    first, second = _collection(), _collection()
    assert first.model_dump_json() == second.model_dump_json()
    assert provenance_of(first.extras) == INFERRED
    assert all(provenance_of(op.extras) == INFERRED for op in _operations(first).values())


# ---------------------------------------------------------------------------
# Single .bru files and grammar edge cases
# ---------------------------------------------------------------------------


def test_a_single_request_imports_on_its_own() -> None:
    api = _import(_example("02-typical-create-order.bru"))
    operation = _operations(api)["POST /v2/orders"]
    assert api.title == "Bruno collection"
    assert operation.extras["security"] == ["bearer"]
    names = {p.name for p in operation.parameters if p.location is ParameterLocation.HEADER}
    assert {"idempotency-key", "content-type"} <= names
    idem = {p.name: p for p in operation.parameters}["idempotency-key"]
    assert idem.default == "order-0001"  # from the request's own vars:pre-request


def test_scripts_and_tests_are_ignored_with_a_note() -> None:
    api = _import(_example("04-stress-every-block.bru"))
    limits = {limit["construct"]: limit for limit in api.extras[BRUNO_EXTRAS_KEY]["capability_limits"]}
    assert limits["bruno.script"]["note"].startswith("Pre-request and post-response scripts")
    assert limits["bruno.test"]["count"] == 1
    assert limits["bruno.process_env"]["count"] == 1
    manifest = build_import_preview_manifest(api, adapter_key="bruno")
    rows = {row.source_construct: row for row in manifest.document_coverage}
    assert rows["bruno.script"].coverage.value == "not-parsed-by-adapter"
    assert rows["bruno.auth_credential"].coverage.value == "partially-mapped"
    collection_limits = {
        limit["construct"]: limit for limit in _collection().extras[BRUNO_EXTRAS_KEY]["capability_limits"]
    }
    assert collection_limits["bruno.script"]["count"] == 6  # the collection's script applies to every request


def test_only_the_declared_body_mode_is_sent() -> None:
    """Bruno keeps every body block it ever had; the method block's ``body`` mode picks one."""
    api = _import(_example("04-stress-every-block.bru"))
    [operation] = _operations(api).values()
    [message] = [m for m in operation.messages if m.role is MessageRole.REQUEST]
    assert message.content_types == ["application/x-www-form-urlencoded"]
    fields = {f.name for t in api.types if t.name == message.payload.name for f in t.fields}
    assert fields == {"name", "password"}


def test_oauth2_and_api_key_keep_public_facts_only() -> None:
    [stress] = _operations(_import(_example("04-stress-every-block.bru"))).values()
    assert stress.extras[AUTH_EXTRAS_KEY] == [
        {
            "type": "oauth2",
            "scheme": "oauth2",
            "declared_at": "request",
            "grant_type": "client_credentials",
            "token_url": "https://auth.example.com/oauth/token",
            "scopes": ["items:read", "items:write"],
        }
    ]
    [graphql] = _operations(_import(_example("06-composition-graphql-with-vars.bru"))).values()
    assert graphql.extras[AUTH_EXTRAS_KEY][0]["key_name"] == "X-Shop-Key"
    assert graphql.extras["security"] == ["apiKey"]


def test_graphql_body_becomes_query_and_variables() -> None:
    api = _import(_example("06-composition-graphql-with-vars.bru"))
    [operation] = _operations(api).values()
    [message] = [m for m in operation.messages if m.role is MessageRole.REQUEST]
    assert message.content_types == ["application/json"]
    assert {f.name for t in api.types if t.name == message.payload.name for f in t.fields} == {"query", "variables"}


def test_an_undefined_leading_variable_keeps_a_server_without_a_default() -> None:
    api = _import(_example("04-stress-every-block.bru"))
    assert [(s.url, s.variables[0].default) for s in api.servers] == [("{host}", None)]
    [operation] = _operations(api).values()
    assert operation.http_path == "/v3/tenants/{tenantId}/items/{itemId}"


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

_PLANTED = [
    "demo-bearer-not-real",
    "demo-header-key-not-real",
    "demo-client-secret-not-real",
    "demo-unused-bearer-not-real",
    "demo-form-password-not-real",
    "demo-admin-not-real",
]


@pytest.mark.parametrize("name", ["02-typical-create-order.bru", "04-stress-every-block.bru"])
def test_no_secret_reaches_the_model_or_the_ledger(name: str) -> None:
    api = _import(_example(name))
    manifest = build_import_preview_manifest(api, adapter_key="bruno")
    rendered = api.model_dump_json() + repr(manifest.document_coverage) + repr(manifest.entity_rows)
    for secret in _PLANTED:
        assert secret not in rendered, secret


def test_no_secret_reaches_the_stored_source_of_a_file_or_an_archive() -> None:
    for name in ("02-typical-create-order.bru", "04-stress-every-block.bru"):
        text = _example(name)
        intake = _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None)
        fields, report = scrub_intake_source(intake)
        assert report["scrubbed"] is True
        for secret in _PLANTED:
            assert secret not in fields["sourceContent"], (name, secret)
    members = _members()
    members["users/admin/folder.bru"] = members["users/admin/folder.bru"].replace(
        "{{adminPassword}}", "demo-admin-not-real"
    )
    fileset = IntakeFileset.from_members(members, root="bruno.json")
    intake = _ResolvedIntake(raw_bytes=b"", text=None, fileset=fileset, archive_root="bruno.json")
    fields, _ = scrub_intake_source(intake)
    assert "demo-admin-not-real" not in json.dumps(fields)


def test_a_literal_api_key_value_in_a_bru_file_is_scrubbed() -> None:
    text = _bru(
        auth="apikey", extra="auth:apikey {\n  key: X-API-Key\n  value: literal-key-0042\n  placement: header\n}\n"
    )
    assert "literal-key-0042" not in scrub_document_text(text).text
    assert "literal-key-0042" not in _import(text).model_dump_json()


# ---------------------------------------------------------------------------
# Taxonomy codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("negative/01-syntactic-line-outside-block.bru", "INPUT_MALFORMED"),
        ("negative/02-semantic-environment-alone.bru", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-unclosed-block.bru", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-postman.json", "FORMAT_MISMATCH"),
        ("negative/06-semantic-bruno-json-alone.json", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_negative_corpus_codes(name: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        _import(_example(name), label=name)
    assert excinfo.value.code == code


def test_utf16_upload_is_an_encoding_fault() -> None:
    text = (_EXAMPLES / "negative/05-encoding-utf16.bru").read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(BrunoParseError) as excinfo:
        parse_bruno_text(text)
    assert excinfo.value.code == "INPUT_ENCODING_INVALID"


@pytest.mark.parametrize(
    ("members", "code"),
    [
        ({"a.bru": _bru()}, "INPUT_SEMANTIC_INVALID"),  # .bru files but no bruno.json
        ({"notes.md": "# x"}, "FORMAT_MISMATCH"),
        ({"bruno.json": json.dumps({"version": "1", "name": "E", "type": "collection"})}, "INPUT_SEMANTIC_INVALID"),
        ({"bruno.json": "[]", "a.bru": _bru()}, "INPUT_MALFORMED"),
        (
            {"bruno.json": '{"version": "1", "name": "E", "type": "collection"}', "a.bru": _bru(url="")},
            "INPUT_SEMANTIC_INVALID",
        ),
        (
            {"bruno.json": '{"version": "1", "name": "E", "type": "collection"}', "a.bru": "meta {\n  name: X\n}\n"},
            "INPUT_MALFORMED",
        ),
        (
            {"bruno.json": '{"version": "1", "name": "E", "type": "collection"}', "a.bru": _bru(url="{{nowhere}}")},
            "INPUT_SEMANTIC_INVALID",
        ),
    ],
)
def test_fileset_refusals(members: Dict[str, str], code: str) -> None:
    root = "bruno.json" if "bruno.json" in members else next(iter(members))
    with pytest.raises(BrunoParseError) as excinfo:
        parse_bruno_fileset(members, root=root)
    assert excinfo.value.code == code


def test_normalize_rejects_a_foreign_ast() -> None:
    with pytest.raises(ImportSourceError):
        _adapter().normalize({"version": "1"})
