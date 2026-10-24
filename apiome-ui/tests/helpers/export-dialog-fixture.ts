/**
 * The Export dialog's mocked registry (MFX-6.x), shared by `tests/ExportDialog.test.tsx` and the
 * RC6-H2 dialog fixture dumps (`tests/rc6-dialog-fixtures.test.tsx`), so both draw the same dialog.
 */
import { jest } from '@jest/globals';

import type { ExportTargetsResponse } from '../../src/app/components/ade/dashboard/export/exportTargetCatalog';
import type { ExportFidelityEnvelope } from '../../src/app/components/ade/dashboard/export/exportFidelityPreview';

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
};

export function mockExportDialogFetch(): jest.Mock {
  return jest.fn((input: unknown, init?: { method?: string; body?: string }) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/export/targets')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, ...EXPORT_DIALOG_TARGETS }),
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
