/**
 * Tests for the pointer → diff-line focus heuristic — CTG-3.2 (#4476).
 *
 * Pins the "last meaningful segment" selection (JSON Pointer unescaping, numeric-index
 * skipping), the quoted-key-first matching, and the -1 no-match / no-segment behavior.
 */

import { describe, expect, it } from 'vitest';
import { findDiffLineIndexForPointer } from '../focus';

describe('findDiffLineIndexForPointer', () => {
  it('finds the quoted key of the pointer last segment', () => {
    const lines = ['{', '  "paths": {', '    "summary": "List pets",', '}'];
    expect(findDiffLineIndexForPointer(lines, '/paths/~1pets/get/summary')).toBe(2);
  });

  it('prefers a quoted-key match over an earlier bare occurrence', () => {
    const lines = [
      '  "description": "the summary of it all",',
      '  "summary": "List pets",',
    ];
    expect(findDiffLineIndexForPointer(lines, '/paths/~1pets/get/summary')).toBe(1);
  });

  it('falls back to a bare substring match when no quoted key exists', () => {
    const lines = ['{', '  "x-summary-notes": "hi",'];
    expect(findDiffLineIndexForPointer(lines, '/summary')).toBe(1);
  });

  it('unescapes ~1 to / in segments', () => {
    const lines = ['  "paths": {', '    "/pets/{id}": {'];
    expect(findDiffLineIndexForPointer(lines, '/paths/~1pets~1{id}')).toBe(1);
  });

  it('unescapes ~0 to ~ in segments', () => {
    const lines = ['  "a~b": 1,'];
    expect(findDiffLineIndexForPointer(lines, '/a~0b')).toBe(0);
  });

  it('skips purely numeric trailing segments (array indices, status codes)', () => {
    const lines = ['  "responses": {', '    "200": {'];
    expect(findDiffLineIndexForPointer(lines, '/paths/~1pets/get/responses/200')).toBe(0);
  });

  it('returns -1 when the pointer has no meaningful segment', () => {
    expect(findDiffLineIndexForPointer(['"0": 1'], '/0/1')).toBe(-1);
    expect(findDiffLineIndexForPointer(['{}'], '')).toBe(-1);
    expect(findDiffLineIndexForPointer(['{}'], '/')).toBe(-1);
  });

  it('returns -1 when nothing matches', () => {
    expect(findDiffLineIndexForPointer(['{', '}'], '/components/schemas/Pet')).toBe(-1);
    expect(findDiffLineIndexForPointer([], '/paths/~1pets')).toBe(-1);
  });
});
