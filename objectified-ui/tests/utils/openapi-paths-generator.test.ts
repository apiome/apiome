/**
 * Tests for OpenAPI Paths Generator
 */

import {
  buildParameterForOpenAPI,
  buildResponseForOpenAPI,
  buildOperationForOpenAPI,
  buildPathItemForOpenAPI,
  generatePathsForOpenAPI,
  generateOpenAPISpecWithPaths,
  collectReferencedClassNames,
  type PathInfo,
  type OperationInfo,
  type PathParameter,
  type ResponseInfo,
  type RequestBodyInfo,
} from '../../lib/utils/openapi-paths-generator';

describe('OpenAPI Paths Generator', () => {
  describe('buildParameterForOpenAPI', () => {
    it('should build a basic path parameter', () => {
      const param: PathParameter = {
        id: 'param-1',
        name: 'userId',
        in_location: 'path',
        description: 'The user ID',
        data: { type: 'string', format: 'uuid' },
      };

      const result = buildParameterForOpenAPI(param);

      expect(result).toEqual({
        name: 'userId',
        in: 'path',
        description: 'The user ID',
        required: true, // path params are always required
        schema: { type: 'string', format: 'uuid' },
      });
    });

    it('should build a query parameter with optional flag', () => {
      const param: PathParameter = {
        id: 'param-2',
        name: 'limit',
        in_location: 'query',
        description: 'Max items to return',
        data: { type: 'integer', minimum: 1, maximum: 100, required: false },
      };

      const result = buildParameterForOpenAPI(param);

      expect(result).toEqual({
        name: 'limit',
        in: 'query',
        description: 'Max items to return',
        schema: { type: 'integer', minimum: 1, maximum: 100 },
      });
      expect(result.required).toBeUndefined();
    });

    it('should handle deprecated parameters', () => {
      const param: PathParameter = {
        id: 'param-3',
        name: 'oldParam',
        in_location: 'header',
        data: { type: 'string', deprecated: true },
      };

      const result = buildParameterForOpenAPI(param);

      expect(result.deprecated).toBe(true);
    });

    it('should handle style and explode', () => {
      const param: PathParameter = {
        id: 'param-4',
        name: 'tags',
        in_location: 'query',
        data: { type: 'array', items: { type: 'string' }, style: 'form', explode: true },
      };

      const result = buildParameterForOpenAPI(param);

      expect(result.style).toBe('form');
      expect(result.explode).toBe(true);
    });

    it('should use inline JSON Schema when schemaMode is inline', () => {
      const param: PathParameter = {
        id: 'param-inline',
        name: 'filter',
        in_location: 'query',
        data: {
          schemaMode: 'inline',
          inlineSchema: { type: 'string', pattern: '^[a-z]+$' },
          required: false,
          style: 'form',
          explode: false,
        },
      };

      const result = buildParameterForOpenAPI(param);

      expect(result.schema).toEqual({ type: 'string', pattern: '^[a-z]+$' });
      expect(result.required).toBeUndefined();
      expect(result.style).toBe('form');
    });
  });

  describe('buildResponseForOpenAPI', () => {
    it('should build a response with class reference', () => {
      const response: ResponseInfo = {
        id: 'resp-1',
        status_code: '200',
        description: 'Successful response',
        class_id: 'class-123',
        class_name: 'User',
      };

      const result = buildResponseForOpenAPI(response);

      expect(result).toEqual({
        description: 'Successful response',
        content: {
          'application/json': {
            schema: { $ref: '#/components/schemas/User' },
          },
        },
      });
    });

    it('should build a response with inline schema', () => {
      const response: ResponseInfo = {
        id: 'resp-2',
        status_code: '201',
        description: 'Created',
        inline_schema: {
          type: 'object',
          properties: [
            { id: 'prop-1', name: 'id', data: { type: 'string' }, parent_id: null },
            { id: 'prop-2', name: 'createdAt', data: { type: 'string', format: 'date-time' }, parent_id: null },
          ],
        },
      };

      const result = buildResponseForOpenAPI(response);

      expect(result.description).toBe('Created');
      expect(result.content).toBeDefined();
      expect((result.content as Record<string, unknown>)['application/json']).toBeDefined();
    });

    it('should provide default description if missing', () => {
      const response: ResponseInfo = {
        id: 'resp-3',
        status_code: '404',
      };

      const result = buildResponseForOpenAPI(response);

      expect(result.description).toBe('404 response');
    });
  });

  describe('buildOperationForOpenAPI', () => {
    it('should build a complete GET operation', () => {
      const operation: OperationInfo = {
        id: 'op-1',
        operation: 'GET',
        description: {
          id: 'desc-1',
          summary: 'Get user by ID',
          description: 'Returns a single user',
          operationId: 'getUserById',
          tags: ['users'],
        },
        parameters: [
          {
            id: 'param-1',
            name: 'userId',
            in_location: 'path',
            description: 'User ID',
            data: { type: 'string', required: true },
          },
        ],
        responses: [
          {
            id: 'resp-1',
            status_code: '200',
            description: 'Successful',
            class_name: 'User',
            class_id: 'class-1',
          },
        ],
      };

      const result = buildOperationForOpenAPI(operation);

      expect(result.summary).toBe('Get user by ID');
      expect(result.description).toBe('Returns a single user');
      expect(result.operationId).toBe('getUserById');
      expect(result.tags).toEqual(['users']);
      expect(result.parameters).toHaveLength(1);
      expect(result.responses).toBeDefined();
      expect((result.responses as Record<string, unknown>)['200']).toBeDefined();
    });

    it('should build a POST operation with request body', () => {
      const requestBody: RequestBodyInfo = {
        id: 'rb-1',
        name: 'CreateUserRequest',
        description: 'User to create',
        required: true,
        content_types: [
          {
            id: 'ct-1',
            media_type: 'application/json',
            inline_schema: {
              type: 'object',
              properties: [
                { id: 'p1', name: 'email', data: { type: 'string', format: 'email', required: true }, parent_id: null },
                { id: 'p2', name: 'name', data: { type: 'string' }, parent_id: null },
              ],
            },
          },
        ],
      };

      const operation: OperationInfo = {
        id: 'op-2',
        operation: 'POST',
        description: {
          id: 'desc-2',
          summary: 'Create user',
          operationId: 'createUser',
        },
        parameters: [],
        requestBody,
        responses: [
          { id: 'resp-1', status_code: '201', description: 'Created' },
        ],
      };

      const result = buildOperationForOpenAPI(operation);

      expect(result.requestBody).toBeDefined();
      expect((result.requestBody as Record<string, unknown>).required).toBe(true);
      expect((result.requestBody as Record<string, unknown>).content).toBeDefined();
    });

    it('should not include requestBody for GET operations', () => {
      const operation: OperationInfo = {
        id: 'op-3',
        operation: 'GET',
        parameters: [],
        requestBody: {
          id: 'rb-1',
          name: 'ShouldBeIgnored',
          required: true,
          content_types: [],
        },
        responses: [],
      };

      const result = buildOperationForOpenAPI(operation);

      expect(result.requestBody).toBeUndefined();
    });

    it('should include security requirements when present', () => {
      const operation: OperationInfo = {
        id: 'op-1',
        operation: 'GET',
        description: {
          id: 'd1',
          summary: 'Get user',
          operationId: 'getUser',
          security: [{ bearerAuth: [] }, { oauth2: ['read', 'write'] }],
        },
        parameters: [],
        responses: [{ id: 'r1', status_code: '200', description: 'OK' }],
      };

      const result = buildOperationForOpenAPI(operation);

      expect(result.security).toEqual([{ bearerAuth: [] }, { oauth2: ['read', 'write'] }]);
    });

    it('should include deprecated flag when present', () => {
      const operation: OperationInfo = {
        id: 'op-1',
        operation: 'GET',
        description: {
          id: 'd1',
          summary: 'Old endpoint',
          operationId: 'getOldUsers',
          deprecated: true,
        },
        parameters: [],
        responses: [{ id: 'r1', status_code: '200', description: 'OK' }],
      };

      const result = buildOperationForOpenAPI(operation);

      expect(result.deprecated).toBe(true);
    });

    it('should not include deprecated flag when false', () => {
      const operation: OperationInfo = {
        id: 'op-1',
        operation: 'GET',
        description: {
          id: 'd1',
          summary: 'Active endpoint',
          operationId: 'getUsers',
          deprecated: false,
        },
        parameters: [],
        responses: [{ id: 'r1', status_code: '200', description: 'OK' }],
      };

      const result = buildOperationForOpenAPI(operation);

      expect(result.deprecated).toBeUndefined();
    });

    it('defaults OPTIONS to 204 when no responses are defined', () => {
      const operation: OperationInfo = {
        id: 'op-opt',
        operation: 'OPTIONS',
        parameters: [],
        responses: [],
      };

      const result = buildOperationForOpenAPI(operation);

      expect((result.responses as Record<string, unknown>)['204']).toEqual({ description: 'No Content' });
    });

    it('does not emit requestBody for OPTIONS even if present in data', () => {
      const operation: OperationInfo = {
        id: 'op-opt',
        operation: 'OPTIONS',
        parameters: [],
        requestBody: {
          id: 'rb-1',
          name: 'Preflight',
          required: false,
          content_types: [
            {
              id: 'ct-1',
              media_type: 'application/json',
              inline_schema: {
                type: 'object',
                properties: [],
              },
            },
          ],
        },
        responses: [],
      };

      const result = buildOperationForOpenAPI(operation);

      expect(result.requestBody).toBeUndefined();
    });

    it('includes options on path item for OPTIONS operations', () => {
      const path: PathInfo = {
        id: 'path-cors',
        pathname: '/resource',
        operations: [
          {
            id: 'op-opt',
            operation: 'OPTIONS',
            parameters: [],
            responses: [],
          },
        ],
      };

      const result = buildPathItemForOpenAPI(path);

      expect(result.options).toBeDefined();
      expect((result.options as Record<string, unknown>).responses).toBeDefined();
    });
  });

  describe('buildPathItemForOpenAPI', () => {
    it('should build a path item with multiple operations', () => {
      const path: PathInfo = {
        id: 'path-1',
        pathname: '/users/{userId}',
        summary: 'User operations',
        description: 'Manage individual users',
        operations: [
          {
            id: 'op-1',
            operation: 'GET',
            description: { id: 'd1', summary: 'Get user' },
            parameters: [{ id: 'p1', name: 'userId', in_location: 'path', data: { type: 'string' } }],
            responses: [{ id: 'r1', status_code: '200', description: 'OK' }],
          },
          {
            id: 'op-2',
            operation: 'DELETE',
            description: { id: 'd2', summary: 'Delete user' },
            parameters: [{ id: 'p1', name: 'userId', in_location: 'path', data: { type: 'string' } }],
            responses: [{ id: 'r2', status_code: '204', description: 'Deleted' }],
          },
        ],
      };

      const result = buildPathItemForOpenAPI(path);

      expect(result.summary).toBe('User operations');
      expect(result.description).toBe('Manage individual users');
      expect(result.get).toBeDefined();
      expect(result.delete).toBeDefined();
    });
  });

  describe('generatePathsForOpenAPI', () => {
    it('should generate paths object from multiple paths', () => {
      const paths: PathInfo[] = [
        {
          id: 'path-1',
          pathname: '/users',
          operations: [
            {
              id: 'op-1',
              operation: 'GET',
              parameters: [],
              responses: [{ id: 'r1', status_code: '200', description: 'OK' }],
            },
          ],
        },
        {
          id: 'path-2',
          pathname: '/users/{userId}',
          operations: [
            {
              id: 'op-2',
              operation: 'GET',
              parameters: [{ id: 'p1', name: 'userId', in_location: 'path', data: { type: 'string' } }],
              responses: [{ id: 'r2', status_code: '200', description: 'OK' }],
            },
          ],
        },
      ];

      const result = generatePathsForOpenAPI(paths);

      expect(result['/users']).toBeDefined();
      expect(result['/users/{userId}']).toBeDefined();
    });
  });

  describe('generateOpenAPISpecWithPaths', () => {
    it('should generate a complete OpenAPI spec', () => {
      const paths: PathInfo[] = [
        {
          id: 'path-1',
          pathname: '/users',
          operations: [
            {
              id: 'op-1',
              operation: 'GET',
              description: { id: 'd1', summary: 'List users', operationId: 'listUsers' },
              parameters: [],
              responses: [{ id: 'r1', status_code: '200', description: 'OK', class_name: 'UserList', class_id: 'c1' }],
            },
          ],
        },
      ];

      const schemas = {
        UserList: { type: 'object', properties: { items: { type: 'array' } } },
      };

      const result = generateOpenAPISpecWithPaths(paths, schemas, {
        title: 'My API',
        version: '1.0.0',
        description: 'Test API',
        servers: [{ url: 'https://api.example.com', description: 'Production' }],
      });

      expect(result.openapi).toBe('3.1.0');
      expect((result.info as Record<string, unknown>).title).toBe('My API');
      expect((result.info as Record<string, unknown>).version).toBe('1.0.0');
      expect(result.servers).toHaveLength(1);
      expect(result.paths).toBeDefined();
      expect(result.components).toBeDefined();
    });
  });

  describe('collectReferencedClassNames', () => {
    it('should collect class names from request bodies and responses', () => {
      const paths: PathInfo[] = [
        {
          id: 'path-1',
          pathname: '/users',
          operations: [
            {
              id: 'op-1',
              operation: 'POST',
              parameters: [],
              requestBody: {
                id: 'rb-1',
                name: 'CreateUser',
                required: true,
                content_types: [
                  { id: 'ct-1', media_type: 'application/json', class_id: 'c1', class_name: 'CreateUserRequest' },
                ],
              },
              responses: [
                { id: 'r1', status_code: '201', class_id: 'c2', class_name: 'User' },
              ],
            },
            {
              id: 'op-2',
              operation: 'GET',
              parameters: [],
              responses: [
                { id: 'r2', status_code: '200', class_id: 'c3', class_name: 'UserList' },
                { id: 'r3', status_code: '200', data: { $ref: '#/components/schemas/Error' } },
              ],
            },
          ],
        },
      ];

      const result = collectReferencedClassNames(paths);

      expect(result.has('CreateUserRequest')).toBe(true);
      expect(result.has('User')).toBe(true);
      expect(result.has('UserList')).toBe(true);
      expect(result.has('Error')).toBe(true);
    });

    it('should return empty set for paths with inline schemas only', () => {
      const paths: PathInfo[] = [
        {
          id: 'path-1',
          pathname: '/health',
          operations: [
            {
              id: 'op-1',
              operation: 'GET',
              parameters: [],
              responses: [
                {
                  id: 'r1',
                  status_code: '200',
                  description: 'OK',
                  inline_schema: {
                    type: 'object',
                    properties: [{ id: 'p1', name: 'status', data: { type: 'string' }, parent_id: null }],
                  },
                },
              ],
            },
          ],
        },
      ];

      const result = collectReferencedClassNames(paths);

      expect(result.size).toBe(0);
    });
  });
});
