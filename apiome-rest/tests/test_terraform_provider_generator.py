"""Tests for the Terraform provider generator — SDK-4.4 (#4498).

Most tests read the generated files as text. Two are gates that need real toolchains and are
skipped without them:

* with ``go`` on ``PATH``, the generated provider for the corpus fixture is built, vetted and
  gofmt-checked with ``-mod=readonly`` — which also proves the pinned ``go.mod``/``go.sum`` are
  complete;
* with ``terraform`` on ``PATH`` as well, the provider is driven through ``terraform validate``
  and a full ``apply`` → in-place update → ``import`` → ``destroy`` cycle against a stateful fake of
  the fixture's widget collection.

The same cycle has been run by hand against the SIM mock (``apiome-mock run`` serving the fixture
with ``X-Mock-Session``); the fake keeps the gate free of a bundle build and a second runtime.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest
import yaml
from corpus_loader import load_corpus

from app.openapi_normalizer import OpenApiNormalizer
from app.terraform_provider_generator import (
    TERRAFORM_PROVIDER_SCHEMA_VERSION,
    TerraformProviderPackage,
    generate_terraform_provider,
    terraform_module_path,
    terraform_namespace,
    terraform_registry_address,
)
from app.terraform_provider_runtime import GO_SUM, PLUGIN_FRAMEWORK_VERSION, PLUGIN_GO_VERSION


def _fixture_document() -> Dict[str, Any]:
    """The corpus fixture that follows the CRUD conventions."""
    [entry] = load_corpus(format="openapi", feature="terraform-crud")
    return yaml.safe_load(entry.read_text())


def _generate(document: Optional[Dict[str, Any]] = None, **options: Any) -> TerraformProviderPackage:
    """Generate the provider for ``document`` (default: the fixture) under the ``acme`` namespace."""
    api = OpenApiNormalizer().normalize(document if document is not None else _fixture_document())
    options.setdefault("namespace", "acme")
    return generate_terraform_provider(api, **options)


def _files(package: TerraformProviderPackage) -> Dict[str, str]:
    """``path → text``."""
    return package.file_map()


def _write(package: TerraformProviderPackage, root: Path) -> Path:
    """Write the provider to ``root`` and return it."""
    for path, text in package.file_map().items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


# ===========================================================================
# Shape
# ===========================================================================


def test_the_provider_has_the_registry_layout() -> None:
    files = _files(_generate())
    for path in (
        "go.mod",
        "go.sum",
        "main.go",
        "README.md",
        "terraform-registry-manifest.json",
        "internal/client/client.go",
        "internal/provider/provider.go",
        "internal/provider/runtime.go",
        "internal/provider/resource_widget.go",
        "internal/provider/resource_project.go",
        "internal/provider/resource_gadget.go",
        "internal/provider/data_source_widget.go",
        "internal/provider/data_source_region.go",
        "internal/provider/data_source_widget_list.go",
        "docs/index.md",
        "docs/resources/widget.md",
        "docs/data-sources/region_list.md",
        "examples/provider/provider.tf",
        "examples/resources/widgetplatformapi_widget/resource.tf",
        "examples/resources/widgetplatformapi_widget/import.sh",
        "examples/data-sources/widgetplatformapi_region/data-source.tf",
    ):
        assert path in files, path
    # Import is disabled for gadgets by hint, so there is no import example for them.
    assert "examples/resources/widgetplatformapi_gadget/import.sh" not in files


def test_the_files_are_sorted_and_end_with_a_newline() -> None:
    package = _generate()
    paths = [item.path for item in package.files]
    assert paths == sorted(paths)
    assert all(item.text.endswith("\n") for item in package.files)


def test_generation_is_byte_deterministic() -> None:
    assert _files(_generate()) == _files(_generate())


def test_the_package_reports_its_types_and_coordinates() -> None:
    package = _generate()
    assert package.provider_name == "widgetplatformapi"
    assert package.address == "registry.terraform.io/acme/widgetplatformapi"
    assert package.module_path == "example.com/acme/terraform-provider-widgetplatformapi"
    assert package.resource_types == [
        "widgetplatformapi_gadget",
        "widgetplatformapi_project",
        "widgetplatformapi_widget",
    ]
    assert "widgetplatformapi_widget_list" in package.data_source_types
    assert package.framework_version == PLUGIN_FRAMEWORK_VERSION


def test_go_mod_pins_the_framework_and_go_sum_is_the_pinned_set() -> None:
    files = _files(_generate())
    go_mod = files["go.mod"]
    assert go_mod.startswith("module example.com/acme/terraform-provider-widgetplatformapi\n\ngo 1.24.0\n")
    assert f"github.com/hashicorp/terraform-plugin-framework {PLUGIN_FRAMEWORK_VERSION}" in go_mod
    assert f"github.com/hashicorp/terraform-plugin-go {PLUGIN_GO_VERSION}" in go_mod
    assert files["go.sum"] == GO_SUM
    assert f"github.com/hashicorp/terraform-plugin-framework {PLUGIN_FRAMEWORK_VERSION} h1:" in GO_SUM


def test_every_go_file_is_marked_generated_and_carries_the_licence() -> None:
    files = _files(_generate(license_header="Copyright (c) 2026 Acme */ Inc."))
    for path, text in files.items():
        if path.endswith(".go"):
            assert text.startswith(
                "// Copyright (c) 2026 Acme */ Inc.\n\n// Code generated by Apiome. DO NOT EDIT.\n"
            ), path


def test_the_runtime_imports_the_generated_module() -> None:
    runtime = _files(_generate(module_path="github.com/acme/terraform-provider-widgets"))[
        "internal/provider/runtime.go"
    ]
    assert '"github.com/acme/terraform-provider-widgets/internal/client"' in runtime
    assert "__MODULE__" not in runtime


def test_main_serves_the_registry_address() -> None:
    main = _files(_generate())["main.go"]
    assert 'Address: "registry.terraform.io/acme/widgetplatformapi"' in main
    assert '"example.com/acme/terraform-provider-widgetplatformapi/internal/provider"' in main


def test_the_registry_manifest_declares_protocol_six() -> None:
    manifest = json.loads(_files(_generate())["terraform-registry-manifest.json"])
    assert manifest == {"version": 1, "metadata": {"protocol_versions": ["6.0"]}}


# ===========================================================================
# Provider configuration
# ===========================================================================


def test_the_provider_configures_the_endpoint_headers_and_each_scheme() -> None:
    provider = _files(_generate())["internal/provider/provider.go"]
    assert 'const defaultEndpoint = "https://api.example.com/v1"' in provider
    assert '"WIDGETPLATFORMAPI_ENDPOINT"' in provider
    assert 'attributes["headers"] = schema.MapAttribute{' in provider
    assert 'c.Headers["Authorization"] = "Bearer " + token' in provider
    assert 'c.Headers["X-Platform-Key"] = apiKey' in provider
    assert '"WIDGETPLATFORMAPI_TOKEN"' in provider and '"WIDGETPLATFORMAPI_API_KEY"' in provider
    assert 'resp.TypeName = "widgetplatformapi"' in provider


def test_basic_auth_and_query_keys_are_wired() -> None:
    document = _fixture_document()
    document["components"]["securitySchemes"] = {
        "basicAuth": {"type": "http", "scheme": "basic"},
        "queryKey": {"type": "apiKey", "in": "query", "name": "key"},
    }
    provider = _files(_generate(document))["internal/provider/provider.go"]
    assert '"encoding/base64"' in provider
    assert 'base64.StdEncoding.EncodeToString([]byte(username+":"+password))' in provider
    assert 'c.Query["key"] = apiKey' in provider


def test_the_user_agent_comes_from_branding() -> None:
    provider = _files(_generate(user_agent="acme-sdk/1.0.0"))["internal/provider/provider.go"]
    assert 'const userAgent = "acme-sdk/1.0.0"' in provider
    default = _files(_generate())["internal/provider/provider.go"]
    assert 'const userAgent = "terraform-provider-widgetplatformapi"' in default


def test_every_resource_and_data_source_is_registered() -> None:
    provider = _files(_generate())["internal/provider/provider.go"]
    for constructor in (
        "newWidgetResource",
        "newProjectResource",
        "newGadgetResource",
        "newRegionDataSource",
        "newWidgetListDataSource",
    ):
        assert f"\t\t{constructor}," in provider


# ===========================================================================
# Resources
# ===========================================================================


def test_the_resource_spec_names_the_paths_and_methods() -> None:
    widget = _files(_generate())["internal/provider/resource_widget.go"]
    assert 'spec.collectionPath = "/widgets"' in widget
    assert 'spec.itemPath = "/widgets/{widgetId}"' in widget
    assert 'spec.idParam = "widgetId"' in widget
    assert 'spec.updateMethod = "PUT"' in widget
    assert 'spec.importParts = []string{"id"}' in widget
    assert '{field: field{attr: "name", wire: "name", kind: kindString}, create: true, update: true},' in widget


def test_the_resource_schema_carries_modes_and_plan_modifiers() -> None:
    widget = _files(_generate())["internal/provider/resource_widget.go"]
    assert (
        'attributes["name"] = rschema.StringAttribute{Required: true, Description: "A human-readable name."}' in widget
    )
    assert re.search(
        r'attributes\["region"\] = rschema\.StringAttribute\{Required: true, .*stringplanmodifier\.RequiresReplace\(\)',
        widget,
    )
    assert re.search(
        r'attributes\["id"\] = rschema\.Int64Attribute\{Computed: true, .*int64planmodifier\.UseStateForUnknown\(\)',
        widget,
    )
    assert "settingsAttributes := map[string]rschema.Attribute{}" in widget
    assert (
        'attributes["tags"] = rschema.ListAttribute{ElementType: types.StringType, Optional: true, Computed: true'
        in widget
    )
    assert "One of `us-east`, `eu-west`." in widget
    assert 'attributes["quotas"] = rschema.MapAttribute{ElementType: types.Int64Type, Optional: true, Computed: true' in widget


def test_a_nested_resource_fills_its_parent_placeholder() -> None:
    project = _files(_generate())["internal/provider/resource_project.go"]
    assert '{field: field{attr: "org_id", wire: "orgId", kind: kindString}, pathParam: "orgId"},' in project
    assert 'spec.importParts = []string{"org_id", "id"}' in project
    assert 'spec.updateMethod = "PATCH"' in project


def test_a_resource_without_import_has_no_import_parts() -> None:
    gadget = _files(_generate())["internal/provider/resource_gadget.go"]
    assert "importParts" not in gadget
    assert "spec.updateMethod" not in gadget


def test_a_json_attribute_is_a_string_in_the_schema() -> None:
    gadget = _files(_generate())["internal/provider/resource_gadget.go"]
    assert "kind: kindJSON" in gadget
    assert "A JSON-encoded value; use `jsonencode()`." in gadget


def test_list_data_sources_name_their_envelope_member() -> None:
    widgets = _files(_generate())["internal/provider/data_source_widget_list.go"]
    assert 'spec.listMember = "items"' in widgets
    assert 'attributes["items"] = dschema.ListNestedAttribute{NestedObject: dschema.NestedAttributeObject{' in widgets


def test_descriptions_are_escaped_as_go_strings() -> None:
    document = _fixture_document()
    document["components"]["schemas"]["Widget"]["properties"]["name"]["description"] = 'A "quoted" \\ back\nslash 🚀'
    widget = _files(_generate(document))["internal/provider/resource_widget.go"]
    assert 'Description: "A \\"quoted\\" \\\\ back slash 🚀."' in widget


# ===========================================================================
# Documentation and examples
# ===========================================================================


def test_the_resource_doc_follows_the_registry_layout() -> None:
    doc = _files(_generate())["docs/resources/widget.md"]
    assert doc.startswith(
        '---\npage_title: "widgetplatformapi_widget Resource - terraform-provider-widgetplatformapi"\n'
    )
    for heading in (
        "# widgetplatformapi_widget (Resource)",
        "## Example Usage",
        "### Required",
        "### Optional",
        "### Read-Only",
        "## Import",
    ):
        assert heading in doc
    assert (
        "- `region` (String) Where the widget runs. One of `us-east`, `eu-west`. Changing it replaces the resource."
        in doc
    )
    assert "### Nested Schema for `settings`" in doc
    assert 'terraform import widgetplatformapi_widget.example "<id>"' in doc
    assert "| create | `POST /widgets` |" in doc


def test_a_non_importable_resource_doc_has_no_import_section() -> None:
    assert "## Import" not in _files(_generate())["docs/resources/gadget.md"]


def test_examples_set_every_required_attribute() -> None:
    files = _files(_generate())
    widget = files["examples/resources/widgetplatformapi_widget/resource.tf"]
    assert widget.startswith('resource "widgetplatformapi_widget" "example" {\n')
    assert '  name    = "example"' in widget
    assert '  region  = "us-east"' in widget  # the first enum value
    project = files["examples/resources/widgetplatformapi_project/resource.tf"]
    assert "org_id" in project
    assert (
        files["examples/resources/widgetplatformapi_project/import.sh"]
        == 'terraform import widgetplatformapi_project.example "<org_id>/<id>"\n'
    )
    region = files["examples/data-sources/widgetplatformapi_region/data-source.tf"]
    assert region == 'data "widgetplatformapi_region" "example" {\n  id = "example"\n}\n'


def test_the_provider_example_declares_the_source_address() -> None:
    example = _files(_generate())["examples/provider/provider.tf"]
    assert 'source = "registry.terraform.io/acme/widgetplatformapi"' in example
    assert "WIDGETPLATFORMAPI_TOKEN" in example


def test_the_readme_reports_readiness_and_the_hints() -> None:
    readme = _files(_generate(revision="rev-1"))["README.md"]
    assert "## Readiness" in readme
    assert "`terraform.not-crud-shaped` — POST /widgets/{widgetId}/restart" in readme
    assert "`terraform.incomplete-resource`" in readme
    assert "## Steering the mapping with `x-terraform`" in readme
    assert "| `widgetplatformapi_widget` | `Widget` |" in readme
    assert f"`{TERRAFORM_PROVIDER_SCHEMA_VERSION}`" in readme and "revision `rev-1`" in readme
    assert "X-Mock-Session" in readme


def test_a_contract_with_nothing_to_manage_still_yields_a_reporting_provider() -> None:
    document = {
        "openapi": "3.0.3",
        "info": {"title": "Ping", "version": "1"},
        "paths": {"/ping": {"post": {"operationId": "ping", "responses": {"204": {"description": "ok"}}}}},
    }
    package = _generate(document)
    assert package.resource_types == [] and package.data_source_types == []
    readme = _files(package)["README.md"]
    assert "has no resources" in readme
    assert "terraform.not-crud-shaped" in readme


# ===========================================================================
# Coordinates
# ===========================================================================


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, "example.com/acme/terraform-provider-widgets"),
        ("github.com/acme/widgets-go", "github.com/acme/terraform-provider-widgets"),
        ("github.com/acme/widgets-go/", "github.com/acme/terraform-provider-widgets"),
        ("widgets", "widgets/terraform-provider-widgets"),
    ],
)
def test_the_module_path_is_a_sibling_of_the_go_client(configured: Optional[str], expected: str) -> None:
    assert terraform_module_path(configured, "acme", "widgets") == expected


def test_namespaces_and_addresses_are_sanitized() -> None:
    assert terraform_namespace("Acme Corp!") == "acme-corp"
    assert terraform_namespace(None, "") == "apiome"
    assert terraform_registry_address("acme", "widgets") == "registry.terraform.io/acme/widgets"


# ===========================================================================
# Gates (need real toolchains)
# ===========================================================================


def _toolchain(name: str) -> Optional[str]:
    """Return a binary on ``PATH``, or ``None``."""
    return shutil.which(name)


def _run(command: List[str], cwd: Path, environment: Dict[str, str]) -> subprocess.CompletedProcess:
    """Run a command, failing the test with its output when it fails."""
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=environment, timeout=900)
    assert result.returncode == 0, f"{' '.join(command)} failed:\n{result.stdout}{result.stderr}"
    return result


def _go_environment() -> Dict[str, str]:
    """The environment the Go gate builds in: ``-mod=readonly`` proves go.mod/go.sum are complete."""
    return {**os.environ, "GOFLAGS": "-mod=readonly -p=2", "GOTOOLCHAIN": "local"}


@pytest.mark.skipif(_toolchain("go") is None, reason="no Go toolchain on PATH")
def test_the_generated_provider_builds_vets_and_is_gofmt_clean(tmp_path: Path) -> None:
    """The compile gate: the fixture's provider is Go that builds against the pinned framework."""
    root = _write(_generate(license_header="Copyright (c) 2026 Acme */ Inc."), tmp_path / "provider")
    environment = _go_environment()
    go = _toolchain("go")
    assert go is not None
    _run([go, "build", "./..."], root, environment)
    _run([go, "vet", "./..."], root, environment)
    gofmt = os.path.join(os.path.dirname(go), "gofmt")
    if os.path.exists(gofmt):
        unformatted = _run([gofmt, "-l", "."], root, environment).stdout.strip()
        assert unformatted == "", f"not gofmt-clean:\n{unformatted}"


class _WidgetStore(BaseHTTPRequestHandler):
    """A stateful fake of the fixture's widget collection, requiring the bearer token."""

    widgets: Dict[int, Dict[str, Any]] = {}
    calls: List[str] = []

    def _answer(self, status: int, body: Any = None) -> None:
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self) -> None:
        self.calls.append(f"{self.command} {self.path}")
        if self.headers.get("Authorization") != "Bearer t0ken":
            return self._answer(401, {"error": "unauthorized"})
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        match = re.fullmatch(r"/widgets/(\d+)", self.path)
        if self.path == "/widgets" and self.command == "POST":
            identifier = len(self.calls)
            stored = {**body, "id": identifier, "created_at": "2026-01-01T00:00:00Z", "etag": "e1"}
            stored.setdefault("size", 1)
            self.widgets[identifier] = stored
            return self._answer(201, stored)
        if self.path == "/widgets" and self.command == "GET":
            return self._answer(200, {"items": list(self.widgets.values())})
        if match and int(match.group(1)) in self.widgets:
            identifier = int(match.group(1))
            if self.command == "GET":
                return self._answer(200, self.widgets[identifier])
            if self.command == "PUT":
                previous = self.widgets[identifier]
                self.widgets[identifier] = {
                    **body,
                    "id": identifier,
                    "created_at": previous["created_at"],
                    "etag": "e2",
                }
                self.widgets[identifier].setdefault("size", 1)
                return self._answer(200, self.widgets[identifier])
            if self.command == "DELETE":
                del self.widgets[identifier]
                return self._answer(204)
        return self._answer(404, {"error": "not found"})

    do_GET = do_POST = do_PUT = do_DELETE = _handle  # noqa: N815 - http.server's dispatch names

    def log_message(self, *_args: Any) -> None:  # noqa: D401 - silence the default stderr log
        """Keep the test output clean."""


@pytest.fixture()
def widget_store() -> Iterator[str]:
    """Serve the fake on a free port and yield its base URL."""
    _WidgetStore.widgets = {}
    _WidgetStore.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WidgetStore)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


@pytest.mark.skipif(
    _toolchain("go") is None or _toolchain("terraform") is None, reason="needs Go and Terraform on PATH"
)
def test_terraform_creates_updates_imports_and_destroys_a_widget(tmp_path: Path, widget_store: str) -> None:
    """The acceptance gate: plan/apply against a stateful API creates, reads, updates and deletes."""
    package = _generate()
    root = _write(package, tmp_path / "provider")
    environment = _go_environment()
    go, terraform = _toolchain("go"), _toolchain("terraform")
    assert go is not None and terraform is not None
    _run([go, "build", "-o", str(tmp_path / "bin") + "/", "."], root, environment)

    rc = tmp_path / "terraformrc"
    rc.write_text(
        "provider_installation {\n"
        f'  dev_overrides {{ "{package.address}" = "{tmp_path / "bin"}" }}\n'
        "  direct {}\n"
        "}\n"
    )
    environment = {**environment, "TF_CLI_CONFIG_FILE": str(rc), "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"}

    # Every example validates against the provider's schema.
    examples = tmp_path / "examples"
    examples.mkdir()
    shutil.copy(root / "examples/provider/provider.tf", examples / "provider.tf")
    for kind in ("resources", "data-sources"):
        for example in sorted((root / "examples" / kind).glob("*/*.tf")):
            shutil.copy(example, examples / f"{kind}-{example.parent.name}.tf")
    _run([terraform, "validate", "-no-color"], examples, environment)
    _run([terraform, "fmt", "-check", "-recursive", str(root / "examples")], examples, environment)

    work = tmp_path / "work"
    work.mkdir()
    (work / "main.tf").write_text(
        "terraform {\n"
        f'  required_providers {{\n    widgetplatformapi = {{ source = "{package.address}" }}\n  }}\n'
        "}\n"
        'provider "widgetplatformapi" {\n'
        f'  endpoint = "{widget_store}"\n'
        '  token    = "t0ken"\n'
        "}\n"
        'variable "size" {\n  default = 1\n}\n'
        'resource "widgetplatformapi_widget" "web" {\n'
        '  name     = "web"\n'
        '  region   = "us-east"\n'
        "  size     = var.size\n"
        '  tags     = ["a", "b"]\n'
        '  settings = { color = "blue" }\n'
        "  quotas   = { cpu = 2 }\n"
        "}\n"
        'data "widgetplatformapi_widget" "back" {\n  id = widgetplatformapi_widget.web.id\n}\n'
        'data "widgetplatformapi_widget_list" "all" {\n  depends_on = [widgetplatformapi_widget.web]\n}\n'
        'output "size" {\n  value = data.widgetplatformapi_widget.back.size\n}\n'
        'output "count" {\n  value = length(data.widgetplatformapi_widget_list.all.items)\n}\n'
    )

    def terraform_run(*arguments: str) -> subprocess.CompletedProcess:
        return _run([terraform, *arguments, "-no-color"], work, environment)

    def outputs() -> Dict[str, Any]:
        result = _run([terraform, "output", "-json"], work, environment)
        return {name: value["value"] for name, value in json.loads(result.stdout).items()}

    def plan_is_clean(*arguments: str) -> bool:
        result = subprocess.run(
            [terraform, "plan", "-detailed-exitcode", "-no-color", *arguments],
            cwd=work,
            capture_output=True,
            text=True,
            env=environment,
            timeout=900,
        )
        return result.returncode == 0

    terraform_run("apply", "-auto-approve")
    assert outputs() == {"size": 1, "count": 1}
    assert _WidgetStore.calls[0] == "POST /widgets"
    assert plan_is_clean(), "a fresh apply must leave nothing to change"

    terraform_run("apply", "-auto-approve", "-var", "size=3")
    assert outputs()["size"] == 3
    assert any(call.startswith("PUT /widgets/") for call in _WidgetStore.calls), "size changes in place"
    assert not [call for call in _WidgetStore.calls if call.startswith("DELETE")]
    assert plan_is_clean("-var", "size=3")

    [identifier] = list(_WidgetStore.widgets)
    terraform_run("state", "rm", "widgetplatformapi_widget.web")
    terraform_run("import", "-var", "size=3", "widgetplatformapi_widget.web", str(identifier))
    assert plan_is_clean("-var", "size=3"), "an imported widget matches its configuration"

    terraform_run("destroy", "-auto-approve", "-var", "size=3")
    assert _WidgetStore.widgets == {}
