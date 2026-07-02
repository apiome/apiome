/**
 * Integration tests for the OpenAPI 3.2.0 normalization layer (OA2, #3499).
 *
 * Verifies a 3.2.0 document carrying 3.2-only constructs is normalized and imported
 * successfully, that the carried-forward constructs are surfaced (never silently
 * dropped), and that a 3.2.0 doc and its hand-written 3.1 equivalent produce identical
 * imported classes/properties.
 */

import { parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { analyzeSpecification } from '../src/app/utils/openapi-analyzer';

/** A 3.2.0 document exercising the OA3–OA6 constructs plus the safe normalizations. */
const SPEC_32 = JSON.stringify({
  openapi: '3.2.0',
  info: { title: 'Constructs API', version: '1.0.0', description: 'Exercises 3.2-only constructs.' },
  servers: [{ url: 'https://api.example.com' }],
  tags: [
    { name: 'pets', summary: 'Pet operations', parent: 'store', kind: 'nav' },
    { name: 'store' }
  ],
  paths: {
    '/pets': {
      get: {
        operationId: 'listPets',
        tags: ['pets'],
        responses: {
          '200': {
            description: 'A list of pets',
            content: {
              'application/json': {
                schema: { type: 'array', items: { $ref: '#/components/schemas/Pet' } },
                example: [{ id: '1', name: 'Rex' }]
              }
            }
          }
        }
      },
      // OA4: custom HTTP methods map.
      additionalOperations: {
        PURGE: { operationId: 'purgePets', responses: { '204': { description: 'purged' } } }
      }
    },
    // OA4: the QUERY HTTP method.
    '/pets/search': {
      query: {
        operationId: 'searchPets',
        responses: { '200': { description: 'results' } }
      }
    },
    // OA3: sequential media types / itemSchema.
    '/pets/events': {
      get: {
        operationId: 'streamPets',
        responses: {
          '200': {
            description: 'event stream',
            content: {
              'text/event-stream': {
                itemSchema: { $ref: '#/components/schemas/Pet' }
              }
            }
          }
        }
      }
    }
  },
  components: {
    securitySchemes: {
      apiKey: { type: 'apiKey', in: 'header', name: 'X-API-Key' }
    },
    schemas: {
      Pet: {
        type: 'object',
        description: 'A pet.',
        required: ['id', 'name'],
        properties: {
          id: { type: 'string', description: 'Identifier.', xml: { nodeType: 'attribute' } },
          name: { type: 'string', description: 'Name.' },
          // OA6: $ref sibling metadata.
          category: { $ref: '#/components/schemas/Category', description: 'The pet category.' }
        }
      },
      Category: {
        type: 'object',
        description: 'A category.',
        properties: {
          name: { type: 'string', description: 'Category name.' }
        }
      }
    }
  }
});

/** The hand-written 3.1 equivalent: same schemas, no 3.2-only constructs. */
const SPEC_31 = JSON.stringify({
  openapi: '3.1.0',
  info: { title: 'Constructs API', version: '1.0.0', description: 'Exercises 3.2-only constructs.' },
  servers: [{ url: 'https://api.example.com' }],
  paths: {
    '/pets': {
      get: {
        operationId: 'listPets',
        responses: {
          '200': {
            description: 'A list of pets',
            content: {
              'application/json': {
                schema: { type: 'array', items: { $ref: '#/components/schemas/Pet' } }
              }
            }
          }
        }
      }
    }
  },
  components: {
    securitySchemes: {
      apiKey: { type: 'apiKey', in: 'header', name: 'X-API-Key' }
    },
    schemas: {
      Pet: {
        type: 'object',
        description: 'A pet.',
        required: ['id', 'name'],
        properties: {
          id: { type: 'string', description: 'Identifier.', xml: { attribute: true } },
          name: { type: 'string', description: 'Name.' },
          category: { $ref: '#/components/schemas/Category', description: 'The pet category.' }
        }
      },
      Category: {
        type: 'object',
        description: 'A category.',
        properties: {
          name: { type: 'string', description: 'Category name.' }
        }
      }
    }
  }
});

describe('OpenAPI 3.2 import integration (OA2 #3499)', () => {
  it('imports a 3.2.0 document with 3.2-only constructs successfully', () => {
    const result = parseOpenAPISpec(SPEC_32);

    expect(result.success).toBe(true);
    expect(result.error).toBeUndefined();

    const pet = result.classes.find((c) => c.name === 'Pet');
    expect(pet).toBeDefined();
    const propNames = pet?.properties.map((p) => p.name) ?? [];
    expect(propNames).toEqual(expect.arrayContaining(['id', 'name', 'category']));

    expect(result.classes.find((c) => c.name === 'Category')).toBeDefined();
  });

  it('surfaces carried-forward constructs in the import warnings (never silently dropped)', () => {
    const result = parseOpenAPISpec(SPEC_32);
    const joined = result.warnings.join('\n');
    expect(joined).toMatch(/Normalized OpenAPI 3\.2/);
    expect(joined).toMatch(/additionalOperations/i);
    expect(joined).toMatch(/QUERY/i);
    expect(joined).toMatch(/itemSchema/i);
  });

  it('produces the same classes/properties as the hand-written 3.1 equivalent (round-trip)', () => {
    const result32 = parseOpenAPISpec(SPEC_32);
    const result31 = parseOpenAPISpec(SPEC_31);

    const shape = (r: ReturnType<typeof parseOpenAPISpec>) =>
      r.classes
        .map((c) => ({ name: c.name, props: c.properties.map((p) => p.name).sort() }))
        .sort((a, b) => a.name.localeCompare(b.name));

    expect(shape(result32)).toEqual(shape(result31));
  });

  it('analyzer keeps the 3.2.0 version display and surfaces 3.2 constructs as unsupported features', async () => {
    const analysis = await analyzeSpecification(SPEC_32, 'constructs-3.2.json');

    // OA1 behavior preserved: still reported as 3.2.0.
    expect(analysis.version).toBe('3.2.0');
    expect(analysis.formatDisplayName).toContain('3.2.0');

    // 3.2-only constructs are surfaced for the pre-import compatibility check.
    const ids = analysis.unsupportedFeatures.map((f) => f.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        'openapi32-additional-operations',
        'openapi32-query-method',
        'openapi32-item-schema',
        'openapi32-tag-metadata'
      ])
    );
  });
});
