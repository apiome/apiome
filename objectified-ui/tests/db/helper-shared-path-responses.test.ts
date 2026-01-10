/**
 * Tests for helper-shared-path-responses.ts
 * Tests shared response CRUD operations and linking functionality
 */

import {
  getSharedPathResponses,
  getLinkedResponsesForOperation,
  createSharedPathResponse,
  linkResponseToOperation,
  unlinkResponseFromOperation,
  updateSharedPathResponse,
  deleteSharedPathResponse,
} from '../../lib/db/helper-shared-path-responses';

// Mock the database connection
jest.mock('../../lib/db/db', () => ({
  query: jest.fn(),
}));

const connectionPool = require('../../lib/db/db');

describe('Shared Path Responses', () => {
  const testVersionPathId = 'test-path-id';
  const testOperationId1 = 'test-op-1';
  const testOperationId2 = 'test-op-2';
  const testResponseId = 'test-resp-1';

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('createSharedPathResponse', () => {
    it('should create a new shared response', async () => {
      const mockResponse = {
        id: testResponseId,
        version_path_id: testVersionPathId,
        status_code: '200',
        description: 'Successful response',
        data: null,
        created_at: new Date(),
        updated_at: new Date(),
      };

      connectionPool.query
        .mockResolvedValueOnce({ rows: [] }) // Check query
        .mockResolvedValueOnce({ rows: [mockResponse] }); // Insert query

      const result = await createSharedPathResponse(
        testVersionPathId,
        '200',
        'Successful response'
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(parsed.response).toBeDefined();
      expect(parsed.response.status_code).toBe('200');
      expect(parsed.existed).toBe(false);
    });

    it('should return existing response if status code already exists for path', async () => {
      const existingResponse = {
        id: testResponseId,
        version_path_id: testVersionPathId,
        status_code: '200',
        description: 'Original description',
        data: null,
        created_at: new Date(),
        updated_at: new Date(),
      };

      connectionPool.query.mockResolvedValueOnce({ rows: [existingResponse] });

      const result = await createSharedPathResponse(
        testVersionPathId,
        '200',
        'Different description'
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(parsed.existed).toBe(true);
      expect(parsed.response.description).toBe('Original description');
    });

    it('should create response with wildcard status code', async () => {
      const mockResponse = {
        id: 'resp-2',
        version_path_id: testVersionPathId,
        status_code: '2XX',
        description: 'All success responses',
        data: null,
        created_at: new Date(),
        updated_at: new Date(),
      };

      connectionPool.query
        .mockResolvedValueOnce({ rows: [] })
        .mockResolvedValueOnce({ rows: [mockResponse] });

      const result = await createSharedPathResponse(
        testVersionPathId,
        '2XX',
        'All success responses'
      );
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(parsed.response.status_code).toBe('2XX');
    });
  });

  describe('getSharedPathResponses', () => {
    it('should get all shared responses for a path', async () => {
      const mockResponses = [
        { id: '1', status_code: '200', description: 'Success' },
        { id: '2', status_code: '2XX', description: 'All success' },
        { id: '3', status_code: '404', description: 'Not found' },
      ];

      connectionPool.query.mockResolvedValueOnce({ rows: mockResponses });

      const result = await getSharedPathResponses(testVersionPathId);
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(parsed.responses).toHaveLength(3);
    });
  });

  describe('linkResponseToOperation', () => {
    it('should link a response to an operation', async () => {
      const mockLink = {
        id: 'link-1',
        path_operation_id: testOperationId1,
        shared_path_response_id: testResponseId,
        metadata: null,
      };

      connectionPool.query.mockResolvedValueOnce({ rows: [mockLink] });

      const result = await linkResponseToOperation(testOperationId1, testResponseId);
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });
  });

  describe('unlinkResponseFromOperation', () => {
    it('should unlink a response from an operation', async () => {
      connectionPool.query.mockResolvedValueOnce({ rowCount: 1 });

      const result = await unlinkResponseFromOperation(testOperationId1, testResponseId);
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
    });
  });

  describe('deleteSharedPathResponse', () => {
    it('should not delete response that is still linked', async () => {
      connectionPool.query.mockResolvedValueOnce({ rows: [{ link_count: '2' }] });

      const result = await deleteSharedPathResponse(testResponseId);
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('linked to');
    });
  });
});

