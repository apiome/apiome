/**
 * Unit tests for OpenAPI path extraction and parsing.
 * Verifies extractPaths, extractSecuritySchemes, and parseOpenAPISpec produce
 * the path/security structures that importOpenAPIPathsAndSecurity expects,
 * and that the resulting logical DB shape (version_path, path_operation,
 * parameters, request bodies, responses) is as expected.
 */

import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import {
  extractPaths,
  extractSecuritySchemes,
  parseOpenAPISpec,
} from '../../src/app/utils/openapi-import';

describe('OpenAPI Paths Import', () => {
  describe('extractPaths', () => {
    it('returns empty array when spec has no paths', () => {
      const spec = { openapi: '3.1.0', info: { title: 'Test', version: '1.0' }, components: { schemas: {} } };
      expect(extractPaths(spec)).toEqual([]);
    });

    it('returns empty array when paths is not an object', () => {
      expect(extractPaths({ openapi: '3.1.0', paths: null })).toEqual([]);
      expect(extractPaths({ openapi: '3.1.0', paths: [] })).toEqual([]);
    });

    it('ignores path keys that do not start with /', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/valid': { get: { responses: { '200': { description: 'OK' } } } },
          invalid: { get: { responses: { '200': { description: 'OK' } } } },
        },
      };
      const result = extractPaths(spec);
      expect(result).toHaveLength(1);
      expect(result[0].path).toBe('/valid');
    });

    it('parses path-level and operation-level parameters', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/users/{userId}': {
            parameters: [
              { name: 'X-Request-ID', in: 'header', schema: { type: 'string' } },
            ],
            get: {
              parameters: [
                { name: 'userId', in: 'path', required: true, schema: { type: 'string' } },
                { name: 'limit', in: 'query', schema: { type: 'integer' } },
              ],
              responses: { '200': { description: 'OK' } },
            },
          },
        },
      };
      const result = extractPaths(spec);
      expect(result).toHaveLength(1);
      expect(result[0].path).toBe('/users/{userId}');
      expect(result[0].parameters).toBeDefined();
      expect(result[0].parameters!.length).toBe(1);
      expect(result[0].parameters![0].name).toBe('X-Request-ID');
      expect(result[0].parameters![0].in).toBe('header');

      const op = result[0].operations[0];
      expect(op.method).toBe('GET');
      expect(op.parameters).toHaveLength(3); // path-level + operation-level merged
      const paramNames = op.parameters.map(p => p.name);
      expect(paramNames).toContain('userId');
      expect(paramNames).toContain('limit');
      expect(paramNames).toContain('X-Request-ID');
      const pathParam = op.parameters.find(p => p.name === 'userId' && p.in === 'path');
      expect(pathParam?.required).toBe(true);
    });

    it('parses requestBody with $ref and inline schema', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/pets': {
            post: {
              requestBody: {
                required: true,
                content: {
                  'application/json': {
                    schema: { $ref: '#/components/schemas/Pet' },
                  },
                  'application/x-www-form-urlencoded': {
                    schema: {
                      type: 'object',
                      properties: { name: { type: 'string' } },
                      required: ['name'],
                    },
                  },
                },
              },
              responses: { '201': { description: 'Created' } },
            },
          },
        },
      };
      const result = extractPaths(spec);
      expect(result).toHaveLength(1);
      const postOp = result[0].operations.find(o => o.method === 'POST');
      expect(postOp?.requestBody).toBeDefined();
      expect(postOp?.requestBody?.required).toBe(true);
      expect(postOp?.requestBody?.content).toBeDefined();
      expect(postOp?.requestBody?.content!['application/json']).toEqual({ $ref: '#/components/schemas/Pet' });
      expect(postOp?.requestBody?.content!['application/x-www-form-urlencoded'].schema).toBeDefined();
      expect(postOp?.requestBody?.content!['application/x-www-form-urlencoded'].schema?.type).toBe('object');
    });

    it('parses responses with content and multiple status codes', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/items': {
            get: {
              responses: {
                '200': {
                  description: 'OK',
                  content: {
                    'application/json': {
                      schema: { $ref: '#/components/schemas/Item' },
                    },
                  },
                },
                '404': {
                  description: 'Not found',
                  content: {
                    'application/json': {
                      schema: { type: 'object', properties: { error: { type: 'string' } } },
                    },
                  },
                },
              },
            },
          },
        },
      };
      const result = extractPaths(spec);
      expect(result).toHaveLength(1);
      const getOp = result[0].operations[0];
      expect(Object.keys(getOp.responses)).toHaveLength(2);
      expect(getOp.responses['200'].description).toBe('OK');
      expect(getOp.responses['200'].content!['application/json']).toEqual({ $ref: '#/components/schemas/Item' });
      expect(getOp.responses['404'].content!['application/json'].schema).toBeDefined();
    });

    it('parses all HTTP methods', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/r': {
            get: { responses: { '200': { description: 'OK' } } },
            post: { responses: { '201': { description: 'Created' } } },
            put: { responses: { '200': { description: 'OK' } } },
            patch: { responses: { '200': { description: 'OK' } } },
            delete: { responses: { '204': { description: 'No content' } } },
            head: { responses: { '200': { description: 'OK' } } },
            options: { responses: { '200': { description: 'OK' } } },
            trace: { responses: { '200': { description: 'OK' } } },
          },
        },
      };
      const result = extractPaths(spec);
      expect(result).toHaveLength(1);
      const ops = result[0].operations;
      const methods = ops.map(o => o.method);
      expect(methods).toContain('GET');
      expect(methods).toContain('POST');
      expect(methods).toContain('PUT');
      expect(methods).toContain('PATCH');
      expect(methods).toContain('DELETE');
      expect(methods).toContain('HEAD');
      expect(methods).toContain('OPTIONS');
      expect(methods).toContain('TRACE');
      expect(ops).toHaveLength(8);
    });

    it('parses operationId, summary, description, tags, deprecated', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/test': {
            get: {
              operationId: 'getTest',
              summary: 'Get test',
              description: 'Longer description',
              tags: ['tests', 'admin'],
              deprecated: true,
              responses: { '200': { description: 'OK' } },
            },
          },
        },
      };
      const result = extractPaths(spec);
      const op = result[0].operations[0];
      expect(op.operationId).toBe('getTest');
      expect(op.summary).toBe('Get test');
      expect(op.description).toBe('Longer description');
      expect(op.tags).toEqual(['tests', 'admin']);
      expect(op.deprecated).toBe(true);
    });

    it('operation parameters override path-level parameters with same name and in', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/x': {
            parameters: [{ name: 'foo', in: 'query', schema: { type: 'string' }, description: 'Path level' }],
            get: {
              parameters: [{ name: 'foo', in: 'query', schema: { type: 'integer' }, description: 'Op level' }],
              responses: { '200': { description: 'OK' } },
            },
          },
        },
      };
      const result = extractPaths(spec);
      const params = result[0].operations[0].parameters;
      const foo = params.find(p => p.name === 'foo' && p.in === 'query');
      expect(foo?.description).toBe('Op level');
      expect(foo?.schema?.type).toBe('integer');
    });
  });

  describe('extractSecuritySchemes', () => {
    it('returns empty array when components.securitySchemes is missing', () => {
      expect(extractSecuritySchemes({})).toEqual([]);
      expect(extractSecuritySchemes({ components: {} })).toEqual([]);
    });

    it('parses apiKey scheme', () => {
      const spec = {
        components: {
          securitySchemes: {
            apiKey: {
              type: 'apiKey',
              in: 'header',
              name: 'X-API-Key',
              description: 'API key',
            },
          },
        },
      };
      const result = extractSecuritySchemes(spec);
      expect(result).toHaveLength(1);
      expect(result[0].scheme_name).toBe('apiKey');
      expect(result[0].scheme_type).toBe('apiKey');
      expect(result[0].in_location).toBe('header');
      expect(result[0].param_name).toBe('X-API-Key');
      expect(result[0].description).toBe('API key');
    });

    it('parses http bearer scheme', () => {
      const spec = {
        components: {
          securitySchemes: {
            bearerAuth: {
              type: 'http',
              scheme: 'bearer',
              bearerFormat: 'JWT',
              description: 'JWT',
            },
          },
        },
      };
      const result = extractSecuritySchemes(spec);
      expect(result).toHaveLength(1);
      expect(result[0].scheme_type).toBe('http');
      expect(result[0].http_scheme).toBe('bearer');
      expect((result[0].data as any)?.bearerFormat).toBe('JWT');
    });

    it('parses oauth2 and openIdConnect', () => {
      const spec = {
        components: {
          securitySchemes: {
            oauth: {
              type: 'oauth2',
              flows: { authorizationCode: { authorizationUrl: 'https://a', tokenUrl: 'https://t' } },
            },
            oidc: {
              type: 'openIdConnect',
              openIdConnectUrl: 'https://id.example.com/.well-known/openid-configuration',
            },
          },
        },
      };
      const result = extractSecuritySchemes(spec);
      expect(result).toHaveLength(2);
      const oauth = result.find(s => s.scheme_name === 'oauth');
      expect(oauth?.scheme_type).toBe('oauth2');
      expect(oauth?.data).toEqual({ flows: spec.components.securitySchemes.oauth.flows });
      const oidc = result.find(s => s.scheme_name === 'oidc');
      expect(oidc?.scheme_type).toBe('openIdConnect');
      expect(oidc?.data).toEqual({ openIdConnectUrl: 'https://id.example.com/.well-known/openid-configuration' });
    });
  });

  describe('parseOpenAPISpec returns paths and securitySchemes', () => {
    it('includes paths when spec has paths', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Test
  version: 1.0
paths:
  /health:
    get:
      responses:
        '200':
          description: OK
components:
  schemas: {}
`;
      const result = await parseOpenAPISpec(spec);
      expect(result.success).toBe(true);
      expect(result.paths).toBeDefined();
      expect(result.paths!).toHaveLength(1);
      expect(result.paths![0].path).toBe('/health');
      expect(result.paths![0].operations[0].method).toBe('GET');
    });

    it('includes securitySchemes when spec has components.securitySchemes', async () => {
      const spec = `
openapi: 3.1.0
info:
  title: Test
  version: 1.0
paths: {}
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
  securitySchemes:
    bearer:
      type: http
      scheme: bearer
`;
      const result = await parseOpenAPISpec(spec);
      expect(result.success).toBe(true);
      expect(result.securitySchemes).toBeDefined();
      expect(result.securitySchemes!).toHaveLength(1);
      expect(result.securitySchemes![0].scheme_name).toBe('bearer');
      expect(result.securitySchemes![0].scheme_type).toBe('http');
    });
  });

  describe('Example files: paths parsed and expected DB shape', () => {
    const examplesDir = path.join(__dirname, '../../examples/openapi');

    it('30-openapi-3.0-petstore.yaml has paths with params, request body, responses', async () => {
      const filePath = path.join(examplesDir, '30-openapi-3.0-petstore.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const result = await parseOpenAPISpec(content);
      expect(result.success).toBe(true);
      expect(result.paths).toBeDefined();
      const paths = result.paths!;

      // Expect /pets and /pets/{petId}
      expect(paths.length).toBeGreaterThanOrEqual(2);
      const petsPath = paths.find(p => p.path === '/pets');
      const petByIdPath = paths.find(p => p.path === '/pets/{petId}');
      expect(petsPath).toBeDefined();
      expect(petByIdPath).toBeDefined();

      // /pets: path-level header param, get (query params), post (request body, multiple responses)
      expect(petsPath!.parameters?.length).toBeGreaterThanOrEqual(1);
      const listOp = petsPath!.operations.find(o => o.method === 'GET');
      expect(listOp).toBeDefined();
      expect(listOp!.parameters.some(p => p.in === 'query')).toBe(true);
      const createOp = petsPath!.operations.find(o => o.method === 'POST');
      expect(createOp).toBeDefined();
      expect(createOp!.requestBody).toBeDefined();
      expect(createOp!.requestBody!.content!['application/json']).toBeDefined();
      expect(Object.keys(createOp!.responses)).toContain('201');
      expect(Object.keys(createOp!.responses)).toContain('400');
      expect(Object.keys(createOp!.responses)).toContain('422');

      // /pets/{petId}: get (path param), put (path param + body), delete (path param, 204/404)
      expect(petByIdPath!.operations.some(o => o.method === 'GET')).toBe(true);
      expect(petByIdPath!.operations.some(o => o.method === 'PUT')).toBe(true);
      expect(petByIdPath!.operations.some(o => o.method === 'DELETE')).toBe(true);
      const getOp = petByIdPath!.operations.find(o => o.method === 'GET');
      expect(getOp!.parameters.some(p => p.name === 'petId' && p.in === 'path')).toBe(true);
    });

    it('20-comprehensive-features.yaml has paths with AdvancedOrder refs', () => {
      const filePath = path.join(examplesDir, '20-comprehensive-features.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const spec = YAML.parse(content);
      const paths = extractPaths(spec);
      expect(paths.length).toBeGreaterThanOrEqual(2);
      const ordersPath = paths.find(p => p.path === '/orders');
      const orderByIdPath = paths.find(p => p.path === '/orders/{orderId}');
      expect(ordersPath).toBeDefined();
      expect(orderByIdPath).toBeDefined();
      const postOrder = ordersPath!.operations.find(o => o.method === 'POST');
      expect(postOrder?.requestBody?.content?.['application/json']?.$ref).toContain('AdvancedOrder');
      const getOrder = orderByIdPath!.operations.find(o => o.method === 'GET');
      expect(getOrder?.parameters.some(p => p.name === 'orderId' && p.in === 'path')).toBe(true);
    });

    it('31-paths-comprehensive.yaml has path/query/header/cookie params and securitySchemes', async () => {
      const filePath = path.join(examplesDir, '31-paths-comprehensive.yaml');
      const content = fs.readFileSync(filePath, 'utf-8');
      const result = await parseOpenAPISpec(content);
      expect(result.success).toBe(true);
      expect(result.paths).toBeDefined();
      expect(result.securitySchemes).toBeDefined();
      expect(result.securitySchemes!.length).toBeGreaterThanOrEqual(2);

      const paths = result.paths!;
      expect(paths.length).toBeGreaterThanOrEqual(3);
      const itemsPath = paths.find(p => p.path === '/api/items');
      expect(itemsPath?.summary).toBeDefined();
      const getItems = itemsPath?.operations.find(o => o.method === 'GET');
      expect(getItems?.parameters.some(p => p.in === 'query')).toBe(true);
      expect(itemsPath?.parameters?.some(p => p.in === 'header')).toBe(true);

      const sessionPath = paths.find(p => p.path === '/api/session');
      const sessionOp = sessionPath?.operations.find(o => o.method === 'POST');
      expect(sessionOp?.parameters.some(p => p.in === 'header')).toBe(true);
      expect(sessionOp?.parameters.some(p => p.in === 'query')).toBe(true);

      const searchPath = paths.find(p => p.path === '/api/search');
      const searchOp = searchPath?.operations.find(o => o.method === 'GET');
      expect(searchOp?.parameters.some(p => p.in === 'cookie')).toBe(true);
    });
  });

  describe('Parsed path structure maps to expected DB objects', () => {
    /**
     * For each ParsedPath, the importer creates:
     * - 1 version_path (pathname, metadata with summary/description)
     * - N path_operation (one per operation)
     * - path_operation_description (summary, description, operation_id, metadata with tags/deprecated)
     * - shared_path_parameter + path_operation_parameter_link for each param
     * - shared_path_request_body + shared_path_request_body_content + path_operation_request_body_link when requestBody present
     * - shared_path_response + shared_path_response_content + path_operation_response_link for each response
     * We assert that the parsed structure has the right shape so that these DB rows can be created.
     */
    it('parsed path yields expected logical version_path and operations count', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/users': {
            get: { responses: { '200': { description: 'OK' } } },
            post: { requestBody: { content: { 'application/json': { schema: { type: 'object' } } } }, responses: { '201': { description: 'Created' } } },
          },
          '/users/{id}': {
            get: { parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'string' } }], responses: { '200': { description: 'OK' } } },
          },
        },
      };
      const paths = extractPaths(spec);
      expect(paths).toHaveLength(2);

      // First path: 2 operations (GET, POST); POST has requestBody
      expect(paths[0].path).toBe('/users');
      expect(paths[0].operations).toHaveLength(2);
      const postOp = paths[0].operations.find(o => o.method === 'POST');
      expect(postOp?.requestBody?.content).toBeDefined();
      expect(Object.keys(postOp!.requestBody!.content!).length).toBe(1);

      // Second path: 1 operation, 1 path parameter
      expect(paths[1].path).toBe('/users/{id}');
      expect(paths[1].operations).toHaveLength(1);
      expect(paths[1].operations[0].parameters).toHaveLength(1);
      expect(paths[1].operations[0].parameters[0].name).toBe('id');
      expect(paths[1].operations[0].parameters[0].in).toBe('path');
    });

    it('parsed responses yield expected status codes and content per operation', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/r': {
            get: {
              responses: {
                '200': { description: 'OK', content: { 'application/json': { schema: { type: 'object' } } } },
                '404': { description: 'Not found' },
              },
            },
          },
        },
      };
      const paths = extractPaths(spec);
      const op = paths[0].operations[0];
      expect(Object.keys(op.responses)).toEqual(['200', '404']);
      expect(op.responses['200'].content).toBeDefined();
      expect(op.responses['200'].content!['application/json'].schema).toEqual({ type: 'object' });
      expect(op.responses['404'].content).toBeUndefined();
    });

    it('inline request body schema is preserved for shared_path_request_body_content', () => {
      const spec = {
        openapi: '3.1.0',
        paths: {
          '/echo': {
            post: {
              requestBody: {
                content: {
                  'application/json': {
                    schema: {
                      type: 'object',
                      properties: { message: { type: 'string' } },
                      required: ['message'],
                    },
                  },
                },
              },
              responses: { '200': { description: 'OK' } },
            },
          },
        },
      };
      const paths = extractPaths(spec);
      const content = paths[0].operations[0].requestBody!.content!['application/json'];
      expect(content.schema).toBeDefined();
      expect(content.schema!.type).toBe('object');
      expect(content.schema!.properties!.message).toEqual({ type: 'string' });
      expect(content.$ref).toBeUndefined();
    });
  });
});
