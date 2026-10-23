/**
 * Official technical documentation URLs for catalog import formats (MFI-23.12).
 *
 * The supported-formats gallery links each importable card to the authoritative spec or reference
 * for that format. Keys are canonical {@link CatalogFormat.id} values from
 * {@link catalog-format-registry}.
 */

/** Official documentation URL per importable catalog format id. */
export const CATALOG_FORMAT_DOCUMENTATION_URL: Readonly<Record<string, string>> = {
  // RPC
  grpc: 'https://grpc.io/docs/',
  protobuf: 'https://protobuf.dev/overview/',
  thrift: 'https://thrift.apache.org/docs/',
  ros2: 'https://docs.ros.org/en/rolling/Concepts/Basic/About-Interfaces.html',
  connectrpc: 'https://connectrpc.com/docs/introduction',
  capnproto: 'https://capnproto.org/language.html',
  wit: 'https://component-model.bytecodealliance.org/design/wit.html',
  flatbuffers: 'https://flatbuffers.dev/docs/',
  corbaidl: 'https://www.omg.org/spec/IDL/',
  oncrpc: 'https://datatracker.ietf.org/doc/html/rfc5531',
  xmlrpc: 'https://xmlrpc.com/spec',
  openrpc: 'https://spec.open-rpc.org/',

  // Graph
  graphql: 'https://spec.graphql.org/',

  // Event
  asyncapi: 'https://www.asyncapi.com/docs/reference/specification/latest',
  cloudevents: 'https://cloudevents.io/',
  xregistry: 'https://xregistry.io/',
  sparkplug: 'https://sparkplug.eclipse.org/specification/',

  // REST (non-OpenAPI)
  raml: 'https://raml.org/specs/300',
  postman: 'https://schema.getpostman.com/json/collection/v2.1.0/docs/index.html',
  hoppscotch: 'https://docs.hoppscotch.io/documentation/features/collections',
  'thunder-client': 'https://docs.thunderclient.com/features/collections',
  soapui: 'https://www.soapui.org/docs/soap-and-wsdl/working-with-wsdls/',
  'http-file': 'https://www.jetbrains.com/help/idea/exploring-http-syntax.html',
  kong: 'https://docs.konghq.com/gateway/latest/production/deployment-topologies/db-less-and-declarative-config/',
  'gateway-api': 'https://gateway-api.sigs.k8s.io/api-types/httproute/',
  odata: 'https://www.odata.org/documentation/',
  wsdl: 'https://www.w3.org/TR/wsdl',
  wadl: 'https://www.w3.org/Submission/wadl/',
  discovery: 'https://developers.google.com/discovery/v1/reference',
  apiblueprint: 'https://apiblueprint.org/documentation/specification.html',
  smithy: 'https://smithy.io/2.0/spec/index.html',
  typespec: 'https://typespec.io/docs',

  // Workflows
  arazzo: 'https://spec.openapis.org/arazzo/latest.html',

  // Agent
  'llm-tools': 'https://platform.openai.com/docs/guides/function-calling',
  a2a: 'https://a2a-protocol.org/latest/specification/',
  acp: 'https://agentcommunicationprotocol.dev/',
  'agents-manifest': 'https://agents-txt.com/',
  mcp: 'https://modelcontextprotocol.io/specification/2025-06-18/server',

  // Data schema
  jsonschema: 'https://json-schema.org/draft/2020-12/json-schema-core',
  'k8s-crd':
    'https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/',
  avro: 'https://avro.apache.org/docs/current/specification/',
  jtd: 'https://www.rfc-editor.org/rfc/rfc8927',
  xsd: 'https://www.w3.org/TR/xmlschema11-1/',
  dtd: 'https://www.w3.org/TR/xml/#dt-doctype',
  shacl: 'https://www.w3.org/TR/shacl/',
  owl: 'https://www.w3.org/TR/owl2-overview/',
  jsonld: 'https://www.w3.org/TR/json-ld11/',
  relaxng: 'https://relaxng.org/spec-20011203.html',
  asn1: 'https://www.itu.int/rec/T-REC-X.680',
  cddl: 'https://www.rfc-editor.org/rfc/rfc8610',
  arrow: 'https://arrow.apache.org/docs/format/Columnar.html',
  'sql-ddl': 'https://www.iso.org/standard/76583.html',
  'typescript-types': 'https://www.typescriptlang.org/docs/handbook/declaration-files/introduction.html',
  zod: 'https://v3.zod.dev/',
  trpc: 'https://trpc.io/docs/server/routers',
  'opcua-nodeset': 'https://reference.opcfoundation.org/Core/Part6/v105/docs/F',
  lwm2m: 'https://www.openmobilealliance.org/specifications/registries/objects',
  matter: 'https://csa-iot.org/developer-resource/specifications-download-request/',
  pydantic: 'https://docs.pydantic.dev/latest/concepts/models/',
  cue: 'https://cuelang.org/docs/reference/spec/',
  pkl: 'https://pkl-lang.org/main/current/language-reference/index.html',
  dhall: 'https://docs.dhall-lang.org/',
  dbt: 'https://docs.getdbt.com/reference/configs-and-properties',
  odcs: 'https://bitol-io.github.io/open-data-contract-standard/latest/',
  'kafka-connect': 'https://kafka.apache.org/documentation/#connect_schemas',
  cobolcopybook: 'https://www.ibm.com/docs/en/cobol-zos/latest?topic=programs-copybook',
  'vsam-idcams': 'https://www.ibm.com/docs/en/zos/latest?topic=commands-define-cluster',
  'cics-bms': 'https://www.ibm.com/docs/en/cics-ts/latest?topic=programs-basic-mapping-support',

  // Healthcare
  dicom: 'https://www.dicomstandard.org/current',
  ncpdp: 'https://standards.ncpdp.org/',
  fhir: 'https://hl7.org/fhir/R4/',
  hl7v2: 'https://www.hl7.org/implement/standards/product_brief.cfm?product_id=185',
  hl7v3: 'https://www.hl7.org/implement/standards/product_brief.cfm?product_id=7',

  // Finance / B2B
  edix12: 'https://x12.org/products/industry-data-standards',
  edifact: 'https://unece.org/trade/uncefact/introducing-unedifact',
  tradacoms: 'https://www.gs1uk.org/knowledge-hub/standards/can-gs1-uk-support-me-with-tradacoms',
  nacha: 'https://www.nacha.org/rules',
  idoc: 'https://help.sap.com/docs/SAP_ERP/7792d36f3fe04f5fb52bf0d7ee565a06/840cc253d0a4b54ce10000000a174cb4.html',
  iso20022: 'https://www.iso20022.org/iso-20022-message-definitions',
  'swift-mt': 'https://www.swift.com/standards',
  iso8583: 'https://www.iso.org/standard/31628.html',
  fix: 'https://www.fixtrading.org/standards/',
  'fix-orchestra': 'https://www.fixtrading.org/standards/fix-orchestra/',

  // Mainframe
  zosconnect: 'https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=apis-creating-api',
};

/** Resolve the official technical documentation URL for a catalog format id, if known. */
export function catalogFormatDocumentationUrl(formatId: string): string | undefined {
  return CATALOG_FORMAT_DOCUMENTATION_URL[formatId];
}
