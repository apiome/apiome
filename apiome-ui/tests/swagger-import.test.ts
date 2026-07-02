/**
 * Swagger 2.x Import Test Suite
 *
 * Tests the conversion of Swagger 2.0 specifications to OpenAPI 3.1.x
 * and validates the import functionality.
 */

import { describe, test, expect } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';
import * as YAML from 'yaml';
import {
  convertSwaggerToOpenAPI,
  isSwagger2,
  getSwaggerVersion
} from '../src/app/utils/swagger-converter';
import { parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { analyzeSpecification, extractFileMetadata } from '../src/app/utils/openapi-analyzer';

// Test configuration
const EXAMPLES_DIR = path.join(__dirname, '../examples/swagger');
const SWAGGER_FILE = path.join(EXAMPLES_DIR, '01-swagger-2-petstore.yaml');

/**
 * Load a YAML file and parse it
 */
function loadYamlFile(filePath: string): any {
  const content = fs.readFileSync(filePath, 'utf-8');
  return YAML.parse(content);
}

/**
 * Load file content as string
 */
function loadFileContent(filePath: string): string {
  return fs.readFileSync(filePath, 'utf-8');
}

describe('Swagger 2.x Import Tests', () => {
  describe('Swagger Detection', () => {
    test('should detect Swagger 2.0 specification', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      expect(isSwagger2(doc)).toBe(true);
    });

    test('should return correct Swagger version', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      expect(getSwaggerVersion(doc)).toBe('2.0');
    });

    test('should not detect OpenAPI 3.x as Swagger', () => {
      const openapi3Doc = {
        openapi: '3.1.0',
        info: { title: 'Test', version: '1.0.0' }
      };
      expect(isSwagger2(openapi3Doc)).toBe(false);
    });

    test('should return null for non-Swagger document', () => {
      const doc = { title: 'Not a spec' };
      expect(getSwaggerVersion(doc)).toBeNull();
    });
  });

  describe('Swagger to OpenAPI Conversion', () => {
    test('should convert Swagger 2.0 to OpenAPI 3.1.0', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      expect(result.success).toBe(true);
      expect(result.document).toBeDefined();
      expect(result.document.openapi).toBe('3.1.0');
    });

    test('should convert info section correctly', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      expect(result.document.info.title).toBe('Pet Store API');
      expect(result.document.info.version).toBe('1.0.0');
      expect(result.document.info.description).toBeDefined();
    });

    test('should convert definitions to components/schemas', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      expect(result.document.components).toBeDefined();
      expect(result.document.components.schemas).toBeDefined();
      expect(result.document.components.schemas.Pet).toBeDefined();
      expect(result.document.components.schemas.NewPet).toBeDefined();
      expect(result.document.components.schemas.Error).toBeDefined();
    });

    test('should convert $ref paths from #/definitions/ to #/components/schemas/', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      // Check that Pet's category reference is converted
      const petSchema = result.document.components.schemas.Pet;
      expect(petSchema.properties.category.$ref).toBe('#/components/schemas/Category');
    });

    test('should convert host/basePath/schemes to servers', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      expect(result.document.servers).toBeDefined();
      expect(result.document.servers.length).toBeGreaterThan(0);

      // Should have HTTPS server
      const httpsServer = result.document.servers.find((s: any) => s.url.startsWith('https://'));
      expect(httpsServer).toBeDefined();
      expect(httpsServer.url).toContain('api.petstore.example.com');
    });

    test('should convert security definitions to security schemes', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      expect(result.document.components.securitySchemes).toBeDefined();
      expect(result.document.components.securitySchemes.api_key).toBeDefined();
      expect(result.document.components.securitySchemes.api_key.type).toBe('apiKey');

      expect(result.document.components.securitySchemes.basic_auth).toBeDefined();
      expect(result.document.components.securitySchemes.basic_auth.type).toBe('http');
      expect(result.document.components.securitySchemes.basic_auth.scheme).toBe('basic');

      expect(result.document.components.securitySchemes.oauth2).toBeDefined();
      expect(result.document.components.securitySchemes.oauth2.type).toBe('oauth2');
      expect(result.document.components.securitySchemes.oauth2.flows.authorizationCode).toBeDefined();
    });

    test('should convert paths with parameters', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      expect(result.document.paths).toBeDefined();
      expect(result.document.paths['/pets']).toBeDefined();
      expect(result.document.paths['/pets'].get).toBeDefined();

      // Check query parameter conversion
      const getOperation = result.document.paths['/pets'].get;
      expect(getOperation.parameters).toBeDefined();

      const limitParam = getOperation.parameters.find((p: any) => p.name === 'limit');
      expect(limitParam).toBeDefined();
      expect(limitParam.schema).toBeDefined();
      expect(limitParam.schema.type).toBe('integer');
    });

    test('should convert body parameter to requestBody', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      const postOperation = result.document.paths['/pets'].post;
      expect(postOperation.requestBody).toBeDefined();
      expect(postOperation.requestBody.content).toBeDefined();
      expect(postOperation.requestBody.content['application/json']).toBeDefined();
    });

    test('should convert responses with schemas', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      const getOperation = result.document.paths['/pets'].get;
      expect(getOperation.responses['200']).toBeDefined();
      expect(getOperation.responses['200'].content).toBeDefined();
      expect(getOperation.responses['200'].content['application/json']).toBeDefined();
    });

    test('should preserve tags', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      expect(result.document.tags).toBeDefined();
      expect(result.document.tags.length).toBe(3);
      expect(result.document.tags.find((t: any) => t.name === 'pet')).toBeDefined();
    });

    test('should handle file type conversion', () => {
      const doc = loadYamlFile(SWAGGER_FILE);
      const result = convertSwaggerToOpenAPI(doc);

      // Check the upload endpoint with file parameter
      const uploadPath = result.document.paths['/pets/{petId}/upload'];
      expect(uploadPath).toBeDefined();
      expect(uploadPath.post.requestBody).toBeDefined();
    });

    test('should handle x-nullable conversion', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        definitions: {
          TestSchema: {
            type: 'object',
            properties: {
              nullableField: {
                type: 'string',
                'x-nullable': true
              }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const nullableField = result.document.components.schemas.TestSchema.properties.nullableField;
      // In OpenAPI 3.1, nullable is represented as type array
      expect(nullableField.type).toEqual(['string', 'null']);
    });

    test('should fail for invalid Swagger version', () => {
      const invalidDoc = {
        swagger: '1.0',
        info: { title: 'Test', version: '1.0.0' }
      };

      const result = convertSwaggerToOpenAPI(invalidDoc);
      expect(result.success).toBe(false);
      expect(result.error).toContain('Invalid Swagger version');
    });

    test('should fail for invalid document', () => {
      const result = convertSwaggerToOpenAPI(null);
      expect(result.success).toBe(false);
      expect(result.error).toContain('Invalid Swagger document');
    });
  });

  describe('OpenAPI Analyzer with Swagger 2.x', () => {
    test('should analyze Swagger 2.x specification', async () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = await analyzeSpecification(content, '01-swagger-2-petstore.yaml');

      expect(result.isValid).toBe(true);
      expect(result.formatSupported).toBe(true);
      expect(result.syntaxValid).toBe(true);
    });

    test('should detect format as openapi after conversion', async () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = await analyzeSpecification(content, '01-swagger-2-petstore.yaml');

      // After conversion, it should be detected as openapi 3.1.0
      expect(result.format).toBe('openapi');
      expect(result.version).toBe('3.1.0');
    });

    test('should count schemas correctly after conversion', async () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = await analyzeSpecification(content, '01-swagger-2-petstore.yaml');

      // Pet, NewPet, UpdatePet, Category, Error, UploadResponse, Order, User
      expect(result.metrics.schemaCount).toBe(8);
    });

    test('should count paths correctly after conversion', async () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = await analyzeSpecification(content, '01-swagger-2-petstore.yaml');

      // /pets, /pets/{petId}, /pets/{petId}/upload
      expect(result.metrics.pathCount).toBe(3);
    });

    test('should have conversion info in warnings', async () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = await analyzeSpecification(content, '01-swagger-2-petstore.yaml');

      // Should have some conversion-related warnings
      expect(result.warnings.length).toBeGreaterThanOrEqual(0);
    });

    test('should return converted document', async () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = await analyzeSpecification(content, '01-swagger-2-petstore.yaml');

      expect(result.document).toBeDefined();
      expect(result.document.openapi).toBe('3.1.0');
      expect(result.document.components.schemas).toBeDefined();
    });
  });

  describe('File Metadata Extraction for Swagger 2.x', () => {
    test('should extract metadata from Swagger 2.x file', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const metadata = extractFileMetadata(content);

      expect(metadata.syntaxValid).toBe(true);
      expect(metadata.syntax).toBe('yaml');
      expect(metadata.format).toBe('swagger');
      expect(metadata.version).toBe('2.0');
      expect(metadata.formatSupported).toBe(true);
    });

    test('should extract title and description', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const metadata = extractFileMetadata(content);

      expect(metadata.title).toBe('Pet Store API');
      expect(metadata.description).toBeDefined();
      expect(metadata.specVersion).toBe('1.0.0');
    });

    test('should show supported status for Swagger 2.x', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const metadata = extractFileMetadata(content);

      expect(metadata.formatSupported).toBe(true);
      expect(metadata.formatDisplayName).toContain('Swagger 2.0');
      expect(metadata.formatDisplayName).toContain('converted');
    });
  });

  describe('OpenAPI Import with Swagger 2.x', () => {
    test('should parse Swagger 2.x specification successfully', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = parseOpenAPISpec(content);

      expect(result.success).toBe(true);
      expect(result.classes.length).toBeGreaterThan(0);
    });

    test('should extract all schemas as classes', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = parseOpenAPISpec(content);

      expect(result.classes.length).toBe(8);

      const classNames = result.classes.map(c => c.name);
      expect(classNames).toContain('Pet');
      expect(classNames).toContain('NewPet');
      expect(classNames).toContain('UpdatePet');
      expect(classNames).toContain('Category');
      expect(classNames).toContain('Error');
      expect(classNames).toContain('UploadResponse');
      expect(classNames).toContain('Order');
      expect(classNames).toContain('User');
    });

    test('should include conversion info in warnings', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = parseOpenAPISpec(content);

      // Should have conversion info
      const hasConversionInfo = result.warnings.some(w =>
        w.toLowerCase().includes('swagger') || w.toLowerCase().includes('convert')
      );
      expect(hasConversionInfo).toBe(true);
    });

    test('should extract properties from Pet schema', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = parseOpenAPISpec(content);

      const petClass = result.classes.find(c => c.name === 'Pet');
      expect(petClass).toBeDefined();

      const propNames = petClass!.properties.map(p => p.name);
      expect(propNames).toContain('id');
      expect(propNames).toContain('name');
      expect(propNames).toContain('status');
    });

    test('should preserve schema descriptions', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = parseOpenAPISpec(content);

      const petClass = result.classes.find(c => c.name === 'Pet');
      expect(petClass).toBeDefined();
      expect(petClass!.description).toBe('A pet in the store');
    });

    test('should extract title and version from spec', () => {
      const content = loadFileContent(SWAGGER_FILE);
      const result = parseOpenAPISpec(content);

      expect(result.title).toBe('Pet Store API');
      expect(result.version).toBe('1.0.0');
    });
  });

  describe('Edge Cases', () => {
    test('should handle Swagger 2.x with minimal content', () => {
      const minimalSwagger = `
swagger: "2.0"
info:
  title: Minimal API
  version: "1.0.0"
paths: {}
definitions:
  SimpleModel:
    type: object
    properties:
      id:
        type: integer
`;

      const result = convertSwaggerToOpenAPI(YAML.parse(minimalSwagger));
      expect(result.success).toBe(true);
      expect(result.document.components.schemas.SimpleModel).toBeDefined();
    });

    test('should handle Swagger 2.x without definitions', () => {
      const noDefsSwagger = `
swagger: "2.0"
info:
  title: No Definitions API
  version: "1.0.0"
paths:
  /health:
    get:
      responses:
        "200":
          description: OK
`;

      const result = convertSwaggerToOpenAPI(YAML.parse(noDefsSwagger));
      expect(result.success).toBe(true);
      expect(result.document.components.schemas).toEqual({});
    });

    test('should handle collectionFormat conversion', () => {
      const swaggerWithCollection = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        paths: {
          '/test': {
            get: {
              parameters: [
                {
                  name: 'ids',
                  in: 'query',
                  type: 'array',
                  items: { type: 'string' },
                  collectionFormat: 'csv'
                },
                {
                  name: 'tags',
                  in: 'query',
                  type: 'array',
                  items: { type: 'string' },
                  collectionFormat: 'multi'
                }
              ],
              responses: {
                '200': { description: 'OK' }
              }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerWithCollection);
      expect(result.success).toBe(true);

      const params = result.document.paths['/test'].get.parameters;
      const idsParam = params.find((p: any) => p.name === 'ids');
      expect(idsParam.style).toBe('form');
      expect(idsParam.explode).toBe(false);

      const tagsParam = params.find((p: any) => p.name === 'tags');
      expect(tagsParam.style).toBe('form');
      expect(tagsParam.explode).toBe(true);
    });

    test('should handle discriminator string to object conversion', () => {
      const swaggerWithDiscriminator = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        definitions: {
          Animal: {
            type: 'object',
            discriminator: 'animalType',
            properties: {
              animalType: { type: 'string' }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerWithDiscriminator);
      expect(result.success).toBe(true);

      const discriminator = result.document.components.schemas.Animal.discriminator;
      expect(discriminator).toEqual({ propertyName: 'animalType' });
    });

    test('should handle JSON format Swagger 2.x', () => {
      const jsonSwagger = JSON.stringify({
        swagger: '2.0',
        info: { title: 'JSON API', version: '1.0.0' },
        definitions: {
          Model: {
            type: 'object',
            properties: {
              id: { type: 'integer' }
            }
          }
        }
      });

      const result = parseOpenAPISpec(jsonSwagger);
      expect(result.success).toBe(true);
      expect(result.classes.find(c => c.name === 'Model')).toBeDefined();
    });

    test('should resolve #/parameters/$ref for path operations (Adafruit-style)', () => {
      const yaml = `
swagger: "2.0"
info:
  title: Ref params API
  version: "1.0.0"
paths:
  "/{username}/feeds":
    get:
      parameters:
        - $ref: "#/parameters/UsernamePath"
      responses:
        "200":
          description: ok
parameters:
  UsernamePath:
    in: path
    name: username
    required: true
    type: string
`;
      const result = parseOpenAPISpec(yaml);
      expect(result.success).toBe(true);
      const feedsPath = result.paths?.find(p => p.path === '/{username}/feeds');
      expect(feedsPath).toBeDefined();
      const getFeeds = feedsPath!.operations.find(o => o.method === 'GET');
      expect(getFeeds!.parameters.some(p => p.name === 'username' && p.in === 'path')).toBe(true);
    });

    test('should detect Swagger 2.x when swagger is a JSON number', () => {
      expect(isSwagger2({ swagger: 2, info: {} })).toBe(true);
      expect(isSwagger2({ swagger: 2.0, info: {} })).toBe(true);
      expect(getSwaggerVersion({ swagger: 2 })).toBe('2');
    });
  });

  describe('OAuth2 Flow Conversion', () => {
    test('should convert implicit flow', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        securityDefinitions: {
          oauth_implicit: {
            type: 'oauth2',
            flow: 'implicit',
            authorizationUrl: 'https://example.com/oauth/authorize',
            scopes: { read: 'Read access' }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const oauth = result.document.components.securitySchemes.oauth_implicit;
      expect(oauth.flows.implicit).toBeDefined();
      expect(oauth.flows.implicit.authorizationUrl).toBe('https://example.com/oauth/authorize');
    });

    test('should convert password flow', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        securityDefinitions: {
          oauth_password: {
            type: 'oauth2',
            flow: 'password',
            tokenUrl: 'https://example.com/oauth/token',
            scopes: { write: 'Write access' }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const oauth = result.document.components.securitySchemes.oauth_password;
      expect(oauth.flows.password).toBeDefined();
      expect(oauth.flows.password.tokenUrl).toBe('https://example.com/oauth/token');
    });

    test('should convert application flow to clientCredentials', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        securityDefinitions: {
          oauth_app: {
            type: 'oauth2',
            flow: 'application',
            tokenUrl: 'https://example.com/oauth/token',
            scopes: {}
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const oauth = result.document.components.securitySchemes.oauth_app;
      expect(oauth.flows.clientCredentials).toBeDefined();
    });
  });

  describe('Additional Edge Cases', () => {
    test('should handle formData parameters', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        paths: {
          '/upload': {
            post: {
              consumes: ['application/x-www-form-urlencoded'],
              parameters: [
                {
                  name: 'username',
                  in: 'formData',
                  type: 'string',
                  required: true,
                  description: 'User name'
                },
                {
                  name: 'age',
                  in: 'formData',
                  type: 'integer',
                  required: false
                }
              ],
              responses: { '200': { description: 'OK' } }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const postOp = result.document.paths['/upload'].post;
      expect(postOp.requestBody).toBeDefined();
      expect(postOp.requestBody.content['application/x-www-form-urlencoded']).toBeDefined();

      const schema = postOp.requestBody.content['application/x-www-form-urlencoded'].schema;
      expect(schema.properties.username).toBeDefined();
      expect(schema.properties.age).toBeDefined();
      expect(schema.required).toContain('username');
    });

    test('should handle path-level parameters', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        paths: {
          '/users/{id}': {
            parameters: [
              { name: 'id', in: 'path', type: 'integer', required: true }
            ],
            get: {
              responses: { '200': { description: 'OK' } }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const pathItem = result.document.paths['/users/{id}'];
      expect(pathItem.parameters).toBeDefined();
      expect(pathItem.parameters[0].name).toBe('id');
      expect(pathItem.parameters[0].schema.type).toBe('integer');
    });

    test('should handle response headers', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        paths: {
          '/data': {
            get: {
              produces: ['application/json'],
              responses: {
                '200': {
                  description: 'Success',
                  schema: { type: 'object' },
                  headers: {
                    'X-Rate-Limit': {
                      type: 'integer',
                      description: 'Rate limit'
                    }
                  }
                }
              }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const response = result.document.paths['/data'].get.responses['200'];
      expect(response.headers).toBeDefined();
      expect(response.headers['X-Rate-Limit']).toBeDefined();
      expect(response.headers['X-Rate-Limit'].schema.type).toBe('integer');
    });

    test('should handle response examples', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        paths: {
          '/data': {
            get: {
              responses: {
                '200': {
                  description: 'Success',
                  examples: {
                    'application/json': { id: 1, name: 'Test' }
                  }
                }
              }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const response = result.document.paths['/data'].get.responses['200'];
      expect(response.content['application/json'].example).toEqual({ id: 1, name: 'Test' });
    });

    test('should handle unknown OAuth2 flow with warning', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        securityDefinitions: {
          unknown_oauth: {
            type: 'oauth2',
            flow: 'unknown_flow',
            scopes: {}
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);
      expect(result.warnings.some(w => w.includes('Unknown OAuth2 flow'))).toBe(true);
    });

    test('should handle unknown security type with warning', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        securityDefinitions: {
          unknown_sec: {
            type: 'unknown_type',
            description: 'Unknown security'
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);
      expect(result.warnings.some(w => w.includes('Unknown security type'))).toBe(true);
    });

    test('should handle Swagger without host/basePath', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        paths: {}
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);
      // Should not have servers since host wasn't specified
      expect(result.document.servers).toBeUndefined();
    });

    test('should handle Swagger without info section', () => {
      const swaggerDoc = {
        swagger: '2.0',
        paths: {}
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);
      expect(result.document.info.title).toBe('Converted API');
      expect(result.document.info.version).toBe('1.0.0');
    });

    test('should preserve global security', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        security: [{ api_key: [] }],
        securityDefinitions: {
          api_key: { type: 'apiKey', name: 'X-API-Key', in: 'header' }
        },
        paths: {}
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);
      expect(result.document.security).toEqual([{ api_key: [] }]);
    });

    test('should preserve external docs', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        externalDocs: {
          description: 'Find more info here',
          url: 'https://example.com/docs'
        },
        paths: {}
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);
      expect(result.document.externalDocs).toEqual({
        description: 'Find more info here',
        url: 'https://example.com/docs'
      });
    });

    test('should handle array parameter with items', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        paths: {
          '/test': {
            get: {
              parameters: [
                {
                  name: 'ids',
                  in: 'query',
                  type: 'array',
                  items: { type: 'integer' },
                  collectionFormat: 'pipes'
                }
              ],
              responses: { '200': { description: 'OK' } }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const param = result.document.paths['/test'].get.parameters[0];
      expect(param.schema.type).toBe('array');
      expect(param.schema.items.type).toBe('integer');
      expect(param.style).toBe('pipeDelimited');
    });

    test('should handle parameter with allowEmptyValue', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        paths: {
          '/test': {
            get: {
              parameters: [
                {
                  name: 'filter',
                  in: 'query',
                  type: 'string',
                  allowEmptyValue: true
                }
              ],
              responses: { '200': { description: 'OK' } }
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const param = result.document.paths['/test'].get.parameters[0];
      expect(param.allowEmptyValue).toBe(true);
    });

    test('should handle nested allOf in schemas', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        definitions: {
          Base: {
            type: 'object',
            properties: { id: { type: 'integer' } }
          },
          Extended: {
            allOf: [
              { $ref: '#/definitions/Base' },
              { type: 'object', properties: { name: { type: 'string' } } }
            ]
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const extended = result.document.components.schemas.Extended;
      expect(extended.allOf).toBeDefined();
      expect(extended.allOf[0].$ref).toBe('#/components/schemas/Base');
    });

    test('should handle oneOf and anyOf schemas', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        definitions: {
          OneOfExample: {
            oneOf: [
              { type: 'string' },
              { type: 'integer' }
            ]
          },
          AnyOfExample: {
            anyOf: [
              { type: 'boolean' },
              { type: 'number' }
            ]
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      expect(result.document.components.schemas.OneOfExample.oneOf).toHaveLength(2);
      expect(result.document.components.schemas.AnyOfExample.anyOf).toHaveLength(2);
    });

    test('should handle additionalProperties in schemas', () => {
      const swaggerDoc = {
        swagger: '2.0',
        info: { title: 'Test', version: '1.0.0' },
        definitions: {
          MapType: {
            type: 'object',
            additionalProperties: {
              type: 'string'
            }
          }
        }
      };

      const result = convertSwaggerToOpenAPI(swaggerDoc);
      expect(result.success).toBe(true);

      const schema = result.document.components.schemas.MapType;
      expect(schema.additionalProperties).toEqual({ type: 'string' });
    });
  });
});

