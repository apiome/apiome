"""Download a revision's original — COA-5.7 (#7083).

The database is faked (the document tables of :class:`FakeDocumentDatabase` plus the two reads the
route makes); the store is real on every backend (``db``, ``filesystem``, ``s3`` through moto), and
originals are written with the same :func:`store_original` / :func:`store_original_fileset` an
import calls. Pinned acceptance criteria: the downloaded bytes' SHA-256 equals the stored digest
(also for a gzip-coded object) and a ``Range`` request answers ``206``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import version_original_routes
from app.auth import validate_authentication
from app.document_store import (
    BACKEND_DB,
    BACKEND_FILESYSTEM,
    BACKEND_S3,
    DbDocumentStore,
    FilesystemDocumentStore,
    set_document_store,
)
from app.main import app
from app.original_documents import MANIFEST_MEDIA_TYPE, store_original, store_original_fileset
from app.permissions import Action, Resource
from app.version_original import RangeNotSatisfiableError, etag_matches, parse_range
from tests.test_document_store import _s3_store, s3_client  # noqa: F401 - fixture
from tests.test_original_documents import FakeDocumentDatabase

client = TestClient(app)

TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
VERSION = "55555555-5555-4555-8555-555555555555"
SET_VERSION = "66666666-6666-4666-8666-666666666666"
BARE_VERSION = "77777777-7777-4777-8777-777777777777"
URL = f"/v1/versions/acme/{PROJECT}/{VERSION}/original"
DOC = "openapi: 3.1.0\ninfo:\n  title: Pets\n  version: 1.0.0\npaths: {}\n"
_AUTH = {"tenant_id": TENANT, "user_id": "u1", "auth_method": "jwt", "user_email": "a@x.io"}


class _Db(FakeDocumentDatabase):
    """The document tables plus the version and facts reads of the download route."""

    def __init__(self) -> None:
        super().__init__(versions={VERSION: TENANT, SET_VERSION: TENANT, BARE_VERSION: TENANT})
        self.facts: Dict[str, Dict[str, Any]] = {
            VERSION: {"source_label": "uploads/pets.yaml", "project_slug": "pets", "version_label": "1.0.0"},
            SET_VERSION: {"source_label": "bundle.zip", "project_slug": "pets", "version_label": "2.0.0"},
            BARE_VERSION: {"project_slug": "pets", "version_label": "3.0.0"},
        }
        self.legacy: Dict[str, str] = {}

    def get_version_by_id(self, version_id, tenant_id):
        if self.versions.get(version_id) != tenant_id:
            return None
        return {"id": version_id, "project_id": PROJECT}
    get_version_core = get_version_by_id

    def get_version_original_facts(self, *, tenant_id, version_id):
        return self.facts.get(version_id) if self.versions.get(version_id) == tenant_id else None

    def list_version_original_documents(self, *, tenant_id, version_id):
        slots = self.documents.get(version_id) or {}
        rows = []
        for path, object_id in slots.items():
            row = dict(self._object(object_id))
            if row["tenant_id"] != tenant_id:
                continue
            rows.append({**row, "role": "original" if path is None else "original_part", "part_path": path})
        return sorted(rows, key=lambda r: (r["role"] != "original", r["part_path"] or ""))

    def execute_query(self, sql, params):
        """The legacy-column reads of :func:`app.revision_source.revision_source`."""
        version_id = params[0]
        if "version_documents" in sql:
            return []
        text = self.legacy.get(version_id)
        if text is None:
            return []
        return [{"source_format": "openapi", "format_metadata": {"sourceContent": text}, "metadata": {}}]


@pytest.fixture(params=[BACKEND_DB, BACKEND_FILESYSTEM, BACKEND_S3])
def env(request, tmp_path, monkeypatch):
    """A fake database, a store on each backend and the route wired to both."""
    database = _Db()
    if request.param == BACKEND_DB:
        store = DbDocumentStore(prefix="apiome", database=database)
    elif request.param == BACKEND_FILESYSTEM:
        store = FilesystemDocumentStore(path=str(tmp_path / "store"), prefix="apiome")
    else:
        store = _s3_store(request.getfixturevalue("s3_client"))
    monkeypatch.setattr(version_original_routes, "db", database)
    monkeypatch.setattr("app.database.db", database)
    permissions: list = []
    monkeypatch.setattr(
        version_original_routes,
        "enforce_permission",
        lambda _db, _auth, resource, action, **_kw: permissions.append((resource, action)),
    )
    set_document_store(store)
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield {"db": database, "store": store, "backend": request.param, "permissions": permissions}
    app.dependency_overrides.pop(validate_authentication, None)
    set_document_store(None)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _store(env, text: str = DOC, version: str = VERSION):
    return store_original(TENANT, version, text, filename="pets.yaml", database=env["db"], store=env["store"])


class TestDownload:
    """The whole file, its name, digest and validators."""

    def test_downloaded_bytes_match_the_stored_digest(self, env):
        stored = _store(env)

        response = client.get(URL)

        assert response.status_code == 200
        assert response.content == DOC.encode()
        assert _sha(response.content) == stored.sha256 == stored.content_sha256
        assert response.headers["etag"] == f'"{stored.sha256}"'
        assert response.headers["x-apiome-content-sha256"] == stored.sha256
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["content-length"] == str(len(DOC.encode()))
        assert response.headers["content-type"].startswith("application/yaml")
        assert response.headers["content-disposition"] == 'attachment; filename="pets.yaml"'
        assert env["permissions"] == [(Resource.VERSIONS, Action.VIEW)]

    def test_a_gzip_coded_original_downloads_as_its_content(self, env, monkeypatch):
        monkeypatch.setattr("app.original_documents.settings.document_store_gzip_min_bytes", 64)
        text = DOC + "x-filler: " + "abc " * 4000 + "\n"
        stored = _store(env, text)
        assert stored.encoding == "gzip"

        response = client.get(URL)

        assert response.status_code == 200
        assert response.content == text.encode()
        assert _sha(response.content) == stored.content_sha256
        assert response.headers["etag"] == f'"{stored.content_sha256}"'
        ranged = client.get(URL, headers={"Range": "bytes=10-19"})
        assert ranged.status_code == 206 and ranged.content == text.encode()[10:20]

    def test_if_none_match_answers_304(self, env):
        stored = _store(env)

        response = client.get(URL, headers={"If-None-Match": f'W/"{stored.sha256}", "other"'})

        assert response.status_code == 304
        assert response.content == b""
        assert response.headers["etag"] == f'"{stored.sha256}"'

    def test_a_revalidation_reads_nothing_from_the_store(self, env, monkeypatch):
        stored = _store(env)
        monkeypatch.setattr(env["store"], "open_stream", lambda *_a: pytest.fail("the store was read"))

        response = client.get(URL, headers={"If-None-Match": f'"{stored.sha256}"'})

        assert response.status_code == 304

    def test_a_revision_without_a_file_name_gets_one(self, env):
        _store(env, DOC, BARE_VERSION)

        response = client.get(f"/v1/versions/acme/{PROJECT}/{BARE_VERSION}/original")

        assert response.headers["content-disposition"] == 'attachment; filename="pets-3.0.0.yaml"'


class TestRanges:
    """``Range`` → 206 / 416, and ``If-Range``."""

    def test_a_range_request_returns_206(self, env):
        _store(env)
        data = DOC.encode()

        response = client.get(URL, headers={"Range": "bytes=0-9"})

        assert response.status_code == 206
        assert response.content == data[:10]
        assert response.headers["content-range"] == f"bytes 0-9/{len(data)}"
        assert response.headers["content-length"] == "10"

    def test_open_and_suffix_ranges(self, env):
        _store(env)
        data = DOC.encode()

        assert client.get(URL, headers={"Range": "bytes=20-"}).content == data[20:]
        assert client.get(URL, headers={"Range": "bytes=-5"}).content == data[-5:]

    def test_a_range_past_the_end_is_416(self, env):
        _store(env)

        response = client.get(URL, headers={"Range": "bytes=999999-"})

        assert response.status_code == 416
        assert response.headers["content-range"] == f"bytes */{len(DOC.encode())}"

    def test_if_range_with_a_stale_etag_sends_everything(self, env):
        _store(env)

        response = client.get(URL, headers={"Range": "bytes=0-9", "If-Range": '"stale"'})

        assert response.status_code == 200 and response.content == DOC.encode()


class TestFilesets:
    """A set's manifest at ``/original`` and each file at ``/original/{part_path}``."""

    MEMBERS = {"api/openapi.yaml": DOC.encode(), "api/schemas/pet.json": b'{"type": "object"}'}

    def _store_set(self, env):
        return store_original_fileset(
            TENANT, SET_VERSION, self.MEMBERS, root="api/openapi.yaml", database=env["db"], store=env["store"]
        )

    def test_the_original_of_a_set_is_its_manifest(self, env):
        stored = self._store_set(env)

        response = client.get(f"/v1/versions/acme/{PROJECT}/{SET_VERSION}/original")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith(MANIFEST_MEDIA_TYPE)
        assert _sha(response.content) == stored.sha256
        manifest = json.loads(response.content)
        assert manifest["root"] == "api/openapi.yaml"
        assert [member["path"] for member in manifest["members"]] == sorted(self.MEMBERS)
        assert response.headers["content-disposition"] == 'attachment; filename="bundle.zip.manifest.json"'

    def test_each_part_downloads_by_its_path(self, env):
        self._store_set(env)

        response = client.get(f"/v1/versions/acme/{PROJECT}/{SET_VERSION}/original/api/schemas/pet.json")

        assert response.status_code == 200
        assert response.content == self.MEMBERS["api/schemas/pet.json"]
        assert response.headers["content-disposition"] == 'attachment; filename="pet.json"'

    def test_an_unknown_part_is_original_not_stored(self, env):
        self._store_set(env)

        response = client.get(f"/v1/versions/acme/{PROJECT}/{SET_VERSION}/original/missing.yaml")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "original-not-stored"

    def test_a_single_document_has_no_parts(self, env):
        _store(env)

        response = client.get(f"{URL}/pets.yaml")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "original-not-stored"


class TestMissing:
    """404 / 410 and the revision guard."""

    def test_nothing_stored_is_404_original_not_stored(self, env):
        response = client.get(URL)

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "original-not-stored"

    def test_a_withheld_source_is_410(self, env):
        env["db"].facts[VERSION]["source_withheld"] = "secrets-detected"

        response = client.get(URL)

        assert response.status_code == 410
        assert response.json()["detail"]["code"] == "original-withheld"
        assert response.json()["detail"]["reason"] == "secrets-detected"

    def test_another_projects_revision_is_404(self, env):
        _store(env)

        response = client.get(f"/v1/versions/acme/{VERSION}/{VERSION}/original")

        assert response.status_code == 404
        assert response.json()["detail"] == f"Version not found: {VERSION}"

    def test_a_malformed_id_is_404(self, env):
        assert client.get(f"/v1/versions/acme/{PROJECT}/not-a-uuid/original").status_code == 404

    def test_a_legacy_column_source_still_downloads(self, env):
        env["db"].legacy[VERSION] = DOC

        response = client.get(URL)

        assert response.status_code == 200
        assert response.content == DOC.strip().encode()
        assert response.headers["etag"] == f'"{_sha(DOC.strip().encode())}"'

    def test_bytes_gone_from_the_store_is_502(self, env):
        stored = _store(env)
        env["store"].delete(TENANT, stored.sha256)

        response = client.get(URL)

        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "original-unreadable"


class TestPresigned:
    """``?redirect=presigned``: a 302 from S3, a stream from every other backend."""

    def test_redirects_to_a_presigned_link_or_streams(self, env):
        stored = _store(env)

        response = client.get(URL, params={"redirect": "presigned"}, follow_redirects=False)

        if env["backend"] != BACKEND_S3:
            assert response.status_code == 200 and response.content == DOC.encode()
            return
        assert response.status_code == 302
        assert response.headers["cache-control"] == "private, no-store"
        location = urlparse(response.headers["location"])
        assert location.path.endswith(stored.sha256)
        query = parse_qs(location.query)
        assert query["X-Amz-Expires"] == ["300"]
        assert query["response-content-disposition"] == ['attachment; filename="pets.yaml"']
        assert query["response-content-type"] == ["application/yaml"]

    def test_a_gzip_coded_object_streams_instead(self, env, monkeypatch):
        monkeypatch.setattr("app.original_documents.settings.document_store_gzip_min_bytes", 64)
        text = DOC + "x: " + "y " * 4000
        _store(env, text)

        response = client.get(URL, params={"redirect": "presigned"}, follow_redirects=False)

        assert response.status_code == 200 and response.content == text.encode()

    def test_an_unknown_redirect_mode_is_422(self, env):
        assert client.get(URL, params={"redirect": "elsewhere"}).status_code == 422


class TestRangeParsing:
    """:func:`parse_range` and :func:`etag_matches` on their own."""

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            (None, None),
            ("bytes=0-0", (0, 0)),
            ("bytes=5-", (5, 99)),
            ("bytes=-10", (90, 99)),
            ("bytes=-500", (0, 99)),
            ("bytes=90-500", (90, 99)),
            ("bytes=0-1,5-6", None),
            ("items=0-1", None),
            ("bytes=9-3", None),
            ("bytes=-", None),
        ],
    )
    def test_ranges(self, header: Optional[str], expected):
        assert parse_range(header, 100) == expected

    @pytest.mark.parametrize("header", ["bytes=100-", "bytes=-0", "bytes=200-300"])
    def test_unsatisfiable(self, header: str):
        with pytest.raises(RangeNotSatisfiableError):
            parse_range(header, 100)

    def test_etag_matching(self):
        assert etag_matches('"abc"', "abc")
        assert etag_matches('W/"abc"', "abc")
        assert etag_matches("*", "abc")
        assert not etag_matches('"abd"', "abc")
        assert not etag_matches(None, "abc")
