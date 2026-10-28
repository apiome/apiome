"""Security review of the export surface — X6 (#6227).

One test group per finding the review fixed:

1. **Zip slip.** Emitters name files from imported, user-controlled content; the Avro emitter turned a
   namespace such as ``/abs/evil`` or ``C:\\x`` into an absolute or drive-letter archive member.
   Every emitted path is now normalised (:func:`app.zip_bundle.safe_bundle_path`, applied by
   :class:`app.emitter.EmittedFile`), the zip writer refuses an unsafe name outright, and the Avro and
   Avro IDL emitters build folders from sanitised namespace parts. A sweep runs every registered
   emitter over hostile names and extracts each bundle the way a naive tool would.
2. **Download names.** A name outside Latin-1 (``注文 API``) made the download a 500, and the
   synchronous route did not strip quotes. :func:`app.download_headers.attachment_headers` sends an
   ASCII ``filename`` plus an RFC 6266 ``filename*``.
3. **Content sniffing.** Downloads now carry ``X-Content-Type-Options: nosniff``.

Job isolation across tenants and users is covered by ``tests/test_export_permission_matrix.py`` (X4).
"""

from __future__ import annotations

import io
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any, List
from unittest.mock import patch
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.download_headers import attachment_headers, download_basename
from app.emitter import EmitResult, EmittedFile, available_emit_formats
from app.export_job_engine import build_export_zip
from app.export_service import ExportError, emit_canonical
from app.export_source import ExportSource
from app.main import app
from app.zip_bundle import safe_bundle_path, write_zip_entry

HOSTILE_NAMES = ["../../evil", "/abs/evil", "C:\\evil\\x", "a\\..\\..\\b", "line\nbreak", "注文\"API"]


def _api(name: str) -> CanonicalApi:
    """A small REST API whose every name — title, service, operation, type, namespace — is ``name``."""
    record = Type(
        key=name,
        name=name,
        namespace=name,
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key=f"{name}.id", name="id", type=TypeRef(name="string"))],
    )
    operation = Operation(key="GET /x", name=name, kind=OperationKind.QUERY, http_method="GET", http_path="/x")
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name=name),
        services=[Service(key=name, name=name, operations=[operation])],
        types=[record],
    )


def _is_safe(path: str) -> bool:
    return safe_bundle_path(path) == path


def _naive_extract_targets(archive_bytes: bytes, root: Path) -> List[Path]:
    """Where a naive extractor (``os.path.join(root, name)``) would write each member."""
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        return [Path(os.path.realpath(os.path.join(root, name))) for name in archive.namelist()]


# ---------------------------------------------------------------------------
# 1. Zip slip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,safe",
    [
        ("openapi.json", "openapi.json"),
        ("google/protobuf/timestamp.proto", "google/protobuf/timestamp.proto"),
        ("/etc/passwd", "etc/passwd"),
        ("../../etc/passwd", "_/_/etc/passwd"),
        ("a/./b//c", "a/b/c"),
        ("C:\\Windows\\x.dll", "Windows/x.dll"),
        ("a\\..\\b", "a/_/b"),
        ("na\x00me\r\n.txt", "name.txt"),
        ("注文/スキーマ.avsc", "注文/スキーマ.avsc"),
        ("", "file"),
        ("/../", "_"),
    ],
)
def test_safe_bundle_path(raw: str, safe: str) -> None:
    assert safe_bundle_path(raw) == safe
    assert safe_bundle_path(safe) == safe  # idempotent


def test_an_emitted_file_cannot_name_a_path_outside_the_bundle() -> None:
    assert EmittedFile(path="/abs/../x.json", content="{}").path == "abs/_/x.json"


@pytest.mark.parametrize("name", ["/abs/x", "../x", "a\\b", "C:x", "a/\x07b", ""])
def test_the_zip_writer_refuses_an_unsafe_member_name(name: str) -> None:
    with zipfile.ZipFile(io.BytesIO(), "w") as archive, pytest.raises(ValueError, match="unsafe zip entry"):
        write_zip_entry(archive, name, "x")


@pytest.mark.parametrize("namespace", ["/abs/evil", "..\\evil", "a/../../b", "C:\\x", ".hidden..ns."])
def test_avro_folders_come_from_sanitised_namespace_parts(namespace: str, tmp_path: Path) -> None:
    """The namespace from the source and the ``namespace`` option both stay inside the bundle."""
    record = _api("Widget").types[0].model_copy(update={"namespace": None})
    plain = _api("Widget").model_copy(update={"types": [record]})
    from_source = emit_canonical(_api(namespace), "avro")
    from_option = emit_canonical(plain, "avro", opts={"namespace": namespace})
    for result in (from_source, from_option):
        assert all(_is_safe(f.path) for f in result.files), [f.path for f in result.files]
        for target in _naive_extract_targets(build_export_zip(result, "avro"), tmp_path):
            assert tmp_path in target.parents


def test_avro_keeps_a_well_formed_namespace_as_folders() -> None:
    result = emit_canonical(_api("Widget").model_copy(update={"types": [
        _api("Widget").types[0].model_copy(update={"namespace": "com.acme.orders"})
    ]}), "avro")
    assert [f.path for f in result.files] == ["com/acme/orders/Widget.avsc"]


@pytest.mark.parametrize("namespace", ["/abs/../evil", "C:\\x", "..\\evil"])
def test_avro_idl_folders_come_from_sanitised_namespace_parts(namespace: str) -> None:
    """The ``.avdl`` output (``output_syntax: avdl``) names its folder from the namespace too."""
    result = emit_canonical(_api("Widget"), "avro", opts={"output_syntax": "avdl", "namespace": namespace})
    assert [f.path.endswith(".avdl") for f in result.files] == [True] * len(result.files)
    assert all(_is_safe(f.path) for f in result.files), [f.path for f in result.files]


@pytest.mark.parametrize("fmt", sorted(available_emit_formats()))
@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_no_emitter_writes_outside_the_bundle(fmt: str, name: str, tmp_path: Path) -> None:
    """Every emitter, over hostile names: safe paths, and a naive extraction stays under the root."""
    try:
        result = emit_canonical(_api(name), fmt)
    except (ExportError, ValueError):
        return  # a refusal (source-bound target, invalid generated name) writes nothing
    assert all(_is_safe(f.path) for f in result.files), [f.path for f in result.files]
    for target in _naive_extract_targets(build_export_zip(result, fmt), tmp_path):
        assert tmp_path in target.parents, target


def test_a_multi_file_bundle_with_hostile_paths_extracts_inside_the_root(tmp_path: Path) -> None:
    result = EmitResult(
        media_type="text/plain",
        files=[EmittedFile(path="../../escape.txt", content="a"), EmittedFile(path="/abs.txt", content="b")],
    )
    for target in _naive_extract_targets(build_export_zip(result, "x"), tmp_path):
        assert tmp_path in target.parents


# ---------------------------------------------------------------------------
# 2 + 3. Download names and nosniff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,ascii_name,utf8_name",
    [
        ("openapi.json", "openapi.json", None),
        ("注文 API.jtd.json", "API.jtd.json", "注文 API.jtd.json"),
        ('a"b.json', "ab.json", None),
        ("evil\r\nSet-Cookie: x.json", "evilSet-Cookie: x.json", None),
        ("dir/sub/name.proto", "name.proto", None),
        ("", "download", None),
    ],
)
def test_attachment_headers(filename: str, ascii_name: str, utf8_name: str | None) -> None:
    headers = attachment_headers(filename)
    for value in headers.values():
        value.encode("latin-1")  # never raises
        assert "\r" not in value and "\n" not in value
    disposition = headers["Content-Disposition"]
    assert disposition.startswith(f'attachment; filename="{ascii_name}"')
    extended = re.search(r"filename\*=UTF-8''(.+)$", disposition)
    assert (unquote(extended.group(1)) if extended else None) == utf8_name
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_download_basename_keeps_only_the_last_safe_segment() -> None:
    assert download_basename("../../x/y.json") == "y.json"
    assert download_basename("\\\\server\\share\\z.json") == "z.json"


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def signed_in():
    app.dependency_overrides[validate_authentication] = lambda tenant_slug: {
        "tenant_id": "tenant-acme",
        "tenant_slug": tenant_slug,
        "user_id": "user-1",
        "auth_method": "jwt",
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _source(name: str) -> ExportSource:
    return ExportSource(api=_api(name), artifact_id="artifact-1", version_record_id="rev-1", version_label="1.0.0")


def _assert_unicode_download(response: Any, expected: str) -> None:
    assert response.status_code == 200, response.text[:300]
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="')
    assert unquote(re.search(r"filename\*=UTF-8''(.+)$", disposition).group(1)) == expected


def test_the_document_route_downloads_a_non_ascii_name(signed_in) -> None:
    """Before X6 this was a 500: the name could not be encoded into the header."""
    with patch("app.export_routes.load_export_source", return_value=_source("注文 API")):
        response = client.post("/v1/export/acme/document", json={"artifact": "artifact-1", "target": "jtd"})
    _assert_unicode_download(response, "注文-api.jtd.json")


def test_the_job_download_route_downloads_a_non_ascii_name(signed_in) -> None:
    from app import export_job_engine as eje

    eje._jobs.clear()
    with patch("app.export_job_engine.load_export_source", return_value=_source("注文 API")):
        job_id = client.post("/v1/export/acme/jobs", json={"artifact": "artifact-1", "target": "jtd"}).json()["job_id"]
        for _ in range(500):
            if client.get(f"/v1/export/acme/jobs/{job_id}").json()["state"] in ("completed", "failed"):
                break
            time.sleep(0.01)
    _assert_unicode_download(client.get(f"/v1/export/acme/jobs/{job_id}/download"), "注文-api.jtd.json")
    eje._jobs.clear()


def test_a_bundle_download_is_nosniff(signed_in) -> None:
    from app import export_job_engine as eje

    eje._jobs.clear()
    with patch("app.export_job_engine.load_export_source", return_value=_source("Widgets")):
        job_id = client.post(
            "/v1/export/acme/jobs",
            json={"artifact": "artifact-1", "targets": [{"target": "openapi"}, {"target": "jtd"}]},
        ).json()["job_id"]
        for _ in range(500):
            if client.get(f"/v1/export/acme/jobs/{job_id}").json()["state"] in ("completed", "failed"):
                break
            time.sleep(0.01)
    response = client.get(f"/v1/export/acme/jobs/{job_id}/download")
    assert response.status_code == 200, response.text[:300]
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-content-type-options"] == "nosniff"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert all(_is_safe(name) for name in archive.namelist())
    eje._jobs.clear()
