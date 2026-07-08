/**
 * Structural assertions over the MCP catalog collections migration (#4667, V2-MCP-36.4 / MCAT-22.4).
 */

import fs from 'node:fs/promises';
import path from 'node:path';

import { beforeAll, describe, expect, it } from 'vitest';

import { listMigrationFiles } from '../src/migrate.js';

const SCRIPTS_DIR = new URL('../scripts', import.meta.url).pathname;
const MIGRATION = 'V152__mcp_collections_4667.sql';

let sql = '';
let lower = '';

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), 'utf8');
  lower = sql.toLowerCase();
});

describe('MCP catalog collections migration', () => {
  it('is present in scripts/ and ordered after V151', async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf('V151__mcp_endpoint_notes_4666.sql'),
    );
  });

  it('creates collection tables idempotently in the apiome schema', () => {
    expect(lower).toContain('set search_path to apiome, public');
    expect(lower).toMatch(/create table if not exists mcp_collections/);
    expect(lower).toMatch(/create table if not exists mcp_collection_members/);
  });

  it('defines tenant scope, publish flag, and author audit on collections', () => {
    for (const col of [
      'id',
      'tenant_id',
      'name',
      'slug',
      'description',
      'is_published',
      'created_by',
      'created_at',
      'updated_at',
    ]) {
      expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, 'm'));
    }
    expect(lower).toMatch(/tenant_id uuid not null references tenants\(id\) on delete cascade/);
    expect(lower).toMatch(/created_by uuid not null references users\(id\) on delete restrict/);
    expect(lower).toMatch(/constraint mcp_collections_tenant_slug_unique unique \(tenant_id, slug\)/);
  });

  it('defines many-to-many membership with ordering', () => {
    expect(lower).toMatch(/primary key \(collection_id, endpoint_id\)/);
    expect(lower).toMatch(
      /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
    );
    expect(sql).toMatch(/^\s+position INT NOT NULL DEFAULT 0/m);
  });
});
