/** Structural assertions over version mock toggle migration (#4422, SIM-2.1). */

import fs from 'node:fs/promises';
import path from 'node:path';

import { beforeAll, describe, expect, it } from 'vitest';

import { listMigrationFiles } from '../src/migrate.js';

const SCRIPTS_DIR = new URL('../scripts', import.meta.url).pathname;
const MIGRATION = 'V155__version_mock_enabled_4422.sql';

let sql = '';
let lower = '';

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), 'utf8');
  lower = sql.toLowerCase();
});

describe('version mock enabled migration', () => {
  it('is present in scripts/ and ordered after V154', async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf('V154__mock_usage_rate_limits_4420.sql'),
    );
  });

  it('adds mock_enabled and mock_settings on versions', () => {
    expect(lower).toContain('set search_path to apiome, public');
    expect(lower).toContain('alter table versions');
    expect(lower).toContain('mock_enabled boolean not null default false');
    expect(lower).toContain('mock_settings jsonb not null default');
  });
});
