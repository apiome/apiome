"""Tests for MFI-1.5 format auto-detection (#3737).

Each listed format must auto-route to the right detector from a representative
fixture; ambiguous inputs must be flagged so the importer can prompt the user.
"""

import pytest

from app.format_detection import (
    DEFAULT_AMBIGUITY_MARGIN,
    SNIFFED_FORMATS,
    FormatCandidate,
    _dedupe_by_format,
    detect_format,
)
from app.import_source import DetectionInput

# Minimal, representative fixtures keyed by the format they should detect.
_FIXTURES = {
    "raml": "#%RAML 1.0\ntitle: My API\n",
    "api-blueprint": "FORMAT: 1A\n\n# My API\n\n## GET /thing\n",
    "protobuf": 'syntax = "proto3";\npackage foo;\nmessage M { string id = 1; }\n',
    "graphql": "type Query {\n  hello: String\n}\n",
    "wsdl": (
        '<?xml version="1.0"?>\n'
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">'
        "</wsdl:definitions>"
    ),
    "wadl": (
        '<?xml version="1.0"?>\n'
        '<application xmlns="http://wadl.dev.java.net/2009/02">'
        "<resources base=\"https://api.example.com/\"><resource path=\"items\">"
        "<method name=\"GET\"/></resource></resources></application>"
    ),
    "odata": (
        '<edmx:Edmx Version="4.0" '
        'xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx"></edmx:Edmx>'
    ),
    "smithy": '$version: "2.0"\nnamespace com.example\nservice Foo { version: "1" }\n',
    "typespec": 'import "@typespec/http";\nnamespace Demo;\nmodel Pet { name: string; }\n',
    "asyncapi-2": "asyncapi: 2.6.0\ninfo:\n  title: x\n  version: 1.0.0\n",
    "arazzo": (
        "arazzo: 1.0.1\ninfo:\n  title: My Workflow\n  version: 1.0.0\n"
        "sourceDescriptions:\n  - name: api\n    url: ./openapi.yaml\n    type: openapi\n"
    ),
    "avro": '{"type": "record", "name": "User", "fields": [{"name": "id", "type": "string"}]}',
    "openrpc": (
        '{"openrpc":"1.2.6","info":{"title":"Wallet API","version":"1.0.0"},'
        '"methods":[{"name":"getBalance"}]}'
    ),
    "xmlrpc": (
        '<?xml version="1.0"?>\n'
        "<methodCall><methodName>ping</methodName><params></params></methodCall>"
    ),
    "xsd": (
        '<?xml version="1.0"?>\n'
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:simpleType name="Code"><xs:restriction base="xs:string"/></xs:simpleType>'
        "</xs:schema>"
    ),
    "postman": (
        '{"info":{"name":"Tasks API","schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},'
        '"item":[{"name":"Ping","request":{"method":"GET","url":{"raw":"{{baseUrl}}/ping","path":["ping"]}}}]}'
    ),
    "cloudevents": (
        '{"specversion":"1.0","id":"evt-1","type":"com.example.order.created",'
        '"source":"/orders/service","data":{"orderId":"abc"}}'
    ),
}


@pytest.mark.parametrize("expected_format,text", list(_FIXTURES.items()))
def test_each_format_fixture_auto_routes(expected_format: str, text: str) -> None:
    detection = detect_format(DetectionInput(text=text))
    assert detection.matched, f"{expected_format} fixture was not recognized"
    assert detection.detected is not None
    assert detection.detected.format == expected_format
    assert not detection.ambiguous, f"{expected_format} should be an unambiguous match"


def test_sniffed_formats_cover_every_fixture() -> None:
    # Every format a fixture targets is in the declared sniffer catalogue.
    assert set(_FIXTURES) <= SNIFFED_FORMATS
    assert "asyncapi-3" in SNIFFED_FORMATS


def test_asyncapi_v3_detected_distinctly() -> None:
    detection = detect_format(
        DetectionInput(text="asyncapi: 3.0.0\ninfo:\n  title: x\n  version: 1.0.0\n")
    )
    assert detection.detected is not None
    assert detection.detected.format == "asyncapi-3"


def test_arazzo_detected_by_version_marker() -> None:
    # MFI-26.6 (#4101): an Arazzo workflow document is named by its `arazzo:` version
    # marker so the §0.3 routing policy can send it to the publishable Projects path
    # instead of letting it fall through to the catalog.
    detection = detect_format(DetectionInput(text=_FIXTURES["arazzo"]))
    assert detection.detected is not None
    assert detection.detected.format == "arazzo"
    assert not detection.ambiguous


def test_arazzo_detected_from_parsed_document() -> None:
    detection = detect_format(
        DetectionInput(document={"arazzo": "1.0.1", "info": {"title": "x"}})
    )
    assert detection.detected is not None
    assert detection.detected.format == "arazzo"


def test_openapi_routes_to_importable_adapter() -> None:
    detection = detect_format(
        DetectionInput(text='{"openapi": "3.1.0", "info": {}, "paths": {}}')
    )
    assert detection.detected is not None
    assert detection.detected.format == "openapi-3.1"
    # The OpenAPI adapter exists today, so this match is importable.
    assert detection.detected.importable is True
    assert detection.detected.source_key == "openapi"


def test_sniffed_formats_are_not_importable_yet() -> None:
    # TypeSpec is still sniffer-only (its adapter lands in a later epic).
    detection = detect_format(DetectionInput(text=_FIXTURES["typespec"]))
    assert detection.detected is not None
    assert detection.detected.format == "typespec"
    assert detection.detected.importable is False
    assert detection.detected.source_key is None


def test_odata_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["odata"]))
    assert detection.detected is not None
    assert detection.detected.format == "odata"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "odata"


def test_raml_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text="#%RAML 1.0\ntitle: Example\nbaseUri: https://api.example.com\n/books:\n  get:\n"))
    assert detection.detected is not None
    assert detection.detected.format == "raml"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "raml"


def test_wadl_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["wadl"]))
    assert detection.detected is not None
    assert detection.detected.format == "wadl"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "wadl"


def test_avro_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["avro"]))
    assert detection.detected is not None
    assert detection.detected.format == "avro"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "avro"


def test_openrpc_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["openrpc"]))
    assert detection.detected is not None
    assert detection.detected.format == "openrpc"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "openrpc"


def test_xmlrpc_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["xmlrpc"]))
    assert detection.detected is not None
    assert detection.detected.format == "xmlrpc"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "xmlrpc"


def test_xsd_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["xsd"]))
    assert detection.detected is not None
    assert detection.detected.format == "xsd"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "xsd"


def test_postman_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["postman"]))
    assert detection.detected is not None
    assert detection.detected.format == "postman"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "postman"


def test_oncrpc_is_now_importable() -> None:
    detection = detect_format(
        DetectionInput(
            text=(
                "program DEMO {\n"
                "    version VERS {\n"
                "        int PING(void) = 1;\n"
                "    } = 1;\n"
                "} = 1;\n"
            )
        )
    )
    assert detection.detected is not None
    assert detection.detected.format == "oncrpc"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "oncrpc"


def test_corbaidl_is_now_importable() -> None:
    detection = detect_format(
        DetectionInput(
            text=(
                "module Demo {\n"
                "  interface Ping {\n"
                "    long echo(in long value);\n"
                "  };\n"
                "};\n"
            )
        )
    )
    assert detection.detected is not None
    assert detection.detected.format == "corbaidl"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "corbaidl"


def test_edix12_is_now_importable() -> None:
    detection = detect_format(
        DetectionInput(
            text=(
                "ISA*00*          *00*          *ZZ*SENDERID       *ZZ*RECEIVERID     "
                "*260115*0830*U*00401*000000001*0*P*>~\n"
                "GS*PO*SENDERID*RECEIVERID*20260115*0830*1*X*004010~\n"
                "ST*850*0001~\n"
                "SE*2*0001~\n"
                "GE*1*1~\n"
                "IEA*1*000000001~\n"
            )
        )
    )
    assert detection.detected is not None
    assert detection.detected.format == "edix12"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "edix12"


def test_asn1_is_now_importable() -> None:
    detection = detect_format(
        DetectionInput(
            text=(
                "PersonModule DEFINITIONS AUTOMATIC TAGS ::= BEGIN\n"
                "  Status ::= ENUMERATED { active(0) }\n"
                "END\n"
            )
        )
    )
    assert detection.detected is not None
    assert detection.detected.format == "asn1"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "asn1"


def test_smithy_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["smithy"]))
    assert detection.detected is not None
    assert detection.detected.format == "smithy"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "smithy"


def test_api_blueprint_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["api-blueprint"]))
    assert detection.detected is not None
    assert detection.detected.format == "api-blueprint"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "apiblueprint"


def test_cloudevents_is_now_importable() -> None:
    detection = detect_format(DetectionInput(text=_FIXTURES["cloudevents"]))
    assert detection.detected is not None
    assert detection.detected.format == "cloudevents"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "cloudevents"


def test_protobuf_is_now_importable() -> None:
    # MFI-9.6 registered the gRPC / Protobuf adapter, so a .proto is recognized *and* importable.
    detection = detect_format(DetectionInput(text=_FIXTURES["protobuf"]))
    assert detection.detected is not None
    assert detection.detected.format == "protobuf"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "grpc"


def test_graphql_is_now_importable() -> None:
    # MFI-10.6 registered the GraphQL adapter, so SDL is recognized *and* importable.
    detection = detect_format(DetectionInput(text=_FIXTURES["graphql"]))
    assert detection.detected is not None
    assert detection.detected.format == "graphql"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "graphql"


def test_parsed_document_is_sniffed_like_raw_text() -> None:
    # AsyncAPI supplied as a pre-parsed document (no raw text) still detects.
    detection = detect_format(
        DetectionInput(document={"asyncapi": "2.0.0", "info": {"title": "x"}})
    )
    assert detection.detected is not None
    assert detection.detected.format == "asyncapi-2"


def test_bare_namespace_is_ambiguous_between_smithy_and_typespec() -> None:
    detection = detect_format(DetectionInput(text="namespace com.example.bare\n"))
    assert detection.ambiguous is True
    formats = {c.format for c in detection.ambiguous_candidates}
    assert formats == {"smithy", "typespec"}
    # The leading candidate is still reported (the caller prompts among the close set).
    assert detection.detected is not None
    assert detection.detected.format in formats


def test_unrecognized_input_does_not_match() -> None:
    detection = detect_format(DetectionInput(text="just some prose with no markers"))
    assert detection.matched is False
    assert detection.detected is None
    assert detection.candidates == []
    assert detection.ambiguous is False


def test_empty_payload_does_not_match() -> None:
    assert detect_format(DetectionInput()).matched is False


def test_candidates_are_ranked_by_confidence_then_format() -> None:
    # protobuf (0.97) outranks graphql (0.9) when a document carries both markers.
    text = 'syntax = "proto3";\ntype Query {\n  hello: String\n}\n'
    detection = detect_format(DetectionInput(text=text))
    assert detection.detected is not None
    assert detection.detected.format == "protobuf"
    ordered = [c.confidence for c in detection.candidates]
    assert ordered == sorted(ordered, reverse=True)


def test_ambiguity_margin_is_respected() -> None:
    # A clear winner (protobuf 0.97) over a much weaker signal is not ambiguous.
    detection = detect_format(DetectionInput(text=_FIXTURES["protobuf"]))
    assert detection.ambiguous is False
    assert DEFAULT_AMBIGUITY_MARGIN > 0


def test_dedupe_keeps_strongest_and_prefers_importable() -> None:
    weaker_sniffer = FormatCandidate(
        format="openapi-3.1", confidence=0.6, reason="sniffer", source_key=None, importable=False
    )
    adapter_match = FormatCandidate(
        format="openapi-3.1", confidence=0.99, reason="adapter", source_key="openapi", importable=True
    )
    deduped = _dedupe_by_format([weaker_sniffer, adapter_match])
    assert len(deduped) == 1
    assert deduped[0].importable is True
    assert deduped[0].confidence == 0.99


def test_dedupe_prefers_importable_on_confidence_tie() -> None:
    sniffer = FormatCandidate(
        format="x", confidence=0.8, reason=None, source_key=None, importable=False
    )
    adapter = FormatCandidate(
        format="x", confidence=0.8, reason=None, source_key="x", importable=True
    )
    deduped = _dedupe_by_format([sniffer, adapter])
    assert len(deduped) == 1
    assert deduped[0].importable is True
