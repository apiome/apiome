import { describe, test, expect } from '@jest/globals';
import { parseStaleHeadFromVersionsPostJson } from '@/app/utils/push-conflict';

describe('parseStaleHeadFromVersionsPostJson', () => {
  test('returns null for non-409', () => {
    expect(parseStaleHeadFromVersionsPostJson({ code: 'STALE_HEAD' }, 400)).toBeNull();
  });

  test('returns null when code is not STALE_HEAD', () => {
    expect(
      parseStaleHeadFromVersionsPostJson({ success: false, error: 'x' }, 409)
    ).toBeNull();
  });

  test('parses STALE_HEAD proxy body', () => {
    const json = {
      success: false,
      error: 'Branch tip does not match baseRevisionId (stale head or wrong base).',
      code: 'STALE_HEAD',
      currentHeadRevisionId: 'rev-1',
      currentHead: { revisionId: 'rev-1', versionId: '1.0.1' },
    };
    const out = parseStaleHeadFromVersionsPostJson(json, 409);
    expect(out).not.toBeNull();
    expect(out!.code).toBe('STALE_HEAD');
    expect(out!.message).toBe('Branch tip does not match baseRevisionId (stale head or wrong base).');
    expect(out!.currentHeadRevisionId).toBe('rev-1');
    expect(out!.currentHead?.versionId).toBe('1.0.1');
  });

  test('returns undefined message when server provides no specific error string', () => {
    const json = { code: 'STALE_HEAD', currentHeadRevisionId: 'rev-2' };
    const out = parseStaleHeadFromVersionsPostJson(json, 409);
    expect(out).not.toBeNull();
    expect(out!.code).toBe('STALE_HEAD');
    expect(out!.message).toBeUndefined();
    expect(out!.currentHeadRevisionId).toBe('rev-2');
  });
});
