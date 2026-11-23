/**
 * DBP-1.15 (#7198): the Browse pool caps statement time, like the UI pool and apiome-rest.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('pg', () => ({
  Pool: class {
    on() {}
  },
}));

import { statementTimeoutOption } from '../db/db';

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
