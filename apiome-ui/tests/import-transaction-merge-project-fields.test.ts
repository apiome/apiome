/**
 * `mergeProjectImportOpenApiFieldsTx` — the project info an import into an existing project writes.
 *
 * The description is filled only when blank; metadata is shallow-merged, with the incoming keys
 * winning unless `metadataFillOnly` is set (a lower-precedence file of a multi-repository project,
 * REPO-5.7 #2792), when the project's existing keys win.
 */

import { describe, test, expect, jest } from '@jest/globals';

jest.mock('../lib/db/db', () => ({}));

import { mergeProjectImportOpenApiFieldsTx } from '../lib/db/import-transaction';

function client(current: { description: string | null; metadata: Record<string, unknown> }) {
  const query = jest.fn(async (sql: string, ...rest: unknown[]) => {
    void rest;
    return /^SELECT/.test(sql.trim()) ? { rows: [current] } : { rows: [] };
  });
  return { query, release: jest.fn() } as unknown as Parameters<typeof mergeProjectImportOpenApiFieldsTx>[0] & {
    query: typeof query;
  };
}

describe('mergeProjectImportOpenApiFieldsTx', () => {
  test('incoming metadata keys win by default', async () => {
    const c = client({ description: 'Users API', metadata: { contact: { name: 'Users' }, keep: 1 } });
    const res = JSON.parse(
      await mergeProjectImportOpenApiFieldsTx(c, 'p1', {
        descriptionFromSpec: 'Billing API',
        metadataPatch: { contact: { name: 'Billing' }, license: 'MIT' },
      }),
    );
    expect(res.success).toBe(true);
    const [, params] = c.query.mock.calls[1];
    expect(params[0]).toBe('Users API');
    expect(JSON.parse(params[1])).toEqual({ contact: { name: 'Billing' }, keep: 1, license: 'MIT' });
  });

  test('metadataFillOnly keeps existing keys and adds missing ones', async () => {
    const c = client({ description: null, metadata: { contact: { name: 'Users' } } });
    await mergeProjectImportOpenApiFieldsTx(c, 'p1', {
      descriptionFromSpec: 'Billing API',
      metadataPatch: { contact: { name: 'Billing' }, license: 'MIT' },
      metadataFillOnly: true,
    });
    const [, params] = c.query.mock.calls[1];
    expect(params[0]).toBe('Billing API');
    expect(JSON.parse(params[1])).toEqual({ contact: { name: 'Users' }, license: 'MIT' });
  });
});
