/**
 * Recording an import's original document (COA-5.3, #7079).
 *
 * Pins: the record body carries the revision, the text as read and where it came from; nothing is
 * recorded without a revision or without text; and sending is best-effort.
 */

import { describe, expect, jest, test } from '@jest/globals';

import { buildImportOriginalRecord, recordImportOriginal } from '@/app/utils/import-original-record';

const TEXT = 'openapi: 3.1.0\ninfo:\n  title: Pets\n';

describe('buildImportOriginalRecord', () => {
  test('carries the revision, the text as read and the file name', () => {
    expect(buildImportOriginalRecord({ versionId: 'v-1' }, TEXT, ' pets.yaml ')).toEqual({
      versionId: 'v-1',
      content: TEXT,
      filename: 'pets.yaml',
    });
  });

  test('leaves the file name out when there is none', () => {
    expect(buildImportOriginalRecord({ versionId: 'v-1' }, TEXT)).toEqual({ versionId: 'v-1', content: TEXT });
    expect(buildImportOriginalRecord({ versionId: 'v-1' }, TEXT, '  ')).not.toHaveProperty('filename');
  });

  test('records nothing without a revision or without text', () => {
    expect(buildImportOriginalRecord(undefined, TEXT)).toBeNull();
    expect(buildImportOriginalRecord({ versionId: '  ' }, TEXT)).toBeNull();
    expect(buildImportOriginalRecord({ versionId: 'v-1' }, '   ')).toBeNull();
    expect(buildImportOriginalRecord({ versionId: 'v-1' }, null)).toBeNull();
  });
});

describe('recordImportOriginal', () => {
  const body = buildImportOriginalRecord({ versionId: 'v-1' }, TEXT, 'pets.yaml')!;

  test('posts the body to the proxy', async () => {
    const fetchImpl = jest.fn(async () => ({ ok: true, status: 200 })) as unknown as typeof fetch;
    expect(await recordImportOriginal(body, fetchImpl)).toBe(true);
    const [url, init] = (fetchImpl as unknown as jest.Mock).mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/import-originals');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual(body);
  });

  test('a refusal or a network failure is reported, never thrown', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    const refused = jest.fn(async () => ({ ok: false, status: 403 })) as unknown as typeof fetch;
    const broken = jest.fn(async () => {
      throw new TypeError('network');
    }) as unknown as typeof fetch;
    expect(await recordImportOriginal(body, refused)).toBe(false);
    expect(await recordImportOriginal(body, broken)).toBe(false);
    expect(warn).toHaveBeenCalledTimes(2);
    warn.mockRestore();
  });
});
