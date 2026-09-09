/**
 * FastAPI error-body reading — shared by the public export and Get SDK surfaces.
 *
 * Pins what counts as a usable `detail` and, just as importantly, that reading one never throws:
 * every caller is already on an error path.
 */

import { describe, expect, it } from 'vitest';
import { detailFromBody, readProblemDetail } from '../problemDetail';

/** A Response double whose `text()` behaviour the test controls. */
function response(body: string | Error, status = 404): Response {
  return {
    status,
    text: async () => {
      if (body instanceof Error) throw body;
      return body;
    },
  } as unknown as Response;
}

describe('detailFromBody', () => {
  it('lifts the detail sentence out of a FastAPI body', () => {
    expect(detailFromBody('{"detail": "Version not found"}')).toBe('Version not found');
  });

  it('trims surrounding whitespace from the body and the sentence', () => {
    expect(detailFromBody('  {"detail": "  spaced  "}  ')).toBe('spaced');
  });

  it('returns null for a body that is not JSON', () => {
    expect(detailFromBody('Internal Server Error')).toBeNull();
    expect(detailFromBody('')).toBeNull();
  });

  it('returns null for a JSON array, which cannot carry a detail', () => {
    expect(detailFromBody('[{"detail": "nope"}]')).toBeNull();
  });

  it('returns null for malformed JSON rather than throwing', () => {
    expect(detailFromBody('{"detail": ')).toBeNull();
  });

  it('ignores a detail that is not a non-empty string', () => {
    expect(detailFromBody('{"detail": 42}')).toBeNull();
    expect(detailFromBody('{"detail": "   "}')).toBeNull();
    expect(detailFromBody('{"detail": {"msg": "nested"}}')).toBeNull();
  });

  it('returns null when the body names no detail at all', () => {
    expect(detailFromBody('{"error": {"message": "nope"}}')).toBeNull();
  });
});

describe('readProblemDetail', () => {
  it('reads the body once and returns its detail', async () => {
    await expect(readProblemDetail(response('{"detail": "Rate limited"}'))).resolves.toBe(
      'Rate limited'
    );
  });

  it('returns null when the body cannot be read', async () => {
    await expect(readProblemDetail(response(new Error('stream consumed')))).resolves.toBeNull();
  });

  it('returns null for a body with no detail', async () => {
    await expect(readProblemDetail(response('not json'))).resolves.toBeNull();
  });
});
