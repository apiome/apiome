/**
 * The Browse pool's limits: statement time (DBP-1.15, #7198), like the UI pool and apiome-rest, and
 * an explicit size (DBP-1.16, #7199).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('pg', () => ({
  Pool: class {
    on() {}
  },
}));

import { DEFAULT_DB_POOL_MAX, isStatementTimeout, poolMax, statementTimeoutOption } from '../db/db';

describe('statementTimeoutOption', () => {
  afterEach(() => {
    delete process.env.DB_STATEMENT_TIMEOUT_MS;
  });

  it('defaults to 30 s', () => {
    expect(statementTimeoutOption()).toBe(' -c statement_timeout=30000');
  });

  it('reads DB_STATEMENT_TIMEOUT_MS', () => {
    process.env.DB_STATEMENT_TIMEOUT_MS = '5000';
    expect(statementTimeoutOption()).toBe(' -c statement_timeout=5000');
  });

  it('is off at 0', () => {
    process.env.DB_STATEMENT_TIMEOUT_MS = '0';
    expect(statementTimeoutOption()).toBe('');
  });

  it('ignores a value that is not a whole number of milliseconds', () => {
    process.env.DB_STATEMENT_TIMEOUT_MS = 'soon';
    expect(statementTimeoutOption()).toBe(' -c statement_timeout=30000');
    process.env.DB_STATEMENT_TIMEOUT_MS = '-5';
    expect(statementTimeoutOption()).toBe(' -c statement_timeout=30000');
  });
});

describe('poolMax', () => {
  afterEach(() => {
    delete process.env.DB_POOL_MAX;
  });

  it('defaults to 10 connections', () => {
    expect(DEFAULT_DB_POOL_MAX).toBe(10);
    expect(poolMax()).toBe(10);
  });

  it('reads DB_POOL_MAX', () => {
    process.env.DB_POOL_MAX = '25';
    expect(poolMax()).toBe(25);
  });

  it('ignores zero, negative and non-numeric values, which would leave the site without a pool', () => {
    for (const value of ['0', '-3', 'many', '2.5', '']) {
      process.env.DB_POOL_MAX = value;
      expect(poolMax()).toBe(10);
    }
  });
});

describe('isStatementTimeout', () => {
  it('recognizes a statement cancelled by statement_timeout', () => {
    expect(isStatementTimeout({ code: '57014', message: 'canceling statement due to statement timeout' })).toBe(true);
  });

  it('is false for other failures', () => {
    expect(isStatementTimeout({ code: '42P01' })).toBe(false);
    expect(isStatementTimeout(new Error('connection terminated'))).toBe(false);
    expect(isStatementTimeout(null)).toBe(false);
    expect(isStatementTimeout('57014')).toBe(false);
  });
});
