"""OpenAPI documents are not misread as IDL formats by import detection.

Reported on 2026-10-25: importing ``apiome-rest/openapi.yaml`` was detected as **Thrift**. Two
defects combined, and a third made detection take minutes:

* The OpenAPI adapter recognised a document only after parsing it, so a document that did not
  parse — this one breaches ``INPUT_ENTITY_LIMIT`` — dropped out of detection altogether.
* The Thrift sniffer (and WIT, FlatBuffers, gRPC's keyword fallback, …) matched keywords anywhere
  in the text, so the indented prose line ``namespace to its primitives`` made the YAML "Thrift".
* The WIT sniffer read ``std/*`` in a description as an unclosed block comment, blanked the rest
  of the file and ran a quadratic ``^\\s*package`` scan over it.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.document_markers import looks_like_structured_document, top_level_api_marker
from app.flatbuffers_parser import is_flatbuffers
from app.format_detection import DetectionInput, detect_format
from app.intake_resource_guard import IntakeLimitError
from app.thrift_parser import is_thrift
from app.wit_parser import is_wit

_HEAD = "openapi: 3.0.3\ninfo:\n  title: Orders\n  version: 1.0.0\n"


def _detect(text: str, filename: str = "api.yaml"):
    return detect_format(DetectionInput(text=text, filename=filename))


# ---------------------------------------------------------------------------
# The markers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("openapi: 3.1.0\ninfo: {}\n", ("openapi", "3.1.0")),
        ("# generated\n---\nopenapi: '3.0.3'\n", ("openapi", "3.0.3")),
        ('\ufeffswagger: "2.0"\n', ("swagger", "2.0")),
        ("swaggerVersion: 1.2\napis: []\n", ("swaggerVersion", "1.2")),
        ('{\n  "openapi": "3.1.0",\n  "info": {}\n}', ("openapi", "3.1.0")),
        ("info:\n  openapi: 3.1.0\n", None),  # nested, not the document's marker
        ('namespace java com.acme\nstruct A { 1: i32 x }\n', None),
    ],
)
def test_top_level_api_marker(text, expected):
    assert top_level_api_marker(text) == expected


@pytest.mark.parametrize(
    "text, structured",
    [
        (_HEAD, True),
        ('{"a": 1}', True),
        ("[1, 2]", True),
        ("# comment\nkey: value\n", True),
        ('namespace java com.acme\n', False),
        ('include "shared.thrift"\n', False),
        ('const map<string,string> M = {"a": "b"}\n', False),
        ("package wasi:http@0.2.0;\n", False),
        ('syntax = "proto3";\n', False),
        ("table Monster { hp: short; }\n", False),
        ("{1:F01EXAMPLNL2AXXXX2381000050}{2:I103EXAMPUS44XXXXN}\n", False),  # SWIFT MT
        ("[\n  {\"a\": 1}\n]", True),
        ("", False),
    ],
)
def test_looks_like_structured_document(text, structured):
    assert looks_like_structured_document(text) is structured


# ---------------------------------------------------------------------------
# Prose in an OpenAPI document no longer reads as an IDL
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "body",
    [
        # The reported trigger: a folded description line beginning with "namespace".
        "paths: {}\ncomponents:\n  schemas:\n    Ns:\n      description: >-\n"
        "        Each tenant owns one\n        namespace to its primitives); only base URI\n",
        "paths: {}\n# service Orders { rpc Get() }\n",
        "paths: {}\n# struct Order { id }\n",
        "  description: 'typedef id is a string'\npaths: {}\n",
        "paths: {}\n# include \"shared.thrift\"\n",
    ],
)
def test_idl_words_in_a_valid_openapi_document_are_ignored(body):
    detection = _detect(_HEAD + body)

    assert detection.detected is not None
    assert detection.detected.format == "openapi-3.0"
    assert not detection.ambiguous
    assert all(c.format not in {"thrift", "flatbuffers", "wit", "protobuf"} for c in detection.candidates)


@pytest.mark.parametrize(
    "body",
    [
        # Unquoted colon in a scalar: invalid YAML, plus a Thrift keyword in a comment.
        "paths:\n  /a:\n    get:\n      summary: Note: see below\n# service Orders { }\n",
        # Tab indentation: invalid YAML, plus a FlatBuffers/Thrift keyword.
        "paths:\n\t/a: {}\n# struct Order { id }\n",
    ],
)
def test_an_openapi_document_that_does_not_parse_is_still_openapi(body):
    """The top-level marker claims it, so the import reports the YAML error, not a wrong format."""
    detection = _detect(_HEAD + body)

    assert detection.detected is not None
    assert detection.detected.format == "openapi-3.0"
    assert "did not fully parse" in detection.detected.reason
    assert not detection.ambiguous


def test_an_openapi_document_over_an_intake_limit_is_still_openapi():
    """The reported file breaches INPUT_ENTITY_LIMIT; detection must still name it OpenAPI."""
    text = "openapi: 3.1.0\ninfo:\n  title: Big\n  version: '1'\npaths: {}\n"

    def over_limit(*_args, **_kwargs):
        raise IntakeLimitError("too many entities", code="INPUT_ENTITY_LIMIT")

    with patch("app.openapi_import_source.parse_document", side_effect=over_limit), patch(
        "app.format_detection.parse_document", side_effect=over_limit
    ):
        detection = _detect(text, "openapi.yaml")

    assert detection.detected is not None
    assert detection.detected.format == "openapi-3.1"


# ---------------------------------------------------------------------------
# Real IDL sources are still recognised
# ---------------------------------------------------------------------------
def test_real_thrift_is_still_thrift():
    source = (
        "namespace java com.acme.orders\n"
        'include "shared.thrift"\n\n'
        "struct Order {\n  1: required string id\n}\n\n"
        "service Orders {\n  Order get(1: string id)\n}\n"
    )
    assert is_thrift(source)
    # Thrift keeps its full-confidence candidate. (Smithy's sniffer ties it at 0.95 on this
    # sample, as it does on main — a separate issue, not this fix's.)
    candidates = {c.format: c.confidence for c in _detect(source, "orders.thrift").candidates}
    assert candidates.get("thrift") == 0.95


def test_a_thrift_namespace_line_alone_is_still_thrift():
    assert is_thrift("namespace py acme.orders\n")
    assert is_thrift("namespace * acme ; // all languages\n")
    assert not is_thrift("namespace to its primitives); only base URI, version root\n")


def test_real_wit_and_flatbuffers_are_still_recognised():
    assert is_wit("package acme:orders@1.0.0;\n\ninterface api {\n  get: func(id: string);\n}\n")
    assert is_flatbuffers("namespace Acme;\ntable Order { id: string; }\nroot_type Order;\n")


def test_proto_keywords_still_detect_a_proto_file_without_syntax():
    detection = _detect("message Order {\n  string id = 1;\n}\n", "orders.proto")
    assert detection.detected is not None
    assert detection.detected.format == "protobuf"


# ---------------------------------------------------------------------------
# Speed on large documents
# ---------------------------------------------------------------------------
def test_wit_sniffing_a_large_document_with_an_unclosed_comment_is_linear():
    """``std/*`` opens a "comment" the WIT stripper never closes; the scan must stay linear."""
    text = "notes: 'see std/*'\n" + ("   \n" * 200_000)
    started = time.monotonic()
    assert not is_wit(text)
    # Structured documents are rejected before stripping; prove the regex path is linear too.
    assert not is_wit("see std/*\n" + ("   \n" * 200_000))
    assert time.monotonic() - started < 5.0


def test_a_failed_parse_is_not_repeated_for_the_same_text():
    from app import import_ingestion

    calls = []

    def failing(text, *, source_label=None):
        calls.append(source_label)
        raise IntakeLimitError("too many entities", code="INPUT_ENTITY_LIMIT")

    import_ingestion._LAST_FAILURE = None
    text = "openapi: 3.1.0\n" + "x: 1\n" * 10
    with patch.object(import_ingestion, "_parse_document_uncached", side_effect=failing):
        for label in ("a.yaml", None, "a.yaml"):
            with pytest.raises(IntakeLimitError):
                import_ingestion.parse_document(text, source_label=label)
        with pytest.raises(IntakeLimitError):
            import_ingestion.parse_document(text + "y: 2\n", source_label="a.yaml")
    import_ingestion._LAST_FAILURE = None

    assert len(calls) == 2  # once for the text, once for the different text
