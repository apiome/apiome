/**
 * Tests for the OpenAPI 3.2.0 to 3.1.x normalization layer (OA2, #3499).
 */

import {
  convertOpenAPI32ToOpenAPI31,
  isOpenAPI32,
  OpenAPI32ConversionResult
} from '../src/app/utils/openapi32-converter';

/** Minimal valid 3.2.0 envelope with the supplied body merged in. */
function doc(body: Record<string, any>): any {
  return {
    openapi: '3.2.0',
    info: { title: 'Test API', version: '1.0.0' },
    ...body
  };
}

describe('OpenAPI 3.2 to 3.1 normalization layer', () => {
  describe('isOpenAPI32', () => {
    it('detects 3.2.0', () => {
      expect(isOpenAPI32({ openapi: '3.2.0' })).toBe(true);
    });

    it('detects 3.2.x minors', () => {
      expect(isOpenAPI32({ openapi: '3.2.5' })).toBe(true);
    });

    it('does not detect 3.0.x / 3.1.x', () => {
      expect(isOpenAPI32({ openapi: '3.0.0' })).toBe(false);
      expect(isOpenAPI32({ openapi: '3.1.0' })).toBe(false);
    });

    it('does not detect Swagger or invalid documents', () => {
      expect(isOpenAPI32({ swagger: '2.0' })).toBe(false);
      expect(isOpenAPI32(null)).toBe(false);
      expect(isOpenAPI32({})).toBe(false);
    });
  });

  describe('convertOpenAPI32ToOpenAPI31 — guard rails', () => {
    it('rewrites the version to 3.1.0', () => {
      const result = convertOpenAPI32ToOpenAPI31(doc({ components: { schemas: {} } }));
      expect(result.success).toBe(true);
      expect(result.document.openapi).toBe('3.1.0');
    });

    it('rejects non-3.2 versions', () => {
      const result = convertOpenAPI32ToOpenAPI31({ openapi: '3.1.0', info: { title: 'T', version: '1' } });
      expect(result.success).toBe(false);
      expect(result.error).toContain('3.2.x');
    });

    it('rejects invalid input', () => {
      const result = convertOpenAPI32ToOpenAPI31(null);
      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });

    it('does not mutate the input document', () => {
      const input = doc({
        paths: { '/a': { query: { responses: { '200': { description: 'ok' } } } } }
      });
      const snapshot = JSON.stringify(input);
      convertOpenAPI32ToOpenAPI31(input);
      expect(JSON.stringify(input)).toBe(snapshot);
    });
  });

  describe('example -> examples normalization', () => {
    it('folds a singular media type example into the examples map', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          paths: {
            '/pets': {
              get: {
                responses: {
                  '200': {
                    description: 'ok',
                    content: {
                      'application/json': {
                        schema: { type: 'object' },
                        example: { id: 1 }
                      }
                    }
                  }
                }
              }
            }
          }
        })
      );

      expect(result.success).toBe(true);
      const media = result.document.paths['/pets'].get.responses['200'].content['application/json'];
      expect(media.example).toBeUndefined();
      expect(media.examples).toEqual({ default: { value: { id: 1 } } });
      expect(result.warnings.some((w) => w.toLowerCase().includes('example'))).toBe(true);
    });

    it('folds a singular parameter example into the examples map', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          components: {
            parameters: {
              Limit: { name: 'limit', in: 'query', schema: { type: 'integer' }, example: 10 }
            }
          }
        })
      );

      const param = result.document.components.parameters.Limit;
      expect(param.example).toBeUndefined();
      expect(param.examples).toEqual({ default: { value: 10 } });
    });

    it('drops a redundant singular example when an examples map already exists', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          components: {
            parameters: {
              Limit: {
                name: 'limit',
                in: 'query',
                schema: { type: 'integer' },
                example: 10,
                examples: { ten: { value: 10 }, twenty: { value: 20 } }
              }
            }
          }
        })
      );

      const param = result.document.components.parameters.Limit;
      expect(param.example).toBeUndefined();
      expect(param.examples).toEqual({ ten: { value: 10 }, twenty: { value: 20 } });
    });
  });

  describe('XML nodeType mapping', () => {
    it('maps nodeType "attribute" to the legacy attribute: true field', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          components: {
            schemas: {
              Pet: {
                type: 'object',
                properties: {
                  id: { type: 'string', xml: { nodeType: 'attribute' } }
                }
              }
            }
          }
        })
      );

      const xml = result.document.components.schemas.Pet.properties.id.xml;
      expect(xml.nodeType).toBeUndefined();
      expect(xml.attribute).toBe(true);
    });

    it('stashes nodeType values without a legacy equivalent and reports them for OA6', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          components: {
            schemas: {
              Pet: {
                type: 'object',
                properties: {
                  note: { type: 'string', xml: { nodeType: 'cdata' } }
                }
              }
            }
          }
        })
      );

      const xml = result.document.components.schemas.Pet.properties.note.xml;
      expect(xml.nodeType).toBeUndefined();
      expect(xml['x-apiome-xml-node-type']).toBe('cdata');
      const construct = result.unsupportedConstructs.find((c) => c.id === 'xml-node-type');
      expect(construct).toBeDefined();
      expect(construct?.ownedBy).toBe('OA6');
    });
  });

  describe('$ref sibling metadata (OA6)', () => {
    it('preserves summary/description siblings on a $ref and reports them', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          components: {
            schemas: {
              Pet: {
                type: 'object',
                properties: {
                  category: {
                    $ref: '#/components/schemas/Category',
                    summary: 'The pet category',
                    description: 'A reference with metadata'
                  }
                }
              }
            }
          }
        })
      );

      const category = result.document.components.schemas.Pet.properties.category;
      expect(category.$ref).toBe('#/components/schemas/Category');
      expect(category.summary).toBe('The pet category');
      expect(category.description).toBe('A reference with metadata');
      expect(result.unsupportedConstructs.find((c) => c.id === 'ref-sibling-metadata')?.ownedBy).toBe('OA6');
    });
  });

  describe('OA4 — additionalOperations and QUERY method', () => {
    it('stashes additionalOperations on an extension and reports the count', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          paths: {
            '/pets': {
              get: { responses: { '200': { description: 'ok' } } },
              additionalOperations: {
                PURGE: { responses: { '204': { description: 'purged' } } }
              }
            }
          }
        })
      );

      const pathItem = result.document.paths['/pets'];
      expect(pathItem.additionalOperations).toBeUndefined();
      expect(pathItem['x-apiome-additional-operations'].PURGE).toBeDefined();
      const construct = result.unsupportedConstructs.find((c) => c.id === 'additional-operations');
      expect(construct?.ownedBy).toBe('OA4');
      expect(construct?.count).toBe(1);
    });

    it('stashes a QUERY operation on an extension and reports it', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          paths: {
            '/search': {
              query: { responses: { '200': { description: 'results' } } }
            }
          }
        })
      );

      const pathItem = result.document.paths['/search'];
      expect(pathItem.query).toBeUndefined();
      expect(pathItem['x-apiome-query-operation']).toBeDefined();
      expect(result.unsupportedConstructs.find((c) => c.id === 'query-method')?.ownedBy).toBe('OA4');
    });
  });

  describe('OA3 — sequential media types / itemSchema', () => {
    it('stashes itemSchema on an extension and reports it', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          paths: {
            '/events': {
              get: {
                responses: {
                  '200': {
                    description: 'stream',
                    content: {
                      'text/event-stream': {
                        itemSchema: { type: 'object', properties: { data: { type: 'string' } } }
                      }
                    }
                  }
                }
              }
            }
          }
        })
      );

      const media = result.document.paths['/events'].get.responses['200'].content['text/event-stream'];
      expect(media.itemSchema).toBeUndefined();
      expect(media['x-apiome-item-schema']).toBeDefined();
      expect(result.unsupportedConstructs.find((c) => c.id === 'item-schema')?.ownedBy).toBe('OA3');
    });
  });

  describe('OA5 — tag metadata', () => {
    it('preserves summary/parent/kind on tags and reports them', () => {
      const result = convertOpenAPI32ToOpenAPI31(
        doc({
          tags: [
            { name: 'pets', summary: 'Pet operations', parent: 'store', kind: 'nav' },
            { name: 'store' }
          ]
        })
      );

      const petsTag = result.document.tags.find((t: any) => t.name === 'pets');
      expect(petsTag.summary).toBe('Pet operations');
      expect(petsTag.parent).toBe('store');
      expect(petsTag.kind).toBe('nav');
      const construct = result.unsupportedConstructs.find((c) => c.id === 'tag-metadata');
      expect(construct?.ownedBy).toBe('OA5');
      expect(construct?.count).toBe(1);
    });
  });

  describe('lossless pass-through', () => {
    it('leaves a plain 3.1-compatible 3.2 document structurally identical (besides version)', () => {
      const input = doc({
        components: {
          schemas: {
            Widget: {
              type: 'object',
              required: ['id'],
              properties: {
                id: { type: 'string' },
                tags: { type: 'array', items: { $ref: '#/components/schemas/Tag' } }
              }
            },
            Tag: { type: 'object', properties: { name: { type: 'string' } } }
          }
        }
      });

      const result = convertOpenAPI32ToOpenAPI31(input);
      expect(result.success).toBe(true);
      expect(result.unsupportedConstructs).toHaveLength(0);

      const expected = JSON.parse(JSON.stringify(input));
      expected.openapi = '3.1.0';
      expect(result.document).toEqual(expected);
    });
  });
});
