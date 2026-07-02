import { describe, it, expect } from '@jest/globals';
import {
  validateOpenAPISemantics,
  type OpenAPIExportIssue,
} from '../../src/app/utils/openapi-export-validation';

function collect(spec: Record<string, unknown>): OpenAPIExportIssue[] {
  return validateOpenAPISemantics(spec);
}

describe('validateOpenAPISemantics', () => {
  it('reports duplicate operationId as error', () => {
    const spec: Record<string, unknown> = {
      openapi: '3.2.0',
      info: { title: 'T', version: '1' },
      paths: {
        '/a': {
          get: { operationId: 'dup', responses: { '200': { description: 'ok' } } },
        },
        '/b': {
          get: { operationId: 'dup', responses: { '200': { description: 'ok' } } },
        },
      },
      components: { schemas: {} },
    };
    const issues = collect(spec);
    expect(issues.some((i) => i.severity === 'error' && i.message.includes('Duplicate operationId'))).toBe(true);
  });

  it('reports missing path parameter for template segment as error', () => {
    const spec: Record<string, unknown> = {
      openapi: '3.2.0',
      info: { title: 'T', version: '1' },
      paths: {
        '/items/{id}': {
          get: {
            responses: { '200': { description: 'ok' } },
          },
        },
      },
      components: { schemas: {} },
    };
    const issues = collect(spec);
    expect(issues.some((i) => i.severity === 'error' && i.message.includes('{id}'))).toBe(true);
  });

  it('reports unresolved local $ref as error', () => {
    const spec: Record<string, unknown> = {
      openapi: '3.2.0',
      info: { title: 'T', version: '1' },
      paths: {
        '/x': {
          get: {
            responses: {
              '200': {
                description: 'ok',
                content: { 'application/json': { schema: { $ref: '#/components/schemas/Missing' } } },
              },
            },
          },
        },
      },
      components: { schemas: { Other: { type: 'object' } } },
    };
    const issues = collect(spec);
    expect(issues.some((i) => i.severity === 'error' && i.message.includes('Unresolved local $ref'))).toBe(true);
  });

  it('warns when operation has no summary or description', () => {
    const spec: Record<string, unknown> = {
      openapi: '3.2.0',
      info: { title: 'T', version: '1' },
      paths: {
        '/z': {
          get: {
            responses: { '200': { description: 'ok' } },
          },
        },
      },
      components: { schemas: {} },
    };
    const issues = collect(spec);
    expect(issues.some((i) => i.severity === 'warning' && i.message.includes('no summary or description'))).toBe(
      true
    );
  });
});
