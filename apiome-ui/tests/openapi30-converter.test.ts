/**
 * Tests for OpenAPI 3.0.x to 3.1.x converter
 */

import {
  convertOpenAPI30ToOpenAPI31,
  isOpenAPI30,
  OpenAPI30ConversionResult
} from '../src/app/utils/openapi30-converter';

describe('OpenAPI 3.0 to 3.1 Converter', () => {
  describe('isOpenAPI30', () => {
    it('should detect OpenAPI 3.0.0', () => {
      const doc = { openapi: '3.0.0' };
      expect(isOpenAPI30(doc)).toBe(true);
    });

    it('should detect OpenAPI 3.0.1', () => {
      const doc = { openapi: '3.0.1' };
      expect(isOpenAPI30(doc)).toBe(true);
    });

    it('should detect OpenAPI 3.0.3', () => {
      const doc = { openapi: '3.0.3' };
      expect(isOpenAPI30(doc)).toBe(true);
    });

    it('should not detect OpenAPI 3.1.0', () => {
      const doc = { openapi: '3.1.0' };
      expect(isOpenAPI30(doc)).toBe(false);
    });

    it('should not detect Swagger 2.0', () => {
      const doc = { swagger: '2.0' };
      expect(isOpenAPI30(doc)).toBe(false);
    });

    it('should not detect invalid documents', () => {
      expect(isOpenAPI30(null)).toBe(false);
      expect(isOpenAPI30({})).toBe(false);
      expect(isOpenAPI30({ openapi: '2.0' })).toBe(false);
    });
  });

  describe('convertOpenAPI30ToOpenAPI31', () => {
    it('should convert version number', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        components: { schemas: {} }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      expect(result.document.openapi).toBe('3.1.0');
    });

    it('should convert nullable to type array', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        components: {
          schemas: {
            Pet: {
              type: 'object',
              properties: {
                name: {
                  type: 'string',
                  nullable: true
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Pet.properties.name.type).toEqual(['string', 'null']);
      expect(result.document.components.schemas.Pet.properties.name.nullable).toBeUndefined();
      expect(result.warnings.length).toBeGreaterThan(0);
    });

    it('should convert nullable with no type to anyOf', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        components: {
          schemas: {
            Pet: {
              type: 'object',
              properties: {
                metadata: {
                  nullable: true,
                  properties: {
                    tags: { type: 'array' }
                  }
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Pet.properties.metadata.anyOf).toBeDefined();
      expect(result.document.components.schemas.Pet.properties.metadata.anyOf).toHaveLength(2);
      expect(result.document.components.schemas.Pet.properties.metadata.nullable).toBeUndefined();
    });

    it('removes top-level allOf/oneOf when wrapping nullable composition in anyOf', () => {
      // Regression: previously the converter left the original allOf at the top
      // of the schema while ALSO embedding it inside the new anyOf branch,
      // producing a malformed `{ allOf: [...], anyOf: [{ allOf: [...] }, { type: null }] }`.
      const doc = {
        openapi: '3.0.0',
        info: { title: 'N', version: '1' },
        components: {
          schemas: {
            Thing: {
              nullable: true,
              allOf: [{ type: 'object', properties: { x: { type: 'string' } } }],
            },
            ThingOne: {
              nullable: true,
              oneOf: [{ type: 'string' }, { type: 'integer' }],
            },
          },
        },
      };
      const result = convertOpenAPI30ToOpenAPI31(doc);
      expect(result.success).toBe(true);
      const t = result.document.components.schemas.Thing;
      expect(t.allOf).toBeUndefined();
      expect(t.nullable).toBeUndefined();
      expect(Array.isArray(t.anyOf)).toBe(true);
      expect(t.anyOf).toHaveLength(2);
      expect(t.anyOf[0].allOf).toBeDefined();
      expect(t.anyOf[1]).toEqual({ type: 'null' });

      const o = result.document.components.schemas.ThingOne;
      expect(o.oneOf).toBeUndefined();
      expect(o.anyOf[0].oneOf).toBeDefined();
      expect(o.anyOf[1]).toEqual({ type: 'null' });
    });

    it('should convert exclusiveMinimum from boolean to numeric', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        components: {
          schemas: {
            Product: {
              type: 'object',
              properties: {
                price: {
                  type: 'number',
                  minimum: 0,
                  exclusiveMinimum: true
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Product.properties.price.exclusiveMinimum).toBe(0);
      expect(result.document.components.schemas.Product.properties.price.minimum).toBeUndefined();
    });

    it('should convert exclusiveMaximum from boolean to numeric', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        components: {
          schemas: {
            Product: {
              type: 'object',
              properties: {
                discount: {
                  type: 'number',
                  maximum: 100,
                  exclusiveMaximum: true
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Product.properties.discount.exclusiveMaximum).toBe(100);
      expect(result.document.components.schemas.Product.properties.discount.maximum).toBeUndefined();
    });

    it('should convert nested schemas', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        components: {
          schemas: {
            Order: {
              type: 'object',
              properties: {
                items: {
                  type: 'array',
                  items: {
                    type: 'object',
                    properties: {
                      productId: {
                        type: 'string',
                        nullable: true
                      }
                    }
                  }
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      const itemSchema = result.document.components.schemas.Order.properties.items.items;
      expect(itemSchema.properties.productId.type).toEqual(['string', 'null']);
      expect(itemSchema.properties.productId.nullable).toBeUndefined();
    });

    it('should convert schemas in allOf', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        components: {
          schemas: {
            ExtendedPet: {
              allOf: [
                { $ref: '#/components/schemas/Pet' },
                {
                  type: 'object',
                  properties: {
                    breed: {
                      type: 'string',
                      nullable: true
                    }
                  }
                }
              ]
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      const allOfSchema = result.document.components.schemas.ExtendedPet.allOf[1];
      expect(allOfSchema.properties.breed.type).toEqual(['string', 'null']);
      expect(allOfSchema.properties.breed.nullable).toBeUndefined();
    });

    it('should handle paths and operations', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        paths: {
          '/pets': {
            get: {
              parameters: [
                {
                  name: 'limit',
                  in: 'query',
                  schema: {
                    type: 'integer',
                    nullable: true
                  }
                }
              ],
              responses: {
                '200': {
                  description: 'Success',
                  content: {
                    'application/json': {
                      schema: {
                        type: 'object',
                        properties: {
                          count: {
                            type: 'integer',
                            nullable: true
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      const paramSchema = result.document.paths['/pets'].get.parameters[0].schema;
      expect(paramSchema.type).toEqual(['integer', 'null']);
      expect(paramSchema.nullable).toBeUndefined();

      const responseSchema = result.document.paths['/pets'].get.responses['200'].content['application/json'].schema;
      expect(responseSchema.properties.count.type).toEqual(['integer', 'null']);
      expect(responseSchema.properties.count.nullable).toBeUndefined();
    });

    it('should handle request bodies', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        paths: {
          '/pets': {
            post: {
              requestBody: {
                content: {
                  'application/json': {
                    schema: {
                      type: 'object',
                      properties: {
                        name: {
                          type: 'string',
                          nullable: true
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      const bodySchema = result.document.paths['/pets'].post.requestBody.content['application/json'].schema;
      expect(bodySchema.properties.name.type).toEqual(['string', 'null']);
      expect(bodySchema.properties.name.nullable).toBeUndefined();
    });

    it('should preserve $ref without modification', () => {
      const doc = {
        openapi: '3.0.0',
        info: { title: 'Test API', version: '1.0.0' },
        components: {
          schemas: {
            Pet: {
              type: 'object',
              properties: {
                category: {
                  $ref: '#/components/schemas/Category'
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      expect(result.document.components.schemas.Pet.properties.category.$ref).toBe('#/components/schemas/Category');
    });

    it('should handle invalid input gracefully', () => {
      const result = convertOpenAPI30ToOpenAPI31(null);

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });

    it('should reject non-3.0 versions', () => {
      const doc = {
        openapi: '3.1.0',
        info: { title: 'Test API', version: '1.0.0' }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(false);
      expect(result.error).toContain('3.0.x');
    });

    it('should convert complete Petstore example', () => {
      const doc = {
        openapi: '3.0.0',
        info: {
          title: 'Petstore API',
          version: '1.0.0',
          description: 'A sample pet store API'
        },
        servers: [
          { url: 'https://api.petstore.com/v1' }
        ],
        components: {
          schemas: {
            Pet: {
              type: 'object',
              required: ['id', 'name'],
              properties: {
                id: {
                  type: 'integer',
                  format: 'int64'
                },
                name: {
                  type: 'string'
                },
                tag: {
                  type: 'string',
                  nullable: true
                },
                age: {
                  type: 'integer',
                  minimum: 0,
                  exclusiveMinimum: true
                }
              }
            }
          }
        },
        paths: {
          '/pets': {
            get: {
              summary: 'List all pets',
              responses: {
                '200': {
                  description: 'Success',
                  content: {
                    'application/json': {
                      schema: {
                        type: 'array',
                        items: {
                          $ref: '#/components/schemas/Pet'
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      };

      const result = convertOpenAPI30ToOpenAPI31(doc);

      expect(result.success).toBe(true);
      expect(result.document.openapi).toBe('3.1.0');
      expect(result.document.info.title).toBe('Petstore API');
      expect(result.document.components.schemas.Pet.properties.tag.type).toEqual(['string', 'null']);
      expect(result.document.components.schemas.Pet.properties.tag.nullable).toBeUndefined();
      expect(result.document.components.schemas.Pet.properties.age.exclusiveMinimum).toBe(0);
      expect(result.document.paths['/pets'].get.responses['200'].content['application/json'].schema.items.$ref).toBe('#/components/schemas/Pet');
    });
  });
});

