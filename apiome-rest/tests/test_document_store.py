"""Contract tests for the document store SPI and its three backends (COA-5.1, #7077).

One suite (``TestContract``) runs against ``db``, ``filesystem`` and ``s3`` (moto). Backend
specifics — multipart, encryption, presigned links, redaction, configuration — follow.
"""

from __future__ import annotations

import hashlib
import io
import logging
from types import SimpleNamespace

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from moto import mock_aws

from app import document_store as ds
from app.config import settings
from app.document_store import (
    BACKEND_DB,
    BACKEND_FILESYSTEM,
    BACKEND_S3,
    DbDocumentStore,
    DocumentNotFound,
    DocumentStore,
    DocumentStoreConfigError,
    DocumentStoreError,
    DocumentTooLarge,
    FilesystemDocumentStore,
    S3DocumentStore,
    build_document_store,
    get_document_store,
    normalize_prefix,
    object_key,
    parse_object_uri,
    set_document_store,
)

BUCKET = "apiome-documents"
ACCESS_KEY = "AKIAEXAMPLEKEY000001"
SECRET_KEY = "s3cr3t-Example/Key+Value0123456789abcdef"
TENANT = "0b7e6c1e-4a53-4c8e-9d0e-1f2a3b4c5d6e"
OTHER_TENANT = "acme"


class FakeBlobDatabase:
    """In-memory stand-in for the ``*_document_store_blob`` database methods."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.writes = 0

    def put_document_store_blob(self, *, tenant_id, sha256, size_bytes, media_type, content):
        if (tenant_id, sha256) in self.rows:
            return False
        self.writes += 1
        self.rows[(tenant_id, sha256)] = {
            "size_bytes": size_bytes,
            "media_type": media_type,
            "content": bytes(content),
        }
        return True

    def head_document_store_blob(self, tenant_id, sha256):
        row = self.rows.get((tenant_id, sha256))
        return None if row is None else {"size_bytes": row["size_bytes"], "media_type": row["media_type"]}

    def get_document_store_blob(self, tenant_id, sha256):
        row = self.rows.get((tenant_id, sha256))
        return None if row is None else row["content"]

    def delete_document_store_blob(self, tenant_id, sha256):
        return self.rows.pop((tenant_id, sha256), None) is not None


@pytest.fixture
def s3_client():
    """A boto3 client bound to an in-process moto S3 with the test bucket created."""
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        client.create_bucket(Bucket=BUCKET)
        yield client


def _s3_store(client, **overrides) -> S3DocumentStore:
    options = dict(
        bucket=BUCKET,
        prefix="apiome",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
        client_factory=lambda: client,
    )
    options.update(overrides)
    return S3DocumentStore(**options)


@pytest.fixture(params=[BACKEND_DB, BACKEND_FILESYSTEM, BACKEND_S3])
def store(request, tmp_path):
    """Each backend in turn, configured with the same storage folder."""
    if request.param == BACKEND_DB:
        yield DbDocumentStore(prefix="apiome", database=FakeBlobDatabase())
    elif request.param == BACKEND_FILESYSTEM:
        yield FilesystemDocumentStore(path=str(tmp_path / "store"), prefix="apiome")
    else:
        yield _s3_store(request.getfixturevalue("s3_client"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestContract:
    """Behavior every backend must share."""

    def test_meets_the_protocol(self, store):
        assert isinstance(store, DocumentStore)
        assert store.backend in (BACKEND_DB, BACKEND_FILESYSTEM, BACKEND_S3)

    def test_put_returns_a_content_addressed_reference(self, store):
        data = b'{"openapi":"3.1.0"}'
        ref = store.put(TENANT, data, "application/json")
        digest = _sha(data)
        assert ref.sha256 == digest
        assert ref.size_bytes == len(data)
        assert ref.media_type == "application/json"
        assert ref.backend == store.backend
        assert ref.tenant_id == TENANT
        assert ref.key == f"apiome/tenants/{TENANT}/objects/sha256/{digest[:2]}/{digest}"
        assert ref.uri.endswith(ref.key)
        assert ref.created is True

    def test_same_bytes_give_the_same_key_and_the_second_put_writes_nothing(self, store, monkeypatch):
        first = store.put(TENANT, b"same bytes", "text/plain")
        writes = []
        original = store._write
        monkeypatch.setattr(store, "_write", lambda *a, **k: writes.append(a) or original(*a, **k))
        second = store.put(TENANT, io.BytesIO(b"same bytes"), "text/plain")
        assert writes == []
        assert second == first
        assert second.key == first.key
        assert second.created is False

    def test_get_and_stream_return_the_bytes(self, store):
        data = b"line one\nline two\n" * 100
        ref = store.put(TENANT, data, "text/plain")
        assert store.get(TENANT, ref.sha256) == data
        with store.open_stream(TENANT, ref.sha256) as stream:
            assert stream.read(8) == b"line one"
            assert stream.read() == data[8:]

    def test_put_accepts_a_stream(self, store):
        data = bytes(range(256)) * 64
        ref = store.put(TENANT, io.BytesIO(data))
        assert ref.sha256 == _sha(data)
        assert ref.media_type == "application/octet-stream"
        assert store.get(TENANT, ref.sha256) == data

    def test_head_and_exists(self, store):
        data = b"headed"
        assert store.head(TENANT, _sha(data)) is None
        assert store.exists(TENANT, _sha(data)) is False
        ref = store.put(TENANT, data, "text/markdown")
        head = store.head(TENANT, "sha256:" + ref.sha256)
        assert head == ref
        assert head.media_type == "text/markdown"
        assert head.created is False
        assert store.exists(TENANT, ref.sha256) is True

    def test_missing_object_raises_not_found(self, store):
        missing = _sha(b"never stored")
        with pytest.raises(DocumentNotFound):
            store.get(TENANT, missing)
        with pytest.raises(DocumentNotFound):
            store.open_stream(TENANT, missing)

    def test_delete_removes_the_object_once(self, store):
        ref = store.put(TENANT, b"short-lived")
        assert store.delete(TENANT, ref.sha256) is True
        assert store.exists(TENANT, ref.sha256) is False
        assert store.delete(TENANT, ref.sha256) is False

    def test_tenants_never_share_an_object(self, store):
        data = b"equal bytes in two tenants"
        mine = store.put(TENANT, data)
        assert store.exists(OTHER_TENANT, mine.sha256) is False
        with pytest.raises(DocumentNotFound):
            store.get(OTHER_TENANT, mine.sha256)
        theirs = store.put(OTHER_TENANT, data)
        assert theirs.created is True
        assert theirs.key != mine.key
        assert store.delete(OTHER_TENANT, theirs.sha256) is True
        assert store.get(TENANT, mine.sha256) == data

    def test_empty_object_round_trips(self, store):
        ref = store.put(TENANT, b"")
        assert ref.size_bytes == 0
        assert store.get(TENANT, ref.sha256) == b""

    @pytest.mark.parametrize("tenant", ["", "..", "a/b", "../etc", "with space", "x" * 129, ".hidden"])
    def test_unsafe_tenant_ids_are_refused(self, store, tenant):
        with pytest.raises(ValueError):
            store.put(tenant, b"data")
        with pytest.raises(ValueError):
            store.get(tenant, _sha(b"data"))

    @pytest.mark.parametrize("digest", ["", "abc", "g" * 64, "../" + "a" * 61, "a" * 63])
    def test_malformed_digests_are_refused(self, store, digest):
        with pytest.raises(ValueError):
            store.head(TENANT, digest)

    def test_text_is_refused(self, store):
        with pytest.raises(TypeError):
            store.put(TENANT, "not bytes")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.put(TENANT, io.StringIO("not bytes"))  # type: ignore[arg-type]

    def test_reference_uri_parses_back(self, store):
        ref = store.put(TENANT, b"locate me")
        assert parse_object_uri(ref.uri) == (TENANT, ref.sha256)


class TestKeys:
    def test_key_layout(self):
        digest = "ab" + "0" * 62
        assert object_key("", "acme", digest) == f"tenants/acme/objects/sha256/ab/{digest}"
        assert object_key("a/b", "acme", digest) == f"a/b/tenants/acme/objects/sha256/ab/{digest}"
        assert object_key("", "acme", "SHA256:" + digest.upper()).endswith(digest)

    @pytest.mark.parametrize(
        "raw, expected",
        [(None, ""), ("", ""), ("/", ""), ("apiome", "apiome"), ("/teams/platform/apiome/", "teams/platform/apiome")],
    )
    def test_prefix_is_normalized(self, raw, expected):
        assert normalize_prefix(raw) == expected

    @pytest.mark.parametrize("raw", ["../up", "a/../b", "a//b", "a/./b", "a\\b", "a\nb"])
    def test_unsafe_prefix_is_refused(self, raw):
        with pytest.raises(DocumentStoreConfigError):
            normalize_prefix(raw)

    def test_empty_prefix_writes_at_the_root(self, tmp_path):
        store = FilesystemDocumentStore(path=str(tmp_path), prefix="")
        ref = store.put("acme", b"root")
        assert ref.key.startswith("tenants/acme/")
        assert (tmp_path / ref.key).read_bytes() == b"root"

    @pytest.mark.parametrize("uri", ["", "s3://bucket/other/key", "fs://tenants/acme/objects/sha256/ab/short"])
    def test_foreign_locators_are_refused(self, uri):
        with pytest.raises(ValueError):
            parse_object_uri(uri)


class TestDbBackend:
    def test_object_over_the_cap_is_refused_without_a_write(self):
        database = FakeBlobDatabase()
        store = DbDocumentStore(max_bytes=10, database=database)
        with pytest.raises(DocumentTooLarge) as excinfo:
            store.put(TENANT, io.BytesIO(b"x" * 11))
        assert excinfo.value.max_bytes == 10
        assert database.writes == 0
        assert store.put(TENANT, b"x" * 10).size_bytes == 10

    def test_a_lost_race_reports_not_created(self):
        database = FakeBlobDatabase()
        store = DbDocumentStore(database=database)
        database.put_document_store_blob = lambda **kwargs: False  # another writer inserted first
        assert store.put(TENANT, b"raced").created is False


class TestFilesystemBackend:
    def test_needs_a_path(self):
        with pytest.raises(DocumentStoreConfigError, match="APIOME_DOCUMENT_STORE_PATH"):
            FilesystemDocumentStore(path="  ")

    def test_objects_live_under_the_configured_directory(self, tmp_path):
        store = FilesystemDocumentStore(path=str(tmp_path / "data"), prefix="apiome")
        ref = store.put("acme", b"on disk", "text/plain")
        target = tmp_path / "data" / ref.key
        assert target.read_bytes() == b"on disk"
        assert not list(target.parent.glob(".upload-*"))

    def test_a_lost_sidecar_keeps_the_object(self, tmp_path):
        store = FilesystemDocumentStore(path=str(tmp_path))
        ref = store.put("acme", b"no sidecar", "text/plain")
        (tmp_path / (ref.key + ".meta")).unlink()
        head = store.head("acme", ref.sha256)
        assert head is not None and head.media_type == "application/octet-stream"
        assert store.get("acme", ref.sha256) == b"no sidecar"

    def test_write_failure_is_a_store_error_without_the_path(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where a directory is needed")
        store = FilesystemDocumentStore(path=str(blocker))
        with pytest.raises(DocumentStoreError) as excinfo:
            store.put("acme", b"data")
        assert str(tmp_path) not in str(excinfo.value)


class TestS3Backend:
    def test_reference_names_the_bucket(self, s3_client):
        ref = _s3_store(s3_client).put(TENANT, b"in a bucket", "text/plain")
        assert ref.uri == f"s3://{BUCKET}/{ref.key}"
        stored = s3_client.head_object(Bucket=BUCKET, Key=ref.key)
        assert stored["ContentType"] == "text/plain"
        assert stored["Metadata"]["sha256"] == ref.sha256

    def test_large_object_uploads_in_parts(self, s3_client, monkeypatch):
        monkeypatch.setattr(ds, "MULTIPART_THRESHOLD_BYTES", 5 * 1024 * 1024)
        monkeypatch.setattr(ds, "MULTIPART_CHUNK_BYTES", 5 * 1024 * 1024)
        data = b"0123456789abcdef" * (11 * 1024 * 1024 // 16)
        ref = _s3_store(s3_client).put(TENANT, io.BytesIO(data), "application/zip")
        stored = s3_client.head_object(Bucket=BUCKET, Key=ref.key)
        assert stored["ETag"].strip('"').endswith("-3")  # three parts
        assert stored["ContentLength"] == len(data)
        assert hashlib.sha256(s3_client.get_object(Bucket=BUCKET, Key=ref.key)["Body"].read()).hexdigest() == ref.sha256

    def test_sse_s3_is_requested(self, s3_client):
        ref = _s3_store(s3_client, sse="s3").put(TENANT, b"encrypted at rest")
        assert s3_client.head_object(Bucket=BUCKET, Key=ref.key)["ServerSideEncryption"] == "AES256"

    def test_sse_kms_is_requested_with_the_key(self, s3_client):
        ref = _s3_store(s3_client, sse="kms", kms_key_id="alias/apiome").put(TENANT, b"kms")
        stored = s3_client.head_object(Bucket=BUCKET, Key=ref.key)
        assert stored["ServerSideEncryption"] == "aws:kms"
        assert stored["SSEKMSKeyId"].endswith("alias/apiome")

    def test_presigned_link(self, s3_client):
        store = _s3_store(s3_client, presign_ttl_seconds=120)
        ref = store.put(TENANT, b"download me")
        url = store.presign_get(TENANT, ref.sha256)
        assert ref.key in url and "X-Amz-Expires=120" in url
        assert SECRET_KEY not in url
        assert "X-Amz-Expires=60" in store.presign_get(TENANT, ref.sha256, ttl=60)
        assert "X-Amz-Expires=604800" in store.presign_get(TENANT, ref.sha256, ttl=10**9)
        assert "X-Amz-Expires=1&" in store.presign_get(TENANT, ref.sha256, ttl=0) + "&"

    def test_other_backends_have_no_presigned_link(self, tmp_path):
        assert FilesystemDocumentStore(path=str(tmp_path)).presign_get(TENANT, _sha(b"x")) is None
        assert DbDocumentStore(database=FakeBlobDatabase()).presign_get(TENANT, _sha(b"x")) is None

    def test_missing_bucket_is_an_error_not_an_absent_object(self, s3_client):
        store = _s3_store(s3_client, bucket="no-such-bucket")
        with pytest.raises(DocumentStoreError) as excinfo:
            store.put(TENANT, b"data")
        assert not isinstance(excinfo.value, DocumentNotFound)
        assert "no-such-bucket" in str(excinfo.value)

    @pytest.mark.parametrize(
        "overrides, needle",
        [
            ({"bucket": ""}, "APIOME_DOCUMENT_STORE_BUCKET"),
            ({"addressing_style": "sideways"}, "ADDRESSING_STYLE"),
            ({"sse": "rot13"}, "APIOME_DOCUMENT_STORE_SSE"),
            ({"secret_access_key": ""}, "SECRET_ACCESS_KEY"),
            ({"prefix": "../escape"}, "APIOME_DOCUMENT_STORE_PREFIX"),
        ],
    )
    def test_bad_settings_are_refused(self, overrides, needle):
        with pytest.raises(DocumentStoreConfigError, match=needle):
            _s3_store(None, **overrides)

    def test_client_is_built_for_a_path_style_endpoint(self):
        """The shape Garage and MinIO need: custom endpoint, path-style, own region, static keys."""
        store = S3DocumentStore(
            bucket=BUCKET,
            prefix="apiome",
            region="garage",
            endpoint_url="http://127.0.0.1:3900",
            addressing_style="path",
            access_key_id=ACCESS_KEY,
            secret_access_key=SECRET_KEY,
            allow_private=True,
        )
        client = store.client
        assert client.meta.endpoint_url == "http://127.0.0.1:3900"
        assert client.meta.region_name == "garage"
        assert client.meta.config.s3["addressing_style"] == "path"
        assert client.meta.config.request_checksum_calculation == "when_required"
        url = store.presign_get(TENANT, _sha(b"x"))
        assert url.startswith(f"http://127.0.0.1:3900/{BUCKET}/apiome/tenants/{TENANT}/objects/sha256/")
        assert store.client is client


class TestEndpointGuard:
    def test_private_endpoint_is_refused_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "ssrf_allow_private", False)
        with pytest.raises(DocumentStoreConfigError, match="APIOME_DOCUMENT_STORE_ALLOW_PRIVATE"):
            S3DocumentStore(bucket=BUCKET, endpoint_url="http://127.0.0.1:3900")

    def test_private_endpoint_is_allowed_when_opted_in(self, monkeypatch):
        monkeypatch.setattr(settings, "ssrf_allow_private", False)
        store = S3DocumentStore(bucket=BUCKET, endpoint_url="http://127.0.0.1:3900", allow_private=True)
        assert store.endpoint_url == "http://127.0.0.1:3900"

    @pytest.mark.parametrize("endpoint", ["ftp://127.0.0.1/", "http://user:pw@127.0.0.1:3900", "not a url"])
    def test_malformed_endpoint_is_refused_even_when_private_is_allowed(self, endpoint):
        with pytest.raises(DocumentStoreConfigError):
            S3DocumentStore(bucket=BUCKET, endpoint_url=endpoint, allow_private=True)

    def test_refusal_does_not_echo_url_credentials(self):
        with pytest.raises(DocumentStoreConfigError) as excinfo:
            S3DocumentStore(
                bucket=BUCKET,
                endpoint_url=f"http://{ACCESS_KEY}:{SECRET_KEY}@127.0.0.1:3900",
                access_key_id=ACCESS_KEY,
                secret_access_key=SECRET_KEY,
                allow_private=True,
            )
        assert SECRET_KEY not in str(excinfo.value)
        assert ACCESS_KEY not in str(excinfo.value)


class _LeakyClient:
    """A client whose every call fails with an error that quotes both keys."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __getattr__(self, name):
        def _fail(*args, **kwargs):
            raise self._exc

        return _fail


def _leaky_errors():
    quoted = f"key {ACCESS_KEY} with secret {SECRET_KEY} was rejected"
    return [
        ClientError({"Error": {"Code": "SignatureDoesNotMatch", "Message": quoted}}, "PutObject"),
        RuntimeError(quoted),
    ]


class TestRedaction:
    """Secrets never appear in errors or logs."""

    @pytest.mark.parametrize("exc", _leaky_errors(), ids=["client-error", "other-error"])
    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.put(TENANT, b"data"),
            lambda s: s.get(TENANT, _sha(b"data")),
            lambda s: s.head(TENANT, _sha(b"data")),
            lambda s: s.delete(TENANT, _sha(b"data")),
            lambda s: s.presign_get(TENANT, _sha(b"data")),
        ],
        ids=["put", "get", "head", "delete", "presign"],
    )
    def test_provider_errors_are_redacted(self, exc, call, caplog):
        store = _s3_store(_LeakyClient(exc))
        with caplog.at_level(logging.DEBUG), pytest.raises(DocumentStoreError) as excinfo:
            call(store)
        error = excinfo.value
        for text in (str(error), repr(error), caplog.text):
            assert SECRET_KEY not in text
            assert ACCESS_KEY not in text
        assert "[redacted]" in str(error)
        assert error.__cause__ is None and error.__suppress_context__ is True

    def test_client_build_failure_is_redacted(self):
        def _factory():
            raise RuntimeError(f"cannot sign with {SECRET_KEY}")

        store = _s3_store(None, client_factory=_factory)
        with pytest.raises(DocumentStoreError) as excinfo:
            store.put(TENANT, b"data")
        assert SECRET_KEY not in str(excinfo.value)
        assert excinfo.value.__suppress_context__ is True

    def test_repr_holds_no_credentials(self, s3_client):
        text = repr(_s3_store(s3_client))
        assert SECRET_KEY not in text and ACCESS_KEY not in text
        assert BUCKET in text


def _config(**overrides):
    values = dict(
        document_store="db",
        document_store_bucket="",
        document_store_prefix="apiome",
        document_store_path="",
        document_store_region="",
        document_store_endpoint_url="",
        document_store_addressing_style="auto",
        document_store_sse="",
        document_store_kms_key_id="",
        document_store_access_key_id="",
        document_store_secret_access_key="",
        document_store_presign_ttl_seconds=300,
        document_store_db_max_bytes=1024,
        document_store_allow_private=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class TestConfiguration:
    def test_defaults_keep_the_database_backend(self):
        assert settings.document_store == "db"
        assert settings.document_store_prefix == "apiome"
        assert settings.document_store_presign_ttl_seconds == 300
        assert settings.document_store_db_max_bytes == 33_554_432
        assert settings.document_store_allow_private is False

    def test_builds_the_db_backend(self):
        store = build_document_store(_config())
        assert isinstance(store, DbDocumentStore)
        assert store.max_bytes == 1024 and store.prefix == "apiome"

    def test_builds_the_filesystem_backend(self, tmp_path):
        store = build_document_store(_config(document_store="Filesystem", document_store_path=str(tmp_path)))
        assert isinstance(store, FilesystemDocumentStore)
        assert store.root == tmp_path.resolve()

    def test_builds_the_s3_backend(self):
        store = build_document_store(
            _config(
                document_store="s3",
                document_store_bucket=BUCKET,
                document_store_prefix="/shared/apiome/",
                document_store_region="garage",
                document_store_endpoint_url="http://127.0.0.1:3900",
                document_store_addressing_style="path",
                document_store_sse="kms",
                document_store_kms_key_id="alias/apiome",
                document_store_access_key_id=ACCESS_KEY,
                document_store_secret_access_key=SECRET_KEY,
                document_store_presign_ttl_seconds=60,
                document_store_allow_private=True,
            )
        )
        assert isinstance(store, S3DocumentStore)
        assert (store.bucket, store.prefix, store.region) == (BUCKET, "shared/apiome", "garage")
        assert (store.addressing_style, store.sse, store.kms_key_id) == ("path", "aws:kms", "alias/apiome")
        assert store.presign_ttl_seconds == 60

    @pytest.mark.parametrize(
        "overrides",
        [{"document_store": "ftp"}, {"document_store": "s3"}, {"document_store": "filesystem"}],
    )
    def test_incomplete_settings_are_refused(self, overrides):
        with pytest.raises(DocumentStoreConfigError):
            build_document_store(_config(**overrides))

    def test_environment_names(self, monkeypatch, tmp_path):
        from app.config import Settings

        monkeypatch.setenv("APIOME_DOCUMENT_STORE", "filesystem")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_PATH", str(tmp_path))
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_PREFIX", "stores/apiome")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_BUCKET", "bucket")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_REGION", "garage")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_ENDPOINT_URL", "http://garage:3900")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_ADDRESSING_STYLE", "path")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_SSE", "s3")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_KMS_KEY_ID", "key")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_ACCESS_KEY_ID", ACCESS_KEY)
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_SECRET_ACCESS_KEY", SECRET_KEY)
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_PRESIGN_TTL_SECONDS", "90")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_DB_MAX_BYTES", "2048")
        monkeypatch.setenv("APIOME_DOCUMENT_STORE_ALLOW_PRIVATE", "true")
        loaded = Settings()
        assert loaded.document_store == "filesystem"
        assert loaded.document_store_path == str(tmp_path)
        assert loaded.document_store_prefix == "stores/apiome"
        assert loaded.document_store_bucket == "bucket"
        assert loaded.document_store_region == "garage"
        assert loaded.document_store_endpoint_url == "http://garage:3900"
        assert loaded.document_store_addressing_style == "path"
        assert loaded.document_store_sse == "s3"
        assert loaded.document_store_kms_key_id == "key"
        assert loaded.document_store_access_key_id == ACCESS_KEY
        assert loaded.document_store_secret_access_key == SECRET_KEY
        assert loaded.document_store_presign_ttl_seconds == 90
        assert loaded.document_store_db_max_bytes == 2048
        assert loaded.document_store_allow_private is True
        store = build_document_store(loaded)
        assert isinstance(store, FilesystemDocumentStore) and store.prefix == "stores/apiome"

    def test_process_store_is_built_once_and_replaceable(self, monkeypatch, tmp_path):
        set_document_store(None)
        try:
            monkeypatch.setattr(settings, "document_store", "filesystem")
            monkeypatch.setattr(settings, "document_store_path", str(tmp_path))
            first = get_document_store()
            assert isinstance(first, FilesystemDocumentStore)
            assert get_document_store() is first
            replacement = DbDocumentStore(database=FakeBlobDatabase())
            set_document_store(replacement)
            assert get_document_store() is replacement
        finally:
            set_document_store(None)
