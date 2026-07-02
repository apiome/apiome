import { describe, it, expect } from '@jest/globals';
import {
  computePathQuality,
  pathQualityHasOperations,
} from '@/app/utils/path-quality';

describe('path-quality', () => {
  it('returns no operations when paths are empty', () => {
    expect(pathQualityHasOperations({})).toBe(false);
    const d = computePathQuality({}, { openapi: '3.1.0', paths: {} });
    expect(d.overall).toBe(0);
    expect(d.issues).toEqual([]);
  });

  it('scores a minimal valid operation highly', () => {
    const paths = {
      '/pets': {
        get: {
          operationId: 'listPets',
          summary: 'List pets',
          responses: {
            '200': {
              description: 'OK',
              content: { 'application/json': { schema: { type: 'array', items: { type: 'string' } } } },
            },
            '400': { description: 'Bad request' },
          },
        },
      },
    };
    expect(pathQualityHasOperations(paths)).toBe(true);
    const merged = {
      openapi: '3.1.0',
      paths,
      components: { schemas: {} },
    };
    const d = computePathQuality(paths, merged);
    expect(d.overall).toBeGreaterThanOrEqual(85);
    expect(d.issues.filter((i) => !i.message.includes('Duplicate'))).toHaveLength(0);
  });

  it('flags missing operationId and missing error response', () => {
    const paths = {
      '/x': {
        post: {
          summary: 'Do thing',
          responses: {
            '200': {
              description: 'ok',
              content: { 'application/json': { schema: { type: 'object' } } },
            },
          },
        },
      },
    };
    const d = computePathQuality(paths, { openapi: '3.1.0', paths, components: {} });
    expect(d.issues.some((i) => i.message.includes('operationId'))).toBe(true);
    expect(d.issues.some((i) => i.message.includes('4xx/5xx'))).toBe(true);
  });

  it('detects broken schema $ref against merged spec', () => {
    const paths = {
      '/a': {
        get: {
          operationId: 'getA',
          summary: 'A',
          responses: {
            '200': {
              description: 'ok',
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/Missing' },
                },
              },
            },
            '404': { description: 'missing' },
          },
        },
      },
    };
    const d = computePathQuality(paths, {
      openapi: '3.1.0',
      paths,
      components: { schemas: { Other: { type: 'string' } } },
    });
    expect(d.issues.some((i) => i.message.includes('Broken $ref'))).toBe(true);
  });

  it('resolves valid $ref in merged spec', () => {
    const paths = {
      '/a': {
        get: {
          operationId: 'getA',
          summary: 'A',
          responses: {
            '200': {
              description: 'ok',
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/Pet' },
                },
              },
            },
            '404': { description: 'missing' },
          },
        },
      },
    };
    const d = computePathQuality(paths, {
      openapi: '3.1.0',
      paths,
      components: { schemas: { Pet: { type: 'object' } } },
    });
    expect(d.issues.filter((i) => i.message.includes('$ref'))).toHaveLength(0);
  });
});
