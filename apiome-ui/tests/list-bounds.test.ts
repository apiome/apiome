/**
 * Bounds and keyset cursors of the UI's direct-SQL lists (DBP-1.13, #7196).
 *
 * The cursor format is the one apiome-rest issues (`apiome-rest/src/app/keyset_pagination.py`),
 * so the fixtures here are spelled out byte for byte rather than only round-tripped.
 */

import { describe, expect, test } from '@jest/globals';

import {
  DEFAULT_LIST_ROWS,
  InvalidCursorError,
  MAX_LIST_ROWS,
  MAX_UNPAGED_ROWS,
  clampListLimit,
  cursorTimestampSql,
  decodeKeyCursor,
  decodeTimeIdCursor,
  encodeKeyCursor,
  encodeTimeIdCursor,
  pageOf,
  searchPattern,
  withoutCursorColumns,
} from '../lib/db/list-bounds';

const ID = '0b9f6c0e-6f0a-4a57-9a55-0e7b2f8f3c11';
const STAMP = '2026-01-02T03:04:05.678901Z';

/** Encode any JSON value the way a cursor is encoded. */
const token = (value: unknown) => Buffer.from(JSON.stringify(value), 'utf8').toString('base64url');

describe('the bounds', () => {
  test('are the documented numbers', () => {
    expect(MAX_LIST_ROWS).toBe(200);
    expect(DEFAULT_LIST_ROWS).toBe(50);
    expect(MAX_UNPAGED_ROWS).toBe(1000);
  });
});

describe('clampListLimit', () => {
  test.each([
    [undefined, 50],
    [Number.NaN, 50],
    [Number.POSITIVE_INFINITY, 50],
    [1, 1],
    [50, 50],
    [200, 200],
    [201, 200],
    [100_000, 200],
    [0, 1],
    [-5, 1],
    [12.9, 12],
  ])('clampListLimit(%p) is %p', (limit, expected) => {
    expect(clampListLimit(limit)).toBe(expected);
  });

  test('honours a caller-supplied maximum', () => {
    expect(clampListLimit(5000, MAX_UNPAGED_ROWS)).toBe(1000);
    expect(clampListLimit(undefined, 10)).toBe(10);
  });

  test('ignores a limit that is not a number', () => {
    expect(clampListLimit('25' as unknown as number)).toBe(50);
  });
});

describe('the (timestamp, id) cursor', () => {
  test('round-trips, keeping the microseconds', () => {
    expect(decodeTimeIdCursor(encodeTimeIdCursor(STAMP, ID))).toEqual({ t: STAMP, i: ID });
  });

  test('is unpadded urlsafe base64 over {"t","i"} — the REST format', () => {
    const cursor = encodeTimeIdCursor(STAMP, ID);
    expect(cursor).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(Buffer.from(cursor, 'base64url').toString('utf8')).toBe(`{"t":"${STAMP}","i":"${ID}"}`);
  });

  test('accepts a Date', () => {
    const cursor = encodeTimeIdCursor(new Date('2026-01-02T03:04:05.678Z'), ID);
    expect(decodeTimeIdCursor(cursor).t).toBe('2026-01-02T03:04:05.678Z');
  });

  test('reads a cursor apiome-rest issued (padded, +00:00 offset)', () => {
    const rest = Buffer.from(`{"t":"2026-01-02T03:04:05.678901+00:00","i":"${ID}"}`).toString(
      'base64',
    );
    expect(decodeTimeIdCursor(rest.replace(/\+/g, '-').replace(/\//g, '_'))).toEqual({
      t: '2026-01-02T03:04:05.678901+00:00',
      i: ID,
    });
  });

  test.each([
    ['nothing', undefined],
    ['an empty string', '   '],
    ['a number', 42],
    ['not base64', '!!!not-base64!!!'],
    ['base64 of something that is not JSON', Buffer.from('nope').toString('base64url')],
    ['a JSON array', token([1, 2])],
    ['a JSON string', token('x')],
    ['no id', token({ t: STAMP })],
    ['an empty id', token({ t: STAMP, i: '' })],
    ['a numeric id', token({ t: STAMP, i: 7 })],
    ['no timestamp', token({ i: ID })],
    ['a timestamp that is not one', token({ t: 'yesterday', i: ID })],
    ['a timestamp without a timezone', token({ t: '2026-01-02T03:04:05', i: ID })],
    ['a key cursor', token({ k: ['a', ID] })],
    ['an oversized token', 'A'.repeat(3000)],
  ])('refuses %s', (_label, value) => {
    expect(() => decodeTimeIdCursor(value)).toThrow(InvalidCursorError);
  });
});

describe('the sort-key cursor', () => {
  test('round-trips its values in order', () => {
    const cursor = encodeKeyCursor(['Ada Lovelace', ID]);
    expect(decodeKeyCursor(cursor, 2)).toEqual(['Ada Lovelace', ID]);
    expect(Buffer.from(cursor, 'base64url').toString('utf8')).toBe(
      `{"k":["Ada Lovelace","${ID}"]}`,
    );
  });

  test('carries scalars as JSON scalars and everything else as text', () => {
    const when = new Date('2026-03-04T05:06:07.000Z');
    const values = decodeKeyCursor(
      encodeKeyCursor([true, 3, null, undefined, when, BigInt(10)]),
      6,
    );
    expect(values).toEqual([true, 3, null, null, '2026-03-04T05:06:07.000Z', '10']);
  });

  test('keeps text that base64 would otherwise mangle', () => {
    const name = 'Zoë ??>> 名前';
    expect(decodeKeyCursor(encodeKeyCursor([name]), 1)).toEqual([name]);
  });

  test.each([
    ['a different number of values', token({ k: ['a'] }), 2],
    ['a nested value', token({ k: [['a'], 'b'] }), 2],
    ['an object value', token({ k: [{ a: 1 }, 'b'] }), 2],
    ['a (timestamp, id) cursor', encodeTimeIdCursor(STAMP, ID), 2],
    ['k that is not a list', token({ k: 'ab' }), 2],
    ['garbage', 'zzz', 1],
  ])('refuses %s', (_label, value, size) => {
    expect(() => decodeKeyCursor(value, size)).toThrow(InvalidCursorError);
  });
});

describe('pageOf', () => {
  const rows = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  const cursorOf = (row: { id: string }) => `after-${row.id}`;

  test('a limit + 1 read is cut to the limit and names the next page', () => {
    expect(pageOf(rows, 2, cursorOf)).toEqual({
      items: [{ id: 'a' }, { id: 'b' }],
      hasMore: true,
      nextCursor: 'after-b',
    });
  });

  test('a read that came back short is the last page', () => {
    expect(pageOf(rows, 3, cursorOf)).toEqual({ items: rows, hasMore: false, nextCursor: null });
    expect(pageOf([], 3, cursorOf)).toEqual({ items: [], hasMore: false, nextCursor: null });
  });
});

describe('the SQL helpers', () => {
  test('cursorTimestampSql renders UTC ISO text with microseconds', () => {
    expect(cursorTimestampSql('t.created_at')).toBe(
      `to_char((t.created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`,
    );
  });

  test('searchPattern matches the text anywhere, literally', () => {
    expect(searchPattern('  ada ')).toBe('%ada%');
    expect(searchPattern('100%_done\\')).toBe('%100\\%\\_done\\\\%');
    expect(searchPattern('')).toBeNull();
    expect(searchPattern('   ')).toBeNull();
    expect(searchPattern(null)).toBeNull();
    expect(searchPattern(undefined)).toBeNull();
    expect(searchPattern('x'.repeat(500))).toHaveLength(202);
  });

  test('withoutCursorColumns drops only the named columns, on a copy', () => {
    const row = { id: 'a', name: 'A', cursor_ts: STAMP, cursor_id: 'a' };
    expect(withoutCursorColumns(row, ['cursor_ts', 'cursor_id'])).toEqual({ id: 'a', name: 'A' });
    expect(row.cursor_ts).toBe(STAMP);
  });
});
