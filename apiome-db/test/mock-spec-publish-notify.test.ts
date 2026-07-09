/**
 * Structural assertions over mock spec publish NOTIFY migration (#4416, SIM-1.1).
 */

import fs from 'node:fs/promises';
import path from 'node:path';

import { beforeAll, describe, expect, it } from 'vitest';

import { listMigrationFiles } from '../src/migrate.js';

const SCRIPTS_DIR = new URL('../scripts', import.meta.url).pathname;
const MIGRATION = 'V153__mock_spec_publish_notify_4416.sql';

let sql = '';
let lower = '';

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), 'utf8');
  lower = sql.toLowerCase();
});

describe('mock spec publish notify migration', () => {
  it('is present in scripts/ and ordered after V152', async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf('V152__mcp_collections_4667.sql'),
    );
  });

  it('defines NOTIFY trigger on published versions', () => {
    expect(lower).toContain('set search_path to apiome, public');
    expect(lower).toMatch(/create or replace function apiome\.notify_mock_spec_published/);
    expect(lower).toMatch(/pg_notify\(\s*'apiome_mock_spec_published'/);
    expect(lower).toMatch(
      /create trigger trigger_versions_notify_mock_spec_published[\s\S]*on apiome\.versions/,
    );
  });
});
