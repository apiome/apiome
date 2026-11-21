"""Catalog ↔ Projects import-path parity — COA-4.2 (#7059).

Apiome imports an OpenAPI or Arazzo document on two paths:

* the **Projects** path — the UI importer (``apiome-ui/lib/importers/openapi.ts``,
  ``extractPaths`` in ``src/app/utils/openapi-import.ts``, ``buildTagTaxonomy`` and
  ``lib/importers/arazzo-sources.ts``), which writes classes, paths and project metadata;
* the **Catalog** path — the REST normalizer (:class:`app.openapi_normalizer.OpenApiNormalizer`,
  :class:`app.arazzo_normalizer.ArazzoNormalizer` with
  :mod:`app.arazzo_source_resolution` and :mod:`app.arazzo_workflow_persistence`), which writes
  the canonical model.

RC7 §3.2 built the OpenAPI 3.2 constructs OA3 (streaming ``itemSchema``), OA4 (``query`` and
``additionalOperations``), OA5 (tag hierarchy), OA6 (``$self`` references) and the Arazzo source
resolution AZ2 on the Projects path. This suite imports each fixture in
``tests/golden/path_parity/`` on the Catalog path, reduces the result to a small,
language-neutral **projection** (what each construct imported as), and compares it with
``tests/golden/path_parity/expected.json``. The jest suite
``apiome-ui/tests/catalog-projects-path-parity.test.ts`` compares the Projects path's projection
with the **same** file, so the two paths agree whenever both suites pass.

The differences the projection leaves out on purpose — each a difference in how the result is
*stored*, not in what was imported — are listed under ``differences`` in ``expected.json`` and
in the docs (``apiome-docs/docs/bring-in/import-a-spec.md``, **The same result in the catalog**).

Regenerate ``expected.json`` after an intended change with::

    APIOME_UPDATE_PATH_PARITY=1 pytest tests/test_catalog_projects_path_parity.py

then run the jest suite, which must still pass against the regenerated file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from app.arazzo_normalizer import ArazzoNormalizer
from app.arazzo_source_resolution import resolve_fileset_sources
from app.arazzo_workflow_persistence import (
    OperationIndex,
    build_workflow_rows,
    resolve_workflow_steps,
)
from app.canonical_model import CanonicalApi, Message, MessageRole
from app.openapi_normalizer import OpenApiNormalizer

FIXTURES = Path(__file__).parent / "golden" / "path_parity"
EXPECTED_PATH = FIXTURES / "expected.json"
UPDATE_ENV = "APIOME_UPDATE_PATH_PARITY"


def _load(relative: str) -> Any:
    """Parse one fixture file (YAML or JSON)."""
    return yaml.safe_load((FIXTURES / relative).read_text(encoding="utf-8"))


def _normalize(relative: str) -> CanonicalApi:
    """Import one OpenAPI fixture on the Catalog path."""
    return OpenApiNormalizer().normalize(_load(relative))


def _operations(model: CanonicalApi):
    """Every operation of the model."""
    for service in model.services:
        yield from service.operations


def _message_label(message: Message) -> str:
    """``request`` or ``response <status>`` — the projection's name for a message."""
    if message.role is MessageRole.REQUEST:
        return "request"
    return f"response {message.status_code}"


def _is_class_like(schema: Any) -> bool:
    """Whether an inline element schema is object-shaped (the Projects importer's rule)."""
    if not isinstance(schema, dict) or "$ref" in schema:
        return False
    properties = schema.get("properties")
    return bool(isinstance(properties, dict) and properties) or isinstance(schema.get("allOf"), list)


def project_streams(model: CanonicalApi) -> List[Dict[str, Any]]:
    """OA3: every streamed media type with its kind and element.

    ``element`` is the named class for a ``$ref`` element, ``inline-object`` for an
    object-shaped inline element and ``inline`` for any other inline element.
    """
    rows: List[Dict[str, Any]] = []
    for operation in _operations(model):
        for message in operation.messages:
            for media_type, entry in (message.extras.get("streams") or {}).items():
                if "type" in entry:
                    element = entry["type"].get("name")
                else:
                    element = "inline-object" if _is_class_like(entry.get("schema")) else "inline"
                rows.append(
                    {
                        "operation": f"{operation.http_method} {operation.http_path}",
                        "message": _message_label(message),
                        "mediaType": media_type,
                        "kind": entry["kind"],
                        "element": element,
                    }
                )
    return sorted(rows, key=lambda r: (r["operation"], r["message"], r["mediaType"]))


def project_operations(model: CanonicalApi) -> Dict[str, Any]:
    """OA4: every operation (method, path, token as written, operationId) and the repeats."""
    rows = [
        {
            "operation": f"{operation.http_method} {operation.http_path}",
            "token": operation.extras.get("methodToken") or operation.http_method,
            "operationId": operation.extras.get("operationId"),
        }
        for operation in _operations(model)
    ]
    return {
        "operations": sorted(rows, key=lambda r: r["operation"]),
        "duplicates": dict(sorted((model.extras.get("duplicateMethods") or {}).items())),
    }


def project_tags(model: CanonicalApi) -> Dict[str, Any]:
    """OA5: the effective tag tree (parent / summary / kind) and each operation's tags."""
    tags = {
        name: {key: meta[key] for key in ("parent", "summary", "kind") if key in meta}
        for name, meta in (model.extras.get("tagHierarchy") or {}).items()
    }
    return {
        "tags": dict(sorted((name, meta) for name, meta in tags.items() if meta)),
        "operationTags": {
            f"{op.http_method} {op.http_path}": list(op.tags)
            for op in sorted(_operations(model), key=lambda o: o.key)
            if op.tags
        },
    }


def project_references(model: CanonicalApi) -> Dict[str, Any]:
    """OA6: what each referencing property links to, its description, and external refs."""
    type_keys = {t.key for t in model.types}
    fields: Dict[str, Any] = {}
    for type_ in model.types:
        for field in type_.fields or []:
            external = field.type.extras.get("externalRef") if field.type else None
            if external:
                target = f"external:{external}"
            elif field.type is not None and field.type.name in type_keys:
                target = field.type.name
            else:
                continue
            fields[f"{type_.name}.{field.name}"] = {
                "ref": target,
                "description": field.description,
            }
    return {
        "fields": dict(sorted(fields.items())),
        "externalReferences": sorted(model.extras.get("externalReferences") or []),
    }


def project_arazzo(directory: str, flow: str, sources: Dict[str, str]) -> Dict[str, Any]:
    """AZ2: how each source and each step resolved against the documents imported with it.

    The Catalog path resolves sources against the fileset members and steps against the
    operations imported in the same scan; here those operations come from normalizing the
    fileset's OpenAPI members, keyed ``METHOD path`` like the projection.
    """
    document = _load(f"{directory}/{flow}")
    members = {path: _load(f"{directory}/{path}") for path in sources.values()}
    resolved, pending = resolve_fileset_sources(document, flow, members)

    rows = []
    for path, member in members.items():
        for operation in _operations(OpenApiNormalizer().normalize(member)):
            rows.append(
                {
                    "id": f"{operation.http_method} {operation.http_path}",
                    "operation": operation.http_method,
                    "pathname": operation.http_path,
                    "operation_id": operation.extras.get("operationId"),
                    "source_path": path,
                }
            )
    result = resolve_workflow_steps(
        build_workflow_rows(ArazzoNormalizer().normalize(document)), OperationIndex(rows)
    )
    steps: Dict[str, Any] = {}
    for workflow in result.workflows:
        for step in workflow.steps:
            entry: Dict[str, Any] = {"status": step.resolution_status}
            if step.resolved_path_operation_id:
                entry["operation"] = step.resolved_path_operation_id
            steps[f"{workflow.workflow_id}/{step.step_id}"] = entry
    source_status = {record["name"]: "resolved" for record in resolved}
    source_status.update({record["name"]: "unresolved" for record in pending})
    return {"sources": dict(sorted(source_status.items())), "steps": dict(sorted(steps.items()))}


def catalog_projection() -> Dict[str, Any]:
    """The Catalog path's projection of every parity case."""
    return {
        "oa3-streaming": {"streams": project_streams(_normalize("oa3-streaming.yaml"))},
        "oa4-methods": project_operations(_normalize("oa4-methods.yaml")),
        "oa5-tag-hierarchy": project_tags(_normalize("oa5-tag-hierarchy.yaml")),
        "oa6-self-references": project_references(_normalize("oa6-self-references.yaml")),
        "az2-arazzo": project_arazzo(
            "az2-arazzo",
            "flow.arazzo.yaml",
            {"petstore": "petstore.yaml"},
        ),
    }


def _expected() -> Dict[str, Any]:
    """The committed expected projection file."""
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def test_expected_file_names_every_case_and_documents_differences():
    """``expected.json`` holds one projection per case and a reason for each left-out difference."""
    expected = _expected()
    assert set(expected["cases"]) == set(catalog_projection())
    for difference in expected["differences"]:
        assert difference["case"] in expected["cases"]
        assert difference["projects"].strip() and difference["catalog"].strip()


@pytest.mark.parametrize("case", sorted(catalog_projection()))
def test_catalog_path_matches_the_shared_projection(case: str):
    """Each case imports on the Catalog path to the projection the Projects path must also produce."""
    actual = catalog_projection()[case]
    if os.environ.get(UPDATE_ENV):
        expected = _expected()
        expected["cases"][case] = actual
        EXPECTED_PATH.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    assert actual == _expected()["cases"][case]


def test_external_reference_is_not_bound_to_a_same_named_local_type():
    """A ``$ref`` into another document is marked even when a local type has the same name."""
    document = {
        "openapi": "3.2.0",
        "$self": "https://api.example.com/a.yaml",
        "info": {"title": "t", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Partner": {"type": "object"},
                "Order": {
                    "type": "object",
                    "properties": {"p": {"$ref": "b.yaml#/components/schemas/Partner"}},
                },
            }
        },
    }
    model = OpenApiNormalizer().normalize(document)
    order = next(t for t in model.types if t.key == "Order")
    assert order.fields[0].type.extras["externalRef"] == "b.yaml#/components/schemas/Partner"
    assert model.extras["externalReferences"] == ["b.yaml#/components/schemas/Partner"]


def test_raw_and_preserved_source_keep_references_as_written():
    """``$self`` resolution drives the model only; the stored source is unchanged."""
    document = _load("oa6-self-references.yaml")
    model = OpenApiNormalizer().normalize(document)
    customer_ref = model.raw["components"]["schemas"]["Order"]["properties"]["customer"]["$ref"]
    assert customer_ref.startswith("https://api.example.com/")


def test_tag_hierarchy_issues_name_each_repair():
    """Every tag repair the Projects importer warns about is listed on the Catalog model."""
    issues = _normalize("oa5-tag-hierarchy.yaml").extras["tagHierarchyIssues"]
    assert any("declared more than once" in issue for issue in issues)
    assert any("'missing' is not a declared tag" in issue for issue in issues)
    assert any("alpha → beta → alpha" in issue for issue in issues)
    assert any("selfish → selfish" in issue for issue in issues)


def test_a_document_without_3_2_constructs_gains_no_parity_extras():
    """A plain 3.1 document's model carries none of the new extras."""
    model = OpenApiNormalizer().normalize(_load("az2-arazzo/petstore.yaml"))
    for key in ("tagHierarchyIssues", "externalReferences", "duplicateMethods"):
        assert key not in model.extras
    for operation in _operations(model):
        assert "methodToken" not in operation.extras
        assert all("streams" not in m.extras for m in operation.messages)


# --- unit tests of the helpers the Catalog path gained -------------------------------------


def test_resolve_self_references_without_self_returns_the_document_unchanged():
    """No ``$self`` → the same object back, nothing rewritten or listed."""
    from app.openapi_self_references import resolve_self_references

    document = {"openapi": "3.2.0", "components": {"schemas": {"A": {"$ref": "b.yaml#/X"}}}}
    resolution = resolve_self_references(document)
    assert resolution.document is document
    assert resolution.rewritten == 0 and resolution.external == []


def test_resolve_self_references_handles_relative_self_and_fragmentless_refs():
    """A relative ``$self`` still resolves; a same-document ref with no fragment becomes ``#``."""
    from app.openapi_self_references import resolve_self_references

    document = {
        "$self": "/specs/api.yaml",
        "a": {"$ref": "api.yaml"},
        "b": [{"$ref": "../specs/api.yaml#/components/schemas/B"}],
        "c": {"$ref": "other.yaml#/components/schemas/C"},
        "d": {"$ref": "#/components/schemas/D"},
    }
    resolution = resolve_self_references(document)
    assert resolution.document["a"]["$ref"] == "#"
    assert resolution.document["b"][0]["$ref"] == "#/components/schemas/B"
    assert resolution.document["d"]["$ref"] == "#/components/schemas/D"
    assert resolution.rewritten == 2
    assert resolution.external == ["other.yaml#/components/schemas/C"]
    assert document["a"]["$ref"] == "api.yaml"  # the input is never mutated


@pytest.mark.parametrize(
    ("media_type", "has_item_schema", "kind"),
    [
        ("application/jsonl", False, "jsonl"),
        ("application/vnd.acme+jsonl; charset=utf-8", True, "jsonl"),
        ("Application/JSON-SEQ", True, "json-seq"),
        ("text/event-stream", False, "sse"),
        ("application/problem+json", True, "sequential"),
        ("application/json", False, None),
    ],
)
def test_stream_kind_matches_the_projects_importer(media_type, has_item_schema, kind):
    """``stream_kind`` classifies media types exactly as ``getStreamKind`` does."""
    from app.openapi_normalizer import stream_kind

    assert stream_kind(media_type, has_item_schema) == kind


def test_additional_operation_in_upper_case_records_no_token():
    """``REPORT`` says nothing ``http_method`` does not, so no ``methodToken`` is stored."""
    model = _normalize("oa4-methods.yaml")
    tokens = {op.http_method: op.extras.get("methodToken") for op in _operations(model)}
    assert tokens["REPORT"] is None and tokens["PURGE"] == "Purge"
