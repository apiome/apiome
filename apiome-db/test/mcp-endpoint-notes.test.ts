/**
 * Structural assertions over the MCP cataloger notes migration (#4666, V2-MCP-36.3 / MCAT-22.3).
 */

import fs from 'node:fs/promises';
import path from 'node:path';

import { beforeAll, describe, expect, it } from 'vitest';

import { listMigrationFiles } from '../src/migrate.js';

const SCRIPTS_DIR = new URL('../scripts', import.meta.url).pathname;
const MIGRATION = 'V151__mcp_endpoint_notes_4666.sql';

let sql = '';
let lower = '';

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), 'utf8');
  lower = sql.toLowerCase();
});

describe('MCP cataloger notes migration', () => {
  it('is present in scripts/ and ordered after V150', async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf('V150__mcp_saved_searches_4662.sql'),
    );
  });

  it('creates the table idempotently in the apiome schema', () => {
    expect(lower).toContain('set search_path to apiome, public');
    expect(lower).toMatch(/create table if not exists mcp_endpoint_notes/);
  });

  it('defines tenant + endpoint scope with author audit columns', () => {
    for (const col of [
      'id',
      'tenant_id',
      'endpoint_id',
      'body',
      'created_by',
      'updated_by',
      'created_at',
      'updated_at',
    ]) {
      expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, 'm'));
    }
    expect(lower).toMatch(/tenant_id uuid not null references tenants\(id\) on delete cascade/);
    expect(lower).toMatch(
      /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
    );
    expect(lower).toMatch(/created_by uuid not null references users\(id\) on delete restrict/);
  });

  it('rejects empty note bodies', () => {
    expect(lower).toMatch(/check \(char_length\(trim\(body\)\) > 0\)/);
  });
});
