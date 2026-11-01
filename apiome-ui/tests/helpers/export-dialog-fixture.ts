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
import wsdlTargetsForRest from '../fixtures/export-targets-wsdl-rest.json';
import wsdlTargetsForWsdl from '../fixtures/export-targets-wsdl-wsdl.json';
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
