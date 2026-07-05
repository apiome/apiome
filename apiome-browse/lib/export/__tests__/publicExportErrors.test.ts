/**
 * Tests for public export error presentation — MFX-7.3 (#3862).
 */

import { describe, expect, it } from 'vitest';
import { publicExportErrorMessage } from '../publicExportErrors';

describe('publicExportErrorMessage', () => {
  it('maps 429 to a rate-limit message', () => {
    expect(publicExportErrorMessage(429)).toMatch(/too many export requests/i);
  });

  it('prefers server detail on 429 when present', () => {
    const body = JSON.stringify({ detail: 'Public export rate limit exceeded; slow down.' });
    expect(publicExportErrorMessage(429, body)).toBe(
      'Public export rate limit exceeded; slow down.'
    );
  });

  it('maps 413 to a size-cap message', () => {
    expect(publicExportErrorMessage(413)).toMatch(/too large/i);
  });

  it('maps 404 to an availability message', () => {
    expect(publicExportErrorMessage(404)).toMatch(/not available/i);
  });

  it('falls back to status when unknown', () => {
    expect(publicExportErrorMessage(500)).toBe('Export failed (500).');
  });
});
