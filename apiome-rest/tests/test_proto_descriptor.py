"""Tests for the protobuf ``.proto`` → ``FileDescriptorSet`` compile service (MFI-9.1, #3764).

Two layers, mirroring the module:

* **Read-layer tests** (always run, no ``buf``) build synthetic ``FileDescriptorSet``\\s with
  :mod:`google.protobuf.descriptor_pb2` and assert the metadata extraction — per-file
  syntax/edition (proto2, proto3, Editions 2023, Editions 2024), import flagging, public
  dependencies, message/enum/service counts, and the rolled-up summary.
* **Compile-layer tests** (always run, no ``buf``) drive :func:`compile_proto_descriptor_set`
  with an injected fake runner that stands in for ``buf build``: it snapshots the scratch
  module the service materialised (proving the proto files + ``buf.yaml`` were laid down at the
  right paths) and writes a pre-built descriptor set to the ``--output`` path, so the whole
  orchestration — materialise → invoke → read back → flag imports — is exercised without the
  real binary. Error mapping (tool missing / timeout / compile failure) is covered here too.
* **End-to-end test** (gated, like the AsyncAPI parser e2e) runs the *real* bundled ``buf``
  through the *real* toolchain runner against the on-disk fixtures, but only when ``buf``
  actually resolves in this environment (the built image, or a dev box with
  ``APIOME_BUF_BIN`` set).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest
from google.protobuf import descriptor_pb2

from app.proto_descriptor import (
    BUF_TOOL_KEY,
    PROTO_SUPPORTED_EDITIONS,
    CompiledDescriptorSet,
    DescriptorSetSummary,
    ProtoCompileError,
    ProtoDescriptorError,
    ProtoFile,
    compile_proto_descriptor_set,
    read_file_descriptor_set,
)
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import (
    ToolExecutionError,
    ToolNotAvailableError,
    ToolSandboxError,
    ToolSpec,
    ToolTimeoutError,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "proto"


# ===========================================================================
# Synthetic descriptor builders (the read layer's test vehicle — no buf)
# ===========================================================================


def _add_file(
    fds: descriptor_pb2.FileDescriptorSet,
    name: str,
    *,
    package: str = "",
    syntax: Optional[str] = None,
    edition: Optional[int] = None,
    deps: Sequence[str] = (),
    public_dep_indices: Sequence[int] = (),
    messages: Sequence[str] = (),
    enums: Sequence[str] = (),
    services: Sequence[str] = (),
) -> descriptor_pb2.FileDescriptorProto:
    """Append one ``FileDescriptorProto`` to ``fds`` with the requested shape."""
    f = fds.file.add()
    f.name = name
    if package:
        f.package = package
    if syntax is not None:
        f.syntax = syntax
    if edition is not None:
        f.edition = edition
    for dep in deps:
        f.dependency.append(dep)
    for idx in public_dep_indices:
        f.public_dependency.append(idx)
    for m in messages:
        f.message_type.add().name = m
    for e in enums:
        f.enum_type.add().name = e
    for s in services:
        f.service.add().name = s
    return f


def _sample_descriptor_set() -> descriptor_pb2.FileDescriptorSet:
    """A four-file set spanning proto3, Editions 2023/2024 and a proto2 well-known import."""
    fds = descriptor_pb2.FileDescriptorSet()
    _add_file(
        fds,
        "acme/user.proto",
        package="acme.user",
        syntax="proto3",
        deps=["acme/common.proto", "google/protobuf/timestamp.proto"],
        public_dep_indices=[0],
        messages=["User", "GetUserRequest"],
        enums=["Role"],
        services=["UserService"],
    )
    _add_file(
        fds,
        "acme/common.proto",
        package="acme.common",
        syntax="editions",
        edition=descriptor_pb2.Edition.EDITION_2023,
        messages=["Address", "Money"],
    )
    _add_file(
        fds,
        "acme/v2.proto",
        package="acme.v2",
        syntax="editions",
        edition=descriptor_pb2.Edition.EDITION_2024,
        services=["V2Service"],
    )
    _add_file(
        fds,
        "google/protobuf/timestamp.proto",
        package="google.protobuf",
        messages=["Timestamp"],
    )
    return fds


# ===========================================================================
# Read layer
# ===========================================================================


class TestReadFileDescriptorSet:
    def test_extracts_per_file_metadata(self) -> None:
        data = _sample_descriptor_set().SerializeToString()
        result = read_file_descriptor_set(
            data, target_files=["acme/user.proto", "acme/common.proto", "acme/v2.proto"]
        )
        assert isinstance(result, CompiledDescriptorSet)
        # The bytes are passed through unchanged — this is the canonical artifact to hash.
        assert result.descriptor_set_bytes == data
        assert isinstance(result.proto, descriptor_pb2.FileDescriptorSet)

        by_name = {f.name: f for f in result.files}
        user = by_name["acme/user.proto"]
        assert user.syntax == "proto3"
        assert user.edition is None
        assert user.dependencies == ["acme/common.proto", "google/protobuf/timestamp.proto"]
        # public_dependency index 0 → the first dependency path.
        assert user.public_dependencies == ["acme/common.proto"]
        assert user.message_count == 2
        assert user.enum_count == 1
        assert user.service_count == 1
        assert user.is_import is False

    def test_editions_2023_and_2024_labelled(self) -> None:
        data = _sample_descriptor_set().SerializeToString()
        result = read_file_descriptor_set(data)
        by_name = {f.name: f for f in result.files}
        assert by_name["acme/common.proto"].syntax == "editions"
        assert by_name["acme/common.proto"].edition == "2023"
        assert by_name["acme/v2.proto"].edition == "2024"
        # Both acceptance-criteria editions are recognised.
        assert set(PROTO_SUPPORTED_EDITIONS) == {"2023", "2024"}

    def test_proto2_default_syntax(self) -> None:
        # A FileDescriptorProto with no syntax field is proto2 by definition.
        data = _sample_descriptor_set().SerializeToString()
        result = read_file_descriptor_set(data)
        wkt = {f.name: f for f in result.files}["google/protobuf/timestamp.proto"]
        assert wkt.syntax == "proto2"
        assert wkt.edition is None

    def test_imports_flagged_against_targets(self) -> None:
        data = _sample_descriptor_set().SerializeToString()
        result = read_file_descriptor_set(data, target_files=["acme/user.proto"])
        by_name = {f.name: f for f in result.files}
        assert by_name["acme/user.proto"].is_import is False
        # Everything not in the target set is an import.
        assert by_name["acme/common.proto"].is_import is True
        assert by_name["google/protobuf/timestamp.proto"].is_import is True
        assert {f.name for f in result.target_files} == {"acme/user.proto"}

    def test_no_targets_means_all_targets(self) -> None:
        data = _sample_descriptor_set().SerializeToString()
        result = read_file_descriptor_set(data)  # target_files=None
        assert all(f.is_import is False for f in result.files)
        assert len(result.target_files) == len(result.files)

    def test_summary_rollup(self) -> None:
        data = _sample_descriptor_set().SerializeToString()
        result = read_file_descriptor_set(
            data, target_files=["acme/user.proto", "acme/common.proto", "acme/v2.proto"]
        )
        summary = result.summary
        assert isinstance(summary, DescriptorSetSummary)
        assert summary.file_count == 4
        assert summary.target_file_count == 3
        assert summary.syntaxes == ["editions", "proto2", "proto3"]
        assert summary.editions == ["2023", "2024"]
        assert summary.packages == ["acme.common", "acme.user", "acme.v2", "google.protobuf"]
        assert summary.service_count == 2
        assert summary.message_count == 5  # User, GetUserRequest, Address, Money, Timestamp
        assert summary.enum_count == 1

    def test_empty_descriptor_set_reads_cleanly(self) -> None:
        data = descriptor_pb2.FileDescriptorSet().SerializeToString()
        result = read_file_descriptor_set(data)
        assert result.files == ()
        assert result.summary.file_count == 0
        assert result.summary.syntaxes == []

    @pytest.mark.parametrize("garbage", [b"not a descriptor set", b"\xff\xff\xff\xff", b"{}"])
    def test_unparseable_bytes_raise(self, garbage: bytes) -> None:
        with pytest.raises(ProtoDescriptorError):
            read_file_descriptor_set(garbage)

    def test_public_dependency_out_of_range_is_ignored(self) -> None:
        # A malformed descriptor with a public_dependency index past the end must not crash.
        fds = descriptor_pb2.FileDescriptorSet()
        _add_file(fds, "a.proto", syntax="proto3", deps=["b.proto"], public_dep_indices=[5])
        result = read_file_descriptor_set(fds.SerializeToString())
        assert result.files[0].public_dependencies == []


# ===========================================================================
# A fake runner standing in for `buf build`
# ===========================================================================


@dataclass
class _FakeRunResult:
    """Minimal stand-in for ``ToolRunResult`` (the compile path ignores it on success)."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


@dataclass
class _Call:
    spec: ToolSpec
    args: List[str]
    timeout: Optional[float]
    scratch: Dict[str, str] = field(default_factory=dict)
    output_path: Optional[str] = None


class _FakeBufRunner:
    """A toolchain-runner double for ``buf build``.

    On ``run_spec`` it snapshots the materialised scratch module (so a test can assert the
    proto files and ``buf.yaml`` were written at the right relative paths), then either raises a
    fixed error or writes ``descriptor_bytes`` to the ``--output`` path the service requested —
    exactly what real ``buf`` does — and returns success.
    """

    def __init__(
        self,
        *,
        descriptor_bytes: Optional[bytes] = None,
        error: Optional[Exception] = None,
        write_output: bool = True,
    ) -> None:
        self._descriptor_bytes = descriptor_bytes
        self._error = error
        self._write_output = write_output
        self.calls: List[_Call] = []

    async def run_spec(
        self,
        spec: ToolSpec,
        args: Sequence[str] = (),
        *,
        timeout: Optional[float] = None,
        policy: Any = None,
        **_: Any,
    ) -> _FakeRunResult:
        args = list(args)
        input_dir = args[0]
        output_path = args[args.index("--output") + 1]
        # Snapshot every file the service laid down under the input dir.
        scratch: Dict[str, str] = {}
        base = Path(input_dir)
        for p in sorted(base.rglob("*")):
            if p.is_file():
                scratch[str(p.relative_to(base))] = p.read_text(encoding="utf-8")
        self.calls.append(
            _Call(spec=spec, args=args, timeout=timeout, scratch=scratch, output_path=output_path)
        )

        if self._error is not None:
            raise self._error
        if self._write_output and self._descriptor_bytes is not None:
            Path(output_path).write_bytes(self._descriptor_bytes)
        return _FakeRunResult()


def _two_target_descriptor() -> bytes:
    """A descriptor set whose files mirror a two-target compile plus one pulled-in import."""
    fds = descriptor_pb2.FileDescriptorSet()
    _add_file(fds, "common/types.proto", package="acme.common", syntax="proto3", messages=["Address"])
    _add_file(
        fds,
        "user/user_service.proto",
        package="acme.user",
        syntax="proto3",
        deps=["common/types.proto", "google/protobuf/timestamp.proto"],
        messages=["User"],
        services=["UserService"],
    )
    _add_file(fds, "google/protobuf/timestamp.proto", package="google.protobuf", messages=["Timestamp"])
    return fds.SerializeToString()


# ===========================================================================
# Compile layer (fake runner)
# ===========================================================================


class TestCompileProtoDescriptorSet:
    async def test_materializes_module_and_reads_back(self) -> None:
        files = [
            ProtoFile(path="common/types.proto", content="syntax = \"proto3\";\npackage acme.common;\n"),
            ProtoFile(
                path="user/user_service.proto",
                content="syntax = \"proto3\";\npackage acme.user;\nimport \"common/types.proto\";\n",
            ),
        ]
        runner = _FakeBufRunner(descriptor_bytes=_two_target_descriptor())

        result = await compile_proto_descriptor_set(files, runner=runner)

        # One invocation, with the buf-build spec and the expected args shape.
        assert len(runner.calls) == 1
        call = runner.calls[0]
        assert call.spec.key == BUF_TOOL_KEY
        assert call.spec.base_args == ("build",)
        assert call.spec.parses_json is False
        assert "--as-file-descriptor-set" in call.args
        assert "--output" in call.args
        # Input dir is the scratch root; output lives inside it.
        assert call.output_path.startswith(call.args[0])

        # The scratch module carried both protos (at their import paths) + a buf.yaml.
        assert call.scratch["common/types.proto"] == files[0].content
        assert call.scratch["user/user_service.proto"] == files[1].content
        assert "buf.yaml" in call.scratch
        assert "version: v2" in call.scratch["buf.yaml"]

        # The descriptor was read back; both supplied files are targets, the WKT is an import.
        by_name = {f.name: f for f in result.files}
        assert by_name["common/types.proto"].is_import is False
        assert by_name["user/user_service.proto"].is_import is False
        assert by_name["google/protobuf/timestamp.proto"].is_import is True
        assert {f.name for f in result.target_files} == {
            "common/types.proto",
            "user/user_service.proto",
        }
        assert result.summary.service_count == 1

    async def test_scratch_dir_is_cleaned_up(self) -> None:
        runner = _FakeBufRunner(descriptor_bytes=_two_target_descriptor())
        await compile_proto_descriptor_set(
            [ProtoFile(path="a.proto", content="syntax=\"proto3\";")], runner=runner
        )
        # The TemporaryDirectory must be gone once the call returns.
        assert not Path(runner.calls[0].args[0]).exists()

    async def test_timeout_is_forwarded(self) -> None:
        runner = _FakeBufRunner(descriptor_bytes=_two_target_descriptor())
        await compile_proto_descriptor_set(
            [ProtoFile(path="a.proto", content="syntax=\"proto3\";")], runner=runner, timeout=12.5
        )
        assert runner.calls[0].timeout == 12.5

    async def test_empty_input_rejected(self) -> None:
        with pytest.raises(ProtoCompileError, match="At least one"):
            await compile_proto_descriptor_set([], runner=_FakeBufRunner())

    async def test_too_many_files_rejected(self) -> None:
        files = [ProtoFile(path=f"f{i}.proto", content="syntax=\"proto3\";") for i in range(2001)]
        with pytest.raises(ProtoCompileError, match="Too many"):
            await compile_proto_descriptor_set(files, runner=_FakeBufRunner())

    @pytest.mark.parametrize(
        "bad_path",
        ["/etc/passwd.proto", "../escape.proto", "a/../../b.proto", "noext", "", "sub/x.txt"],
    )
    async def test_unsafe_or_nonproto_paths_rejected(self, bad_path: str) -> None:
        runner = _FakeBufRunner(descriptor_bytes=_two_target_descriptor())
        with pytest.raises(ProtoCompileError):
            await compile_proto_descriptor_set(
                [ProtoFile(path=bad_path, content="syntax=\"proto3\";")], runner=runner
            )
        # Validation happens before the tool is ever invoked.
        assert runner.calls == []

    async def test_duplicate_paths_rejected(self) -> None:
        files = [
            ProtoFile(path="a.proto", content="syntax=\"proto3\";"),
            ProtoFile(path="a.proto", content="syntax=\"proto3\";"),
        ]
        with pytest.raises(ProtoCompileError, match="Duplicate"):
            await compile_proto_descriptor_set(files, runner=_FakeBufRunner())

    async def test_tool_unavailable_mapped(self) -> None:
        runner = _FakeBufRunner(error=ToolNotAvailableError(BUF_TOOL_KEY, "buf"))
        with pytest.raises(ProtoCompileError, match="not available"):
            await compile_proto_descriptor_set(
                [ProtoFile(path="a.proto", content="syntax=\"proto3\";")], runner=runner
            )

    async def test_timeout_mapped(self) -> None:
        runner = _FakeBufRunner(error=ToolTimeoutError(BUF_TOOL_KEY, 30.0))
        with pytest.raises(ProtoCompileError, match="timed out"):
            await compile_proto_descriptor_set(
                [ProtoFile(path="a.proto", content="syntax=\"proto3\";")], runner=runner
            )

    async def test_compile_failure_surfaces_diagnostics(self) -> None:
        stderr = "user/user_service.proto:5:8: import \"missing.proto\" was not found."
        runner = _FakeBufRunner(
            error=ToolExecutionError(BUF_TOOL_KEY, 1, stdout="", stderr=stderr)
        )
        with pytest.raises(ProtoCompileError) as excinfo:
            await compile_proto_descriptor_set(
                [ProtoFile(path="user/user_service.proto", content="syntax=\"proto3\";")],
                runner=runner,
            )
        assert excinfo.value.diagnostics == stderr

    async def test_generic_toolchain_error_mapped(self) -> None:
        runner = _FakeBufRunner(error=ToolSandboxError(BUF_TOOL_KEY, "no namespaces"))
        with pytest.raises(ProtoCompileError, match="buf build failed"):
            await compile_proto_descriptor_set(
                [ProtoFile(path="a.proto", content="syntax=\"proto3\";")], runner=runner
            )

    async def test_missing_output_file_mapped(self) -> None:
        # buf "succeeds" but writes nothing — surface a clean error, not a raw OSError.
        runner = _FakeBufRunner(descriptor_bytes=None, write_output=False)
        with pytest.raises(ProtoCompileError, match="wrote no descriptor set"):
            await compile_proto_descriptor_set(
                [ProtoFile(path="a.proto", content="syntax=\"proto3\";")], runner=runner
            )

    async def test_empty_output_file_mapped(self) -> None:
        runner = _FakeBufRunner(descriptor_bytes=b"")
        with pytest.raises(ProtoCompileError, match="empty descriptor set"):
            await compile_proto_descriptor_set(
                [ProtoFile(path="a.proto", content="syntax=\"proto3\";")], runner=runner
            )


# ===========================================================================
# End-to-end: the real bundled buf through the real runner (gated)
# ===========================================================================

_BUF_AVAILABLE = bool(getattr(probe_tool(BUF_TOOL_KEY), "available", False))


def _load_fixture_files(*relpaths: str) -> List[ProtoFile]:
    return [
        ProtoFile(path=rel, content=(_FIXTURES / rel).read_text(encoding="utf-8"))
        for rel in relpaths
    ]


@pytest.mark.skipif(
    not _BUF_AVAILABLE,
    reason="buf tool is not resolvable in this environment "
    "(bundled only in the image / via APIOME_BUF_BIN)",
)
class TestRealBuf:
    """Exercises the committed fixtures through the real ``buf build`` when present."""

    async def test_multi_file_proto3_compiles(self) -> None:
        files = _load_fixture_files("common/types.proto", "user/user_service.proto")
        result = await compile_proto_descriptor_set(files)

        by_name = {f.name: f for f in result.files}
        # Both targets + the well-known timestamp import resolved into the set.
        assert "common/types.proto" in by_name
        assert "user/user_service.proto" in by_name
        assert "google/protobuf/timestamp.proto" in by_name
        assert by_name["google/protobuf/timestamp.proto"].is_import is True
        assert by_name["user/user_service.proto"].service_count == 1
        # The returned bytes are a genuine FileDescriptorSet: re-reading them yields the
        # same files, so a downstream consumer (MFI-9.2) can rely on the artifact.
        reread = read_file_descriptor_set(result.descriptor_set_bytes)
        assert {f.name for f in reread.files} == by_name.keys()

    async def test_editions_2023_compiles(self) -> None:
        files = _load_fixture_files("common/types.proto", "editions/catalog.proto")
        result = await compile_proto_descriptor_set(files)
        catalog = {f.name: f for f in result.files}["editions/catalog.proto"]
        assert catalog.syntax == "editions"
        assert catalog.edition == "2023"
        assert "2023" in result.summary.editions

    async def test_unresolved_import_raises_with_diagnostics(self) -> None:
        files = _load_fixture_files("broken/unresolved_import.proto")
        with pytest.raises(ProtoCompileError) as excinfo:
            await compile_proto_descriptor_set(files)
        assert excinfo.value.diagnostics  # buf told us which import failed
