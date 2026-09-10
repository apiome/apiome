"""The publishable distributions — SDK-4.1 (#4495).

Pure-function tests for :mod:`app.sdk_distribution`: what an npm tarball and a PyPI sdist contain,
the determinism the dry-run digest rests on, the provenance embedded in each ecosystem's *own*
metadata (the acceptance criterion — not a manifest beside it), the SDK-3.4 branding they inherit,
and the naming rules each registry imposes.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
import tomllib
from typing import Any, Dict, List, Optional

import pytest

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
from app.sdk_distribution import (
    DISTRIBUTION_SCHEMA_VERSION,
    DistributionError,
    build_distribution,
    distribution_filename,
    npm_tarball_filename,
    pypi_module_name,
    pypi_normalized_name,
    pypi_sdist_filename,
    python_module_stem,
)
from app.sdk_generation_settings import ResolvedBranding
from app.sdk_kit import MAX_KIT_OPERATIONS, KitCoordinates

_COORDS = KitCoordinates(
    tenant_slug="acme",
    project_slug="widgets",
    version_slug="1.4.2",
    version_record_id="8f14e45f-e0d2-4d1f-9f1f-000000000001",
    version_label="1.4.2",
)

_BRANDING = ResolvedBranding(
    package_names={"npm": "@acme/widgets-sdk", "pypi": "acme-widgets"},
    license_header="Copyright (c) 2026 Acme, Inc.",
    user_agent="acme-sdk/1.4.2",
)

_SPEC = '{"openapi": "3.1.0", "info": {"title": "Widgets API"}}'


def _http_op(name: str, *, method: str = "get", path: str = "/widgets") -> Operation:
    """One HTTP operation, the kind a snippet is defined for."""
    return Operation(
        key=f"{method.upper()} {path}",
        name=name,
        kind=OperationKind.REQUEST_RESPONSE,
        http_method=method,
        http_path=path,
        extras={"operationId": name},
        parameters=[
            Parameter(
                key="p-id",
                name="id",
                location=ParameterLocation.PATH,
                type=TypeRef(name="string"),
                required=True,
            )
        ]
        if "{id}" in path
        else [],
    )


def _api(operations: Optional[List[Operation]] = None) -> CanonicalApi:
    """A REST model with one HTTP operation and one with no HTTP binding."""
    ops = operations if operations is not None else [
        _http_op("getWidget", path="/widgets/{id}"),
        Operation(key="Query.widgets", name="widgetsQuery", kind=OperationKind.QUERY),
    ]
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title="Widgets API",
        version="1.4.2",
        identity=ApiIdentity(name="widgets"),
        servers=[Server(url="https://api.widgets.dev")],
        services=[Service(key="widgets", name="widgets", operations=ops)],
    )


def _build(ecosystem: str, api: Optional[CanonicalApi] = None, **kwargs: Any):
    """Build a distribution with fixture defaults, overridable per test."""
    options: Dict[str, Any] = {
        "ecosystem": ecosystem,
        "coordinates": _COORDS,
        "branding": _BRANDING,
        "package_name": _BRANDING.package_names.get(ecosystem, "placeholder"),
        "package_version": "1.4.3",
        "release_series": "1.4",
        "regen_counter": 3,
        "source_text": _SPEC,
        "source_format": "openapi-3.1",
        "settings_fingerprint": "sha256:" + "a" * 64,
        "apiome_version": "1.183.0",
    }
    options.update(kwargs)
    return build_distribution(api or _api(), **options)


def _names(content: bytes) -> List[str]:
    """The archive's entry names."""
    return tarfile.open(fileobj=io.BytesIO(content)).getnames()


def _read(content: bytes, path: str) -> str:
    """Read one entry out of the archive."""
    archive = tarfile.open(fileobj=io.BytesIO(content))
    return archive.extractfile(path).read().decode("utf-8")


# --------------------------------------------------------------------------------------------
# Naming
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name, version, expected",
    [
        ("@acme/widgets-sdk", "1.4.3", "acme-widgets-sdk-1.4.3.tgz"),
        ("widgets", "2.0.0-beta.1", "widgets-2.0.0-beta.1.tgz"),
    ],
)
def test_npm_tarball_filename_matches_npm_pack(name, version, expected):
    assert npm_tarball_filename(name, version) == expected


@pytest.mark.parametrize(
    "name, version, expected",
    [
        ("acme-widgets", "1.4.3", "acme_widgets-1.4.3.tar.gz"),
        ("Acme.Widgets", "1.0.0", "acme_widgets-1.0.0.tar.gz"),
    ],
)
def test_pypi_sdist_filename_is_pep_625(name, version, expected):
    assert pypi_sdist_filename(name, version) == expected


def test_pypi_names_normalise_per_pep_503():
    assert pypi_normalized_name("Acme..Widgets_SDK") == "acme-widgets-sdk"


@pytest.mark.parametrize(
    "name, module",
    [
        ("acme-widgets", "acme_widgets"),
        ("2fa-api", "api_2fa_api"),
        ("import", "api_import"),
        ("", "api_client"),
    ],
)
def test_the_python_module_name_is_always_importable(name, module):
    assert pypi_module_name(name) == module


@pytest.mark.parametrize(
    "slug, stem",
    [("getWidget", "getwidget"), ("list-widgets", "list_widgets"), ("2fa", "op_2fa"), ("", "operation")],
)
def test_snippet_module_stems_are_importable(slug, stem):
    assert python_module_stem(slug) == stem


def test_an_unpublishable_ecosystem_has_no_filename():
    """`gomod` names a module path; a Go module is released by a tag, not by an upload."""
    with pytest.raises(DistributionError, match="gomod"):
        distribution_filename("gomod", "x", "1.0.0")


# --------------------------------------------------------------------------------------------
# npm
# --------------------------------------------------------------------------------------------
def test_the_npm_tarball_has_the_layout_npm_expects():
    dist = _build("npm")
    assert dist.filename == "acme-widgets-sdk-1.4.3.tgz"
    names = _names(dist.content)
    # Every entry is under `package/`, which is what npm unpacks from.
    assert all(name.startswith("package/") for name in names)
    assert "package/package.json" in names
    assert "package/index.js" in names
    assert "package/index.d.ts" in names
    assert "package/spec/spec.json" in names
    assert "package/snippets/getWidget.ts" in names


def test_the_npm_package_json_carries_provenance():
    """The acceptance criterion: provenance is *in the package metadata*, not beside it."""
    dist = _build("npm")
    manifest = json.loads(_read(dist.content, "package/package.json"))
    assert manifest["name"] == "@acme/widgets-sdk"
    assert manifest["version"] == "1.4.3"
    provenance = manifest["apiome"]
    assert provenance["schemaVersion"] == DISTRIBUTION_SCHEMA_VERSION
    assert provenance["versionRecordId"] == _COORDS.version_record_id
    assert provenance["versionLine"] == "1.4.2"
    assert provenance["releaseSeries"] == "1.4"
    assert provenance["regenCounter"] == 3
    assert provenance["settingsFingerprint"] == "sha256:" + "a" * 64
    assert provenance["apiomeVersion"] == "1.183.0"


def test_the_npm_package_ships_the_contract_verbatim():
    dist = _build("npm")
    assert _read(dist.content, "package/spec/spec.json") == _SPEC


def test_the_npm_entry_point_declares_what_it_exports():
    dist = _build("npm")
    index = _read(dist.content, "package/index.js")
    assert "module.exports = { provenance, operations, specPath, readSpec }" in index
    declarations = _read(dist.content, "package/index.d.ts")
    assert "export declare const provenance: ApiomeProvenance;" in declarations


# --------------------------------------------------------------------------------------------
# PyPI
# --------------------------------------------------------------------------------------------
def test_the_pypi_sdist_has_the_layout_pip_expects():
    dist = _build("pypi")
    assert dist.filename == "acme_widgets-1.4.3.tar.gz"
    names = _names(dist.content)
    root = "acme_widgets-1.4.3"
    assert all(name.startswith(f"{root}/") for name in names)
    assert f"{root}/PKG-INFO" in names
    assert f"{root}/pyproject.toml" in names
    assert f"{root}/acme_widgets/__init__.py" in names
    assert f"{root}/acme_widgets/snippets/getwidget.py" in names
    assert f"{root}/acme_widgets/spec/spec.json" in names


def test_the_pypi_metadata_carries_provenance_as_project_urls():
    dist = _build("pypi")
    pkg_info = _read(dist.content, "acme_widgets-1.4.3/PKG-INFO")
    assert "Metadata-Version: 2.1" in pkg_info
    assert "Name: acme-widgets" in pkg_info
    assert "Version: 1.4.3" in pkg_info
    assert f"Project-URL: Apiome versionRecordId, {_COORDS.version_record_id}" in pkg_info
    assert "Project-URL: Apiome releaseSeries, 1.4" in pkg_info


def test_the_pypi_module_exposes_provenance_and_the_spec():
    dist = _build("pypi")
    init = _read(dist.content, "acme_widgets-1.4.3/acme_widgets/__init__.py")
    assert '__version__ = "1.4.3"' in init
    assert "PROVENANCE = {" in init
    assert "def read_spec() -> str:" in init
    # The tenant's SDK-3.4 licence header is commented onto generated source.
    assert "# Copyright (c) 2026 Acme, Inc." in init


def test_the_generated_python_module_actually_imports():
    """The gate for a class of bug that *compiles* and then fails on first use.

    JSON spells the empty value ``null``, which Python parses as a name — so a module embedding a
    JSON-serialised provenance object passes ``compile()`` and raises ``NameError`` the moment
    anyone imports it. Executing it is the only assertion that catches that.
    """
    dist = _build("pypi", apiome_version=None, settings_fingerprint=None)
    source = _read(dist.content, "acme_widgets-1.4.3/acme_widgets/__init__.py")
    namespace: Dict[str, Any] = {"__file__": "/tmp/acme_widgets/__init__.py"}
    exec(compile(source, "__init__.py", "exec"), namespace)  # noqa: S102 - that is the assertion

    assert namespace["__version__"] == "1.4.3"
    assert namespace["PROVENANCE"]["versionRecordId"] == _COORDS.version_record_id
    # The two values that would have been `null`.
    assert namespace["PROVENANCE"]["apiomeVersion"] is None
    assert namespace["PROVENANCE"]["settingsFingerprint"] is None
    assert namespace["OPERATIONS"][0]["operationId"] == "getWidget"
    assert namespace["SPEC_PATH"].name == "spec.json"


def test_every_generated_python_file_is_syntactically_valid():
    """Snippets ship inside the package, so an unparseable one breaks `pip install`-then-import."""
    dist = _build("pypi")
    for item in dist.files:
        if item.path.endswith(".py"):
            compile(item.text, item.path, "exec")


def test_the_pyproject_is_valid_toml():
    """A malformed `pyproject.toml` fails `pip install` after the download, not before it."""
    dist = _build("pypi")
    parsed = tomllib.loads(_read(dist.content, "acme_widgets-1.4.3/pyproject.toml"))
    assert parsed["project"]["name"] == "acme-widgets"
    assert parsed["project"]["version"] == "1.4.3"
    assert parsed["build-system"]["build-backend"] == "setuptools.build_meta"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_the_generated_npm_package_runs_under_node(tmp_path):
    """The compile gate, in the spirit of SDK-2.4's `go build` and SDK-2.5's `tsc`.

    Unpacks the tarball and `require`s it exactly as a consumer would after `npm install`.
    """
    dist = _build("npm")
    with tarfile.open(fileobj=io.BytesIO(dist.content)) as archive:
        archive.extractall(tmp_path)
    package = tmp_path / "package"
    script = (
        f"const m = require({str(package / 'index.js')!r});"
        "if (!m.provenance.versionRecordId) throw new Error('no provenance');"
        "if (!m.readSpec().length) throw new Error('no spec');"
        "process.stdout.write(String(m.operations.length));"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "1"


def test_the_generated_npm_module_is_valid_javascript():
    """JSON *is* a subset of JS literals, but the surrounding module still has to parse."""
    dist = _build("npm", apiome_version=None, settings_fingerprint=None)
    index = _read(dist.content, "package/index.js")
    assert "null" in index, "the fixture must exercise an empty provenance value"
    manifest = json.loads(_read(dist.content, "package/package.json"))
    assert manifest["apiome"]["apiomeVersion"] is None
    # Balanced braces are a cheap parse proxy; the JSON blocks are the only nesting.
    assert index.count("{") == index.count("}")


def test_the_pyproject_keeps_the_contract_as_package_data():
    """A wheel built from this sdist that dropped its own spec would be worse than useless."""
    dist = _build("pypi")
    pyproject = _read(dist.content, "acme_widgets-1.4.3/pyproject.toml")
    assert '"acme_widgets" = ["spec/*"]' in pyproject
    assert 'packages = ["acme_widgets", "acme_widgets.snippets"]' in pyproject


# --------------------------------------------------------------------------------------------
# Shared promises
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ecosystem", ["npm", "pypi"])
def test_building_twice_produces_identical_bytes(ecosystem):
    """What the dry run's reported digest rests on."""
    first = _build(ecosystem)
    second = _build(ecosystem)
    assert first.content == second.content
    assert first.sha256 == second.sha256


@pytest.mark.parametrize("ecosystem", ["npm", "pypi"])
def test_an_operation_with_no_http_binding_is_recorded_not_fatal(ecosystem):
    dist = _build(ecosystem)
    assert dist.operation_count == 1
    assert [item["operation_id"] for item in dist.skipped] == ["widgetsQuery"]


@pytest.mark.parametrize("ecosystem", ["npm", "pypi"])
def test_the_readme_explains_the_install_and_the_provenance(ecosystem):
    dist = _build(ecosystem)
    readme = next(item.text for item in dist.files if item.subject == "readme")
    expected_install = (
        "npm install @acme/widgets-sdk" if ecosystem == "npm" else "pip install acme-widgets"
    )
    assert expected_install in readme
    assert "## Provenance" in readme
    assert _COORDS.version_record_id in readme
    assert "Copyright (c) 2026 Acme, Inc." in readme


@pytest.mark.parametrize("ecosystem", ["npm", "pypi"])
def test_a_revision_with_no_captured_contract_cannot_be_packaged(ecosystem):
    with pytest.raises(DistributionError, match="no captured contract"):
        _build(ecosystem, source_text=None)


def test_an_unpublishable_ecosystem_cannot_be_built():
    with pytest.raises(DistributionError, match="gomod"):
        _build("gomod", package_name="example.com/acme/widgets")


@pytest.mark.parametrize("ecosystem", ["npm", "pypi"])
def test_the_file_report_describes_the_archive_without_its_bytes(ecosystem):
    """What a dry run shows the caller."""
    dist = _build(ecosystem)
    subjects = {item.subject for item in dist.files}
    assert {"metadata", "readme", "contract"} <= subjects
    for item in dist.files:
        assert item.size_bytes > 0
        assert len(item.sha256) == 64


@pytest.mark.parametrize("ecosystem", ["npm", "pypi"])
def test_an_api_larger_than_the_snippet_budget_says_so(ecosystem):
    """A package that silently omitted operations is worse than one that admits it did."""
    ops = [
        _http_op(f"op{index}", path=f"/things/{index}")
        for index in range(MAX_KIT_OPERATIONS + 3)
    ]
    dist = _build(ecosystem, _api(ops))
    assert dist.truncated is True
    assert dist.operation_count == MAX_KIT_OPERATIONS
    assert dist.provenance["truncated"] is True
    readme = next(item.text for item in dist.files if item.subject == "readme")
    assert "larger than one package's snippet budget" in readme


@pytest.mark.parametrize("ecosystem", ["npm", "pypi"])
def test_a_normal_api_is_not_marked_truncated(ecosystem):
    dist = _build(ecosystem)
    assert dist.truncated is False
    assert dist.provenance["truncated"] is False


@pytest.mark.parametrize("ecosystem", ["npm", "pypi"])
def test_an_api_with_no_renderable_operations_still_packages(ecosystem):
    """A contract worth shipping is worth shipping even with nothing to snippet."""
    api = _api([Operation(key="Query.only", name="onlyQuery", kind=OperationKind.QUERY)])
    dist = _build(ecosystem, api)
    assert dist.operation_count == 0
    assert dist.content_length > 0
