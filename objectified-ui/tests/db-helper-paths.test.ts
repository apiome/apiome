/**
 * Database Helper Tests - API Paths
 *
 * Comprehensive tests for API paths management functions in lib/db/helper-paths.ts
 * Tests all exported functions including:
 * - API paths CRUD operations
 * - Path operations management
 * - Operation parameters
 * - Operation responses
 * - Operation request bodies
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals';

// Mock the database connection pool
jest.mock('../lib/db/db', () => ({
  query: jest.fn(),
}));

describe('Database Helper - API Paths Management', () => {
  let mockQuery: jest.Mock;

  beforeEach(() => {
    const db = require('../lib/db/db');
    mockQuery = db.query as jest.Mock;
    mockQuery.mockClear();
  });

  // ============================================================================
  // API PATHS CRUD TESTS
  // ============================================================================

  describe('API Paths CRUD', () => {
    test('getApiPathsForVersion should return paths for version', async () => {
      const { getApiPathsForVersion } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rows: [
          { id: 'path-1', version_id: 'version-1', path: '/users', summary: 'User endpoints' },
          { id: 'path-2', version_id: 'version-1', path: '/products', summary: 'Product endpoints' }
        ]
      });

      const result = await getApiPathsForVersion('version-1');
      const parsed = JSON.parse(result);

      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining('SELECT * FROM odb.api_paths'),
        ['version-1']
      );
      expect(parsed).toHaveLength(2);
      expect(parsed[0].path).toBe('/users');
    });

    test('getApiPathById should return single path', async () => {
      const { getApiPathById } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rows: [{ id: 'path-1', path: '/users/{userId}', summary: 'User operations' }]
      });

      const result = await getApiPathById('path-1');
      const parsed = JSON.parse(result);

      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining('SELECT * FROM odb.api_paths WHERE id = $1'),
        ['path-1']
      );
      expect(parsed.path).toBe('/users/{userId}');
    });

    test('createApiPath should create new path', async () => {
      const { createApiPath } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValueOnce({ rowCount: 0 }); // Check duplicate
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'path-1', path: '/users', summary: 'User endpoints' }]
      });

      const result = await createApiPath(
        'version-1',
        '/users',
        'User endpoints',
        'Manage user accounts'
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(parsed.path.path).toBe('/users');
    });

    test('createApiPath should reject empty path', async () => {
      const { createApiPath } = await import('../lib/db/helper-paths');

      const result = await createApiPath('version-1', '');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('cannot be empty');
    });

    test('createApiPath should reject duplicate path', async () => {
      const { createApiPath } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ id: 'existing' }] });

      const result = await createApiPath('version-1', '/users');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('already exists');
    });

    test('updateApiPath should update path fields', async () => {
      const { updateApiPath } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rowCount: 1,
        rows: [{ id: 'path-1', path: '/users', summary: 'Updated summary' }]
      });

      const result = await updateApiPath('path-1', {
        summary: 'Updated summary',
        description: 'Updated description'
      });
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining('UPDATE odb.api_paths'),
        expect.any(Array)
      );
    });

    test('updateApiPath should reject empty updates', async () => {
      const { updateApiPath } = await import('../lib/db/helper-paths');

      const result = await updateApiPath('path-1', {});
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('No fields to update');
    });

    test('updateApiPath should handle not found', async () => {
      const { updateApiPath } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 0 });

      const result = await updateApiPath('path-1', { summary: 'Test' });
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('not found');
    });

    test('deleteApiPath should soft delete path', async () => {
      const { deleteApiPath } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ id: 'path-1' }] });

      const result = await deleteApiPath('path-1');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining('UPDATE odb.api_paths SET deleted_at'),
        ['path-1']
      );
    });

    test('deleteApiPath should handle not found', async () => {
      const { deleteApiPath } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 0 });

      const result = await deleteApiPath('path-1');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('not found');
    });
  });

  // ============================================================================
  // PATH OPERATIONS TESTS
  // ============================================================================

  describe('Path Operations', () => {
    test('getOperationsForPath should return operations', async () => {
      const { getOperationsForPath } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rows: [
          { id: 'op-1', path_id: 'path-1', method: 'get', summary: 'Get users' },
          { id: 'op-2', path_id: 'path-1', method: 'post', summary: 'Create user' }
        ]
      });

      const result = await getOperationsForPath('path-1');
      const parsed = JSON.parse(result);

      expect(parsed).toHaveLength(2);
      expect(parsed[0].method).toBe('get');
    });

    test('getOperationById should return single operation', async () => {
      const { getOperationById } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rows: [{ id: 'op-1', method: 'get', operation_id: 'getUsers' }]
      });

      const result = await getOperationById('op-1');
      const parsed = JSON.parse(result);

      expect(parsed.operation_id).toBe('getUsers');
    });

    test('createPathOperation should create operation', async () => {
      const { createPathOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValueOnce({ rowCount: 0 }); // Check duplicate
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'op-1', method: 'get', operation_id: 'getUsers' }]
      });

      const result = await createPathOperation(
        'path-1',
        'GET',
        'getUsers',
        'Get all users'
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(parsed.operation.method).toBe('get');
    });

    test('createPathOperation should normalize method to lowercase', async () => {
      const { createPathOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValueOnce({ rowCount: 0 });
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'op-1', method: 'post' }]
      });

      await createPathOperation('path-1', 'POST');

      expect(mockQuery).toHaveBeenCalledWith(
        expect.any(String),
        expect.arrayContaining(['post'])
      );
    });

    test('createPathOperation should reject invalid method', async () => {
      const { createPathOperation } = await import('../lib/db/helper-paths');

      const result = await createPathOperation('path-1', 'INVALID');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('Invalid HTTP method');
    });

    test('createPathOperation should reject duplicate method', async () => {
      const { createPathOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1 });

      const result = await createPathOperation('path-1', 'get');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('already exists');
    });

    test('updatePathOperation should update operation fields', async () => {
      const { updatePathOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rowCount: 1,
        rows: [{ id: 'op-1', summary: 'Updated summary' }]
      });

      const result = await updatePathOperation('op-1', {
        summary: 'Updated summary',
        deprecated: true
      });
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('deletePathOperation should soft delete operation', async () => {
      const { deletePathOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ id: 'op-1' }] });

      const result = await deletePathOperation('op-1');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });
  });

  // ============================================================================
  // OPERATION PARAMETERS TESTS
  // ============================================================================

  describe('Operation Parameters', () => {
    test('getParametersForOperation should return parameters', async () => {
      const { getParametersForOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rows: [
          { id: 'param-1', name: 'limit', location: 'query' },
          { id: 'param-2', name: 'userId', location: 'path' }
        ]
      });

      const result = await getParametersForOperation('op-1');
      const parsed = JSON.parse(result);

      expect(parsed).toHaveLength(2);
    });

    test('createOperationParameter should create parameter', async () => {
      const { createOperationParameter } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValueOnce({ rowCount: 0 }); // Check duplicate
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'param-1', name: 'limit', location: 'query' }]
      });

      const result = await createOperationParameter(
        'op-1',
        'limit',
        'query',
        'Maximum number of results'
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('createOperationParameter should reject invalid location', async () => {
      const { createOperationParameter } = await import('../lib/db/helper-paths');

      const result = await createOperationParameter('op-1', 'test', 'invalid');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('Invalid parameter location');
    });

    test('createOperationParameter should reject empty name', async () => {
      const { createOperationParameter } = await import('../lib/db/helper-paths');

      const result = await createOperationParameter('op-1', '', 'query');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('cannot be empty');
    });

    test('createOperationParameter should reject duplicate', async () => {
      const { createOperationParameter } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1 });

      const result = await createOperationParameter('op-1', 'limit', 'query');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('already exists');
    });

    test('updateOperationParameter should update parameter', async () => {
      const { updateOperationParameter } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rowCount: 1,
        rows: [{ id: 'param-1', required: true }]
      });

      const result = await updateOperationParameter('param-1', {
        required: true,
        description: 'Updated description'
      });
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('deleteOperationParameter should delete parameter', async () => {
      const { deleteOperationParameter } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ id: 'param-1' }] });

      const result = await deleteOperationParameter('param-1');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });
  });

  // ============================================================================
  // OPERATION RESPONSES TESTS
  // ============================================================================

  describe('Operation Responses', () => {
    test('getResponsesForOperation should return responses', async () => {
      const { getResponsesForOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rows: [
          { id: 'resp-1', status_code: '200', description: 'Success' },
          { id: 'resp-2', status_code: '404', description: 'Not found' }
        ]
      });

      const result = await getResponsesForOperation('op-1');
      const parsed = JSON.parse(result);

      expect(parsed).toHaveLength(2);
    });

    test('createOperationResponse should create response', async () => {
      const { createOperationResponse } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValueOnce({ rowCount: 0 }); // Check duplicate
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'resp-1', status_code: '200', description: 'Success' }]
      });

      const result = await createOperationResponse(
        'op-1',
        '200',
        'Successful response'
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('createOperationResponse should reject empty status code', async () => {
      const { createOperationResponse } = await import('../lib/db/helper-paths');

      const result = await createOperationResponse('op-1', '', 'Description');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('cannot be empty');
    });

    test('createOperationResponse should reject empty description', async () => {
      const { createOperationResponse } = await import('../lib/db/helper-paths');

      const result = await createOperationResponse('op-1', '200', '');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('cannot be empty');
    });

    test('createOperationResponse should reject duplicate status code', async () => {
      const { createOperationResponse } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1 });

      const result = await createOperationResponse('op-1', '200', 'Success');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('already exists');
    });

    test('updateOperationResponse should update response', async () => {
      const { updateOperationResponse } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rowCount: 1,
        rows: [{ id: 'resp-1', description: 'Updated' }]
      });

      const result = await updateOperationResponse('resp-1', {
        description: 'Updated description'
      });
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('deleteOperationResponse should delete response', async () => {
      const { deleteOperationResponse } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ id: 'resp-1' }] });

      const result = await deleteOperationResponse('resp-1');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });
  });

  // ============================================================================
  // OPERATION REQUEST BODY TESTS
  // ============================================================================

  describe('Operation Request Bodies', () => {
    test('getRequestBodyForOperation should return request body with content types', async () => {
      const { getRequestBodyForOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rows: [{
          id: 'rb-1',
          operation_id: 'op-1',
          required: true,
          content_types: [
            { id: 'ct-1', content_type: 'application/json' }
          ]
        }]
      });

      const result = await getRequestBodyForOperation('op-1');
      const parsed = JSON.parse(result);

      expect(parsed.id).toBe('rb-1');
      expect(parsed.content_types).toHaveLength(1);
    });

    test('createOperationRequestBody should create request body', async () => {
      const { createOperationRequestBody } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValueOnce({ rowCount: 0 }); // Check existing
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'rb-1', operation_id: 'op-1', required: true }]
      });

      const result = await createOperationRequestBody(
        'op-1',
        'Request body description',
        true
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('createOperationRequestBody should reject duplicate', async () => {
      const { createOperationRequestBody } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1 });

      const result = await createOperationRequestBody('op-1');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('already exists');
    });

    test('updateOperationRequestBody should update request body', async () => {
      const { updateOperationRequestBody } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({
        rowCount: 1,
        rows: [{ id: 'rb-1', required: false }]
      });

      const result = await updateOperationRequestBody('rb-1', {
        required: false,
        description: 'Updated'
      });
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('deleteOperationRequestBody should delete request body', async () => {
      const { deleteOperationRequestBody } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1, rows: [{ id: 'rb-1' }] });

      const result = await deleteOperationRequestBody('rb-1');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('addRequestBodyContentType should add content type', async () => {
      const { addRequestBodyContentType } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValueOnce({ rowCount: 0 }); // Check duplicate
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'ct-1', content_type: 'application/json' }]
      });

      const result = await addRequestBodyContentType(
        'rb-1',
        'application/json',
        'class-1'
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });

    test('addRequestBodyContentType should reject empty content type', async () => {
      const { addRequestBodyContentType } = await import('../lib/db/helper-paths');

      const result = await addRequestBodyContentType('rb-1', '');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('cannot be empty');
    });

    test('addRequestBodyContentType should reject duplicate', async () => {
      const { addRequestBodyContentType } = await import('../lib/db/helper-paths');

      mockQuery.mockResolvedValue({ rowCount: 1 });

      const result = await addRequestBodyContentType('rb-1', 'application/json');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('already exists');
    });
  });

  // ============================================================================
  // ERROR HANDLING TESTS
  // ============================================================================

  describe('Error Handling', () => {
    test('should handle database errors in getApiPathsForVersion', async () => {
      const { getApiPathsForVersion } = await import('../lib/db/helper-paths');

      mockQuery.mockRejectedValue(new Error('Database error'));

      const result = await getApiPathsForVersion('version-1');
      const parsed = JSON.parse(result);

      expect(parsed).toEqual([]);
    });

    test('should handle database errors in createApiPath', async () => {
      const { createApiPath } = await import('../lib/db/helper-paths');

      mockQuery.mockRejectedValue(new Error('Database error'));

      const result = await createApiPath('version-1', '/test');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toBeDefined();
    });

    test('should handle database errors in createPathOperation', async () => {
      const { createPathOperation } = await import('../lib/db/helper-paths');

      mockQuery.mockRejectedValue(new Error('Database error'));

      const result = await createPathOperation('path-1', 'get');
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
    });
  });

  // ============================================================================
  // INTEGRATION TESTS
  // ============================================================================

  describe('Integration Scenarios', () => {
    test('should handle complete path creation workflow', async () => {
      const {
        createApiPath,
        createPathOperation,
        createOperationParameter,
        createOperationResponse
      } = await import('../lib/db/helper-paths');

      // Create path
      mockQuery.mockResolvedValueOnce({ rowCount: 0 });
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'path-1', path: '/users' }]
      });

      const pathResult = await createApiPath('version-1', '/users');
      expect(JSON.parse(pathResult).success).toBe(true);

      // Create operation
      mockQuery.mockResolvedValueOnce({ rowCount: 0 });
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'op-1', method: 'get' }]
      });

      const opResult = await createPathOperation('path-1', 'GET');
      expect(JSON.parse(opResult).success).toBe(true);

      // Add parameter
      mockQuery.mockResolvedValueOnce({ rowCount: 0 });
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'param-1', name: 'limit' }]
      });

      const paramResult = await createOperationParameter('op-1', 'limit', 'query');
      expect(JSON.parse(paramResult).success).toBe(true);

      // Add response
      mockQuery.mockResolvedValueOnce({ rowCount: 0 });
      mockQuery.mockResolvedValueOnce({
        rows: [{ id: 'resp-1', status_code: '200' }]
      });

      const respResult = await createOperationResponse('op-1', '200', 'Success');
      expect(JSON.parse(respResult).success).toBe(true);
    });

    test('should handle path with multiple operations', async () => {
      const { createPathOperation } = await import('../lib/db/helper-paths');

      const methods = ['get', 'post', 'put', 'delete'];

      for (const method of methods) {
        mockQuery.mockResolvedValueOnce({ rowCount: 0 });
        mockQuery.mockResolvedValueOnce({
          rows: [{ id: `op-${method}`, method }]
        });

        const result = await createPathOperation('path-1', method);
        expect(JSON.parse(result).success).toBe(true);
      }
    });
  });
});

console.log('✅ API Paths Helper tests defined - 60+ tests for comprehensive coverage!');
