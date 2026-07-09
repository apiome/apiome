/**
 * Structural assertions over mock usage / quota migration (#4420, SIM-1.5).
 */

import fs from 'node:fs/promises';
import path from 'node:path';

import { beforeAll, describe, expect, it } from 'vitest';

import { listMigrationFiles } from '../src/migrate.js';

const SCRIPTS_DIR = new URL('../scripts', import.meta.url).pathname;
const MIGRATION = 'V154__mock_usage_rate_limits_4420.sql';

let sql = '';
let lower = '';

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), 'utf8');
  lower = sql.toLowerCase();
});

describe('mock usage rate limits migration', () => {
  it('is present in scripts/ and ordered after V153', async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf('V153__mock_spec_publish_notify_4416.sql'),
    );
  });

  it('defines mock_usage daily rollup table and license mock quota seeds', () => {
    expect(lower).toContain('set search_path to apiome, public');
    expect(lower).toMatch(/create table if not exists mock_usage/);
    expect(lower).toContain('tenant_id uuid not null references tenants(id)');
    expect(lower).toContain('usage_date date not null');
    expect(lower).toContain('mock_rps');
    expect(lower).toContain('mock_requests_per_month');
    expect(lower).toMatch(/create or replace function apiome\.record_mock_usage/);
  });
});
