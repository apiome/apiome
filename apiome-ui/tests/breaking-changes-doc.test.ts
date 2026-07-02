import { describe, it, expect } from '@jest/globals';
import {
  BREAKING_CHANGES_DOC_TEMPLATE_VERSION,
  buildBreakingChangesBullets,
  generateBreakingChangesMarkdown,
  generateBreakingChangesMarkdownFromSummary,
  stableOpenApiComponentId,
} from '../lib/breaking-changes-doc';
import { compareSchemas } from '../lib/schema-diff';

describe('breaking-changes-doc', () => {
  it('stableOpenApiComponentId prefixes components', () => {
    expect(stableOpenApiComponentId('schemas.Pet.properties.name')).toBe(
      'components.schemas.Pet.properties.name'
    );
  });

  it('generateBreakingChangesMarkdown is deterministic for the same specs', () => {
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
    const once = generateBreakingChangesMarkdown(a, b, { baseLabel: 'v1', targetLabel: 'v2' });
    const twice = generateBreakingChangesMarkdown(a, b, { baseLabel: 'v1', targetLabel: 'v2' });
    expect(once).toBe(twice);
    expect(once).toContain(`v${BREAKING_CHANGES_DOC_TEMPLATE_VERSION}`);
    expect(once).toContain('## Breaking');
    expect(once).toContain('## Additions');
    expect(once).toContain('## Other');
  });

  it('classifies removed property as breaking and dedupes under removed schema', () => {
    const base = {
      components: {
        schemas: {
          Box: {
            type: 'object',
            properties: { a: { type: 'string' }, b: { type: 'string' } },
          },
        },
      },
    };
    const head = { components: { schemas: {} } };
    const summary = compareSchemas(base, head);
    const bullets = buildBreakingChangesBullets(summary);
    const ids = bullets.map((x) => x.stableId);
    expect(ids.filter((id) => id.includes('Box.properties')).length).toBe(0);
    expect(bullets.some((b) => b.category === 'breaking' && b.stableId.endsWith('schemas.Box'))).toBe(
      true
    );
  });

  it('classifies new schema as additions (not each property under it)', () => {
    const base = { components: { schemas: {} } };
    const head = {
      components: {
        schemas: {
          NewThing: {
            type: 'object',
            properties: { p: { type: 'string' }, q: { type: 'integer' } },
          },
        },
      },
    };
    const summary = compareSchemas(base, head);
    const bullets = buildBreakingChangesBullets(summary);
    const additions = bullets.filter((b) => b.category === 'additions');
    expect(additions.length).toBe(1);
    expect(additions[0].stableId).toBe('components.schemas.NewThing');
  });

  it('classifies description-only property change as other', () => {
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
    const doc = generateBreakingChangesMarkdownFromSummary(summary);
    expect(doc).toContain('## Other');
    expect(doc).toMatch(/`components\.schemas\.U\.properties\.n`/);
    const breaking = buildBreakingChangesBullets(summary).filter((b) => b.category === 'breaking');
    expect(breaking.length).toBe(0);
  });
});
