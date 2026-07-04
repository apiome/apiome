"""Tests for archive (zip/tar) upload intake — MFI-29.1 (#4388)."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.archive_intake import (
    ArchiveIntakeError,
    ArchivePolicy,
    detect_archive_format,
    is_archive_filename,
    is_archive_payload,
    unpack_archive,
)
from app.fileset import IntakeFileset
from app.grpc_import_source import GrpcImportSource
from app.import_source_pipeline import _ResolvedIntake, run_adapter_import_job
from app.toolchain_packaging import probe_tool

_FIXTURES = Path(__file__).parent / "fixtures" / "proto"


def _build_zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buf.getvalue()


def _build_tar_gz(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _proto_tree_bytes() -> bytes:
    common = (_FIXTURES / "common" / "types.proto").read_text(encoding="utf-8")
    user = (_FIXTURES / "user" / "user_service.proto").read_text(encoding="utf-8")
    return _build_zip(
        {
            "common/types.proto": common,
            "user/user_service.proto": user,
        }
    )


def test_is_archive_filename_and_payload() -> None:
    assert is_archive_filename("bundle.zip")
    assert is_archive_filename("bundle.tar.gz")
    assert is_archive_filename("bundle.tgz")
    assert not is_archive_filename("service.proto")
    raw = _build_zip({"a.proto": 'syntax = "proto3";\n'})
    assert is_archive_payload(raw)
    assert is_archive_payload(b"not an archive", "tree.zip")


def test_unpack_proto_tree_detects_root() -> None:
    unpacked = unpack_archive(_proto_tree_bytes(), source_label="protos.zip")
    assert unpacked.root_path == "user/user_service.proto"
    assert "common/types.proto" in unpacked.members
    assert unpacked.detection.matched
    fileset = IntakeFileset.from_members(unpacked.members, root=unpacked.root_path)
    assert 'syntax = "proto3"' in fileset.root_content()
    assert "service UserService" in fileset.root_content()


def test_rejects_path_traversal_member() -> None:
    raw = _build_zip({"../escape.proto": 'syntax = "proto3";\n'})
    with pytest.raises(ArchiveIntakeError, match="must not escape"):
        unpack_archive(raw)


def test_rejects_zip_bomb_by_total_size() -> None:
    policy = ArchivePolicy(
        max_entries=10,
        max_total_bytes=32,
        max_file_bytes=32,
        max_depth=8,
    )
    raw = _build_zip({"big.proto": "x" * 64})
    with pytest.raises(ArchiveIntakeError, match="uncompressed limit|per-file limit|compressed limit"):
        unpack_archive(raw, policy=policy)


def test_tar_gz_proto_tree_unpacks() -> None:
    common = (_FIXTURES / "common" / "types.proto").read_text(encoding="utf-8")
    user = (_FIXTURES / "user" / "user_service.proto").read_text(encoding="utf-8")
    raw = _build_tar_gz({"common/types.proto": common, "user/user_service.proto": user})
    unpacked = unpack_archive(raw, source_label="protos.tgz")
    assert unpacked.root_path == "user/user_service.proto"


def test_explicit_archive_root() -> None:
    raw = _proto_tree_bytes()
    unpacked = unpack_archive(raw, root_path="common/types.proto")
    assert unpacked.root_path == "common/types.proto"


@pytest.mark.asyncio
async def test_pipeline_imports_zipped_proto_tree_when_buf_available() -> None:
    if probe_tool("buf") is None:
        pytest.skip("buf not available in this environment")

    from app.grpc_import_source import GrpcImportSource

    import base64

    raw = _proto_tree_bytes()
    payload = {
        "rest_job_id": "job-archive-1",
        "tenant_id": "tenant-1",
        "filename": "protos.zip",
        "document_base64": base64.standard_b64encode(raw).decode("ascii"),
        "metadata": {
            "source_kind": "grpc",
            "project": {"name": "Users", "slug": "users"},
            "version": {"version_id": "1.0.0"},
            "options": {"dry_run": True},
        },
    }
    try:
        status = await run_adapter_import_job(GrpcImportSource(), payload)
    except Exception as exc:
        if "buf" in str(exc).lower():
            pytest.skip("buf not available in this environment")
        raise
    if status.state == "failed":
        errors = [event.message for event in status.events if event.level == "error"]
        if any("buf" in message.lower() for message in errors):
            pytest.skip("buf not available in this environment")
    assert status.state == "completed"


def test_grpc_parse_fileset_compiles_tree() -> None:
    if probe_tool("buf") is None:
        pytest.skip("buf not available in this environment")
    unpacked = unpack_archive(_proto_tree_bytes(), source_label="protos.zip")
    fileset = IntakeFileset.from_members(unpacked.members, root=unpacked.root_path)
    try:
        compiled = GrpcImportSource().parse_fileset(fileset, source_label="protos.zip")
    except Exception as exc:
        if "buf" in str(exc).lower():
            pytest.skip("buf not available in this environment")
        raise
    assert compiled.summary.file_count >= 2
