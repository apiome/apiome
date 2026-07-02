/**
 * Unit tests for generate-field-value (UUID and timestamp generation for insert form).
 */

import { generateUuid, generateTimestamp } from '../../lib/database/generate-field-value';

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-7][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ISO_DATE_REGEX = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

describe('generateUuid', () => {
  test('v4 returns a valid UUID string', () => {
    const u = generateUuid(4);
    expect(u).toMatch(UUID_REGEX);
    expect(u[14]).toBe('4'); // version digit
  });

  test('v1 returns a valid UUID string', () => {
    const u = generateUuid(1);
    expect(u).toMatch(UUID_REGEX);
    expect(u[14]).toBe('1');
  });

  test('v7 returns a valid UUID (uses v4 when v7 not available)', () => {
    const u = generateUuid(7);
    expect(u).toMatch(UUID_REGEX);
    // In this build v7 is not available, so we get v4
    expect(['4', '7']).toContain(u[14]);
  });

  test('each call returns a new value', () => {
    expect(generateUuid(4)).not.toBe(generateUuid(4));
  });
});

describe('generateTimestamp', () => {
  test('returns ISO 8601 string for any kind', () => {
    expect(generateTimestamp('CURRENT_TIMESTAMP')).toMatch(ISO_DATE_REGEX);
    expect(generateTimestamp('NOW()')).toMatch(ISO_DATE_REGEX);
    expect(generateTimestamp('iso')).toMatch(ISO_DATE_REGEX);
    expect(generateTimestamp(null)).toMatch(ISO_DATE_REGEX);
  });

  test('returns a valid date', () => {
    const t = generateTimestamp('CURRENT_TIMESTAMP');
    const d = new Date(t);
    expect(Number.isNaN(d.getTime())).toBe(false);
  });
});
