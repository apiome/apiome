"""Tests for the OpenAPI construct losslessness audit and its published matrix (COA-2.1, #7044).

The first two tests are the acceptance gate: across the construct corpus (the OpenAPI
Initiative's test and example documents plus Apiome's construct fixtures) no construct of
OpenAPI 3.0, 3.1 or 3.2 is lost without a loss record, and the matrix published on
``reference/openapi-construct-matrix.md`` is the one this audit measures.

The rest pin the audit's own behaviour: the catalogue is well formed, occurrences are found by
object kind (a property *named* ``callbacks`` is not a callback), and a construct the emitter
drops is caught as ``silent`` — or as ``reported`` when a loss names it.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from app import openapi_emitter
from app.emitter import Loss, LossKind
from app.openapi_construct_audit import (
    CATEGORIES,
    CONSTRUCTS,
    VERSIONS,
    DocumentAudit,
    audit_document,
    build_matrix,
    find_occurrences,
    load_corpus,
    render_matrix_markdown,
)
from app.openapi_construct_matrix_doc import (
    BEGIN_MARKER,
    CORPUS_DIR,
    END_MARKER,
    OPENAPI_CONSTRUCT_MATRIX_PAGE,
    REGENERATE_COMMAND,
    apply_construct_matrix,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / CORPUS_DIR
PAGE = REPO_ROOT / OPENAPI_CONSTRUCT_MATRIX_PAGE


@pytest.fixture(scope="module")
def audits() -> List[DocumentAudit]:
    """The audit of every corpus document (computed once for the module)."""
    return [audit_document(name, document) for name, document in load_corpus(CORPUS)]


# ===========================================================================
# Acceptance: zero silent loss, and the published matrix is the measured one
# ===========================================================================


def test_no_construct_is_lost_silently_across_the_corpus(audits: List[DocumentAudit]) -> None:
    """Every construct occurrence is preserved or reported — never silently lost."""
    silent = [
        f"{audit.name}: {occurrence.construct} at {occurrence.pointer}"
        for audit in audits
        for occurrence in audit.silent
    ]
    assert not silent, "silent loss:\n" + "\n".join(silent)


def test_the_published_matrix_matches_the_audit(audits: List[DocumentAudit]) -> None:
    """The committed docs page holds exactly the matrix the corpus produces (drift gate)."""
    current = PAGE.read_text(encoding="utf-8")
    assert current == apply_construct_matrix(current, audits), (
        f"{OPENAPI_CONSTRUCT_MATRIX_PAGE} is stale. Regenerate with: {REGENERATE_COMMAND}"
    )


def test_every_construct_is_covered_for_every_version_it_exists_in(
    audits: List[DocumentAudit],
) -> None:
    """No applicable matrix cell is ``uncovered`` — the corpus exercises every construct."""
    cells = build_matrix(audits)
    uncovered = [f"{c} @ {v}" for (c, v), cell in cells.items() if cell.status == "uncovered"]
    assert not uncovered, "add a corpus document for: " + ", ".join(uncovered)


def test_the_canonical_round_trip_is_lossless_for_every_document(
    audits: List[DocumentAudit],
) -> None:
    """Re-importing the export gives back the same canonical entities (an empty diff)."""
    assert [audit.name for audit in audits if not audit.round_trip_lossless] == []


def test_exports_introduce_no_meta_schema_errors(audits: List[DocumentAudit]) -> None:
    """3.1 / 3.2 exports are no less valid than their sources."""
    assert {audit.name: audit.schema_errors for audit in audits if audit.schema_errors} == {}


def test_the_corpus_spans_every_version() -> None:
    """Each version family has OAI documents and an Apiome construct fixture."""
    names = [name for name, _ in load_corpus(CORPUS)]
    for version in VERSIONS:
        assert f"apiome/oas-{version}-constructs.yaml" in names
        assert any(name.startswith(f"oai/v{version}/") for name in names)


# ===========================================================================
# The catalogue
# ===========================================================================


def test_construct_ids_are_unique_and_well_formed() -> None:
    """Ids are unique; categories are the seven loss categories; versions are known."""
    ids = [construct.id for construct in CONSTRUCTS]
    assert len(ids) == len(set(ids))
    for construct in CONSTRUCTS:
        assert construct.category in CATEGORIES, construct.id
        assert construct.versions and set(construct.versions) <= set(VERSIONS), construct.id


def test_the_issue_named_constructs_are_in_the_catalogue() -> None:
    """The constructs COA-2.1 names are all tracked."""
    ids = {construct.id for construct in CONSTRUCTS}
    assert {
        "webhooks",
        "callbacks",
        "links",
        "discriminator",
        "extensions",
        "self",
        "json-schema-dialect",
        "dynamic-references",
        "item-schema",
        "streaming-media-types",
    } <= ids


# ===========================================================================
# Finding occurrences
# ===========================================================================


def _document(**extra) -> dict:
    """A small 3.1 document with ``extra`` merged into its root."""
    return {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}, "paths": {}, **extra}


def test_occurrences_are_found_by_object_kind_not_by_key_name() -> None:
    """A schema property named ``callbacks`` or ``links`` is data, not a construct."""
    document = _document(
        components={
            "schemas": {
                "Thing": {
                    "type": "object",
                    "properties": {"callbacks": {"type": "string"}, "links": {"type": "string"}},
                    "discriminator": {"propertyName": "kind"},
                }
            }
        }
    )
    found = find_occurrences(document, "3.1")
    assert ("discriminator", "/components/schemas/Thing/discriminator") in found
    assert not [item for item in found if item[0] in ("callbacks", "links")]


def test_occurrence_pointers_are_escaped() -> None:
    """Pointers escape ``/`` in path keys (RFC 6901)."""
    document = _document(
        paths={"/pets/{id}": {"get": {"x-rate": 1, "responses": {"200": {"description": "ok"}}}}}
    )
    assert ("extensions", "/paths/~1pets~1{id}/get/x-rate") in find_occurrences(document, "3.1")


def test_version_specific_constructs_are_only_looked_for_in_their_versions() -> None:
    """``$self`` in a 3.1 document is not counted (it is not a 3.1 construct)."""
    document = _document(**{"$self": "https://example.com/openapi.yaml"})
    assert not [item for item in find_occurrences(document, "3.1") if item[0] == "self"]
    assert ("self", "/$self") in find_occurrences({**document, "openapi": "3.2.0"}, "3.2")


def test_streaming_media_types_and_querystring_parameters_are_whole_objects() -> None:
    """Both constructs point at the object itself."""
    document = {
        "openapi": "3.2.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/s": {
                "get": {
                    "parameters": [{"name": "q", "in": "querystring", "content": {}}],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"text/event-stream": {"itemSchema": {"type": "string"}}},
                        }
                    },
                }
            }
        },
    }
    found = find_occurrences(document, "3.2")
    assert ("querystring-parameter", "/paths/~1s/get/parameters/0") in found
    assert (
        "streaming-media-types",
        "/paths/~1s/get/responses/200/content/text~1event-stream",
    ) in found


# ===========================================================================
# Verdicts
# ===========================================================================

_CALLBACK_DOCUMENT = {
    "openapi": "3.1.0",
    "info": {"title": "T", "version": "1"},
    "paths": {
        "/subscribe": {
            "post": {
                "callbacks": {
                    "onEvent": {
                        "{$request.body#/url}": {
                            "post": {"responses": {"200": {"description": "ok"}}}
                        }
                    }
                },
                "responses": {"201": {"description": "created"}},
            }
        }
    },
}


def test_a_preserved_construct_is_preserved() -> None:
    """The callback survives, so its occurrence is ``preserved``."""
    audit = audit_document("callbacks", _CALLBACK_DOCUMENT)
    verdicts = {o.construct: o.verdict for o in audit.occurrences}
    assert verdicts["callbacks"] == "preserved"
    assert audit.silent == []


def test_a_dropped_construct_without_a_loss_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """With source preservation switched off the callback vanishes unreported: ``silent``."""
    monkeypatch.setattr(openapi_emitter, "preserved_source", lambda api: None)
    audit = audit_document("callbacks", _CALLBACK_DOCUMENT)
    assert ("callbacks", "silent") in {(o.construct, o.verdict) for o in audit.occurrences}


def test_a_dropped_construct_with_a_loss_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a loss names the operation the callback sat on, the occurrence is ``reported``."""
    monkeypatch.setattr(openapi_emitter, "preserved_source", lambda api: None)
    original_emit = openapi_emitter.OpenApiEmitter.emit

    def emit_with_loss(self, api, *, opts=None):
        result = original_emit(self, api, opts=opts)
        loss = Loss(
            kind=LossKind.NA,
            subject="test-drop",
            detail="callbacks not written",
            pointer="#/paths/~1subscribe/post",
        )
        return result.model_copy(update={"losses": [*result.losses, loss]})

    monkeypatch.setattr(openapi_emitter.OpenApiEmitter, "emit", emit_with_loss)
    audit = audit_document("callbacks", _CALLBACK_DOCUMENT)
    callback = next(o for o in audit.occurrences if o.construct == "callbacks")
    assert callback.verdict == "reported"
    assert callback.loss and callback.loss.startswith("test-drop")


# ===========================================================================
# Rendering
# ===========================================================================


def test_render_has_one_row_per_construct_and_marks_inapplicable_cells() -> None:
    """The table has a row per construct; a construct absent from a version shows a dash."""
    markdown = render_matrix_markdown(build_matrix([]), corpus_counts={})
    rows = [line for line in markdown.splitlines() if line.startswith("| ") and "---" not in line]
    assert len(rows) == len(CONSTRUCTS) + 1  # plus the header
    self_row = next(row for row in rows if row.startswith("| `$self`"))
    assert self_row.count("| — ") == 2
    assert "Not covered" in self_row


def test_apply_requires_exactly_one_marker_pair() -> None:
    """A page without (or with duplicated) markers is refused, never half-rewritten."""
    with pytest.raises(ValueError):
        apply_construct_matrix("no markers here", [])
    with pytest.raises(ValueError):
        apply_construct_matrix(f"{BEGIN_MARKER}\n{END_MARKER}\n{BEGIN_MARKER}\n{END_MARKER}", [])


def test_apply_keeps_the_prose_around_the_region() -> None:
    """Only the generated region changes."""
    page = f"before\n\n{BEGIN_MARKER}\nold\n{END_MARKER}\n\nafter\n"
    applied = apply_construct_matrix(page, [])
    assert applied.startswith("before\n\n" + BEGIN_MARKER)
    assert applied.endswith(END_MARKER + "\n\nafter\n")
    assert "old" not in applied
