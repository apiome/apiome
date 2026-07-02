/**
 * Ensures buildOpenApiSpecForVersion merges paths into generateOpenApiSpec (single export path).
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';

const mockQuery = jest.fn();

jest.mock('../../lib/db/db', () => ({
  query: (...args: unknown[]) => mockQuery(...args),
}));

jest.mock('bcrypt', () => ({ compare: jest.fn(), hash: jest.fn() }));
jest.mock('crypto', () => ({ randomBytes: jest.fn(() => Buffer.from('test')) }));

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ getAll: () => [] })),
}));

jest.mock('../../lib/db/plan-entitlements', () => ({
  getPlanBlockMessageForNewProject: jest.fn(async () => null),
  getPlanBlockMessageForNewVersion: jest.fn(async () => null),
}));

const mockGenerateOpenApiSpec = jest.fn(async () => '{"openapi":"3.2.0","paths":{"/pets":{}}}');

jest.mock('../../src/app/utils/openapi', () => ({
  generateOpenApiSpec: (...args: unknown[]) => mockGenerateOpenApiSpec(...args),
}));

jest.mock('../../lib/db/helper-paths-export', () => ({
  loadPathsForOpenAPIExport: jest.fn(async () =>
    JSON.stringify({
      success: true,
      paths: [
        {
          pathname: '/pets',
          operations: [{ operation: 'GET', description: { summary: 'List pets' } }],
        },
      ],
    })
  ),
}));

jest.mock('../../lib/db/helper-security-schemes', () => ({
  getSecuritySchemesForVersion: jest.fn(async () => []),
  securitySchemesToOpenAPI: jest.fn(async () => ({})),
}));

jest.mock('../../lib/db/helper-version-servers', () => ({
  getServersForVersion: jest.fn(async () => []),
  serversToOpenAPI: jest.fn(async () => []),
}));

describe('buildOpenApiSpecForVersion', () => {
  beforeEach(() => {
    mockGenerateOpenApiSpec.mockClear();
    mockQuery.mockReset();
    mockQuery
      .mockResolvedValueOnce({
        rows: [{ id: 'class-1', name: 'Pet', description: null, schema: {}, enabled: true }],
      })
      .mockResolvedValueOnce({ rows: [] })
      .mockResolvedValueOnce({ rows: [] });
  });

  it('passes generated paths to generateOpenApiSpec', async () => {
    const helperPaths = require('../../lib/db/helper-paths-export');
    const { buildOpenApiSpecForVersion } = await import('../../lib/db/helper');

    const { specJson, pathsObject } = await buildOpenApiSpecForVersion('ver-1', {
      projectName: 'Pets API',
      versionLabel: '1.0.0',
    });

    expect(helperPaths.loadPathsForOpenAPIExport).toHaveBeenCalledWith('ver-1');
    expect(Object.keys(pathsObject)).toContain('/pets');
    expect(mockGenerateOpenApiSpec).toHaveBeenCalled();
    const pathsArg = mockGenerateOpenApiSpec.mock.calls[0]?.[2];
    expect(pathsArg).toEqual(expect.objectContaining({ '/pets': expect.anything() }));
    expect(JSON.parse(specJson).paths).toEqual({ '/pets': {} });
  });
});
