"""Tests for the OpenAPI export's ``refs`` option: bundle, dereference, split — COA-2.4 (#7047).

The acceptance gate is the corpus round trip: across the OpenAPI construct corpus (86 documents,
every output version) a split export bundles back to exactly the bundled document, a dereferenced
export imports and dereferences again to itself, and neither adds a meta-schema error to a document
that validates bundled. The rest pin the behaviour: cycles are kept as ``$ref`` and reported (or
refuse the export), literal data is never treated as a reference, split file names stay safe and
unique, and the fileset import bundles a split layout back.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.emitter import EmitPreconditionError, LossTracker
from app.export_service import ExportError, emit_canonical
from app.fileset import IntakeFileset
from app.openapi_construct_audit import load_corpus
from app.openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from app.openapi_fileset_bundle import bundle_openapi_fileset, references_fileset_members
from app.openapi_import_source import OpenApiImportSource
from app.openapi_ref_modes import (
    CYCLE_LOSS_SUBJECT,
    _resolve_pointer,
    apply_ref_mode,
    dereference_document,
    split_document,
)
from app.openapi_validator import validate_openapi_document
from app.roundtrip_matrix import emitted_fileset

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "apiome-rest" / "tests" / "fixtures" / "openapi_construct_corpus"
VERSIONS = ("3.0", "3.1", "3.2", "2.0")


def _internal_refs(value: Any, at: str = "") -> List[Tuple[str, str]]:
    """Every ``(pointer, ref)`` of an internal ``$ref`` in ``value``, outside ``components``."""
    found: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            found.append((at, ref))
        for key, item in value.items():
            if key in ("example", "default", "const", "enum", "value"):
                continue
            found.extend(_internal_refs(item, f"{at}/{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_internal_refs(item, f"{at}/{index}"))
    return found


def _emit(document: Dict[str, Any], **options: Any):
    """Import ``document`` and emit it with ``options``."""
    model = OpenApiImportSource().normalize(copy.deepcopy(document), include_raw=False)
    return OpenApiEmitter().emit(model, opts=OpenApiEmitOptions(**options))


@pytest.fixture(scope="module")
def corpus() -> List[Tuple[str, Dict[str, Any]]]:
    """The OpenAPI construct corpus (COA-2.1)."""
    documents = load_corpus(CORPUS)
    assert len(documents) >= 80
    return documents


#: A small API whose schemas recurse: ``Tree`` refers to itself, ``Person`` and ``Company`` to
#: each other, and ``Leaf`` is shared but not circular.
CYCLIC: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Cycles", "version": "1.0.0"},
    "paths": {
        "/trees": {
            "get": {
                "operationId": "listTrees",
                "responses": {
                    "200": {
                        "description": "Trees.",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Tree"}}},
                    }
                },
            }
        },
        "/people/{id}": {
            "get": {
                "operationId": "getPerson",
                "parameters": [{"$ref": "#/components/parameters/Id"}],
                "responses": {
                    "200": {
                        "description": "A person.",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Person"}}},
                    },
                    "default": {"$ref": "#/components/responses/Error"},
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Leaf": {"type": "object", "properties": {"label": {"type": "string"}}},
            "Tree": {
                "type": "object",
                "properties": {
                    "leaf": {"$ref": "#/components/schemas/Leaf"},
                    "children": {"type": "array", "items": {"$ref": "#/components/schemas/Tree"}},
                },
            },
            "Person": {
                "type": "object",
                "properties": {"employer": {"$ref": "#/components/schemas/Company"}},
            },
            "Company": {
                "type": "object",
                "properties": {
                    "staff": {"type": "array", "items": {"$ref": "#/components/schemas/Person"}}
                },
            },
            "Error": {"type": "object", "properties": {"message": {"type": "string"}}},
        },
        "parameters": {
            "Id": {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
        },
        "responses": {
            "Error": {
                "description": "An error.",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
            }
        },
    },
}


# ===========================================================================
# Acceptance: each mode round-trips on the corpus
# ===========================================================================


@pytest.mark.parametrize("version", VERSIONS)
def test_split_bundles_back_to_the_bundled_document_across_the_corpus(corpus, version: str) -> None:
    """A split export, imported as a fileset, is exactly the bundled export."""
    mismatched = []
    for name, document in corpus:
        bundled = _emit(document, openapi_version=version).document
        split = _emit(document, openapi_version=version, refs="split")
        back = OpenApiImportSource().parse_fileset(emitted_fileset(split))
        if back != bundled:
            mismatched.append(name)
    assert not mismatched, f"split does not bundle back at {version}: {mismatched}"


def test_dereference_round_trips_through_import_across_the_corpus(corpus) -> None:
    """Importing a dereferenced export and dereferencing it again gives the same document."""
    unstable = []
    for name, document in corpus:
        first = _emit(document, refs="dereference").document
        again = _emit(first, refs="dereference").document
        if again != first:
            unstable.append(name)
    assert not unstable, f"dereference is not stable through import: {unstable}"


@pytest.mark.parametrize("version", VERSIONS)
def test_no_mode_breaks_a_valid_document(corpus, version: str) -> None:
    """When the bundled export validates, the dereferenced document and the split root do too."""
    broken = []
    for name, document in corpus:
        if validate_openapi_document(_emit(document, openapi_version=version).document):
            continue
        for mode in ("dereference", "split"):
            emitted = _emit(document, openapi_version=version, refs=mode)
            errors = validate_openapi_document(emitted.document)
            if errors:
                broken.append((name, mode, errors[:1]))
    assert not broken, broken


@pytest.mark.parametrize("version", VERSIONS)
def test_dereference_leaves_no_internal_ref_outside_components(corpus, version: str) -> None:
    """A dereferenced document needs no reference to be read (the corpus has no cycles).

    A reference the bundled document already leaves dangling (a 3.0 downgrade removes the 3.1-only
    ``components/pathItems``, and reports it) has nothing to expand and is not counted.
    """
    leftover = []
    for name, document in corpus:
        result = _emit(document, openapi_version=version, refs="dereference")
        body = {k: v for k, v in result.document.items() if k not in ("components", "definitions")}
        refs = [(at, ref) for at, ref in _internal_refs(body) if _resolve_pointer(result.document, ref)[0]]
        if refs and not any(loss.subject == CYCLE_LOSS_SUBJECT for loss in result.losses):
            leftover.append((name, refs[:2]))
    assert not leftover, leftover


def test_bundle_is_the_default_and_unchanged() -> None:
    """``refs: bundle`` is the default and emits the same single file as no option at all."""
    assert OpenApiEmitOptions().refs == "bundle"
    assert OpenApiEmitOptions().ref_cycles == "keep-ref"
    default = _emit(CYCLIC)
    bundled = _emit(CYCLIC, refs="bundle")
    assert default.files == bundled.files
    assert [file.path for file in default.files] == ["openapi.json"]


# ===========================================================================
# Cycles: reported, never expanded forever
# ===========================================================================


def test_dereference_keeps_the_ref_that_closes_each_cycle_and_reports_it() -> None:
    """``keep-ref``: a cycle stays a ``$ref`` at the point it closes; each one is a loss."""
    losses = LossTracker()
    result = dereference_document(CYCLIC, losses=losses)

    tree = result["paths"]["/trees"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert tree["properties"]["leaf"] == {"type": "object", "properties": {"label": {"type": "string"}}}
    assert tree["properties"]["children"]["items"] == {"$ref": "#/components/schemas/Tree"}

    person = result["paths"]["/people/{id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    company = person["properties"]["employer"]
    assert company["properties"]["staff"]["items"] == {"$ref": "#/components/schemas/Person"}

    # Inside components, an entry's own self reference is kept (it is never expanded one level).
    assert result["components"]["schemas"]["Tree"]["properties"]["children"]["items"] == {
        "$ref": "#/components/schemas/Tree"
    }

    cycle_losses = [loss for loss in losses.records() if loss.subject == CYCLE_LOSS_SUBJECT]
    assert {loss.detail.split(" ")[0] for loss in cycle_losses} == {
        "#/components/schemas/Tree",
        "#/components/schemas/Person",
        "#/components/schemas/Company",
    }
    assert all(loss.pointer and loss.pointer.startswith("/") for loss in cycle_losses)
    # Every remaining reference is one of the reported cycles.
    reported = {loss.detail.split(" ")[0] for loss in cycle_losses}
    assert {ref for _, ref in _internal_refs(result)} <= reported


def test_dereference_with_the_error_policy_refuses_a_cyclic_document() -> None:
    """``error``: the export is refused, naming the cycles."""
    with pytest.raises(EmitPreconditionError) as raised:
        dereference_document(CYCLIC, cycle_policy="error")
    message = str(raised.value)
    assert "3 circular $ref(s)" in message
    assert "#/components/schemas/Tree" in message


def test_the_error_policy_accepts_an_acyclic_document() -> None:
    """``error`` only refuses when there is a cycle."""
    acyclic = copy.deepcopy(CYCLIC)
    del acyclic["components"]["schemas"]["Tree"]["properties"]["children"]
    acyclic["components"]["schemas"]["Company"]["properties"].pop("staff")
    result = dereference_document(acyclic, cycle_policy="error")
    assert not _internal_refs(result)


def test_a_cyclic_export_through_the_emitter_reports_and_validates() -> None:
    """End to end through the emitter: the dereferenced document is valid and the cycles are losses."""
    result = _emit(CYCLIC, refs="dereference")
    assert not validate_openapi_document(result.document)
    assert sum(loss.subject == CYCLE_LOSS_SUBJECT for loss in result.losses) == 3


def test_a_refused_dereference_is_a_422_through_the_export_service() -> None:
    """The export service turns the ``error`` policy's refusal into an HTTP 422."""
    model = OpenApiImportSource().normalize(copy.deepcopy(CYCLIC), include_raw=False)
    with pytest.raises(ExportError) as raised:
        emit_canonical(model, "openapi", opts={"refs": "dereference", "ref_cycles": "error"})
    assert raised.value.status_code == 422


def test_an_unknown_mode_or_policy_is_rejected() -> None:
    """Unknown option values fail validation; the helpers refuse them too."""
    with pytest.raises(ValueError):
        OpenApiEmitOptions(refs="inline")
    with pytest.raises(ValueError):
        OpenApiEmitOptions(ref_cycles="expand")
    with pytest.raises(ValueError):
        dereference_document(CYCLIC, cycle_policy="expand")
    with pytest.raises(ValueError):
        apply_ref_mode(CYCLIC, mode="inline", cycle_policy="keep-ref", root_path="openapi.json",
                       media_type="application/json", losses=LossTracker())


def test_dereference_refuses_a_document_that_would_explode(monkeypatch) -> None:
    """A dereference past the node budget is refused, not left to exhaust memory."""
    from app import openapi_ref_modes

    monkeypatch.setattr(openapi_ref_modes, "MAX_DEREFERENCED_NODES", 50)
    with pytest.raises(EmitPreconditionError, match="bundled or split"):
        dereference_document(CYCLIC)


# ===========================================================================
# Dereference details
# ===========================================================================


def test_literal_data_is_never_treated_as_a_reference() -> None:
    """``example`` / ``default`` / ``enum`` / an Example's ``value`` keep a ``$ref`` key as data."""
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Literal", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Target": {"type": "string"},
                "Doc": {
                    "type": "object",
                    "default": {"$ref": "#/components/schemas/Target"},
                    "example": {"$ref": "#/components/schemas/Target"},
                    "examples": [{"$ref": "#/components/schemas/Target"}],
                    "enum": [{"$ref": "#/components/schemas/Target"}],
                },
            },
            "examples": {"Ref": {"value": {"$ref": "#/components/schemas/Target"}}},
        },
    }
    result = dereference_document(document)
    doc = result["components"]["schemas"]["Doc"]
    for key in ("default", "example"):
        assert doc[key] == {"$ref": "#/components/schemas/Target"}
    assert doc["examples"] == [{"$ref": "#/components/schemas/Target"}]
    assert doc["enum"] == [{"$ref": "#/components/schemas/Target"}]
    assert result["components"]["examples"]["Ref"]["value"] == {"$ref": "#/components/schemas/Target"}


def test_a_default_response_is_dereferenced() -> None:
    """A Responses Object's ``default`` is a Response, not literal data."""
    result = dereference_document(CYCLIC)
    default = result["paths"]["/people/{id}"]["get"]["responses"]["default"]
    assert default["description"] == "An error."
    assert default["content"]["application/json"]["schema"]["type"] == "object"


def test_reference_siblings_are_kept() -> None:
    """``description`` overrides; ``summary`` is dropped where the target has none; conflicts use allOf."""
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Siblings", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Name": {"type": "string", "maxLength": 10, "description": "A name."},
                "UsesName": {
                    "type": "object",
                    "properties": {
                        "described": {"$ref": "#/components/schemas/Name", "description": "Override."},
                        "tighter": {"$ref": "#/components/schemas/Name", "maxLength": 5},
                        "extra": {"$ref": "#/components/schemas/Name", "minLength": 1},
                    },
                },
            },
            "parameters": {"Q": {"name": "q", "in": "query", "schema": {"type": "string"}}},
            "examples": {"E": {"value": 1}},
            "pathItems": {
                "Thing": {
                    "parameters": [{"$ref": "#/components/parameters/Q", "summary": "Ignored."}],
                    "get": {
                        "responses": {"200": {"description": "ok"}},
                    },
                }
            },
            "headers": {
                "H": {
                    "schema": {"type": "string"},
                    "examples": {"one": {"$ref": "#/components/examples/E", "summary": "Kept."}},
                }
            },
        },
    }
    result = dereference_document(document)
    props = result["components"]["schemas"]["UsesName"]["properties"]
    assert props["described"] == {"type": "string", "maxLength": 10, "description": "Override."}
    assert props["tighter"] == {
        "allOf": [{"type": "string", "maxLength": 10, "description": "A name."}],
        "maxLength": 5,
    }
    assert props["extra"] == {"type": "string", "maxLength": 10, "description": "A name.", "minLength": 1}
    assert result["components"]["pathItems"]["Thing"]["parameters"][0] == {
        "name": "q",
        "in": "query",
        "schema": {"type": "string"},
    }
    assert result["components"]["headers"]["H"]["examples"]["one"] == {"value": 1, "summary": "Kept."}


def test_external_and_dangling_references_are_left_as_written() -> None:
    """A URL, an anchor and a pointer that resolves nowhere are not this option's to change."""
    document = {
        "openapi": "3.1.0",
        "info": {"title": "External", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Remote": {"$ref": "https://example.com/schemas/pet.json"},
                "Anchor": {"$ref": "#pet"},
                "Dangling": {"$ref": "#/components/schemas/Missing"},
            }
        },
    }
    assert dereference_document(document)["components"] == document["components"]


def test_a_swagger_document_is_dereferenced_with_its_own_pointers() -> None:
    """Swagger 2.0 ``#/definitions`` references are expanded the same way."""
    result = _emit(CYCLIC, openapi_version="2.0", refs="dereference")
    assert result.files[0].path == "swagger.json"
    body = {k: v for k, v in result.document.items() if k != "definitions"}
    assert {ref for _, ref in _internal_refs(body)} <= {
        "#/definitions/Tree",
        "#/definitions/Person",
        "#/definitions/Company",
    }
    assert not validate_openapi_document(result.document)


# ===========================================================================
# Split details
# ===========================================================================


def test_split_writes_one_file_per_path_item_and_component() -> None:
    """The root comes first; paths and components move to their own files with relative refs."""
    result = _emit(CYCLIC, refs="split")
    paths = [file.path for file in result.files]
    assert paths[0] == "openapi.json"
    assert paths[1:] == sorted(paths[1:])
    assert set(paths[1:]) == {
        "paths/trees.json",
        "paths/people_id.json",
        "components/schemas/Leaf.json",
        "components/schemas/Tree.json",
        "components/schemas/Person.json",
        "components/schemas/Company.json",
        "components/schemas/Error.json",
        "components/parameters/Id.json",
        "components/responses/Error.json",
    }
    root = result.document
    assert root["paths"]["/people/{id}"] == {"$ref": "paths/people_id.json"}
    assert root["components"]["schemas"]["Tree"] == {"$ref": "components/schemas/Tree.json"}

    files = {file.path: file.content for file in result.files}
    tree = files["components/schemas/Tree.json"]
    assert tree["properties"]["children"]["items"] == {"$ref": "Tree.json"}
    assert tree["properties"]["leaf"] == {"$ref": "Leaf.json"}
    person_path = files["paths/people_id.json"]
    assert person_path["get"]["parameters"] == [{"$ref": "../components/parameters/Id.json"}]
    assert person_path["get"]["responses"]["default"] == {"$ref": "../components/responses/Error.json"}
    assert not validate_openapi_document(root)


def test_split_names_files_safely_and_uniquely() -> None:
    """Unsafe characters become ``_``; names that collide (ignoring case) get a suffix."""
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Names", "version": "1"},
        "paths": {
            "/a/{b}": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/a/b": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/": {"get": {"responses": {"200": {"description": "ok"}}}},
        },
        "components": {
            "schemas": {
                "Pet": {"type": "object"},
                "pet": {"type": "string"},
                "../escape": {"type": "string"},
                "com.acme.Thing": {"type": "string"},
            }
        },
    }
    files = [f.path for f in split_document(document, root_path="openapi.json", media_type="application/json")]
    assert "paths/a_b.json" in files and "paths/a_b-2.json" in files
    assert "paths/root.json" in files
    assert "components/schemas/Pet.json" in files and "components/schemas/pet-2.json" in files
    assert "components/schemas/escape.json" in files
    assert "components/schemas/com.acme.Thing.json" in files
    assert all(".." not in path for path in files)


def test_split_keeps_pointers_into_a_unit_and_back_into_the_root() -> None:
    """A pointer inside a unit points into its file; one to an unsplit section points at the root."""
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Pointers", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "PetId": {"$ref": "#/components/schemas/Pet/properties/id", "description": "The id."},
                "Alias": {"$ref": "#/components/schemas/Pet"},
                "Tagged": {
                    "oneOf": [{"$ref": "#/components/schemas/Pet"}],
                    "discriminator": {
                        "propertyName": "kind",
                        "mapping": {"pet": "#/components/schemas/Pet", "named": "Pet"},
                    },
                },
                "Secured": {"$ref": "#/components/securitySchemes/key", "description": "Odd."},
            },
            "securitySchemes": {"key": {"type": "apiKey", "name": "k", "in": "header"}},
        },
    }
    files = {
        f.path: f.content
        for f in split_document(document, root_path="openapi.json", media_type="application/json")
    }
    assert files["components/schemas/PetId.json"] == {"$ref": "Pet.json#/properties/id", "description": "The id."}
    # A bare alias stays in the root, its reference pointing at the moved file.
    assert "components/schemas/Alias.json" not in files
    assert files["openapi.json"]["components"]["schemas"]["Alias"] == {"$ref": "components/schemas/Pet.json"}
    assert files["components/schemas/Tagged.json"]["discriminator"]["mapping"] == {
        "pet": "Pet.json",
        "named": "Pet",
    }
    assert files["components/schemas/Secured.json"] == {
        "$ref": "../../openapi.json#/components/securitySchemes/key",
        "description": "Odd.",
    }
    assert "securitySchemes" in files["openapi.json"]["components"]

    fileset = IntakeFileset.from_members({p: json.dumps(c) for p, c in files.items()}, root="openapi.json")
    assert bundle_openapi_fileset(fileset) == document


def test_split_rebases_relative_file_references() -> None:
    """A relative file reference written for the root is re-based onto the file it moves to."""
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Rebase", "version": "1"},
        "paths": {},
        "components": {"schemas": {"Remote": {"type": "object", "properties": {"a": {"$ref": "shared/a.json"}}}}},
    }
    files = {f.path: f.content for f in split_document(document, root_path="openapi.json", media_type="x")}
    assert files["components/schemas/Remote.json"]["properties"]["a"] == {"$ref": "../../shared/a.json"}


def test_a_document_with_nothing_to_split_is_the_root_alone() -> None:
    """No paths and no components: one file."""
    document = {"openapi": "3.1.0", "info": {"title": "Empty", "version": "1"}, "paths": {}}
    files = split_document(document, root_path="openapi.json", media_type="application/json")
    assert [f.path for f in files] == ["openapi.json"]
    assert files[0].content == document


def test_a_swagger_split_moves_paths_and_definitions_only() -> None:
    """Swagger 2.0 ``parameters`` / ``responses`` entries may not be references: they stay put."""
    result = _emit(CYCLIC, openapi_version="2.0", refs="split")
    paths = {file.path for file in result.files}
    assert "swagger.json" in paths and "definitions/Tree.json" in paths
    assert not any(path.startswith(("parameters/", "responses/")) for path in paths)
    assert not validate_openapi_document(result.document)


# ===========================================================================
# Import: a split fileset is bundled back
# ===========================================================================


def test_a_split_export_imports_as_one_api() -> None:
    """The split files, imported as a fileset, give the same canonical operations and types."""
    split = _emit(CYCLIC, refs="split")
    source = OpenApiImportSource()
    native = source.parse_fileset(emitted_fileset(split))
    model = source.normalize(native, include_raw=False)
    original = source.normalize(copy.deepcopy(CYCLIC), include_raw=False)
    assert sorted(op.key for op in model.operations()) == sorted(op.key for op in original.operations())
    assert sorted(t.name for t in model.types) == sorted(t.name for t in original.types)


def test_references_fileset_members_only_counts_existing_members() -> None:
    """URLs, internal pointers and missing files do not trigger bundling."""
    fileset = IntakeFileset.from_members(
        {"openapi.json": "{}", "components/schemas/Pet.json": "{}"}, root="openapi.json"
    )
    assert references_fileset_members({"a": {"$ref": "components/schemas/Pet.json"}}, "openapi.json", fileset)
    assert not references_fileset_members({"a": {"$ref": "#/components/schemas/Pet"}}, "openapi.json", fileset)
    assert not references_fileset_members({"a": {"$ref": "https://x.test/pet.json"}}, "openapi.json", fileset)
    assert not references_fileset_members({"a": {"$ref": "missing.json"}}, "openapi.json", fileset)
    assert not references_fileset_members({"a": {"$ref": "../../outside.json"}}, "openapi.json", fileset)


def test_the_bundler_leaves_url_references_alone() -> None:
    """A ``$ref`` with a URI scheme is not a fileset member and is kept as written."""
    root = {
        "openapi": "3.1.0",
        "info": {"title": "Urls", "version": "1"},
        "paths": {"/a": {"$ref": "paths/a.json"}},
    }
    path_item = {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {
        "schema": {"$ref": "https://example.com/pet.json"}}}}}}}
    fileset = IntakeFileset.from_members(
        {"openapi.json": json.dumps(root), "paths/a.json": json.dumps(path_item)}, root="openapi.json"
    )
    bundled = bundle_openapi_fileset(fileset)
    assert bundled["paths"]["/a"] == path_item


def test_the_options_schema_carries_titles_for_the_export_studio() -> None:
    """Export studio draws the two options from the JSON Schema: titled enums with defaults."""
    schema = OpenApiEmitter.options_schema()
    refs = schema["properties"]["refs"]
    cycles = schema["properties"]["ref_cycles"]
    assert refs["title"] == "$ref handling"
    assert refs["enum"] == ["bundle", "dereference", "split"] and refs["default"] == "bundle"
    assert cycles["title"] == "Reference cycles"
    assert cycles["enum"] == ["keep-ref", "error"] and cycles["default"] == "keep-ref"


def test_the_split_job_zip_imports_back_through_archive_intake() -> None:
    """The zip a split export job serves (with its ``manifest.json``) imports as the bundled document."""
    from app.archive_intake import unpack_archive
    from app.export_job_engine import build_export_zip

    model = OpenApiImportSource().normalize(copy.deepcopy(CYCLIC), include_raw=False)
    split = OpenApiEmitter().emit(model, opts=OpenApiEmitOptions(refs="split"))
    unpacked = unpack_archive(build_export_zip(split, "openapi-3.1"))
    assert unpacked.root_path == "openapi.json"
    fileset = IntakeFileset.from_members(unpacked.members, root=unpacked.root_path)
    assert OpenApiImportSource().parse_fileset(fileset) == OpenApiEmitter().emit(model).document
