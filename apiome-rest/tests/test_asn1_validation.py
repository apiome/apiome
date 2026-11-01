"""Validate emitted ASN.1 with asn1tools — MFX-27.3 (#4165).

Every emitted module is parsed and compiled with asn1tools, and its type assignments must be exactly the emit
plan's (:mod:`app.asn1_validation`). Pinned here: the corpus fixtures pass, every kind of broken module is
rejected with a located, ruled finding, and a broken module fails the export job (``EMITTED_ARTIFACT_INVALID``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List
from unittest.mock import patch

import pytest

from app.asn1_emitter import asn1_type_plan
from app.asn1_validation import check_emitted_asn1
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitResult, coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_TARGET = "asn1"

#: Corpus sources of several kinds, each exported to ASN.1 and checked.
_CORPUS = [
    ("asn1/01-person.asn1", "asn1"),
    ("asn1/04-imports-reuse.asn1", "asn1"),
    ("asn1/05-stress-grammar.asn1", "asn1"),
    ("asn1/06-x509-certificate-shape.asn1", "asn1"),
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("json-schema/03-multiple-defs.json", "json-schema"),
    ("thrift/01-user-service.thrift", "thrift"),
]


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _source(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _widgets() -> CanonicalApi:
    """A ``Widget`` record (its ``owner`` an ``Owner``) and a ``Colour`` enum."""
    owner = Type(key="Owner", name="Owner", kind=TypeKind.RECORD,
                 fields=[CanonicalField(key="Owner.team", name="team", type=TypeRef(name="string"))])
    widget = Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Widget.owner", name="owner", type=TypeRef(name="Owner")),
    ])
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="Widgets"),
                        title="Widget", types=[owner, widget])


def _emit(api: CanonicalApi, **options: Any) -> EmitResult:
    emitter = get_emitter(_TARGET)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _with_text(result: EmitResult, text: str) -> EmitResult:
    return result.model_copy(update={"files": [result.files[0].model_copy(update={"content": text})]})


def _rules(problems: List[dict]) -> List[str]:
    return [problem["rule"] for problem in problems]


# ---------------------------------------------------------------------------
# The emit plan
# ---------------------------------------------------------------------------


def test_the_plan_names_every_type_with_the_titled_type_first() -> None:
    assert asn1_type_plan(_widgets()) == ["Widget", "Owner"]


@pytest.mark.parametrize("options", [{}, {"module_name": "Acme-Widgets"}, {"include_comments": False},
                                     {"automatic_tags": False}, {"oid": "{ 1 2 3 }"}])
def test_the_plan_matches_whatever_options_wrote_the_module(options: dict) -> None:
    """No option renames a type, so one plan checks every export of the model."""
    assert check_emitted_asn1(_emit(_widgets(), **options), _widgets()) == []


# ---------------------------------------------------------------------------
# Fixtures pass
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "fmt"), _CORPUS)
def test_every_corpus_export_compiles_with_the_planned_types(path: str, fmt: str) -> None:
    api = _source(path, fmt)
    assert check_emitted_asn1(_emit(api), api) == []


@pytest.mark.parametrize(("path", "fmt"), _CORPUS[:3])
async def test_the_gate_passes_the_corpus_exports(path: str, fmt: str) -> None:
    api = _source(path, fmt)
    verdict = await validate_emitted_artifact(_TARGET, _emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors


# ---------------------------------------------------------------------------
# Broken modules are rejected with detail
# ---------------------------------------------------------------------------


def test_a_syntax_error_is_a_located_parse_problem() -> None:
    result = _emit(_widgets())
    text = str(result.files[0].content).replace("SEQUENCE {", "SEQ {", 1)
    problems = check_emitted_asn1(_with_text(result, text), _widgets())
    assert _rules(problems) == ["asn1.parse"]
    assert problems[0]["line"] is not None and problems[0]["column"] is not None
    assert problems[0]["file"] == result.files[0].path


def test_a_reference_to_an_undefined_type_does_not_compile() -> None:
    result = _emit(_widgets())
    text = str(result.files[0].content).replace("owner Owner", "owner Missing", 1)
    assert "owner Missing" in text
    problems = check_emitted_asn1(_with_text(result, text), _widgets())
    assert _rules(problems) == ["asn1.compile"]
    assert "Missing" in problems[0]["message"]


def test_a_planned_type_missing_from_the_module_is_reported() -> None:
    """A model with a type the module does not assign: the emit plan is not what was written."""
    api = _widgets()
    stale = _emit(api.model_copy(update={"types": [t for t in api.types if t.name == "Widget"]}))
    text = str(stale.files[0].content).replace("owner Owner", "owner UTF8String", 1)
    problems = check_emitted_asn1(_with_text(stale, text), api)
    assert _rules(problems) == ["asn1.missing-type"]
    assert "'Owner'" in problems[0]["message"]


def test_an_assignment_the_plan_does_not_name_is_reported() -> None:
    result = _emit(_widgets())
    text = str(result.files[0].content).replace("END", "  Extra ::= INTEGER\n\nEND")
    problems = check_emitted_asn1(_with_text(result, text), _widgets())
    assert _rules(problems) == ["asn1.unexpected-type"]
    assert "'Extra'" in problems[0]["message"]


def test_a_second_module_is_reported() -> None:
    result = _emit(_widgets())
    text = str(result.files[0].content) + "\nOther DEFINITIONS ::= BEGIN\n  Thing ::= INTEGER\nEND\n"
    assert _rules(check_emitted_asn1(_with_text(result, text), _widgets())) == ["asn1.module-count"]


def test_an_export_with_no_module_is_reported() -> None:
    result = _emit(_widgets()).model_copy(update={"files": []})
    assert _rules(check_emitted_asn1(result, _widgets())) == ["asn1.module-count"]


async def test_the_gate_rejects_with_the_rule_and_location() -> None:
    result = _emit(_widgets())
    text = str(result.files[0].content).replace("SEQUENCE {", "SEQ {", 1)
    verdict = await validate_emitted_artifact(_TARGET, _with_text(result, text), api=_widgets())
    assert verdict.valid is False
    finding = verdict.findings[0]
    assert finding.keyword == "asn1.parse" and finding.line is not None and finding.file == result.files[0].path


# ---------------------------------------------------------------------------
# A non-compiling module fails the job
# ---------------------------------------------------------------------------


async def test_a_non_compiling_module_fails_the_export_job_with_detail() -> None:
    """MFX-27.3 acceptance: the job fails with ``EMITTED_ARTIFACT_INVALID`` and asn1tools' error."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _wait_terminal
    from test_export_job_engine import _source as _job_source

    source = _job_source()
    good = _emit(source.api)
    broken = _with_text(good, str(good.files[0].content).replace("UTF8String", "Missing", 1))
    request = ExportJobStartRequest(artifact="artifact-1", target=_TARGET, confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=source), patch(
        "app.export_job_engine.emit_canonical", side_effect=lambda *a, **k: broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    finding = status["error"]["context"]["findings"][0]
    assert finding["keyword"] == "asn1.compile" and "Missing" in finding["message"]
