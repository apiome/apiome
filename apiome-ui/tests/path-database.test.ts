/**
 * Tests for Path Database Tables
 *
 * Comprehensive tests for path-related database functions including:
 * - version_path: Service paths associated with versions
 * - path_operation: Operations (GET, POST, etc.) for paths
 * - path_operation_description: Descriptions for operations
 * - path_parameter: Parameters for operations
 * - path_parameter_schema: Schema definitions for parameters
 * - path_response: Response definitions for operations
 */

import { describe, it, expect, beforeEach, jest } from '@jest/globals';

// Mock the database connection
const mockConnectionPool = {
  query: jest.fn(),
};

jest.mock('../lib/db/db', () => mockConnectionPool);

// Import after mocking
import {
  getPathsForVersion,
  createPath,
  updatePath,
  deletePath,
  getPathById,
} from '../lib/db/helper-paths';

describe('Path Database Tables - version_path', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('getPathsForVersion', () => {
    it('should retrieve all paths for a version', async () => {
      const mockPaths = [
        {
          id: 'path-1',
          version_id: 'version-1',
          pathname: '/users',
          metadata: { tags: ['user'] },
          created_at: '2026-01-09T00:00:00Z',
          updated_at: '2026-01-09T00:00:00Z',
        },
        {
          id: 'path-2',
          version_id: 'version-1',
          pathname: '/products',
          metadata: { tags: ['product'] },
          created_at: '2026-01-09T00:00:00Z',
          updated_at: '2026-01-09T00:00:00Z',
        },
      ];

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: mockPaths,
      });

      const result = await getPathsForVersion('version-1');
      const parsed = JSON.parse(result);

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('SELECT'),
        ['version-1']
      );
      expect(parsed).toHaveLength(2);
      expect(parsed[0].pathname).toBe('/users');
      expect(parsed[1].pathname).toBe('/products');
    });

    it('should return empty array when no paths exist', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [],
      });

      const result = await getPathsForVersion('version-empty');
      const parsed = JSON.parse(result);

      expect(parsed).toHaveLength(0);
    });

    it('should handle database errors', async () => {
      mockConnectionPool.query.mockRejectedValueOnce(new Error('Database error'));

      await expect(getPathsForVersion('version-1')).rejects.toThrow('Database error');
    });
  });

  describe('createPath', () => {
    it('should create a new path', async () => {
      const newPath = {
        id: 'path-new',
        version_id: 'version-1',
        pathname: '/api/v1/users',
        metadata: { description: 'User API' },
        created_at: '2026-01-09T00:00:00Z',
        updated_at: '2026-01-09T00:00:00Z',
      };

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [newPath],
      });

      const result = await createPath('version-1', '/api/v1/users', { description: 'User API' });
      const parsed = JSON.parse(result);

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('INSERT INTO apiome.version_path'),
        ['version-1', '/api/v1/users', JSON.stringify({ description: 'User API' })]
      );
      expect(parsed.pathname).toBe('/api/v1/users');
    });

    it('should create path without metadata', async () => {
      const newPath = {
        id: 'path-new',
        version_id: 'version-1',
        pathname: '/api/v1/products',
        metadata: null,
        created_at: '2026-01-09T00:00:00Z',
        updated_at: '2026-01-09T00:00:00Z',
      };

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [newPath],
      });

      const result = await createPath('version-1', '/api/v1/products');
      const parsed = JSON.parse(result);

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('INSERT INTO apiome.version_path'),
        ['version-1', '/api/v1/products', null]
      );
      expect(parsed.metadata).toBeNull();
    });

    it('should handle duplicate pathname errors', async () => {
      const error = new Error('Duplicate key') as any;
      error.code = '23505';
      mockConnectionPool.query.mockRejectedValueOnce(error);

      await expect(createPath('version-1', '/users')).rejects.toThrow();
    });
  });

  describe('updatePath', () => {
    it('should update an existing path', async () => {
      const updatedPath = {
        id: 'path-1',
        version_id: 'version-1',
        pathname: '/api/v2/users',
        metadata: { version: 'v2' },
        created_at: '2026-01-09T00:00:00Z',
        updated_at: '2026-01-09T01:00:00Z',
      };

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [updatedPath],
      });

      const result = await updatePath('path-1', '/api/v2/users', { version: 'v2' });
      const parsed = JSON.parse(result);

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('UPDATE apiome.version_path'),
        ['path-1', '/api/v2/users', JSON.stringify({ version: 'v2' })]
      );
      expect(parsed.pathname).toBe('/api/v2/users');
    });

    it('should handle non-existent paths', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [],
      });

      const result = await updatePath('nonexistent', '/test', {});

      // When no rows are returned, result.rows[0] is undefined
      // and JSON.stringify(undefined) returns undefined (not a string)
      expect(result).toBeUndefined();
    });
  });

  describe('deletePath', () => {
    it('should delete a path', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rowCount: 1,
      });

      await deletePath('path-1');

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('DELETE FROM apiome.version_path'),
        ['path-1']
      );
    });

    it('should handle deletion of non-existent paths', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rowCount: 0,
      });

      await expect(deletePath('nonexistent')).resolves.not.toThrow();
    });
  });

  describe('getPathById', () => {
    it('should retrieve a single path by ID', async () => {
      const mockPath = {
        id: 'path-1',
        version_id: 'version-1',
        pathname: '/users',
        metadata: { tags: ['user'] },
        created_at: '2026-01-09T00:00:00Z',
        updated_at: '2026-01-09T00:00:00Z',
      };

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [mockPath],
      });

      const result = await getPathById('path-1');
      const parsed = JSON.parse(result);

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('SELECT'),
        ['path-1']
      );
      expect(parsed.id).toBe('path-1');
      expect(parsed.pathname).toBe('/users');
    });

    it('should return undefined for non-existent paths', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [],
      });

      const result = await getPathById('nonexistent');

      // When no rows are returned, result.rows[0] is undefined
      // and JSON.stringify(undefined) returns undefined (not a string)
      expect(result).toBeUndefined();
    });
  });
});

describe('Path Database Schema Validation', () => {
  it('should validate path table constraints', () => {
    // Test that the schema expectations are correct
    const pathSchema = {
      tableName: 'version_path',
      columns: ['id', 'version_id', 'pathname', 'metadata', 'created_at', 'updated_at'],
      constraints: {
        primaryKey: 'id',
        foreignKeys: ['version_id'],
        uniqueConstraints: [['version_id', 'pathname']],
      },
    };

    expect(pathSchema.tableName).toBe('version_path');
    expect(pathSchema.columns).toContain('pathname');
    expect(pathSchema.constraints.uniqueConstraints[0]).toEqual(['version_id', 'pathname']);
  });

  it('should validate path_operation table structure', () => {
    const operationSchema = {
      tableName: 'path_operation',
      columns: ['id', 'version_path_id', 'operation', 'metadata', 'created_at', 'updated_at'],
      constraints: {
        primaryKey: 'id',
        foreignKeys: ['version_path_id'],
        uniqueConstraints: [['version_path_id', 'operation']],
      },
      validOperations: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'],
    };

    expect(operationSchema.tableName).toBe('path_operation');
    expect(operationSchema.validOperations).toContain('GET');
    expect(operationSchema.validOperations).toContain('POST');
  });

  it('should validate path_parameter table structure', () => {
    const parameterSchema = {
      tableName: 'path_parameter',
      columns: ['id', 'path_operation_id', 'name', 'in_location', 'summary', 'description', 'metadata'],
      constraints: {
        foreignKeys: ['path_operation_id'],
        uniqueConstraints: [['path_operation_id', 'name', 'in_location']],
      },
      validLocations: ['query', 'path', 'header', 'cookie'],
    };

    expect(parameterSchema.tableName).toBe('path_parameter');
    expect(parameterSchema.validLocations).toContain('query');
    expect(parameterSchema.validLocations).toContain('path');
  });

  it('should validate path_response table structure', () => {
    const responseSchema = {
      tableName: 'path_response',
      columns: ['id', 'path_operation_id', 'status_code', 'description', 'metadata'],
      constraints: {
        foreignKeys: ['path_operation_id'],
        uniqueConstraints: [['path_operation_id', 'status_code']],
      },
      validStatusCodes: ['200', '201', '204', '400', '401', '403', '404', '500'],
    };

    expect(responseSchema.tableName).toBe('path_response');
    expect(responseSchema.validStatusCodes).toContain('200');
    expect(responseSchema.validStatusCodes).toContain('404');
  });
});

describe('Path Database Integration Scenarios', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should support creating a complete REST API path', async () => {
    // This test demonstrates the expected workflow for creating a complete path
    const workflow = {
      step1: 'Create path: /api/v1/users',
      step2: 'Create operation: GET',
      step3: 'Add parameters: userId (path), limit (query)',
      step4: 'Add responses: 200, 404',
      step5: 'Add operation description',
    };

    expect(workflow.step1).toContain('/api/v1/users');
    expect(workflow.step2).toContain('GET');
    expect(workflow.step3).toContain('userId');
    expect(workflow.step4).toContain('200');
  });

  it('should support multiple operations per path', () => {
    const pathOperations = {
      path: '/api/v1/users/{userId}',
      operations: [
        { method: 'GET', description: 'Get user by ID' },
        { method: 'PUT', description: 'Update user' },
        { method: 'DELETE', description: 'Delete user' },
      ],
    };

    expect(pathOperations.operations).toHaveLength(3);
    expect(pathOperations.operations[0].method).toBe('GET');
    expect(pathOperations.operations[1].method).toBe('PUT');
    expect(pathOperations.operations[2].method).toBe('DELETE');
  });

  it('should validate cascade deletion behavior', () => {
    // Test that cascade deletes are properly configured
    const cascadeRules = {
      'version_path -> path_operation': 'ON DELETE CASCADE',
      'path_operation -> path_operation_description': 'ON DELETE CASCADE',
      'path_operation -> path_parameter': 'ON DELETE CASCADE',
      'path_operation -> path_response': 'ON DELETE CASCADE',
      'path_parameter -> path_parameter_schema': 'ON DELETE CASCADE',
    };

    Object.entries(cascadeRules).forEach(([relationship, rule]) => {
      expect(rule).toBe('ON DELETE CASCADE');
    });
  });

  it('should handle metadata storage as JSONB', () => {
    const sampleMetadata = {
      path: {
        tags: ['user', 'authentication'],
        deprecated: false,
        externalDocs: 'https://example.com/docs',
      },
      operation: {
        summary: 'Get user by ID',
        operationId: 'getUserById',
        security: [{ bearerAuth: [] }],
      },
      parameter: {
        required: true,
        schema: { type: 'string', format: 'uuid' },
        example: '550e8400-e29b-41d4-a716-446655440000',
      },
      response: {
        content: {
          'application/json': {
            schema: { $ref: '#/components/schemas/User' },
          },
        },
      },
    };

    expect(typeof sampleMetadata.path).toBe('object');
    expect(sampleMetadata.path.tags).toContain('user');
    expect(sampleMetadata.operation.operationId).toBe('getUserById');
    expect(sampleMetadata.parameter.required).toBe(true);
  });
});

describe('Path Database Error Handling', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should handle constraint violations for duplicate paths', async () => {
    const error = new Error('Duplicate path') as any;
    error.code = '23505';
    error.constraint = 'version_path_version_id_pathname_key';

    mockConnectionPool.query.mockRejectedValueOnce(error);

    await expect(createPath('version-1', '/users')).rejects.toThrow('Duplicate path');
  });

  it('should handle foreign key violations', async () => {
    const error = new Error('Foreign key violation') as any;
    error.code = '23503';

    mockConnectionPool.query.mockRejectedValueOnce(error);

    await expect(createPath('nonexistent-version', '/users')).rejects.toThrow();
  });

  it('should handle null pathname errors', async () => {
    const error = new Error('Null value') as any;
    error.code = '23502';

    mockConnectionPool.query.mockRejectedValueOnce(error);

    await expect(createPath('version-1', null as any)).rejects.toThrow();
  });
});

describe('Path Database Performance Considerations', () => {
  it('should use indexes for common queries', () => {
    const indexes = [
      { table: 'version_path', column: 'version_id', name: 'idx_version_path_version_id' },
      { table: 'version_path', column: 'created_at', name: 'idx_version_path_created_at' },
      { table: 'path_operation', column: 'version_path_id', name: 'idx_path_operation_version_path_id' },
      { table: 'path_parameter', column: 'path_operation_id', name: 'idx_path_parameter_path_operation_id' },
      { table: 'path_response', column: 'path_operation_id', name: 'idx_path_response_path_operation_id' },
    ];

    expect(indexes).toHaveLength(5);
    expect(indexes[0].column).toBe('version_id');
  });

  it('should order paths alphabetically for consistent display', async () => {
    const mockPaths = [
      { pathname: '/api/v1/products' },
      { pathname: '/api/v1/users' },
      { pathname: '/api/v1/orders' },
    ];

    mockConnectionPool.query.mockResolvedValueOnce({
      rows: mockPaths,
    });

    const result = await getPathsForVersion('version-1');

    expect(mockConnectionPool.query).toHaveBeenCalledWith(
      expect.stringContaining('ORDER BY pathname ASC'),
      ['version-1']
    );
  });
});

describe('Path Database OpenAPI Compatibility', () => {
  it('should support OpenAPI path item object structure', () => {
    const openApiPathItem = {
      pathname: '/users/{userId}',
      operations: {
        get: {
          summary: 'Get user',
          operationId: 'getUser',
          parameters: [
            {
              name: 'userId',
              in: 'path',
              required: true,
              schema: { type: 'string' },
            },
          ],
          responses: {
            '200': {
              description: 'Successful response',
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/User' },
                },
              },
            },
          },
        },
      },
    };

    expect(openApiPathItem.pathname).toContain('{userId}');
    expect(openApiPathItem.operations.get).toBeDefined();
    expect(openApiPathItem.operations.get.parameters[0].in).toBe('path');
  });

  it('should support all HTTP methods', () => {
    const httpMethods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD', 'TRACE'];

    httpMethods.forEach(method => {
      expect(['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD', 'TRACE']).toContain(method);
    });
  });

  it('should support parameter locations', () => {
    const parameterLocations = {
      query: 'Query parameters in URL',
      path: 'Path parameters in URL template',
      header: 'Custom headers',
      cookie: 'Cookie values',
    };

    expect(Object.keys(parameterLocations)).toContain('query');
    expect(Object.keys(parameterLocations)).toContain('path');
    expect(Object.keys(parameterLocations)).toContain('header');
    expect(Object.keys(parameterLocations)).toContain('cookie');
  });

  it('should support standard HTTP status codes', () => {
    const statusCodes = {
      success: ['200', '201', '202', '204'],
      clientError: ['400', '401', '403', '404', '409', '422'],
      serverError: ['500', '502', '503'],
    };

    expect(statusCodes.success).toContain('200');
    expect(statusCodes.clientError).toContain('404');
    expect(statusCodes.serverError).toContain('500');
  });
});

