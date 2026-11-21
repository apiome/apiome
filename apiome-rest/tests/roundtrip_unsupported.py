"""Round-trip matrix cells that are **deliberately** not run — COA-1.4 (#7040).

Each cell here is an export the product refuses by design, so there is nothing to round-trip:
the emitter rejects the source before writing anything, with the reason quoted below (for every
target but COBOL copybook, through source_unsupported_reason, so the export card is greyed out
with it). :mod: records these cells as unsupported with that reason instead of
listing them as strict xfails, and tests/test_roundtrip_matrix.py keeps the list honest: every
cell must still be refused, so a target that learns to export such a source fails the suite until
its cell is removed here and run for real.

Two families, both about Arazzo:

* **Types-only sources → Arazzo** (MFX-10.3, #3872): a schema-valid Arazzo document needs at least
  one workflow step, and a source of types or events has no operation to sequence.
* **Arazzo → targets that need what a workflow does not carry**: an HTTP binding (gateways, API
  clients, API Blueprint, Discovery), a record type (Arrow, COBOL, Orchestra, Kafka Connect, ODCS,
  SQL DDL), an event or type (xRegistry), or import-only extras (EDI X12, FIX, HL7 v2, IDoc,
  ISO 20022, ISO 8583, z/OS Connect).

A third family is the re-import triage of COA-3.3 (#7054):

* **Sources with nothing the target can hold → ASN.1, Avro, CDDL, FlatBuffers, XSD, WADL, RAML,
  Postman**: a source with no type (agent cards, gateway configurations, an Arazzo workflow) used to
  be written as an empty ASN.1 module, CDDL file, FlatBuffers schema or XSD, no .avsc at all, or
  a WADL / RAML document with no resource, and none of those read back. The target now refuses the
  source up front (requires_source); Postman already refused a source with no HTTP operation.
"""

from __future__ import annotations

from typing import Dict, Tuple

#: The reason every types-only source → Arazzo cell carries.
_NO_OPERATION_TO_SEQUENCE = (
    "Deliberate refusal (MFX-10.3, #3872; COA-1.4, #7040): Arazzo export needs at least one operation "
    "to sequence into a workflow, and this source has only types or events."
)


def _arazzo_source_refusal(message: str) -> str:
    """The reason for an Arazzo → target cell the target refuses, quoting the target's own message."""
    return (
        "Deliberate refusal (COA-1.4, #7040): an Arazzo source is workflow steps with no HTTP binding "
        f"and no types, and the target refuses it: {message}"
    )


def _reimport_triage_refusal(message: str) -> str:
    """The reason for a cell the target refuses because the source has nothing it can hold (COA-3.3)."""
    return f"Deliberate refusal (COA-3.3, #7054): the target refuses this source: {message}"

_ASN1_REFUSAL = _reimport_triage_refusal(
    'ASN.1 export needs at least one type; this source has none (only operations, agents or channels).'
)
_AVRO_REFUSAL = _reimport_triage_refusal(
    'Apache Avro schema export writes one .avsc per type, and this source has none; export Avro IDL (.avdl) to keep its operations.'
)
_CDDL_REFUSAL = _reimport_triage_refusal(
    'CDDL export needs at least one type; this source has none (only operations, agents or channels).'
)
_FLATBUFFERS_REFUSAL = _reimport_triage_refusal(
    'FlatBuffers export needs at least one type; this source has none (only operations, agents or channels).'
)
_POSTMAN_REFUSAL = _reimport_triage_refusal(
    'Postman export requires at least one HTTP operation: a collection is a set of saved requests, and a model with no HTTP binding has no request to save.'
)
_RAML_REFUSAL = _reimport_triage_refusal(
    'RAML export needs at least one HTTP operation or one type; this source has neither.'
)
_WADL_REFUSAL = _reimport_triage_refusal(
    'WADL export needs at least one HTTP operation or one type; this source has neither.'
)
_XSD_REFUSAL = _reimport_triage_refusal(
    'XSD export needs at least one type; this source has none (only operations, agents or channels).'
)

DELIBERATE_UNSUPPORTED_CELLS: Dict[Tuple[str, str], str] = {
    ('arrow', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('asn1', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('asyncapi', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('avro', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('cddl', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('cics-bms', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('cloudevents', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('cobolcopybook', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('cue', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('dbt', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('dhall', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('dicom', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('dtd', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('edifact', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('edix12', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('fix', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('fix-orchestra', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('flatbuffers', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('hl7v2', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('hl7v3', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('idoc', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('ims', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('iso20022', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('iso8583', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('json-schema', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('jsonld', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('jtd', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('k8s-crd', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('kafka-connect', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('nacha', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('natural-ddm', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('ncpdp', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('odcs', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('openapi', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('owl', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('pkl', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('pli', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('pydantic', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('relaxng', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('ros2', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('sepa', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('shacl', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('sparkplug', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('sql-ddl', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('swift-mt', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('tradacoms', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('typescript-types', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('vsam-idcams', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('xregistry', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('xsd', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('zod', 'arazzo'): _NO_OPERATION_TO_SEQUENCE,
    ('arazzo', 'apiblueprint'): _arazzo_source_refusal(
        'API Blueprint export needs at least one HTTP operation or one type; this source has neither.'
    ),
    ('arazzo', 'apigee'): _arazzo_source_refusal(
        'Apigee API proxy bundle export requires at least one HTTP operation: a gateway configuration is '
        'a routing surface, and a model with no operations has no route to declare.'
    ),
    ('arazzo', 'arrow'): _arazzo_source_refusal(
        'An Arrow schema is a table of columns, and this model has no record type.'
    ),
    ('arazzo', 'aws-apigateway'): _arazzo_source_refusal(
        'AWS API Gateway export requires at least one HTTP operation: a REST API integrates methods, and '
        'a model with none has nothing to integrate.'
    ),
    ('arazzo', 'azure-apim'): _arazzo_source_refusal(
        'Azure API Management export requires at least one HTTP operation: an APIM API is a set of HTTP '
        'operations, and a model with none has nothing to declare.'
    ),
    ('arazzo', 'bruno'): _arazzo_source_refusal(
        'Bruno export requires at least one HTTP operation: a collection is a set of saved requests, and '
        'a model with no HTTP binding has no request to save.'
    ),
    ('arazzo', 'cobolcopybook'): _arazzo_source_refusal(
        'COBOL copybook export lays out record types, and this model has none (only enums, scalars or '
        'operations).'
    ),
    ('arazzo', 'discovery'): _arazzo_source_refusal(
        'Google API Discovery export needs at least one HTTP operation or one type; this source has neither.'
    ),
    ('arazzo', 'edix12'): _arazzo_source_refusal(
        'EDI X12 export requires `x12_transactions` extras from import'
    ),
    ('arazzo', 'envoy-xds'): _arazzo_source_refusal(
        'Envoy RouteConfiguration export requires at least one HTTP operation: a gateway configuration is'
        ' a routing surface, and a model with no operations has no route to declare.'
    ),
    ('arazzo', 'fix'): _arazzo_source_refusal(
        'FIX export requires `fix_fields` extras from import'
    ),
    ('arazzo', 'fix-orchestra'): _arazzo_source_refusal(
        'An Orchestra repository describes messages, and this model has no record type.'
    ),
    ('arazzo', 'gateway-api'): _arazzo_source_refusal(
        'Gateway API export requires at least one HTTP operation: an HTTPRoute is a routing surface, and '
        'a model with no operations has no rule to declare (an HTTPRoute with no rules routes nothing).'
    ),
    ('arazzo', 'hl7v2'): _arazzo_source_refusal(
        'HL7 v2 export requires `hl7v2_segments` extras from import'
    ),
    ('arazzo', 'hoppscotch'): _arazzo_source_refusal(
        'Hoppscotch export requires at least one HTTP operation: a collection is a set of saved requests,'
        ' and a model with no HTTP binding has no request to save.'
    ),
    ('arazzo', 'http-file'): _arazzo_source_refusal(
        'HTTP request-file export requires at least one HTTP operation: a request file is a collection of'
        ' calls, and a model with no HTTP binding has no request to write.'
    ),
    ('arazzo', 'idoc'): _arazzo_source_refusal(
        'IDoc export requires `idoc_control` extras from import'
    ),
    ('arazzo', 'insomnia'): _arazzo_source_refusal(
        'Insomnia export requires at least one HTTP operation: a collection is a set of saved requests, '
        'and a model with no HTTP binding has no request to save.'
    ),
    ('arazzo', 'iso20022'): _arazzo_source_refusal(
        'ISO 20022 export requires `iso20022_tree` extras from import'
    ),
    ('arazzo', 'iso8583'): _arazzo_source_refusal(
        'ISO 8583 export requires `iso8583_data_elements` extras from import'
    ),
    ('arazzo', 'istio'): _arazzo_source_refusal(
        'Istio VirtualService export requires at least one HTTP operation: a gateway configuration is a '
        'routing surface, and a model with no operations has no route to declare.'
    ),
    ('arazzo', 'kafka-connect'): _arazzo_source_refusal(
        'Kafka Connect export requires at least one record type — a Connect schema describes a struct, '
        'and this model declares none.'
    ),
    ('arazzo', 'kong'): _arazzo_source_refusal(
        'Kong declarative export requires at least one HTTP operation: a declarative configuration is a '
        'routing surface, and a model with no operations has no route to declare (Kong rejects a config '
        'with none).'
    ),
    ('arazzo', 'odcs'): _arazzo_source_refusal(
        "ODCS export requires at least one record type — a data contract states a dataset's structure, "
        'and this model describes none'
    ),
    ('arazzo', 'postman'): _arazzo_source_refusal(
        'Postman export requires at least one HTTP operation: a collection is a set of saved requests, '
        'and a model with no HTTP binding has no request to save.'
    ),
    ('arazzo', 'sql-ddl'): _arazzo_source_refusal(
        'SQL DDL export lays out record types as tables, and this model has none (only enums, scalars or '
        'operations).'
    ),
    ('arazzo', 'thunder-client'): _arazzo_source_refusal(
        'Thunder Client export requires at least one HTTP operation: a collection is a set of saved '
        'requests, and a model with no HTTP binding has no request to save.'
    ),
    ('arazzo', 'traefik'): _arazzo_source_refusal(
        'Traefik dynamic configuration export requires at least one HTTP operation: a gateway '
        'configuration is a routing surface, and a model with no operations has no route to declare.'
    ),
    ('arazzo', 'xregistry'): _arazzo_source_refusal(
        'An xRegistry document holds schemas and event message definitions, and this model has neither a '
        'type nor an event (publish / subscribe) operation.'
    ),
    ('arazzo', 'zosconnect'): _arazzo_source_refusal(
        'z/OS Connect export requires `zosconnect_descriptor` extras from import'
    ),
    # --- COA-3.3 (#7054): sources with nothing the target can hold ---
    ('a2a', 'asn1'): _ASN1_REFUSAL,
    ('a2a', 'avro'): _AVRO_REFUSAL,
    ('a2a', 'cddl'): _CDDL_REFUSAL,
    ('a2a', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('a2a', 'postman'): _POSTMAN_REFUSAL,
    ('a2a', 'raml'): _RAML_REFUSAL,
    ('a2a', 'wadl'): _WADL_REFUSAL,
    ('a2a', 'xsd'): _XSD_REFUSAL,
    ('acp', 'asn1'): _ASN1_REFUSAL,
    ('acp', 'avro'): _AVRO_REFUSAL,
    ('acp', 'cddl'): _CDDL_REFUSAL,
    ('acp', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('acp', 'postman'): _POSTMAN_REFUSAL,
    ('acp', 'raml'): _RAML_REFUSAL,
    ('acp', 'wadl'): _WADL_REFUSAL,
    ('acp', 'xsd'): _XSD_REFUSAL,
    ('agents-manifest', 'asn1'): _ASN1_REFUSAL,
    ('agents-manifest', 'avro'): _AVRO_REFUSAL,
    ('agents-manifest', 'cddl'): _CDDL_REFUSAL,
    ('agents-manifest', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('agents-manifest', 'postman'): _POSTMAN_REFUSAL,
    ('agents-manifest', 'raml'): _RAML_REFUSAL,
    ('agents-manifest', 'wadl'): _WADL_REFUSAL,
    ('agents-manifest', 'xsd'): _XSD_REFUSAL,
    ('apigee', 'asn1'): _ASN1_REFUSAL,
    ('apigee', 'avro'): _AVRO_REFUSAL,
    ('apigee', 'cddl'): _CDDL_REFUSAL,
    ('apigee', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('apigee', 'xsd'): _XSD_REFUSAL,
    ('arazzo', 'asn1'): _ASN1_REFUSAL,
    ('arazzo', 'avro'): _AVRO_REFUSAL,
    ('arazzo', 'cddl'): _CDDL_REFUSAL,
    ('arazzo', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('arazzo', 'raml'): _RAML_REFUSAL,
    ('arazzo', 'wadl'): _WADL_REFUSAL,
    ('arazzo', 'xsd'): _XSD_REFUSAL,
    ('arrow', 'postman'): _POSTMAN_REFUSAL,
    ('asn1', 'postman'): _POSTMAN_REFUSAL,
    ('asyncapi', 'asn1'): _ASN1_REFUSAL,
    ('asyncapi', 'avro'): _AVRO_REFUSAL,
    ('asyncapi', 'cddl'): _CDDL_REFUSAL,
    ('asyncapi', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('asyncapi', 'postman'): _POSTMAN_REFUSAL,
    ('asyncapi', 'raml'): _RAML_REFUSAL,
    ('asyncapi', 'wadl'): _WADL_REFUSAL,
    ('asyncapi', 'xsd'): _XSD_REFUSAL,
    ('avro', 'postman'): _POSTMAN_REFUSAL,
    ('avro-idl', 'postman'): _POSTMAN_REFUSAL,
    ('azure-apim', 'asn1'): _ASN1_REFUSAL,
    ('azure-apim', 'avro'): _AVRO_REFUSAL,
    ('azure-apim', 'cddl'): _CDDL_REFUSAL,
    ('azure-apim', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('azure-apim', 'xsd'): _XSD_REFUSAL,
    ('capnproto', 'postman'): _POSTMAN_REFUSAL,
    ('cddl', 'postman'): _POSTMAN_REFUSAL,
    ('cics-bms', 'postman'): _POSTMAN_REFUSAL,
    ('cloudevents', 'postman'): _POSTMAN_REFUSAL,
    ('cobolcopybook', 'postman'): _POSTMAN_REFUSAL,
    ('connectrpc', 'postman'): _POSTMAN_REFUSAL,
    ('consul', 'asn1'): _ASN1_REFUSAL,
    ('consul', 'avro'): _AVRO_REFUSAL,
    ('consul', 'cddl'): _CDDL_REFUSAL,
    ('consul', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('consul', 'xsd'): _XSD_REFUSAL,
    ('corbaidl', 'postman'): _POSTMAN_REFUSAL,
    ('cue', 'postman'): _POSTMAN_REFUSAL,
    ('dbt', 'postman'): _POSTMAN_REFUSAL,
    ('dhall', 'postman'): _POSTMAN_REFUSAL,
    ('dicom', 'postman'): _POSTMAN_REFUSAL,
    ('dtd', 'postman'): _POSTMAN_REFUSAL,
    ('edifact', 'postman'): _POSTMAN_REFUSAL,
    ('edix12', 'postman'): _POSTMAN_REFUSAL,
    ('envoy-xds', 'asn1'): _ASN1_REFUSAL,
    ('envoy-xds', 'avro'): _AVRO_REFUSAL,
    ('envoy-xds', 'cddl'): _CDDL_REFUSAL,
    ('envoy-xds', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('envoy-xds', 'xsd'): _XSD_REFUSAL,
    ('fix', 'postman'): _POSTMAN_REFUSAL,
    ('fix-orchestra', 'postman'): _POSTMAN_REFUSAL,
    ('flatbuffers', 'postman'): _POSTMAN_REFUSAL,
    ('gateway-api', 'asn1'): _ASN1_REFUSAL,
    ('gateway-api', 'avro'): _AVRO_REFUSAL,
    ('gateway-api', 'cddl'): _CDDL_REFUSAL,
    ('gateway-api', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('gateway-api', 'xsd'): _XSD_REFUSAL,
    ('graphql', 'postman'): _POSTMAN_REFUSAL,
    ('haproxy', 'asn1'): _ASN1_REFUSAL,
    ('haproxy', 'avro'): _AVRO_REFUSAL,
    ('haproxy', 'cddl'): _CDDL_REFUSAL,
    ('haproxy', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('haproxy', 'xsd'): _XSD_REFUSAL,
    ('hl7v2', 'postman'): _POSTMAN_REFUSAL,
    ('hl7v3', 'postman'): _POSTMAN_REFUSAL,
    ('idoc', 'postman'): _POSTMAN_REFUSAL,
    ('ims', 'postman'): _POSTMAN_REFUSAL,
    ('iso20022', 'postman'): _POSTMAN_REFUSAL,
    ('iso8583', 'postman'): _POSTMAN_REFUSAL,
    ('istio', 'asn1'): _ASN1_REFUSAL,
    ('istio', 'avro'): _AVRO_REFUSAL,
    ('istio', 'cddl'): _CDDL_REFUSAL,
    ('istio', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('istio', 'xsd'): _XSD_REFUSAL,
    ('json-schema', 'postman'): _POSTMAN_REFUSAL,
    ('jsonld', 'postman'): _POSTMAN_REFUSAL,
    ('jtd', 'postman'): _POSTMAN_REFUSAL,
    ('k8s-crd', 'postman'): _POSTMAN_REFUSAL,
    ('kafka-connect', 'postman'): _POSTMAN_REFUSAL,
    ('kong', 'asn1'): _ASN1_REFUSAL,
    ('kong', 'avro'): _AVRO_REFUSAL,
    ('kong', 'cddl'): _CDDL_REFUSAL,
    ('kong', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('kong', 'xsd'): _XSD_REFUSAL,
    ('llm-tools', 'postman'): _POSTMAN_REFUSAL,
    ('lwm2m', 'postman'): _POSTMAN_REFUSAL,
    ('matter', 'postman'): _POSTMAN_REFUSAL,
    ('mcp', 'postman'): _POSTMAN_REFUSAL,
    ('nacha', 'postman'): _POSTMAN_REFUSAL,
    ('natural-ddm', 'postman'): _POSTMAN_REFUSAL,
    ('ncpdp', 'postman'): _POSTMAN_REFUSAL,
    ('nginx', 'asn1'): _ASN1_REFUSAL,
    ('nginx', 'avro'): _AVRO_REFUSAL,
    ('nginx', 'cddl'): _CDDL_REFUSAL,
    ('nginx', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('nginx', 'xsd'): _XSD_REFUSAL,
    ('odcs', 'postman'): _POSTMAN_REFUSAL,
    ('oncrpc', 'postman'): _POSTMAN_REFUSAL,
    ('opcua-nodeset', 'postman'): _POSTMAN_REFUSAL,
    ('openapi', 'postman'): _POSTMAN_REFUSAL,
    ('openrpc', 'postman'): _POSTMAN_REFUSAL,
    ('owl', 'postman'): _POSTMAN_REFUSAL,
    ('pkl', 'postman'): _POSTMAN_REFUSAL,
    ('pli', 'postman'): _POSTMAN_REFUSAL,
    ('protobuf', 'postman'): _POSTMAN_REFUSAL,
    ('protobuf-editions', 'postman'): _POSTMAN_REFUSAL,
    ('pydantic', 'postman'): _POSTMAN_REFUSAL,
    ('relaxng', 'postman'): _POSTMAN_REFUSAL,
    ('ros2', 'postman'): _POSTMAN_REFUSAL,
    ('sepa', 'postman'): _POSTMAN_REFUSAL,
    ('shacl', 'postman'): _POSTMAN_REFUSAL,
    ('smithy', 'postman'): _POSTMAN_REFUSAL,
    ('sparkplug', 'postman'): _POSTMAN_REFUSAL,
    ('sql-ddl', 'postman'): _POSTMAN_REFUSAL,
    ('swift-mt', 'postman'): _POSTMAN_REFUSAL,
    ('thrift', 'postman'): _POSTMAN_REFUSAL,
    ('tradacoms', 'postman'): _POSTMAN_REFUSAL,
    ('traefik', 'asn1'): _ASN1_REFUSAL,
    ('traefik', 'avro'): _AVRO_REFUSAL,
    ('traefik', 'cddl'): _CDDL_REFUSAL,
    ('traefik', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('traefik', 'xsd'): _XSD_REFUSAL,
    ('trpc', 'postman'): _POSTMAN_REFUSAL,
    ('tyk', 'asn1'): _ASN1_REFUSAL,
    ('tyk', 'avro'): _AVRO_REFUSAL,
    ('tyk', 'cddl'): _CDDL_REFUSAL,
    ('tyk', 'flatbuffers'): _FLATBUFFERS_REFUSAL,
    ('tyk', 'xsd'): _XSD_REFUSAL,
    ('typescript-types', 'postman'): _POSTMAN_REFUSAL,
    ('vsam-idcams', 'postman'): _POSTMAN_REFUSAL,
    ('wit', 'postman'): _POSTMAN_REFUSAL,
    ('wsdl', 'postman'): _POSTMAN_REFUSAL,
    ('wsdl2', 'postman'): _POSTMAN_REFUSAL,
    ('xmlrpc', 'postman'): _POSTMAN_REFUSAL,
    ('xregistry', 'postman'): _POSTMAN_REFUSAL,
    ('xsd', 'postman'): _POSTMAN_REFUSAL,
    ('zod', 'postman'): _POSTMAN_REFUSAL,
}
