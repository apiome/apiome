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
}
