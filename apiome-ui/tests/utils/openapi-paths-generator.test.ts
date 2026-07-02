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

    it('should emit header and cookie parameters with correct `in` and schema', () => {
      const headerParam: PathParameter = {
        id: 'h1',
        name: 'Authorization',
        in_location: 'header',
        data: { type: 'string', style: 'simple', required: true },
      };
      const cookieParam: PathParameter = {
        id: 'c1',
        name: 'session',
        in_location: 'cookie',
        data: { type: 'string', style: 'form', required: false },
      };

      const h = buildParameterForOpenAPI(headerParam);
      expect(h.in).toBe('header');
      expect(h.name).toBe('Authorization');
      expect(h.required).toBe(true);
      expect(h.schema).toEqual({ type: 'string' });
      expect(h.style).toBe('simple');

      const c = buildParameterForOpenAPI(cookieParam);
      expect(c.in).toBe('cookie');
      expect(c.name).toBe('session');
      expect(c.required).toBeUndefined();
      expect(c.schema).toEqual({ type: 'string' });
      expect(c.style).toBe('form');
    });

    it('should emit allowReserved for query parameters when set', () => {
      const param: PathParameter = {
        id: 'q1',
        name: 'q',
        in_location: 'query',
        data: { type: 'string', allowReserved: true },
      };
      const result = buildParameterForOpenAPI(param);
      expect(result.allowReserved).toBe(true);
    });

    it('should NOT emit allowReserved for header or cookie parameters even if stored', () => {
      const headerParam: PathParameter = {
        id: 'h2',
        name: 'X-Custom',
        in_location: 'header',
        data: { type: 'string', allowReserved: true },
      };
      const cookieParam: PathParameter = {
        id: 'c2',
        name: 'prefs',
        in_location: 'cookie',
        data: { type: 'string', allowReserved: true },
      };
      expect(buildParameterForOpenAPI(headerParam).allowReserved).toBeUndefined();
      expect(buildParameterForOpenAPI(cookieParam).allowReserved).toBeUndefined();
    });

    it('should NOT emit allowReserved for inline-schema header params', () => {
      const param: PathParameter = {
        id: 'h-inline',
        name: 'Authorization',
        in_location: 'header',
        data: {
          schemaMode: 'inline',
          inlineSchema: { type: 'string' },
          allowReserved: true,
        },
      };
      expect(buildParameterForOpenAPI(param).allowReserved).toBeUndefined();
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

    it('should build per-media content map with multiple content types', () => {
      const response: ResponseInfo = {
        id: 'resp-multi',
        status_code: '200',
        description: 'OK',
        content_types: [
          {
            id: 'ct-1',
            media_type: 'application/json',
            class_id: 'c1',
            class_name: 'User',
          },
          {
            id: 'ct-2',
            media_type: 'application/xml',
            class_id: 'c2',
            class_name: 'User',
          },
        ],
      };

      const result = buildResponseForOpenAPI(response);

      expect(result.description).toBe('OK');
      const content = result.content as Record<string, { schema: { $ref: string } }>;
      expect(content['application/json'].schema.$ref).toBe('#/components/schemas/User');
      expect(content['application/xml'].schema.$ref).toBe('#/components/schemas/User');
    });

    it('should include response headers from data.headers (OpenAPI Header Object map)', () => {
      const response: ResponseInfo = {
        id: 'resp-h',
        status_code: '200',
        description: 'Paginated list',
        class_name: 'ItemList',
        class_id: 'c1',
        data: {
          headers: {
            'X-Total-Count': {
              description: 'Total items',
              schema: { type: 'integer' },
            },
          },
        },
      };

      const result = buildResponseForOpenAPI(response);

      expect(result.headers).toEqual({
        'X-Total-Count': {
          description: 'Total items',
          schema: { type: 'integer' },
        },
      });
      expect(result.content).toBeDefined();
    });

    it('should build schema from direct array data payload', () => {
      const response: ResponseInfo = {
        id: 'resp-array-data',
        status_code: '200',
        description: 'List response',
        data: {
          type: 'array',
          items: { type: 'string' },
        },
      };

      const result = buildResponseForOpenAPI(response);
      const content = result.content as Record<string, { schema: Record<string, unknown> }>;
      expect(content['application/json'].schema).toEqual({
        type: 'array',
        items: { type: 'string' },
      });
    });

    it('preserves array items and example on an inline-schema response (#symbols regression)', () => {
      // The 1Forge /symbols 200 response: `type: array` with `items` + `example`. These must survive
      // export, not collapse to a bare `type: array`.
      const response: ResponseInfo = {
        id: 'resp-symbols',
        status_code: '200',
        description: 'A list of symbols',
        inline_schema: {
          type: 'array',
          items: { type: 'string' },
          example: ['EURUSD', 'GBPJPY', 'AUDUSD'],
        },
      };

      const result = buildResponseForOpenAPI(response);
      const content = result.content as Record<string, { schema: Record<string, unknown> }>;
      expect(content['application/json'].schema).toEqual({
        type: 'array',
        items: { type: 'string' },
        example: ['EURUSD', 'GBPJPY', 'AUDUSD'],
      });
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

    it('should build responses map with multiple status codes each having description and content', () => {
      const operation: OperationInfo = {
        id: 'op-multi',
        operation: 'GET',
        parameters: [],
        responses: [
          {
            id: 'r-200',
            status_code: '200',
            description: 'Found',
            content_types: [
              { id: 'ct1', media_type: 'application/json', class_id: 'a', class_name: 'User' },
            ],
          },
          {
            id: 'r-404',
            status_code: '404',
            description: 'Not found',
            content_types: [
              { id: 'ct2', media_type: 'application/json', class_id: 'b', class_name: 'ErrorBody' },
            ],
          },
        ],
      };

      const built = buildOperationForOpenAPI(operation);
      const responses = built.responses as Record<string, Record<string, unknown>>;

      expect(responses['200'].description).toBe('Found');
      expect(responses['200'].content).toBeDefined();
      expect(responses['404'].description).toBe('Not found');
      expect(responses['404'].content).toBeDefined();
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

    it('should collect class names from response content_types when top-level class is unset', () => {
      const paths: PathInfo[] = [
        {
          id: 'path-1',
          pathname: '/items',
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
                  content_types: [
                    {
                      id: 'ct-1',
                      media_type: 'application/json',
                      class_id: 'c1',
                      class_name: 'ItemPage',
                    },
                  ],
                },
              ],
            },
          ],
        },
      ];

      expect(collectReferencedClassNames(paths).has('ItemPage')).toBe(true);
    });

    it('should collect $ref names nested inside allOf/oneOf/anyOf in content_type inline schemas', () => {
      const paths: PathInfo[] = [
        {
          id: 'path-1',
          pathname: '/nested',
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
                  content_types: [
                    {
                      id: 'ct-1',
                      media_type: 'application/json',
                      inline_schema: {
                        type: 'object',
                        allOf: [
                          { $ref: '#/components/schemas/BaseItem' },
                          {
                            type: 'object',
                            properties: [
                              {
                                id: 'p1',
                                name: 'extra',
                                data: { $ref: '#/components/schemas/ExtraInfo' },
                                parent_id: null,
                              },
                            ],
                          },
                        ],
                        anyOf: [{ $ref: '#/components/schemas/VariantA' }],
                      } as any,
                    },
                  ],
                },
              ],
            },
          ],
        },
      ];

      const result = collectReferencedClassNames(paths);
      expect(result.has('BaseItem')).toBe(true);
      expect(result.has('ExtraInfo')).toBe(true);
      expect(result.has('VariantA')).toBe(true);
    });

    it('should collect items.$ref nested inside array inline schema in content_types', () => {
      const paths: PathInfo[] = [
        {
          id: 'path-1',
          pathname: '/list',
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
                  content_types: [
                    {
                      id: 'ct-1',
                      media_type: 'application/json',
                      inline_schema: {
                        type: 'array',
                        items: { $ref: '#/components/schemas/Widget' },
                      },
                    },
                  ],
                },
              ],
            },
          ],
        },
      ];

      expect(collectReferencedClassNames(paths).has('Widget')).toBe(true);
    });
  });
});

describe('buildResponseForOpenAPI – inline schema pass-through', () => {
  it('should emit $ref directly when inline_schema has a top-level $ref', () => {
    const response: ResponseInfo = {
      id: 'resp-ref',
      status_code: '200',
      description: 'OK',
      content_types: [
        {
          id: 'ct1',
          media_type: 'application/json',
          inline_schema: { type: 'object', $ref: '#/components/schemas/Widget' } as any,
        },
      ],
    };

    const result = buildResponseForOpenAPI(response);
    const content = result.content as Record<string, { schema: Record<string, unknown> }>;
    expect(content['application/json'].schema).toEqual({ $ref: '#/components/schemas/Widget' });
  });

  it('should emit type:array with items.$ref when inline_schema is an array referencing a schema', () => {
    const response: ResponseInfo = {
      id: 'resp-arr',
      status_code: '200',
      description: 'OK',
      content_types: [
        {
          id: 'ct1',
          media_type: 'application/json',
          inline_schema: {
            type: 'array',
            items: { $ref: '#/components/schemas/Item' },
          },
        },
      ],
    };

    const result = buildResponseForOpenAPI(response);
    const content = result.content as Record<string, { schema: Record<string, unknown> }>;
    expect(content['application/json'].schema).toEqual({
      type: 'array',
      items: { $ref: '#/components/schemas/Item' },
    });
  });

  it('should emit type:string with format/enum constraints when inline_schema is a primitive', () => {
    const response: ResponseInfo = {
      id: 'resp-str',
      status_code: '200',
      description: 'OK',
      content_types: [
        {
          id: 'ct1',
          media_type: 'application/json',
          inline_schema: {
            type: 'string',
            format: 'email',
            minLength: 3,
            maxLength: 254,
          },
        },
      ],
    };

    const result = buildResponseForOpenAPI(response);
    const content = result.content as Record<string, { schema: Record<string, unknown> }>;
    expect(content['application/json'].schema).toEqual({
      type: 'string',
      format: 'email',
      minLength: 3,
      maxLength: 254,
    });
  });

  it('should use buildSchemaFromInlineProperties for object inline_schema with properties array', () => {
    const response: ResponseInfo = {
      id: 'resp-obj',
      status_code: '200',
      description: 'OK',
      content_types: [
        {
          id: 'ct1',
          media_type: 'application/json',
          inline_schema: {
            type: 'object',
            properties: [
              { id: 'p1', name: 'id', data: { type: 'string' }, parent_id: null },
            ],
          },
        },
      ],
    };

    const result = buildResponseForOpenAPI(response);
    const content = result.content as Record<string, { schema: Record<string, unknown> }>;
    expect((content['application/json'].schema as any).type).toBe('object');
    expect((content['application/json'].schema as any).properties).toHaveProperty('id');
  });
});
