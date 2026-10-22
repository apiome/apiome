# Corpus parity report

<!-- GENERATED FILE — do not edit by hand. -->
<!-- Regenerate with: cd apiome-rest && uv run python scripts/generate_corpus_parity_report.py -->

Every shipped, non-preview import adapter must carry four artifacts: corpus examples (at least one valid and one negative), a golden snapshot directory, a round-trip matrix row, and a `format_capability_registry` entry. This report is what the FMT-1.4 parity gate (`apiome-rest/tests/test_corpus_parity.py`) asserts.

- **Formats gated:** 78
- **Formats with an unwaived gap:** 0
- **Formats with a waived requirement:** 0

## Fixture counts

| Format | Label | Paradigm | Valid | Negative | Adversarial | Scale | Total | Rungs | Goldens | Emitter |
|---|---|---|---:|---:|---:|---:|---:|---|---:|---|
| `a2a` | A2A Agent Card | agent | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | — |
| `acp` | ACP Agent Manifest | agent | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | — |
| `agents-manifest` | Agentic-web Site Manifest | agent | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | — |
| `apiblueprint` | API Blueprint | rest | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `apiblueprint` |
| `apigee` | Apigee proxy bundle | rest | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | `apigee` |
| `arazzo` | Arazzo | rest | 14 | 11 | 0 | 0 | 25 | 6/6 | 13 | `arazzo` |
| `arrow` | Apache Arrow | data_schema | 10 | 7 | 0 | 0 | 17 | 6/6 | 9 | — |
| `asn1` | ASN.1 | data_schema | 7 | 5 | 0 | 0 | 12 | 5/6 (+1 waived) | 6 | `asn1` |
| `asyncapi` | AsyncAPI | event | 9 | 5 | 0 | 0 | 14 | 6/6 | 7 | `asyncapi` |
| `avro` | Avro | data_schema | 14 | 11 | 0 | 0 | 25 | 6/6 | 12 | `avro` |
| `aws-apigateway` | AWS API Gateway | rest | 8 | 5 | 0 | 0 | 13 | 6/6 | 7 | `aws-apigateway` |
| `azure-apim` | Azure API Management | rest | 8 | 6 | 0 | 0 | 14 | 6/6 | 7 | `azure-apim` |
| `capnproto` | Cap'n Proto | rpc | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `capnproto` |
| `cddl` | CDDL | data_schema | 8 | 6 | 0 | 0 | 14 | 6/6 | 7 | `cddl` |
| `cloudevents` | CloudEvents | event | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 5 | `cloudevents` |
| `cobolcopybook` | COBOL Copybook | data_schema | 8 | 5 | 0 | 0 | 13 | 5/6 (+1 waived) | 8 | `cobolcopybook` |
| `connectrpc` | Connect RPC | rpc | 7 | 5 | 0 | 0 | 12 | 6/6 | 6 | `connectrpc` |
| `consul` | Consul service definitions | rest | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `corbaidl` | CORBA IDL | rpc | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `corbaidl` |
| `dbt` | dbt Project | data_schema | 10 | 6 | 0 | 0 | 16 | 6/6 | 7 | — |
| `dicom` | DICOM | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `discovery` | Google API Discovery | rest | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | — |
| `dtd` | DTD | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `edifact` | UN/EDIFACT | data_schema | 10 | 7 | 0 | 0 | 17 | 6/6 | 9 | — |
| `edix12` | EDI X12 | data_schema | 7 | 5 | 0 | 0 | 12 | 5/6 (+1 waived) | 7 | `edix12` |
| `envoy-xds` | Envoy xDS routes | rest | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | `envoy-xds` |
| `fhir` | FHIR | rest | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `fhir` |
| `fix` | FIX | data_schema | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 7 | `fix` |
| `fix-orchestra` | FIX Orchestra | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 14 | — |
| `flatbuffers` | FlatBuffers | data_schema | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `flatbuffers` |
| `gateway-api` | Gateway API HTTPRoute | rest | 8 | 5 | 0 | 0 | 13 | 6/6 | 6 | `gateway-api` |
| `graphql` | GraphQL | graph | 18 | 5 | 0 | 0 | 23 | 6/6 | 14 | `graphql` |
| `grpc` | gRPC / Protobuf | rpc | 18 | 13 | 0 | 0 | 31 | 6/6 | 16 | `protobuf` |
| `haproxy` | HAProxy configuration | rest | 10 | 6 | 0 | 0 | 16 | 6/6 | 8 | — |
| `hl7v2` | HL7 v2 | data_schema | 6 | 5 | 0 | 0 | 11 | 4/6 (+2 waived) | 6 | `hl7v2` |
| `hl7v3` | HL7 v3 / CDA | data_schema | 8 | 6 | 0 | 0 | 14 | 6/6 | 7 | — |
| `http-file` | HTTP Request File | rest | 10 | 5 | 0 | 0 | 15 | 6/6 | 8 | `http-file` |
| `idoc` | SAP IDoc | data_schema | 8 | 6 | 0 | 0 | 14 | 6/6 | 7 | `idoc` |
| `iso20022` | ISO 20022 | data_schema | 14 | 11 | 1 | 0 | 26 | 6/6 | 13 | `iso20022` |
| `iso8583` | ISO 8583 | data_schema | 6 | 5 | 0 | 0 | 11 | 4/6 (+2 waived) | 6 | `iso8583` |
| `istio` | Istio VirtualService | rest | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | `istio` |
| `json-schema` | JSON Schema | data_schema | 12 | 5 | 0 | 0 | 17 | 5/6 (+1 waived) | 12 | `json-schema` |
| `jtd` | JSON Type Definition | data_schema | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `jtd` |
| `k8s-crd` | Kubernetes CRD | data_schema | 7 | 5 | 0 | 0 | 12 | 5/6 (+1 waived) | 7 | `k8s-crd` |
| `kafka-connect` | Kafka Connect Schema | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | `kafka-connect` |
| `kong` | Kong Declarative Config | rest | 7 | 5 | 0 | 0 | 12 | 6/6 | 6 | `kong` |
| `llm-tools` | LLM Tools | agent | 8 | 5 | 0 | 0 | 13 | 5/6 (+1 waived) | 8 | `llm-tools` |
| `mcp` | MCP Server Manifest | agent | 7 | 5 | 0 | 0 | 12 | 6/6 | 6 | — |
| `nacha` | NACHA ACH | data_schema | 8 | 6 | 0 | 0 | 14 | 6/6 | 7 | — |
| `ncpdp` | NCPDP SCRIPT / Telecom | data_schema | 8 | 6 | 0 | 0 | 14 | 6/6 | 7 | — |
| `nginx` | nginx configuration | rest | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `odata` | OData | rest | 14 | 11 | 1 | 0 | 26 | 6/6 | 13 | `odata` |
| `odcs` | ODCS Data Contract | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | `odcs` |
| `oncrpc` | ONC RPC | rpc | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `oncrpc` |
| `openapi` | OpenAPI / Swagger | rest | 47 | 12 | 0 | 0 | 59 | 6/6 | 42 | `openapi` |
| `openrpc` | OpenRPC | rpc | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `openrpc` |
| `postman` | Postman | rest | 13 | 11 | 0 | 0 | 24 | 6/6 | 12 | `postman` |
| `pydantic` | Pydantic models | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `raml` | RAML | rest | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `raml` |
| `relaxng` | RELAX NG | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `smithy` | Smithy | rpc | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `smithy` |
| `sql-ddl` | SQL DDL | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `swift-mt` | SWIFT MT | data_schema | 8 | 6 | 0 | 0 | 14 | 6/6 | 7 | — |
| `thrift` | Thrift | rpc | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `thrift` |
| `tradacoms` | TRADACOMS | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 8 | — |
| `traefik` | Traefik dynamic config | rest | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | `traefik` |
| `trpc` | tRPC router | rpc | 10 | 6 | 0 | 0 | 16 | 6/6 | 7 | — |
| `tyk` | Tyk API definition | rest | 8 | 6 | 0 | 0 | 14 | 6/6 | 7 | — |
| `typescript-types` | TypeScript types | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `typespec` | TypeSpec | rest | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `typespec` |
| `wadl` | WADL | rest | 6 | 5 | 1 | 0 | 12 | 5/6 (+1 waived) | 6 | `wadl` |
| `wit` | WIT (WebAssembly) | rpc | 11 | 5 | 0 | 0 | 16 | 6/6 | 9 | `wit` |
| `wsdl` | WSDL | rest | 13 | 11 | 2 | 0 | 26 | 6/6 | 12 | `wsdl` |
| `xmlrpc` | XML-RPC | rpc | 6 | 5 | 2 | 0 | 13 | 5/6 (+1 waived) | 6 | `xmlrpc` |
| `xregistry` | CNCF xRegistry | event | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | — |
| `xsd` | XSD | data_schema | 6 | 5 | 2 | 0 | 13 | 5/6 (+1 waived) | 6 | `xsd` |
| `zod` | Zod schemas | data_schema | 9 | 6 | 0 | 0 | 15 | 6/6 | 7 | — |
| `zosconnect` | z/OS Connect | rest | 6 | 5 | 0 | 0 | 11 | 5/6 (+1 waived) | 6 | `zosconnect` |

## Required artifacts

✅ present · ⚠️ waived with a reason · ❌ missing (this is what fails the gate).

| Format | Valid examples | Negative examples | Golden snapshots | Round-trip row | Capability entry |
|---|:-:|:-:|:-:|:-:|:-:|
| `a2a` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `acp` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `agents-manifest` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `apiblueprint` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `apigee` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `arazzo` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `arrow` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `asn1` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `asyncapi` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `avro` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `aws-apigateway` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `azure-apim` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `capnproto` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cddl` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cloudevents` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `cobolcopybook` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `connectrpc` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `consul` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `corbaidl` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dbt` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dicom` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `discovery` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dtd` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `edifact` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `edix12` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `envoy-xds` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `fhir` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `fix` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `fix-orchestra` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `flatbuffers` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `gateway-api` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `graphql` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `grpc` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `haproxy` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `hl7v2` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `hl7v3` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `http-file` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `idoc` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `iso20022` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `iso8583` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `istio` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `json-schema` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `jtd` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `k8s-crd` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `kafka-connect` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `kong` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `llm-tools` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `mcp` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `nacha` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ncpdp` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `nginx` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `odata` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `odcs` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `oncrpc` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `openapi` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `openrpc` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `postman` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `pydantic` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `raml` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `relaxng` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `smithy` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `sql-ddl` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `swift-mt` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `thrift` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `tradacoms` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `traefik` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `trpc` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `tyk` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `typescript-types` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `typespec` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `wadl` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `wit` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `wsdl` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `xmlrpc` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `xregistry` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `xsd` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `zod` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `zosconnect` | ✅ | ✅ | ✅ | ✅ | ✅ |

## Gaps

None — every gated format carries all four artifacts.

## Waived requirements

None.

## Not gated

| Registry key | Why it is exempt |
|---|---|
| `sample` | internal machinery, not a format a user can import |

## Corpus directories awaiting an adapter

Fixtures staged ahead of the adapter that will claim them (`adapter_key: null`). They are not gated until an adapter registers, at which point every requirement above applies.

`cics-bms`, `cue`, `dhall`, `hoppscotch`, `ims`, `jsonld`, `lwm2m`, `matter`, `natural-ddm`, `opcua-nodeset`, `owl`, `pkl`, `pli`, `ros2`, `schematron`, `shacl`, `soapui`, `sparkplug`, `thunder-client`, `vsam-idcams`
