import { describe, it, expect } from '@jest/globals';
import {
  isRevisionDeprecated,
  revisionDeprecationLines,
  MIGRATION_GUIDE_ISSUE_URL,
} from '@/app/utils/revision-deprecation';

describe('revision-deprecation', () => {
  it('detects deprecated flag', () => {
    expect(isRevisionDeprecated(undefined)).toBe(false);
    expect(isRevisionDeprecated({ deprecated: true })).toBe(true);
    expect(isRevisionDeprecated({ deprecated: 'true' })).toBe(true);
  });

  it('handles JSON string metadata', () => {
    expect(isRevisionDeprecated('{"deprecated":true}')).toBe(true);
    expect(isRevisionDeprecated('{"deprecated":false}')).toBe(false);
    expect(isRevisionDeprecated('not-json')).toBe(false);
    const lines = revisionDeprecationLines('{"deprecated":true,"sunsetDate":"2026-12-01"}');
    expect(lines.some((l) => l.includes('2026-12-01'))).toBe(true);
  });

  it('builds lines with guide link', () => {
    const lines = revisionDeprecationLines({
      deprecated: true,
      deprecationMessage: 'Migrate',
      sunsetDate: '2026-12-01',
    });
    expect(lines.some((l) => l.includes(MIGRATION_GUIDE_ISSUE_URL))).toBe(true);
    expect(lines.some((l) => l.includes('2026-12-01'))).toBe(true);
  });
});
