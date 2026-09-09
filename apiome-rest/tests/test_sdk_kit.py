"""The public client-kit builder — SDK-3.3 (#4493), SDK-2.4 (#4488), SDK-2.5 (#4490).

Pure-function tests for :mod:`app.sdk_kit`: what an archive contains, the determinism guarantee
its ``ETag`` rests on, the provenance its manifest carries, the branding it inherits from SDK-3.4,
and the two things that must never take a kit down — an operation with no HTTP binding, and an API
with more operations than one kit carries.

The generated *projects* the kit carries — the Go client and the two server stubs — are tested in
their own modules. What is checked here is only the wiring: that they are staged under the right
directories, described in the manifest, pointed at from the README, and that a failure in either
generator degrades the kit to its snippets rather than taking the download down.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    TypeRef,
)
from app.go_client_generator import GO_CLIENT_SCHEMA_VERSION
from app.server_stub_generator import SERVER_STUB_SCHEMA_VERSION
from app.sdk_generation_settings import ResolvedBranding
from app.sdk_kit import (
    KIT_SCHEMA_VERSION,
    MAX_KIT_OPERATIONS,
    SERVER_STUB_DIRECTORY,
    KitCoordinates,
    build_client_kit,
    kit_filename,
    package_install_command,
    spec_filename,
    summarize_kit,
)

_COORDS = KitCoordinates(
    tenant_slug="acme",
    project_slug="widgets",
    version_slug="1.0.0",
    version_record_id="rev-uuid-1",
    version_label="1.0.0",
)

_UNBRANDED = ResolvedBranding(package_names={})

_BRANDED = ResolvedBranding(
    package_names={"npm": "@acme/widgets-sdk", "pypi": "acme-widgets"},
    license_header="Copyright (c) 2026 Acme, Inc.",
    user_agent="acme-sdk/1.0.0",
)


def _http_op(
    name: str,
    *,
    method: str = "get",
    path: str = "/widgets",
    operation_id: Optional[str] = None,
    parameters: Optional[List[Parameter]] = None,
) -> Operation:
    """One HTTP operation, the kind a kit renders."""
    return Operation(
        key=f"{method.upper()} {path}",
        name=name,
        kind=OperationKind.REQUEST_RESPONSE,
        http_method=method,
        http_path=path,
        extras={"operationId": operation_id} if operation_id else {},
        parameters=parameters or [],
    )


def _api(operations: Optional[List[Operation]] = None) -> CanonicalApi:
    """A REST model with one HTTP operation and one that has no HTTP binding."""
    ops = operations if operations is not None else [
        _http_op(
            "getWidget",
            path="/widgets/{id}",
            operation_id="getWidget",
            parameters=[
                Parameter(
                    key="p-id",
                    name="id",
                    location=ParameterLocation.PATH,
                    type=TypeRef(name="string"),
                    required=True,
                ),
                Parameter(
                    key="p-key",
                    name="X-API-Key",
                    location=ParameterLocation.HEADER,
                    type=TypeRef(name="string"),
                    required=True,
                ),
            ],
        ),
        Operation(key="Query.widgets", name="widgetsQuery", kind=OperationKind.QUERY),
    ]
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title="Widgets API",
        version="1.0.0",
        identity=ApiIdentity(name="widgets"),
        servers=[Server(url="https://api.widgets.dev")],
        services=[Service(key="widgets", name="widgets", operations=ops)],
    )


def _build(api: Optional[CanonicalApi] = None, **kwargs: Any):
    """Build a kit with the fixture defaults, overridable per test."""
    options: Dict[str, Any] = {
        "coordinates": _COORDS,
        "branding": _UNBRANDED,
        "source_text": '{"openapi": "3.1.0"}',
        "source_format": "openapi-3.1",
        "settings_fingerprint": "sha256:" + "a" * 64,
        "apiome_version": "1.180.0",
    }
    options.update(kwargs)
    return build_client_kit(api or _api(), **options)


def _entries(content: bytes) -> List[str]:
    """The archive's entry names."""
    return zipfile.ZipFile(io.BytesIO(content)).namelist()


def _read(content: bytes, name: str) -> str:
    """One entry's text."""
    return zipfile.ZipFile(io.BytesIO(content)).read(name).decode("utf-8")


def _manifest(content: bytes) -> Dict[str, Any]:
    """The archive's manifest."""
    return json.loads(_read(content, "manifest.json"))


# ===========================================================================
# Contents
# ===========================================================================


def test_the_kit_carries_a_readme_manifest_spec_and_one_snippet_per_language() -> None:
    entries = sorted(_entries(_build().content))
    assert entries == [
        "README.md",
        # SDK-2.4 (#4488): the generated Go module rides the same archive, under `go/`.
        "go/README.md",
        "go/client.go",
        "go/errors.go",
        "go/examples/widgets/main.go",
        "go/go.mod",
        "go/widgets.go",
        "manifest.json",
        # SDK-2.5 (#4490): two runnable server skeletons, under `server/`.
        "server/express/README.md",
        "server/express/package.json",
        "server/express/src/app.ts",
        "server/express/src/handlers.ts",
        "server/express/src/models.ts",
        "server/express/src/routes/widgets.ts",
        "server/express/src/runtime.ts",
        "server/express/src/schemas.ts",
        "server/express/src/server.ts",
        "server/express/src/validation.ts",
        "server/express/tsconfig.json",
        "server/fastapi/README.md",
        "server/fastapi/pyproject.toml",
        "server/fastapi/widgets_server/__init__.py",
        "server/fastapi/widgets_server/app.py",
        "server/fastapi/widgets_server/errors.py",
        "server/fastapi/widgets_server/handlers.py",
        "server/fastapi/widgets_server/main.py",
        "server/fastapi/widgets_server/models.py",
        "server/fastapi/widgets_server/routers/__init__.py",
        "server/fastapi/widgets_server/routers/widgets.py",
        "snippets/curl/getWidget.sh",
        "snippets/python/getWidget.py",
        "snippets/ts/getWidget.ts",
        "spec.json",
    ]


def test_the_snippet_files_hold_runnable_code_per_language() -> None:
    content = _build().content
    assert "curl 'https://api.widgets.dev/widgets/ID'" in _read(
        content, "snippets/curl/getWidget.sh"
    )
    assert "await fetch(" in _read(content, "snippets/ts/getWidget.ts")
    assert "import httpx" in _read(content, "snippets/python/getWidget.py")


def test_every_snippet_file_ends_with_a_newline() -> None:
    """These are source files; a consumer's tooling would add one and change the bytes."""
    content = _build().content
    for name in _entries(content):
        if name.startswith("snippets/"):
            assert _read(content, name).endswith("\n")


def test_the_captured_contract_is_shipped_verbatim() -> None:
    content = _build(source_text='{"openapi": "3.1.0"}').content
    assert _read(content, "spec.json") == '{"openapi": "3.1.0"}'


def test_a_revision_with_no_captured_source_still_builds_a_kit() -> None:
    """The snippets are the point; the contract is a bonus we ship when we have it."""
    content = _build(source_text=None).content
    entries = _entries(content)
    assert not any(name.startswith("spec.") for name in entries)
    assert "snippets/ts/getWidget.ts" in entries


def test_the_readme_lists_operations_placeholders_and_requirements() -> None:
    readme = _read(_build().content, "README.md")
    assert "# Widgets API — client kit" in readme
    assert "### GET /widgets/{id}" in readme
    assert "`pip install httpx`" in readme
    # Placeholders come from the renderer's structured records, so a credential is described as
    # one rather than guessed at from the text.
    assert "- `$API_KEY` — credential for `X-API-Key` header" in readme
    assert "- `ID` — path `id`" in readme


# ===========================================================================
# Determinism
# ===========================================================================


def test_two_builds_of_the_same_revision_are_byte_identical() -> None:
    """The route's ETag is a digest of these bytes; an unstable build would break caching."""
    assert _build().content == _build().content


def test_changing_branding_changes_the_bytes() -> None:
    """A kit that ignored its tenant's branding would be indistinguishable from one that applied it."""
    assert _build(branding=_UNBRANDED).content != _build(branding=_BRANDED).content


def test_entries_are_written_in_a_stable_order() -> None:
    assert _entries(_build().content) == _entries(_build().content)


# ===========================================================================
# Branding (SDK-3.4)
# ===========================================================================


def test_branding_reaches_the_snippets_and_the_readme() -> None:
    content = _build(branding=_BRANDED).content
    ts = _read(content, "snippets/ts/getWidget.ts")
    assert ts.startswith("// Copyright (c) 2026 Acme, Inc.")
    assert "acme-sdk/1.0.0" in ts
    readme = _read(content, "README.md")
    assert "npm install @acme/widgets-sdk" in readme
    assert "pip install acme-widgets" in readme
    assert _manifest(content)["package_names"] == {
        "npm": "@acme/widgets-sdk",
        "pypi": "acme-widgets",
    }


def test_an_unbranded_kit_names_no_packages() -> None:
    content = _build(branding=_UNBRANDED).content
    assert _manifest(content)["package_names"] == {}
    assert "## Packages" not in _read(content, "README.md")


# ===========================================================================
# Manifest and provenance
# ===========================================================================


def test_the_manifest_carries_the_revision_and_settings_provenance() -> None:
    manifest = _manifest(_build().content)
    assert manifest["schema_version"] == KIT_SCHEMA_VERSION
    assert manifest["provenance"] == {
        "version_record_id": "rev-uuid-1",
        "version_label": "1.0.0",
        "source_format": "openapi-3.1",
        "renderer": f"app.snippet_render/{KIT_SCHEMA_VERSION}",
        "go_generator": f"app.go_client_generator/{GO_CLIENT_SCHEMA_VERSION}",
        "server_stub_generator": f"app.server_stub_generator/{SERVER_STUB_SCHEMA_VERSION}",
        "apiome_version": "1.180.0",
        "settings_fingerprint": "sha256:" + "a" * 64,
    }


# ---------------------------------------------------------------------------------------------
# The generated Go client — SDK-2.4 (#4488)
# ---------------------------------------------------------------------------------------------


def test_the_kit_carries_a_compilable_go_module() -> None:
    content = _build().content
    entries = _entries(content)
    assert "go/go.mod" in entries
    assert "go/client.go" in entries
    assert "go/errors.go" in entries
    assert "go/README.md" in entries
    assert _read(content, "go/client.go").startswith("// Code generated by Apiome. DO NOT EDIT.")


def test_the_go_module_path_falls_back_to_the_revisions_own_coordinates() -> None:
    """`example.com` is reserved, so a default path can never point at a real repository."""
    assert "module example.com/acme/widgets-go" in _read(_build().content, "go/go.mod")


def test_a_configured_go_module_path_is_used_verbatim() -> None:
    branding = ResolvedBranding(package_names={"gomod": "github.com/acme/widgets-go"})
    content = _build(branding=branding).content
    assert "module github.com/acme/widgets-go" in _read(content, "go/go.mod")
    assert "go get github.com/acme/widgets-go" in _read(content, "go/README.md")


def test_the_go_client_inherits_the_tenants_branding() -> None:
    content = _build(branding=_BRANDED).content
    assert _read(content, "go/client.go").startswith("// Copyright (c) 2026 Acme, Inc.")
    assert 'const DefaultUserAgent = "acme-sdk/1.0.0"' in _read(content, "go/client.go")


def test_the_manifest_describes_the_go_client() -> None:
    manifest = _manifest(_build().content)["go_client"]
    assert manifest["included"] is True
    assert manifest["directory"] == "go"
    assert manifest["module_path"] == "example.com/acme/widgets-go"
    assert manifest["package_name"] == "widgets"
    assert manifest["method_count"] == 1
    assert [method["name"] for method in manifest["methods"]] == ["GetWidget"]
    # The non-HTTP operation is reported there too, for the same reason the snippets report it.
    assert [item["key"] for item in manifest["skipped"]] == ["Query.widgets"]


def test_the_kit_readme_points_at_the_go_client() -> None:
    readme = _read(_build().content, "README.md")
    assert "## Go client" in readme
    assert "cd go && go build ./..." in readme


def test_a_go_generator_failure_degrades_the_kit_rather_than_failing_it() -> None:
    """A kit's snippets are worth shipping even when codegen cannot produce a module."""
    with patch("app.sdk_kit.generate_go_client", side_effect=RuntimeError("boom")):
        kit = _build()
    assert not [name for name in _entries(kit.content) if name.startswith("go/")]
    block = _manifest(kit.content)["go_client"]
    assert block["included"] is False
    assert block["error"] == "RuntimeError: boom"
    # The snippets are untouched.
    assert "snippets/ts/getWidget.ts" in _entries(kit.content)
    assert "No Go client is included" in _read(kit.content, "README.md")


# ===========================================================================
# The server stubs (SDK-2.5)
# ===========================================================================


def test_the_archive_carries_both_server_stub_projects() -> None:
    entries = _entries(_build().content)
    assert f"{SERVER_STUB_DIRECTORY}/fastapi/pyproject.toml" in entries
    assert f"{SERVER_STUB_DIRECTORY}/fastapi/widgets_server/app.py" in entries
    assert f"{SERVER_STUB_DIRECTORY}/express/package.json" in entries
    assert f"{SERVER_STUB_DIRECTORY}/express/src/app.ts" in entries


def test_the_server_stub_packages_never_reuse_the_tenants_client_package_names() -> None:
    """Publishing a server skeleton under the client library's name is two packages, one address."""
    manifest = _manifest(_build(branding=_BRANDED).content)["server_stubs"]
    assert manifest["npm_package"] == "@acme/widgets-sdk-server"
    assert manifest["python_package"] == "widgets_server"


def test_the_server_stubs_inherit_the_tenants_licence_header() -> None:
    content = _build(branding=_BRANDED).content
    assert _read(content, f"{SERVER_STUB_DIRECTORY}/express/src/app.ts").startswith(
        "// Copyright (c) 2026 Acme, Inc."
    )
    assert _read(content, f"{SERVER_STUB_DIRECTORY}/fastapi/widgets_server/app.py").startswith(
        "# Copyright (c) 2026 Acme, Inc."
    )


def test_the_manifest_describes_both_server_stub_targets() -> None:
    manifest = _manifest(_build().content)["server_stubs"]
    assert manifest["included"] is True
    assert manifest["schema_version"] == SERVER_STUB_SCHEMA_VERSION
    assert manifest["directory"] == SERVER_STUB_DIRECTORY
    assert manifest["route_count"] == 1
    assert [target["target"] for target in manifest["targets"]] == ["fastapi", "express"]
    assert [target["directory"] for target in manifest["targets"]] == [
        f"{SERVER_STUB_DIRECTORY}/fastapi",
        f"{SERVER_STUB_DIRECTORY}/express",
    ]
    # The non-HTTP operation is reported there too, for the same reason the snippets report it.
    assert [item["key"] for item in manifest["skipped"]] == ["Query.widgets"]


def test_the_kit_readme_points_at_the_server_stubs() -> None:
    readme = _read(_build().content, "README.md")
    assert "## Server stubs" in readme
    assert f"cd {SERVER_STUB_DIRECTORY}/fastapi" in readme
    assert f"cd {SERVER_STUB_DIRECTORY}/express" in readme


def test_a_server_stub_failure_degrades_the_kit_rather_than_failing_it() -> None:
    """A kit's snippets are worth shipping even when codegen cannot produce a project."""
    with patch("app.sdk_kit.generate_server_stubs", side_effect=RuntimeError("boom")):
        kit = _build()
    assert not [name for name in _entries(kit.content) if name.startswith(f"{SERVER_STUB_DIRECTORY}/")]
    block = _manifest(kit.content)["server_stubs"]
    assert block["included"] is False
    assert block["error"] == "RuntimeError: boom"
    # The snippets and the Go client are untouched.
    assert "snippets/ts/getWidget.ts" in _entries(kit.content)
    assert "go/client.go" in _entries(kit.content)
    assert "No server stubs are included" in _read(kit.content, "README.md")


def test_the_manifest_digests_every_entry_but_never_itself() -> None:
    """A table of contents that contained its own digest could never be verified."""
    manifest = _manifest(_build().content)
    paths = [entry["path"] for entry in manifest["files"]]
    assert "manifest.json" not in paths
    assert sorted(paths) == paths
    for entry in manifest["files"]:
        assert len(entry["sha256"]) == 64
        assert entry["size_bytes"] > 0


def test_the_manifest_echoes_the_requested_coordinates() -> None:
    manifest = _manifest(_build().content)
    assert manifest["tenant_slug"] == "acme"
    assert manifest["project_slug"] == "widgets"
    assert manifest["version_slug"] == "1.0.0"
    assert manifest["languages"] == ["ts", "python", "curl"]


# ===========================================================================
# Operations that cannot be rendered
# ===========================================================================


def test_a_non_http_operation_is_recorded_and_skipped_not_fatal() -> None:
    """A kit covering an API's REST operations is worth shipping despite its subscriptions."""
    manifest = _manifest(_build().content)
    assert manifest["operation_count"] == 1
    assert manifest["total_operation_count"] == 2
    assert manifest["skipped"] == [
        {
            "operation_id": "widgetsQuery",
            "key": "Query.widgets",
            "reason": (
                "Operation 'widgetsQuery' has no HTTP binding; snippets are only available "
                "for HTTP operations"
            ),
        }
    ]


def test_skipped_operations_are_named_in_the_readme() -> None:
    readme = _read(_build().content, "README.md")
    assert "## Not included" in readme
    assert "`Query.widgets`" in readme


def test_an_api_with_no_renderable_operation_still_builds() -> None:
    api = _api([Operation(key="Query.widgets", name="widgetsQuery", kind=OperationKind.QUERY)])
    manifest = _manifest(_build(api).content)
    assert manifest["operation_count"] == 0
    assert len(manifest["skipped"]) == 1


# ===========================================================================
# Naming
# ===========================================================================


def test_operation_filenames_keep_their_casing() -> None:
    """`getWidget.ts` is what a consumer expects to find in the archive."""
    assert "snippets/ts/getWidget.ts" in _entries(_build().content)


def test_colliding_operation_names_are_disambiguated_in_declaration_order() -> None:
    """Uniqueness is case-insensitive, so a kit does not lose a file when unzipped on a Mac.

    ``get-widget`` is a genuinely different stem and keeps its own name; ``GetWidget`` differs
    from ``getWidget`` only in case, so it takes the suffix.
    """
    api = _api(
        [
            _http_op("getWidget", path="/a", operation_id="getWidget"),
            _http_op("get-widget", path="/b", operation_id="get-widget"),
            _http_op("GetWidget", path="/c", operation_id="GetWidget"),
        ]
    )
    entries = [name for name in _entries(_build(api).content) if name.startswith("snippets/ts/")]
    assert sorted(entries) == [
        "snippets/ts/GetWidget-2.ts",
        "snippets/ts/get-widget.ts",
        "snippets/ts/getWidget.ts",
    ]


def test_an_operation_with_no_usable_name_still_gets_a_file() -> None:
    api = _api([Operation(
        key="GET /widgets",
        name="",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="get",
        http_path="/widgets",
    )])
    entries = [name for name in _entries(_build(api).content) if name.startswith("snippets/ts/")]
    assert entries == ["snippets/ts/GET-widgets.ts"]


def test_the_download_filename_keeps_the_version_label_readable() -> None:
    assert kit_filename(_COORDS) == "widgets-1.0.0-sdk.zip"


def test_the_download_filename_survives_unusable_slugs() -> None:
    coords = KitCoordinates(
        tenant_slug="", project_slug="", version_slug="", version_record_id="r"
    )
    assert kit_filename(coords) == "api-latest-sdk.zip"


def test_the_spec_filename_follows_the_format_then_the_content() -> None:
    assert spec_filename("openapi-3.1", '{"openapi": "3.1.0"}') == "spec.json"
    assert spec_filename("openapi-3.1", "openapi: 3.1.0") == "spec.yaml"
    assert spec_filename("graphql", "type Query { a: Int }") == "spec.graphql"
    assert spec_filename("grpc", "syntax = 'proto3';") == "spec.proto"
    assert spec_filename(None, None) == "spec.yaml"


def test_package_install_commands_cover_the_known_ecosystems() -> None:
    assert package_install_command("npm", "@acme/sdk") == "npm install @acme/sdk"
    assert package_install_command("pypi", "acme") == "pip install acme"
    assert package_install_command("cargo", "acme") is None
    assert package_install_command("npm", "") is None


# ===========================================================================
# Bounded work
# ===========================================================================


def test_a_very_large_api_is_capped_and_says_so() -> None:
    """The kit is built per request on an anonymous route; the work has to have a ceiling."""
    ops = [
        _http_op(f"op{index}", path=f"/w{index}", operation_id=f"op{index}")
        for index in range(MAX_KIT_OPERATIONS + 5)
    ]
    manifest = _manifest(_build(_api(ops)).content)
    assert manifest["operation_count"] == MAX_KIT_OPERATIONS
    assert manifest["total_operation_count"] == MAX_KIT_OPERATIONS + 5
    assert manifest["truncated"] is True


def test_non_http_operations_do_not_consume_kit_capacity() -> None:
    """Otherwise a model's subscriptions would silently push its REST operations out of the kit."""
    ops: List[Operation] = [
        Operation(key=f"Query.q{i}", name=f"q{i}", kind=OperationKind.QUERY) for i in range(10)
    ]
    ops += [
        _http_op(f"op{index}", path=f"/w{index}", operation_id=f"op{index}")
        for index in range(MAX_KIT_OPERATIONS)
    ]
    manifest = _manifest(_build(_api(ops)).content)
    assert manifest["operation_count"] == MAX_KIT_OPERATIONS
    assert manifest["truncated"] is False


# ===========================================================================
# summarize_kit
# ===========================================================================


def test_the_summary_matches_what_a_build_actually_produces() -> None:
    """The info route counts with this instead of building; the two must never disagree."""
    for api in (
        _api(),
        _api([Operation(key="Query.q", name="q", kind=OperationKind.QUERY)]),
        _api([
            _http_op(f"op{i}", path=f"/w{i}", operation_id=f"op{i}")
            for i in range(MAX_KIT_OPERATIONS + 3)
        ]),
    ):
        summary = summarize_kit(api)
        manifest = _manifest(_build(api).content)
        assert summary.operation_count == manifest["operation_count"]
        assert summary.total_operation_count == manifest["total_operation_count"]
        assert summary.truncated == manifest["truncated"]
