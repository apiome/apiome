import { describe, it, expect } from '@jest/globals';
import {
  MIGRATION_GUIDE_DOC_TEMPLATE_VERSION,
  generateMigrationGuideMarkdown,
  generateMigrationGuideMarkdownFromSummary,
} from '../lib/migration-guide-doc';
import { BREAKING_CHANGES_DOC_TEMPLATE_ID } from '../lib/breaking-changes-doc';
import { compareSchemas } from '../lib/schema-diff';

describe('migration-guide-doc', () => {
  it('generateMigrationGuideMarkdown is deterministic for the same specs', () => {
    const a = {
      components: {
        schemas: {
          A: { type: 'object', properties: { x: { type: 'string' } } },
        },
      },
    };
    const b = {
      components: {
        schemas: {
          A: { type: 'object', properties: { x: { type: 'number' } } },
        },
      },
    };
    const once = generateMigrationGuideMarkdown(a, b, {
      baseLabel: 'v1',
      targetLabel: 'v2',
      baseRevisionId: 'r1',
      targetRevisionId: 'r2',
    });
    const twice = generateMigrationGuideMarkdown(a, b, {
      baseLabel: 'v1',
      targetLabel: 'v2',
      baseRevisionId: 'r1',
      targetRevisionId: 'r2',
    });
    expect(once).toBe(twice);
    expect(once).toContain(`v${MIGRATION_GUIDE_DOC_TEMPLATE_VERSION}`);
    expect(once).toContain('`r1` → `r2`');
    expect(once).toContain(BREAKING_CHANGES_DOC_TEMPLATE_ID);
    expect(once).toContain('### Step 1');
  });

  it('embeds changelog breaking hints when provided', () => {
    const base = { components: { schemas: {} } };
    const head = {
      components: {
        schemas: {
          N: { type: 'object', properties: { p: { type: 'string' } } },
        },
      },
    };
    const summary = compareSchemas(base, head);
    const doc = generateMigrationGuideMarkdownFromSummary(summary, {
      breakingHintsFromChangelog: ['breaking: removed legacy endpoint'],
    });
    expect(doc).toContain('## Author notes (from version changelog)');
    expect(doc).toContain('removed legacy endpoint');
  });

  it('reports no steps when diff has no breaking items', () => {
    const base = {
      components: {
        schemas: {
          U: { type: 'object', properties: { n: { type: 'string', description: 'a' } } },
        },
      },
    };
    const head = {
      components: {
        schemas: {
          U: { type: 'object', properties: { n: { type: 'string', description: 'b' } } },
        },
      },
    };
    const summary = compareSchemas(base, head);
    const doc = generateMigrationGuideMarkdownFromSummary(summary);
    expect(doc).toContain('No breaking changes were detected');
    expect(doc).not.toContain('### Step 1');
  });
});
