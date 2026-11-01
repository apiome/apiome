"""ASN.1 target card + fixtures — MFX-27.4 (#4166).

What the ``asn1`` export target shows and writes, pinned in ``fixtures/asn1_target/outcomes.json``
(regenerate with ``APIOME_REGEN_ASN1_TARGET=1``):

* **the card** — the tier the Export dialog, browse and ``apiome export targets`` draw for a source of each
  kind (:func:`app.export_routes.build_target_fidelity_entries`). ASN.1 is a types-only target, so a REST,
  RPC, GraphQL, JSON Schema, WSDL or RAML source badges ``types-only``; an imported ASN.1 module badges
  ``lossless``;
* **the fixture cases** — ``fixtures/asn1_target/constrained-devices.yaml`` (an OpenAPI schema set) is written
  with **constrained strings** (``UTF8String (SIZE (8..16))``, a ``pattern`` as ``(FROM ("A".."Z"))``),
  **ranges** (``INTEGER (1..65535)``, ``REAL (0..1)``, ``SEQUENCE (SIZE (1..4)) OF``) and a **CHOICE** for its
  ``oneOf``; the corpus ``05-stress-grammar.asn1`` round-trips its own ``CHOICE``;
* **the options** — ``include_comments`` and ``automatic_tags`` (both default on), ``module_name`` and ``oid``.
  Every pinned choice passes the export gate's check (:func:`app.asn1_validation.check_emitted_asn1`:
  asn1tools parse + compile, the planned type inventory);
* **browse** — the public ``…/document`` route delivers the ``.asn1`` itself;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-asn1.json`` and
  ``apiome-ui/tests/fixtures/export-targets-asn1-{rest,asn1}.json`` carry the live descriptor, options schema,
  defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-asn1-types-only.json`` carries the
  live fidelity summary and file name of the Petstore export.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.asn1_validation import check_emitted_asn1
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_FIXTURES = _TESTS / "fixtures" / "asn1_target"
_GOLDEN = _FIXTURES / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_CLI_TARGETS = _CLI_FIXTURES / "export-targets-asn1.json"
_CLI_JOB = _CLI_FIXTURES / "export-job-completed-asn1-types-only.json"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_ASN1_TARGET"))
_TARGET = "asn1"

#: One corpus source per kind, the ASN.1 cases and the constrained fixture: the file and its format. Every
#: one imports without an external toolchain, so the fixture is reproducible on any machine.
SOURCES: Dict[str, tuple[Path, str]] = {
    "rest": (_EXAMPLES / "openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "rpc": (_EXAMPLES / "thrift/01-user-service.thrift", "thrift"),
    "graphql": (_EXAMPLES / "graphql/06-union-types.graphql", "graphql"),
    "json-schema": (_EXAMPLES / "json-schema/03-multiple-defs.json", "json-schema"),
    "wsdl": (_EXAMPLES / "wsdl/02-order-service.wsdl", "wsdl"),
    "raml": (_EXAMPLES / "raml/03-orders-service.raml", "raml"),
    "asn1": (_EXAMPLES / "asn1/01-person.asn1", "asn1"),
    "asn1-choice": (_EXAMPLES / "asn1/05-stress-grammar.asn1", "asn1"),
    "constrained": (_FIXTURES / "constrained-devices.yaml", "openapi"),
}

#: The kinds that are not ASN.1 sources: ASN.1 keeps only their types.
NON_ASN1_KINDS = ("rest", "rpc", "graphql", "json-schema", "wsdl", "raml", "constrained")

#: The option choices pinned, and the emit options that pick each.
OPTIONS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "no-comments": {"include_comments": False},
    "explicit-tags": {"automatic_tags": False},
    "module-name": {"module_name": "Acme-Devices"},
    "oid": {"oid": "1.3.6.1.4.1.99999.1"},
}

#: The sources whose exports are pinned for every option choice.
OPTION_SOURCES = ("rest", "asn1", "constrained")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _source(kind: str) -> Any:
    file, fmt = SOURCES[kind]
    if not file.is_file():
        pytest.skip(f"corpus file {file} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _card(api: Any) -> Any:
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == _TARGET)


def _emit(api: Any, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(_TARGET)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _header(text: str) -> str:
    """The module header line (``Name [OID] DEFINITIONS [TAGS] ::= BEGIN``)."""
    return next(line for line in text.splitlines() if "DEFINITIONS" in line)


def _assignments(text: str) -> List[str]:
    """Every ``Name ::= …`` and member line of the module, stripped — the shape the fixture pins."""
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("--") and "DEFINITIONS" not in line
            and line.strip() != "END"]


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its files, tier, preserved share, and what the module carries."""
    result = _emit(api, options)
    text = str(result.files[0].content)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    return {
        "files": [emitted.path for emitted in result.files],
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "problems": [problem["rule"] for problem in check_emitted_asn1(result, api)],
        "header": _header(text),
        "header_comment": text.startswith("--"),
    }


def _measure() -> Dict[str, Any]:
    return {
        "cards": {kind: {"available": _card(_source(kind)).descriptor.available,
                         "tier": _card(_source(kind)).fidelity.tier.value} for kind in SOURCES},
        "options": {kind: {choice: _outcome(_source(kind), options) for choice, options in OPTIONS.items()}
                    for kind in OPTION_SOURCES},
        "modules": {kind: _assignments(str(_emit(_source(kind), {}).files[0].content))
                    for kind in ("constrained", "asn1-choice")},
    }


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the ASN.1 target."""
    return {"artifact": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "version": "1.0.0",
            "targets": [_card(_source(kind)).model_dump(mode="json")]}


def _check_recorded(path: Path, live: Dict[str, Any]) -> None:
    """``path`` holds ``live`` (written first under regen); skipped when that package is not checked out."""
    if _REGEN and path.parent.is_dir():
        path.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    if not path.is_file():
        pytest.skip(f"{path.parent} is not checked out")
    assert json.loads(path.read_text(encoding="utf-8")) == live


def test_the_outcomes_match_the_fixture() -> None:
    measured = _measure()
    if _REGEN:
        _GOLDEN.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(_GOLDEN.read_text(encoding="utf-8"))


def test_the_cli_targets_fixture_is_the_live_registry() -> None:
    _check_recorded(_CLI_TARGETS, _targets_body("rest"))


@pytest.mark.parametrize("kind", ["rest", "asn1"])
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-asn1-{kind}.json", _targets_body(kind))


def test_the_cli_job_fixture_carries_the_live_fidelity_and_file() -> None:
    """The completed-job envelope the CLI tests replay reports what the Petstore export really is."""
    if not _CLI_JOB.is_file():
        pytest.skip(f"{_CLI_JOB.parent} is not checked out")
    api = _source("rest")
    job = json.loads(_CLI_JOB.read_text(encoding="utf-8"))["result"]
    live = build_export_fidelity(api, get_emitter(_TARGET)).summary.model_dump(mode="json")
    assert job["fidelity"]["summary"] == live
    assert [row["path"] for row in job["files"]] == [emitted.path for emitted in _emit(api, {}).files]


@pytest.mark.parametrize("kind", SOURCES)
def test_every_source_is_offered_as_a_single_file_target(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available is True and card.descriptor.multi_file is False


@pytest.mark.parametrize("kind", NON_ASN1_KINDS)
def test_a_non_asn1_source_badges_types_only(kind: str) -> None:
    assert _card(_source(kind)).fidelity.tier.value == "types-only"


@pytest.mark.parametrize("kind", ["asn1", "asn1-choice"])
def test_an_imported_asn1_module_badges_lossless(kind: str) -> None:
    assert _card(_source(kind)).fidelity.tier.value == "lossless"


def test_constrained_strings_ranges_and_choice_are_written_as_subtype_notation() -> None:
    lines = _assignments(str(_emit(_source("constrained"), {}).files[0].content))
    assert "serial UTF8String (SIZE (8..16))," in lines
    assert 'model UTF8String (SIZE (1..MAX)) (FROM ("A".."Z")),' in lines
    assert "port INTEGER (1..65535)," in lines
    assert "ratio REAL (0..1) OPTIONAL," in lines
    assert "tags SEQUENCE (SIZE (1..4)) OF UTF8String OPTIONAL" in lines
    assert "Address ::= CHOICE {" in lines


def test_an_asn1_choice_round_trips() -> None:
    assert "Payload ::= CHOICE {" in _assignments(str(_emit(_source("asn1-choice"), {}).files[0].content))


@pytest.mark.parametrize("choice", OPTIONS)
@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_each_option_choice_writes_a_module_the_gate_accepts(kind: str, choice: str) -> None:
    outcome = _outcome(_source(kind), OPTIONS[choice])
    assert outcome["problems"] == []
    assert [path.rsplit(".", 1)[-1] for path in outcome["files"]] == ["asn1"]
    assert outcome["header_comment"] is (choice != "no-comments")
    assert ("AUTOMATIC TAGS" in outcome["header"]) is (choice != "explicit-tags" or kind == "asn1")


def test_the_module_name_and_oid_options_head_the_module() -> None:
    api = _source("constrained")
    assert _outcome(api, OPTIONS["module-name"])["header"].startswith("Acme-Devices DEFINITIONS")
    assert re.match(r"\S+ \{.*\} DEFINITIONS", _outcome(api, OPTIONS["oid"])["header"])


def test_the_options_are_in_the_descriptor() -> None:
    card = _card(_source("rest"))
    assert set(card.options_schema["properties"]) == {"automatic_tags", "include_comments", "module_name", "oid"}
    assert card.default_options == {"automatic_tags": True, "include_comments": True, "module_name": None,
                                    "oid": None}


def test_browse_delivers_the_asn1_module_itself() -> None:
    response = render_emitted_document(_source("constrained"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type != "application/zip"
    assert response.headers["content-disposition"].endswith('.asn1"')
    assert "DEFINITIONS AUTOMATIC TAGS ::= BEGIN" in response.body.decode("utf-8")


@pytest.mark.parametrize("kind", OPTION_SOURCES)
def test_the_validation_gate_passes_the_default_export(kind: str) -> None:
    """The MFX-27.3 gate: asn1tools parse + compile, and the planned type inventory."""
    api = _source(kind)
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, _emit(api, {}), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid, verdict.errors
