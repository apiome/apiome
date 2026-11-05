/**
 * The Export dialog's mocked registry (MFX-6.x), shared by `tests/ExportDialog.test.tsx` and the
 * RC6-H2 dialog fixture dumps (`tests/rc6-dialog-fixtures.test.tsx`), so both draw the same dialog.
 */
import { jest } from '@jest/globals';

import type { ExportTargetsResponse } from '../../src/app/components/ade/dashboard/export/exportTargetCatalog';
import type { ExportFidelityEnvelope } from '../../src/app/components/ade/dashboard/export/exportFidelityPreview';
import jsonSchemaTargetsForRest from '../fixtures/export-targets-json-schema-rest.json';
import jsonSchemaTargetsForJsonSchema from '../fixtures/export-targets-json-schema-json-schema.json';
import copybookTargetsForRest from '../fixtures/export-targets-copybook-rest.json';
import copybookTargetsForCopybook from '../fixtures/export-targets-copybook-copybook.json';
import x12GuideTargetsForRest from '../fixtures/export-targets-x12-guide-rest.json';
import x12GuideTargetsForX12 from '../fixtures/export-targets-x12-guide-x12.json';
import edifactGuideTargetsForRest from '../fixtures/export-targets-edifact-guide-rest.json';
import edifactGuideTargetsForEdifact from '../fixtures/export-targets-edifact-guide-edifact.json';
import hl7v2GuideTargetsForRest from '../fixtures/export-targets-hl7v2-guide-rest.json';
import hl7v2GuideTargetsForHl7v2 from '../fixtures/export-targets-hl7v2-guide-hl7v2.json';
import wsdlTargetsForRest from '../fixtures/export-targets-wsdl-rest.json';
import wsdlTargetsForWsdl from '../fixtures/export-targets-wsdl-wsdl.json';
import wadlTargetsForRest from '../fixtures/export-targets-wadl-rest.json';
import wadlTargetsForWadl from '../fixtures/export-targets-wadl-wadl.json';
import discoveryTargetsForRest from '../fixtures/export-targets-discovery-rest.json';
import discoveryTargetsForDiscovery from '../fixtures/export-targets-discovery-discovery.json';
import typespecTargetsForRest from '../fixtures/export-targets-typespec-rest.json';
import typespecTargetsForTypespec from '../fixtures/export-targets-typespec-typespec.json';
import odataTargetsForRest from '../fixtures/export-targets-odata-rest.json';
import odataTargetsForOdata from '../fixtures/export-targets-odata-odata.json';
import ramlTargetsForRest from '../fixtures/export-targets-raml-rest.json';
import ramlTargetsForRaml from '../fixtures/export-targets-raml-raml.json';
import ramlTargetsForGraphql from '../fixtures/export-targets-raml-graphql.json';
import ramlPreviewForGraphql from '../fixtures/export-preview-raml-graphql.json';
import apiblueprintTargetsForRest from '../fixtures/export-targets-apiblueprint-rest.json';
import apiblueprintTargetsForApiblueprint from '../fixtures/export-targets-apiblueprint-apiblueprint.json';
import smithyTargetsForRest from '../fixtures/export-targets-smithy-rest.json';
import smithyTargetsForSmithy from '../fixtures/export-targets-smithy-smithy.json';
import xsdTargetsForRest from '../fixtures/export-targets-xsd-rest.json';
import xsdTargetsForXsd from '../fixtures/export-targets-xsd-xsd.json';
import thriftTargetsForRest from '../fixtures/export-targets-thrift-rest.json';
import thriftTargetsForThrift from '../fixtures/export-targets-thrift-thrift.json';
import asn1TargetsForRest from '../fixtures/export-targets-asn1-rest.json';
import asn1TargetsForAsn1 from '../fixtures/export-targets-asn1-asn1.json';
import corbaidlTargetsForRest from '../fixtures/export-targets-corbaidl-rest.json';
import corbaidlTargetsForCorbaidl from '../fixtures/export-targets-corbaidl-corbaidl.json';
import flatbuffersTargetsForRest from '../fixtures/export-targets-flatbuffers-rest.json';
import flatbuffersTargetsForFlatbuffers from '../fixtures/export-targets-flatbuffers-flatbuffers.json';
import capnprotoTargetsForRest from '../fixtures/export-targets-capnproto-rest.json';
import capnprotoTargetsForCapnproto from '../fixtures/export-targets-capnproto-capnproto.json';
import openrpcTargetsForRest from '../fixtures/export-targets-openrpc-rest.json';
import openrpcTargetsForOpenrpc from '../fixtures/export-targets-openrpc-openrpc.json';
import arazzoTargetsForRest from '../fixtures/export-targets-arazzo-rest.json';
import arazzoTargetsForArazzo from '../fixtures/export-targets-arazzo-arazzo.json';
import arazzoTargetsForData from '../fixtures/export-targets-arazzo-data.json';
import mcpTargetsForRest from '../fixtures/export-targets-mcp-rest.json';
import mcpTargetsForMcp from '../fixtures/export-targets-mcp-mcp.json';
import mcpTargetsForData from '../fixtures/export-targets-mcp-data.json';
import a2aTargetsForRest from '../fixtures/export-targets-a2a-rest.json';
import a2aTargetsForA2a from '../fixtures/export-targets-a2a-a2a.json';
import a2aTargetsForData from '../fixtures/export-targets-a2a-data.json';
import xregistryTargetsForRest from '../fixtures/export-targets-xregistry-rest.json';
import xregistryTargetsForXregistry from '../fixtures/export-targets-xregistry-xregistry.json';
import xregistryTargetsForGateway from '../fixtures/export-targets-xregistry-gateway.json';
import sqlDdlTargetsForRest from '../fixtures/export-targets-sql-ddl-rest.json';
import sqlDdlTargetsForSql from '../fixtures/export-targets-sql-ddl-sql.json';
import sqlDdlTargetsForGateway from '../fixtures/export-targets-sql-ddl-gateway.json';
import arrowTargetsForRest from '../fixtures/export-targets-arrow-rest.json';
import arrowTargetsForArrow from '../fixtures/export-targets-arrow-arrow.json';
import arrowTargetsForGateway from '../fixtures/export-targets-arrow-gateway.json';
import icebergTargetsForRest from '../fixtures/export-targets-iceberg-rest.json';
import icebergTargetsForGateway from '../fixtures/export-targets-iceberg-gateway.json';
import fixOrchestraTargetsForRest from '../fixtures/export-targets-fix-orchestra-rest.json';
import fixOrchestraTargetsForOrchestra from '../fixtures/export-targets-fix-orchestra-orchestra.json';
import fixOrchestraTargetsForGateway from '../fixtures/export-targets-fix-orchestra-gateway.json';

/** A three-target registry: lossless OpenAPI, lossy Protobuf (with options), unavailable Avro. */
export const EXPORT_DIALOG_TARGETS: ExportTargetsResponse = {
  artifact: 'proj-petstore',
  version: null,
  version_record_id: 'rev-1',
  version_label: '1.2.0',
  targets: [
    {
      descriptor: {
        key: 'avro',
        format: 'avro-1.12',
        label: 'Avro',
        description: 'Export record schemas to Avro.',
        icon: 'layers',
        paradigm: 'data',
        multi_file: false,
        needs_toolchain: true,
        available: false,
        unavailable_reason: 'Requires the avro toolchain, which is not available in this runtime.',
      },
      capability_profile: {},
      options_schema: {},
      default_options: {},
      fidelity: {
        tier: 'types-only',
        preserved_percent: 31,
        total: 58,
        preserved: 18,
        dropped: 38,
        approximated: 2,
        synthesized: 0,
      },
    },
    {
      descriptor: {
        key: 'openapi',
        format: 'openapi-3.1',
        label: 'OpenAPI 3.1',
        description: 'Export the canonical model as an OpenAPI 3.1 document.',
        icon: 'file-json',
        paradigm: 'rest',
        multi_file: false,
        needs_toolchain: false,
        available: true,
        unavailable_reason: null,
      },
      capability_profile: { operations: true },
      options_schema: {},
      default_options: {},
      fidelity: {
        tier: 'lossless',
        preserved_percent: 100,
        total: 58,
        preserved: 58,
        dropped: 0,
        approximated: 0,
        synthesized: 0,
      },
    },
    {
      descriptor: {
        key: 'proto',
        format: 'proto-3',
        label: 'gRPC / Protobuf',
        description: 'Export services and messages as a .proto file.',
        icon: 'binary',
        paradigm: 'rpc',
        multi_file: false,
        needs_toolchain: false,
        available: true,
        unavailable_reason: null,
      },
      capability_profile: { operations: true },
      options_schema: {
        properties: {
          emit_services: {
            type: 'boolean',
            default: true,
            title: 'Emit Services',
            description: 'Emit service/rpc blocks.',
          },
          package: {
            anyOf: [{ type: 'string' }, { type: 'null' }],
            default: null,
            title: 'Package',
          },
        },
        type: 'object',
      },
      default_options: { emit_services: true, package: null },
      fidelity: {
        tier: 'lossy',
        preserved_percent: 64,
        total: 58,
        preserved: 51,
        dropped: 3,
        approximated: 2,
        synthesized: 2,
      },
    },
  ],
};

/** One API-client collection target, as the registry lists it for a REST source (MFX-31.5). */
function collectionTarget(
  key: string,
  label: string,
  description: string,
  multiFile: boolean,
  options: Record<string, unknown>,
  preserved: number,
): ExportTargetsResponse['targets'][number] {
  return {
    descriptor: {
      key,
      format: key,
      label,
      description,
      icon: key === 'postman' ? 'file-json' : 'send',
      paradigm: 'rest',
      multi_file: multiFile,
      needs_toolchain: false,
      available: true,
      unavailable_reason: null,
    },
    capability_profile: { operations: true, events: false, unions: false },
    options_schema: { type: 'object', properties: options },
    default_options: Object.fromEntries(
      Object.entries(options).map(([name, schema]) => [name, (schema as { default?: unknown }).default]),
    ),
    fidelity: {
      tier: 'lossy',
      preserved_percent: Math.round((preserved / 58) * 100),
      total: 58,
      preserved,
      dropped: 6,
      approximated: 58 - preserved - 9,
      synthesized: 3,
    },
  };
}

const FOLDER_STRATEGY = {
  type: 'string',
  enum: ['tag', 'auto', 'service', 'flat'],
  default: 'tag',
  title: 'Folder Strategy',
  description: 'How requests are filed into folders.',
};
const EXAMPLE_DEPTH = {
  type: 'string',
  enum: ['minimal', 'full'],
  default: 'minimal',
  title: 'Example Depth',
  description: 'Example bodies fill required properties only, or every property.',
};

/**
 * The API-client collection targets of a REST version (MFX-31.3 / MFX-31.5): Postman with its
 * `flavor` option, Insomnia (one file) and Bruno (a multi-file zip) — each lossy, with its tier.
 */
export const EXPORT_DIALOG_COLLECTION_TARGETS: ExportTargetsResponse = {
  ...EXPORT_DIALOG_TARGETS,
  targets: [
    collectionTarget(
      'postman',
      'Postman',
      'Export as a Postman Collection v2.1 with synthesized example bodies and responses.',
      false,
      {
        folder_strategy: { ...FOLDER_STRATEGY, enum: ['auto', 'tag', 'service', 'flat'], default: 'auto' },
        example_depth: EXAMPLE_DEPTH,
        flavor: {
          type: 'string',
          enum: ['postman', 'insomnia', 'bruno'],
          default: 'postman',
          title: 'Flavor',
          description: 'The collection format written: Postman, an Insomnia v4 export or a Bruno collection.',
        },
      },
      41,
    ),
    collectionTarget(
      'insomnia',
      'Insomnia',
      'Export as an Insomnia v4 export: a workspace with one request per operation.',
      false,
      { folder_strategy: FOLDER_STRATEGY, example_depth: EXAMPLE_DEPTH },
      38,
    ),
    collectionTarget(
      'bruno',
      'Bruno',
      'Export as a Bruno collection, delivered as a zip: bruno.json and one .bru file per operation.',
      true,
      { folder_strategy: FOLDER_STRATEGY, example_depth: EXAMPLE_DEPTH },
      38,
    ),
  ],
};

/**
 * The JSON Schema family (`json-schema` + `jtd`) as the registry lists it (MFX-21.5, #4130), for a
 * REST source and for a JSON Schema item. Both JSON files are recorded from the live REST registry by
 * `apiome-rest/tests/test_jsonschema_target_card.py`, which fails when they drift.
 *
 * @param source `rest` (the Petstore OpenAPI: its operations are dropped, so `types-only`) or
 *   `json-schema` (a JSON Schema item exported again: `lossless`).
 * @returns The targets response the dialog's targets route serves.
 */
export function jsonSchemaTargets(source: 'rest' | 'json-schema'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? jsonSchemaTargetsForRest : jsonSchemaTargetsForJsonSchema);
}

/**
 * The COBOL copybook target as the registry lists it (MFX-23.5, #4143), for a REST source and for a
 * copybook item — recorded from the live REST registry by `apiome-rest/tests/test_copybook_target_card.py`.
 *
 * @param source `rest` (an OpenAPI order API: operations dropped, lengths and names synthesized, so
 *   `types-only`) or `copybook` (a copybook item exported again: `lossless`).
 * @returns The targets response the dialog's targets route serves.
 */
export function copybookTargets(source: 'rest' | 'copybook'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? copybookTargetsForRest : copybookTargetsForCopybook);
}

/**
 * The X12 implementation-guide target as the registry lists it (MFX-24.5, #4149), for a REST source and
 * for an imported X12 850 — recorded from the live REST registry by
 * `apiome-rest/tests/test_x12_guide_target_card.py`. A guide invents lengths, codes and segment IDs, so
 * both are `types-only`.
 *
 * @param source `rest` (the Petstore OpenAPI) or `x12` (an imported X12 850 purchase order).
 * @returns The targets response the dialog's targets route serves.
 */
export function x12GuideTargets(source: 'rest' | 'x12'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? x12GuideTargetsForRest : x12GuideTargetsForX12);
}

/**
 * The UN/EDIFACT message-guide target as the registry lists it (MFX-24.2, #4146), for a REST source and for an
 * imported EDIFACT ORDERS message — recorded from the live REST registry by
 * `apiome-rest/tests/test_edifact_guide_target_card.py`. Like the X12 guide, both are `types-only`.
 *
 * @param source `rest` (the Petstore OpenAPI) or `edifact` (an imported EDIFACT ORDERS message).
 * @returns The targets response the dialog's targets route serves.
 */
export function edifactGuideTargets(source: 'rest' | 'edifact'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? edifactGuideTargetsForRest : edifactGuideTargetsForEdifact);
}

/**
 * The HL7 v2 segment-guide target as the registry lists it (MFX-26.3, #4159), for a REST source and for an
 * imported HL7 v2 ADT^A01 message — recorded from the live REST registry by
 * `apiome-rest/tests/test_hl7v2_guide_target_card.py`. Like the X12 and EDIFACT guides, both are `types-only`.
 *
 * @param source `rest` (the Petstore OpenAPI) or `hl7v2` (an imported HL7 v2 ADT^A01 message).
 * @returns The targets response the dialog's targets route serves.
 */
export function hl7v2GuideTargets(source: 'rest' | 'hl7v2'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? hl7v2GuideTargetsForRest : hl7v2GuideTargetsForHl7v2);
}

/**
 * The dialog's registry with its targets replaced by ones recorded from the live REST registry.
 *
 * @param recorded A recorded `GET …/export/targets` body (its `targets` list is what is used).
 * @returns The targets response the dialog's targets route serves.
 */
function recordedTargets(recorded: { targets: unknown[] }): ExportTargetsResponse {
  return {
    ...EXPORT_DIALOG_TARGETS,
    targets: recorded.targets as unknown as ExportTargetsResponse['targets'],
  };
}

/** The MFX-6.2 dry-run previews (advisory + per-construct report) per selectable target. */
export const EXPORT_DIALOG_PREVIEWS: Record<string, ExportFidelityEnvelope> = {
  proto: {
    target: EXPORT_DIALOG_TARGETS.targets[2].descriptor,
    summary: EXPORT_DIALOG_TARGETS.targets[2].fidelity,
    report: {
      items: [
        {
          construct: 'User.name',
          kind: 'ok',
          severity: 'info',
          message: 'Carried faithfully.',
          target_mapping: null,
        },
        {
          construct: 'User.email',
          kind: 'drop',
          severity: 'warn',
          message: 'The email format constraint is unrepresentable in proto3.',
          target_mapping: null,
        },
        {
          construct: 'GET /pets/{id}',
          kind: 'approx',
          severity: 'warn',
          message: 'Query parameters become request-message fields.',
          target_mapping: 'query parameter → request message field',
        },
      ],
      kind_counts: { drop: 1, approx: 1, synth: 0, ok: 1 },
      severity_counts: { info: 1, warn: 2, critical: 0 },
    },
    advisory: {
      show: true,
      severity: 'warn',
      requires_ack: false,
      target_format: 'gRPC / Protobuf',
      dropped: 3,
      approximated: 2,
      synthesized: 2,
      affected: 7,
      headline: 'This export loses fidelity',
      message: 'Exporting to gRPC / Protobuf may lose some fidelity: 7 constructs affected.',
    },
  },
  openapi: {
    target: EXPORT_DIALOG_TARGETS.targets[1].descriptor,
    summary: EXPORT_DIALOG_TARGETS.targets[1].fidelity,
    report: {
      items: [
        {
          construct: 'User.name',
          kind: 'ok',
          severity: 'info',
          message: 'Carried faithfully.',
          target_mapping: null,
        },
      ],
      kind_counts: { drop: 0, approx: 0, synth: 0, ok: 1 },
      severity_counts: { info: 1, warn: 0, critical: 0 },
    },
    advisory: {
      show: false,
      severity: null,
      requires_ack: false,
      target_format: 'OpenAPI 3.1',
      dropped: 0,
      approximated: 0,
      synthesized: 0,
      affected: 0,
      headline: 'Lossless export to OpenAPI 3.1',
      message: 'Every construct is carried faithfully to OpenAPI 3.1.',
    },
  },
  // The GraphQL source's live RAML preview (MFX-17.4), its report led by "RAML captures REST only" —
  // recorded by `apiome-rest/tests/test_raml_target_card.py`.
  raml: ramlPreviewForGraphql as unknown as ExportFidelityEnvelope,
};

/**
 * A `fetch` mock serving the Export dialog's routes.
 *
 * @param targets The registry the targets route lists (the three-target registry by default).
 * @returns The mock.
 */
export function mockExportDialogFetch(targets: ExportTargetsResponse = EXPORT_DIALOG_TARGETS): jest.Mock {
  return jest.fn((input: unknown, init?: { method?: string; body?: string }) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/export/targets')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, ...targets }),
      });
    }
    if (url.includes('/api/export/preview') && init?.method === 'POST') {
      const target = String(JSON.parse(init?.body ?? '{}').target);
      if (!EXPORT_DIALOG_PREVIEWS[target]) {
        // No preview recorded for this target: answer as the API does when it cannot preview,
        // rather than with a fidelity-less envelope no real response carries.
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({ success: false, error: `No preview recorded for ${target}` }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            success: true,
            artifact: 'proj-petstore',
            version: null,
            version_record_id: 'rev-1',
            version_label: '1.2.0',
            fidelity: EXPORT_DIALOG_PREVIEWS[target],
          }),
      });
    }
    if (url.includes('/api/export/projection-evidence') && init?.method === 'POST') {
      // A minimal, internally consistent evidence page (EFP-2.2): one retained field and
      // one dropped operation, for whichever target the dialog is previewing.
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            success: true,
            artifact: 'proj-petstore',
            version: null,
            version_record_id: 'rev-1',
            version_label: '1.2.0',
            redacted: false,
            summary: {
              manifest_hash: 'hash-dialog-evidence',
              target: {},
              status_counts: { retained: 1, dropped: 1 },
              reason_counts: { destination_unsupported: 1 },
              total_constructs: 2,
              node_count: 3,
              edge_count: 2,
              evidence_count: 2,
              is_lossless: false,
              worst_severity: 'warn',
              truncated: false,
            },
            page: {
              manifest_hash: 'hash-dialog-evidence',
              nodes: [
                { id: 'c1', kind: 'canonical', label: 'User.name', construct_key: 'User.name' },
                { id: 'c2', kind: 'canonical', label: 'Sub.onPing', construct_key: 'Sub.onPing' },
                { id: 't1', kind: 'target', label: 'name', target: { json_pointer: '/User/name' } },
              ],
              edges: [
                { id: 'pe1', relation: 'projects', source: 'c1', target: 't1', status: 'retained', severity: 'info', detail: 'Carried faithfully.' },
                { id: 'pe2', relation: 'projects', source: 'c2', target: null, status: 'dropped', severity: 'warn', reason: 'destination_unsupported', detail: 'Subscriptions are not representable.' },
              ],
              next_cursor: null,
              total: 2,
            },
          }),
      });
    }
    if (url.includes('/api/export/document') && init?.method === 'POST') {
      const target = String(JSON.parse(init?.body ?? '{}').target);
      const doc =
        target === 'openapi'
          ? { filename: 'petstore.json', type: 'application/json', text: '{"openapi":"3.1.0"}' }
          : { filename: 'petstore.proto', type: 'text/plain', text: 'syntax = "proto3";' };
      return Promise.resolve({
        ok: true,
        headers: {
          get: (name: string) => {
            if (name.toLowerCase() === 'content-disposition') {
              return `attachment; filename="${doc.filename}"`;
            }
            return name.toLowerCase() === 'content-type' ? doc.type : null;
          },
        },
        text: () => Promise.resolve(doc.text),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
}

/**
 * The WSDL target as the registry lists it (MFX-14.4, #3892), for a REST source and for an imported WSDL —
 * recorded from the live REST registry by `apiome-rest/tests/test_wsdl_target_card.py`. A REST source
 * loses its HTTP method and path (`lossy`); a WSDL item exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `wsdl` (an imported WSDL 1.1 order service).
 * @returns The targets response the dialog's targets route serves.
 */
export function wsdlTargets(source: 'rest' | 'wsdl'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? wsdlTargetsForRest : wsdlTargetsForWsdl);
}

/**
 * The WADL target as the registry lists it (MFX-29.4, #4176), for a REST source and for an imported WADL —
 * recorded from the live REST registry by `apiome-rest/tests/test_legacy_rest_target_cards.py`. A REST source
 * is `lossy`; an imported WADL exports back `lossless`.
 *
 * @param source `rest` (the Petstore OpenAPI) or `wadl` (an imported WADL bookstore).
 * @returns The targets response the dialog's targets route serves.
 */
export function wadlTargets(source: 'rest' | 'wadl'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? wadlTargetsForRest : wadlTargetsForWadl);
}

/**
 * The Google API Discovery target as the registry lists it (MFX-29.4, #4176), for a REST source and for an
 * imported Discovery document — recorded from the live REST registry by
 * `apiome-rest/tests/test_legacy_rest_target_cards.py`. A REST source is `lossy`; an imported Discovery
 * document exports back `lossless`.
 *
 * @param source `rest` (the Petstore OpenAPI) or `discovery` (an imported Google Web Fonts document).
 * @returns The targets response the dialog's targets route serves.
 */
export function discoveryTargets(source: 'rest' | 'discovery'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? discoveryTargetsForRest : discoveryTargetsForDiscovery);
}

/**
 * The TypeSpec target as the registry lists it (MFX-15.4, #3896), for a REST source and for an imported
 * TypeSpec project — recorded from the live REST registry by `apiome-rest/tests/test_typespec_target_card.py`.
 * A REST source loses what TypeSpec does not keep (`lossy`); a TypeSpec project exports again unchanged
 * (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `typespec` (an imported TypeSpec pets API).
 * @returns The targets response the dialog's targets route serves.
 */
export function typespecTargets(source: 'rest' | 'typespec'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? typespecTargetsForRest : typespecTargetsForTypespec);
}

/**
 * The OData target as the registry lists it (MFX-16.4, #3900), for a REST source and for an imported OData
 * service — recorded from the live REST registry by `apiome-rest/tests/test_odata_target_card.py`. A REST
 * source loses what CSDL does not keep (`lossy`); an OData service exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `odata` (an imported Northwind-style OData service).
 * @returns The targets response the dialog's targets route serves.
 */
export function odataTargets(source: 'rest' | 'odata'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? odataTargetsForRest : odataTargetsForOdata);
}

/**
 * The RAML target as the registry lists it (MFX-17.4, #3904), for a REST source, an imported RAML API and a
 * GraphQL source — recorded from the live REST registry by `apiome-rest/tests/test_raml_target_card.py`. A
 * REST or GraphQL source loses what RAML does not keep (`lossy`; a GraphQL source's report also leads with
 * "RAML captures REST only"); a RAML API exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI), `raml` (an imported RAML orders API) or `graphql`.
 * @returns The targets response the dialog's targets route serves.
 */
export function ramlTargets(source: 'rest' | 'raml' | 'graphql'): ExportTargetsResponse {
  const recorded = { rest: ramlTargetsForRest, raml: ramlTargetsForRaml, graphql: ramlTargetsForGraphql };
  return recordedTargets(recorded[source]);
}

/**
 * The API Blueprint target as the registry lists it (MFX-18.4, #3908), for a REST source and for an imported
 * API Blueprint — recorded from the live REST registry by `apiome-rest/tests/test_apiblueprint_target_card.py`.
 * A REST source loses what Markdown + MSON does not keep, its rich constraints among them (`lossy`); an API
 * Blueprint exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `apiblueprint` (an imported bookstore blueprint).
 * @returns The targets response the dialog's targets route serves.
 */
export function apiblueprintTargets(source: 'rest' | 'apiblueprint'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? apiblueprintTargetsForRest : apiblueprintTargetsForApiblueprint);
}

/**
 * The Smithy target as the registry lists it (MFX-20.4, #3917), for a REST source and for an imported Smithy
 * model — recorded from the live REST registry by `apiome-rest/tests/test_smithy_target_card.py`. A REST
 * source loses what Smithy does not keep (`lossy`); a Smithy model exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `smithy` (an imported Smithy orders service).
 * @returns The targets response the dialog's targets route serves.
 */
export function smithyTargets(source: 'rest' | 'smithy'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? smithyTargetsForRest : smithyTargetsForSmithy);
}

/**
 * The standalone XSD target as the registry lists it (MFX-22.6, #4137), for a REST source and for an imported
 * XSD — recorded from the live REST registry by `apiome-rest/tests/test_xsd_target_card.py`. XSD keeps a REST
 * source's types only (`types-only`); an XSD exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `xsd` (an imported purchase-order schema).
 * @returns The targets response the dialog's targets route serves.
 */
export function xsdTargets(source: 'rest' | 'xsd'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? xsdTargetsForRest : xsdTargetsForXsd);
}

/**
 * The Apache Thrift target as the registry lists it (MFX-25.5, #4155), for a REST source and for an imported
 * Thrift IDL — recorded from the live REST registry by `apiome-rest/tests/test_thrift_target_card.py`. A REST
 * source loses what Thrift does not keep (`lossy`); a Thrift IDL exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `thrift` (an imported Thrift user service).
 * @returns The targets response the dialog's targets route serves.
 */
export function thriftTargets(source: 'rest' | 'thrift'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? thriftTargetsForRest : thriftTargetsForThrift);
}

/**
 * The ASN.1 target as the registry lists it (MFX-27.4, #4166), for a REST source and for an imported ASN.1
 * module — recorded from the live REST registry by `apiome-rest/tests/test_asn1_target_card.py`. ASN.1 keeps a
 * REST source's types only (`types-only`); an ASN.1 module exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `asn1` (an imported ASN.1 person module).
 * @returns The targets response the dialog's targets route serves.
 */
export function asn1Targets(source: 'rest' | 'asn1'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? asn1TargetsForRest : asn1TargetsForAsn1);
}

/**
 * The OMG IDL target as the registry lists it (MFX-28.4, #4171), for a REST source and for an imported CORBA
 * IDL — recorded from the live REST registry by `apiome-rest/tests/test_corbaidl_target_card.py`. A REST
 * source loses what IDL does not keep (`lossy`); a CORBA IDL exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `corbaidl` (an imported CORBA bank definition).
 * @returns The targets response the dialog's targets route serves.
 */
export function corbaidlTargets(source: 'rest' | 'corbaidl'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? corbaidlTargetsForRest : corbaidlTargetsForCorbaidl);
}

/**
 * The FlatBuffers and Cap'n Proto targets as the registry lists them (MFX-30.4, #4181), for a REST source and for
 * a source in the target's own format — recorded from the live REST registry by
 * `apiome-rest/tests/test_serialization_idl_target_cards.py`. A REST source badges FlatBuffers `types-only` and
 * Cap'n Proto `lossy`; each format's own schema exports again unchanged (`lossless`).
 *
 * @param target `flatbuffers` or `capnproto`.
 * @param source `rest` (the Petstore OpenAPI) or `own` (the Monster `.fbs` / address-book `.capnp`).
 * @returns The targets response the dialog's targets route serves.
 */
export function serializationIdlTargets(
  target: 'flatbuffers' | 'capnproto',
  source: 'rest' | 'own',
): ExportTargetsResponse {
  const recorded = {
    flatbuffers: { rest: flatbuffersTargetsForRest, own: flatbuffersTargetsForFlatbuffers },
    capnproto: { rest: capnprotoTargetsForRest, own: capnprotoTargetsForCapnproto },
  };
  return recordedTargets(recorded[target][source]);
}

/**
 * The OpenRPC target as the registry lists it (MFX-33.4, #4304), for a REST source and for an imported OpenRPC
 * document — recorded from the live REST registry by `apiome-rest/tests/test_openrpc_target_card.py`. A REST
 * source loses what JSON-RPC does not keep (`lossy`); an OpenRPC document exports again unchanged (`lossless`).
 *
 * @param source `rest` (the Petstore OpenAPI) or `openrpc` (an imported OpenRPC wallet API).
 * @returns The targets response the dialog's targets route serves.
 */
export function openrpcTargets(source: 'rest' | 'openrpc'): ExportTargetsResponse {
  return recordedTargets(source === 'rest' ? openrpcTargetsForRest : openrpcTargetsForOpenrpc);
}

/**
 * The Arazzo target as the registry lists it (MFX-10.4, #3873), for a REST source, an imported Arazzo workflow
 * document and a set of types — recorded from the live REST registry by
 * `apiome-rest/tests/test_arazzo_target_card.py`. Arazzo captures workflows, not the full API surface, so a REST
 * source is `lossy`; an Arazzo document exports again unchanged (`lossless`); a set of types has no operation to
 * sequence, so the target is unavailable.
 *
 * @param source `rest` (the Petstore OpenAPI), `arazzo` (an imported Arazzo 1.0 workflow) or `data` (a JSON
 *   Schema set of types).
 * @returns The targets response the dialog's targets route serves.
 */
export function arazzoTargets(source: 'rest' | 'arazzo' | 'data'): ExportTargetsResponse {
  const recorded = { rest: arazzoTargetsForRest, arazzo: arazzoTargetsForArazzo, data: arazzoTargetsForData };
  return recordedTargets(recorded[source]);
}

/**
 * The MCP Tool Definitions target as the registry lists it (MFX-32.5, #4299), recorded from the live REST
 * registry by `apiome-rest/tests/test_agent_target_cards.py`. A REST API is `lossy` (each tool's HTTP binding
 * becomes description text); an imported MCP server is `lossy` too, because its resources and prompts are not
 * tools; a set of types has no operation to make a tool of, so the card is unavailable with its reason.
 *
 * @param source `rest` (the Petstore OpenAPI), `mcp` (an imported MCP tickets server) or `data` (a JSON Schema item).
 * @returns The targets response the dialog's targets route serves.
 */
export function mcpTargets(source: 'rest' | 'mcp' | 'data'): ExportTargetsResponse {
  const recorded = { rest: mcpTargetsForRest, mcp: mcpTargetsForMcp, data: mcpTargetsForData };
  return recordedTargets(recorded[source]);
}

/**
 * The A2A Agent Card target as the registry lists it (MFX-32.5, #4299), recorded from the live REST registry by
 * `apiome-rest/tests/test_agent_target_cards.py`. A REST API is reframed as an agent (`lossy`); an imported A2A
 * agent exports back `lossless`; a set of types has neither an agent nor an operation, so the card is unavailable.
 *
 * @param source `rest` (the Petstore OpenAPI), `a2a` (an imported travel-concierge card) or `data` (a JSON Schema item).
 * @returns The targets response the dialog's targets route serves.
 */
export function a2aTargets(source: 'rest' | 'a2a' | 'data'): ExportTargetsResponse {
  const recorded = { rest: a2aTargetsForRest, a2a: a2aTargetsForA2a, data: a2aTargetsForData };
  return recordedTargets(recorded[source]);
}

/**
 * The xRegistry target as the registry lists it (MFX-34.4, #4309), recorded from the live REST registry by
 * `apiome-rest/tests/test_xregistry_target_card.py`. A REST API keeps only its types (`lossy`, and its export needs
 * confirmation); an imported xRegistry exports back `lossy` only for its endpoints and re-keys; a gateway
 * configuration has neither a type nor an event, so the card is unavailable with its reason.
 *
 * @param source `rest` (the Petstore OpenAPI), `xregistry` (an imported order-events registry) or `gateway`
 *   (an imported Kong configuration).
 * @returns The targets response the dialog's targets route serves.
 */
export function xregistryTargets(source: 'rest' | 'xregistry' | 'gateway'): ExportTargetsResponse {
  const recorded = {
    rest: xregistryTargetsForRest,
    xregistry: xregistryTargetsForXregistry,
    gateway: xregistryTargetsForGateway,
  };
  return recordedTargets(recorded[source]);
}

/**
 * The SQL DDL target as the registry lists it (MFX-35.5, #4315), recorded from the live REST registry by
 * `apiome-rest/tests/test_sql_ddl_target_card.py`. The target holds data schemas only, so a REST API badges
 * `types-only` (its operations are dropped with a critical warning); a gateway configuration has no record type,
 * so the card is unavailable with its reason. One card writes every output: `ddl`, `dbml`, `prisma`, `liquibase`
 * and `flyway`, in the `postgres`, `mysql` or `ansi` dialect.
 *
 * @param source `rest` (the Petstore OpenAPI), `sql` (an imported PostgreSQL script) or `gateway` (an imported
 *   Kong configuration).
 * @returns The targets response the dialog's targets route serves.
 */
export function sqlDdlTargets(source: 'rest' | 'sql' | 'gateway'): ExportTargetsResponse {
  const recorded = { rest: sqlDdlTargetsForRest, sql: sqlDdlTargetsForSql, gateway: sqlDdlTargetsForGateway };
  return recordedTargets(recorded[source]);
}

/**
 * The Apache Arrow / Parquet target as the registry lists it (MFX-36.5, #4321), recorded from the live REST
 * registry by `apiome-rest/tests/test_data_lake_target_cards.py`. One card writes every mode: `arrow` (Arrow
 * schemas and Parquet messages), `bigquery` and `spark`. A REST API badges `types-only` (its operations are dropped
 * with a critical warning), an imported Arrow schema `lossless`; a gateway configuration has no record type, so the
 * card is unavailable with its reason.
 *
 * @param source `rest` (the Petstore OpenAPI), `arrow` (an imported Arrow schema) or `gateway` (an imported Kong
 *   configuration).
 * @returns The targets response the dialog's targets route serves.
 */
export function arrowTargets(source: 'rest' | 'arrow' | 'gateway'): ExportTargetsResponse {
  const recorded = { rest: arrowTargetsForRest, arrow: arrowTargetsForArrow, gateway: arrowTargetsForGateway };
  return recordedTargets(recorded[source]);
}

/**
 * The Apache Iceberg target as the registry lists it (MFX-36.5, #4321), recorded the same way. Every source with a
 * record type badges `types-only`; the stored field IDs are not an option the card offers.
 *
 * @param source `rest` (the Petstore OpenAPI) or `gateway` (an imported Kong configuration).
 * @returns The targets response the dialog's targets route serves.
 */
export function icebergTargets(source: 'rest' | 'gateway'): ExportTargetsResponse {
  const recorded = { rest: icebergTargetsForRest, gateway: icebergTargetsForGateway };
  return recordedTargets(recorded[source]);
}

/**
 * The FIX Orchestra target as the registry lists it (MFX-37.4, #4326), recorded from the live REST registry by
 * `apiome-rest/tests/test_fix_orchestra_target_card.py`. An Orchestra repository describes messages, so every
 * source badges `types-only` — an imported Orchestra repository with a high preserved share, a REST API with
 * none — and a gateway configuration has no record type, so the card is unavailable with its reason. The card
 * offers the repository `version`; the stored FIX tags are not an option.
 *
 * @param source `rest` (the Petstore OpenAPI), `orchestra` (an imported FIX Orchestra repository) or `gateway`
 *   (an imported Kong configuration).
 * @returns The targets response the dialog's targets route serves.
 */
export function fixOrchestraTargets(source: 'rest' | 'orchestra' | 'gateway'): ExportTargetsResponse {
  const recorded = {
    rest: fixOrchestraTargetsForRest,
    orchestra: fixOrchestraTargetsForOrchestra,
    gateway: fixOrchestraTargetsForGateway,
  };
  return recordedTargets(recorded[source]);
}
