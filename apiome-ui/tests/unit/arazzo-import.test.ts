/**
 * Unit tests for #299: Arazzo document import.
 * Supports components.schemas and inferring schemas from workflow steps.
 */

import { describe, it, expect } from '@jest/globals';
import { arazzoImporter, inferArazzoSchemasFromWorkflows } from '../../lib/importers/arazzo';

describe('#299 Arazzo import', () => {
  describe('inferArazzoSchemasFromWorkflows', () => {
    it('returns empty object when document has no workflows', () => {
      expect(inferArazzoSchemasFromWorkflows({})).toEqual({});
      expect(inferArazzoSchemasFromWorkflows({ workflows: [] })).toEqual({});
    });

    it('returns empty object when document is null or workflows is not an array', () => {
      expect(inferArazzoSchemasFromWorkflows(null as any)).toEqual({});
      expect(inferArazzoSchemasFromWorkflows(undefined as any)).toEqual({});
      expect(inferArazzoSchemasFromWorkflows({ workflows: null })).toEqual({});
      expect(inferArazzoSchemasFromWorkflows({ workflows: 'not-array' })).toEqual({});
    });

    it('skips workflows without workflowId or name', () => {
      const doc = {
        workflows: [
          { steps: [{ stepId: 'S1', requestBody: { payload: { x: 'y' } } }] },
          { workflowId: '', name: '', steps: [] },
        ],
      };
      expect(inferArazzoSchemasFromWorkflows(doc)).toEqual({});
    });

    it('skips steps without stepId or name', () => {
      const doc = {
        workflows: [
          {
            workflowId: 'W1',
            steps: [
              { requestBody: { payload: { a: 1 } } },
              { stepId: '', name: '', requestBody: { payload: { b: 2 } } },
            ],
          },
        ],
      };
      expect(inferArazzoSchemasFromWorkflows(doc)).toEqual({});
    });

    it('skips steps with no request body', () => {
      const doc = {
        workflows: [
          {
            workflowId: 'GetOnly',
            steps: [
              { stepId: 'GetPet', description: 'GET has no body' },
              { stepId: 'WithNullBody', requestBody: { payload: null } },
              { stepId: 'WithEmptyBody', request: { parameters: {} } },
            ],
          },
        ],
      };
      expect(inferArazzoSchemasFromWorkflows(doc)).toEqual({});
    });

    it('skips body keys that look like expressions', () => {
      const doc = {
        workflows: [
          {
            workflowId: 'W',
            steps: [
              {
                stepId: 'S',
                requestBody: {
                  payload: {
                    normal: 'value',
                    $ref: '$steps.other.outputs.id',
                    '${expr}': 'skip',
                  },
                },
              },
            ],
          },
        ],
      };
      const schemas = inferArazzoSchemasFromWorkflows(doc);
      const key = 'WS';
      expect(schemas[key].properties).toHaveProperty('normal');
      expect(schemas[key].properties).not.toHaveProperty('$ref');
      expect(schemas[key].properties).not.toHaveProperty('${expr}');
    });

    it('infers property types: integer, number, boolean, array, object, null', () => {
      const doc = {
        workflows: [
          {
            workflowId: 'Types',
            steps: [
              {
                stepId: 'Step',
                requestBody: {
                  payload: {
                    count: 42,
                    price: 29.99,
                    active: true,
                    tags: ['a', 'b'],
                    nested: { name: 'n' },
                    empty: null,
                  },
                },
              },
            ],
          },
        ],
      };
      const schemas = inferArazzoSchemasFromWorkflows(doc);
      const s = schemas['TypesStep'].properties;
      expect(s.count).toEqual({ type: 'integer' });
      expect(s.price).toEqual({ type: 'number' });
      expect(s.active).toEqual({ type: 'boolean' });
      expect(s.tags).toEqual({ type: 'array', items: { type: 'string' } });
      expect(s.nested).toEqual({ type: 'object', properties: { name: { type: 'string' } } });
      expect(s.empty).toEqual({ type: 'string', nullable: true });
    });

    it('infers multiple workflows and steps without key collision', () => {
      const doc = {
        workflows: [
          {
            workflowId: 'A',
            steps: [
              { stepId: 'Step1', requestBody: { payload: { x: 1 } } },
              { stepId: 'Step2', requestBody: { payload: { y: 2 } } },
            ],
          },
          {
            name: 'B',
            steps: [{ name: 'Only', request: { parameters: { body: { z: 3 } } } }],
          },
        ],
      };
      const schemas = inferArazzoSchemasFromWorkflows(doc);
      expect(Object.keys(schemas).sort()).toEqual(['AStep1', 'AStep2', 'BOnly']);
      expect(schemas['AStep1'].properties).toEqual({ x: { type: 'integer' } });
      expect(schemas['AStep2'].properties).toEqual({ y: { type: 'integer' } });
      expect(schemas['BOnly'].properties).toEqual({ z: { type: 'integer' } });
    });

    it('uses workflow description/summary and step description/summary in inferred schema', () => {
      const doc = {
        workflows: [
          {
            workflowId: 'W',
            description: 'Workflow desc',
            steps: [
              {
                stepId: 'S',
                summary: 'Step summary',
                requestBody: { payload: { a: 1 } },
              },
            ],
          },
        ],
      };
      const schemas = inferArazzoSchemasFromWorkflows(doc);
      expect(schemas['WS'].description).toBe('Step summary');
      const doc2 = {
        workflows: [
          {
            workflowId: 'W2',
            inputs: {
              type: 'object',
              properties: { p: { type: 'string' } },
            },
            summary: 'Inputs summary',
            steps: [],
          },
        ],
      };
      const schemas2 = inferArazzoSchemasFromWorkflows(doc2);
      expect(schemas2['W2Inputs'].description).toBe('Inputs summary');
    });

    it('strips separators in schema key (hyphens, underscores, spaces)', () => {
      const doc = {
        workflows: [
          {
            workflowId: 'my-workflow_id',
            steps: [
              { stepId: 'step-one', requestBody: { payload: { x: 1 } } },
            ],
          },
        ],
      };
      const schemas = inferArazzoSchemasFromWorkflows(doc);
      const key = Object.keys(schemas)[0];
      expect(key).toBe('myworkflowidstepone');
      expect(schemas[key].properties.x).toEqual({ type: 'integer' });
    });

    it('infers schemas from step request.parameters.body (YAML-style)', () => {
      const doc = {
        arazzo: '1.0.1',
        workflows: [
          {
            name: 'CreateAndGetTodo',
            steps: [
              {
                name: 'CreateTodo',
                request: {
                  parameters: {
                    body: {
                      title: 'Buy milk',
                      dueDate: '2025-12-25',
                      priority: 'high',
                    },
                  },
                },
              },
            ],
          },
        ],
      };
      const schemas = inferArazzoSchemasFromWorkflows(doc);
      const key = Object.keys(schemas)[0];
      expect(key).toBe('CreateAndGetTodoCreateTodo');
      const s = schemas[key];
      expect(s.type).toBe('object');
      expect(s.properties).toHaveProperty('title', { type: 'string' });
      expect(s.properties).toHaveProperty('dueDate', { type: 'string' });
      expect(s.properties).toHaveProperty('priority', { type: 'string' });
    });

    it('infers schemas from step requestBody.payload (spec-style)', () => {
      const doc = {
        arazzo: '1.0.1',
        workflows: [
          {
            workflowId: 'loginUser',
            steps: [
              {
                stepId: 'loginStep',
                requestBody: {
                  payload: {
                    username: 'u',
                    password: 'p',
                  },
                },
              },
            ],
          },
        ],
      };
      const schemas = inferArazzoSchemasFromWorkflows(doc);
      const key = 'loginUserloginStep'; // workflowId + stepId, separators stripped
      expect(Object.keys(schemas)).toContain(key);
      expect(schemas[key].properties).toHaveProperty('username');
      expect(schemas[key].properties).toHaveProperty('password');
    });

    it('infers workflow inputs as schema when present', () => {
      const doc = {
        arazzo: '1.0.1',
        workflows: [
          {
            workflowId: 'loginUser',
            inputs: {
              type: 'object',
              properties: {
                username: { type: 'string' },
                password: { type: 'string' },
              },
              required: ['username'],
            },
            steps: [],
          },
        ],
      };
      const schemas = inferArazzoSchemasFromWorkflows(doc);
      const key = 'loginUserInputs'; // workflowId + 'Inputs'
      expect(Object.keys(schemas)).toContain(key);
      expect(schemas[key].properties.username).toEqual({ type: 'string' });
      expect(schemas[key].required).toContain('username');
    });
  });

  describe('arazzoImporter.normalize', () => {
    it('uses components.schemas when present', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Test', version: '1.0.0' },
        components: {
          schemas: {
            Pet: {
              type: 'object',
              properties: {
                id: { type: 'integer' },
                name: { type: 'string' },
              },
              required: ['name'],
            },
          },
        },
        sourceDescriptions: [],
        workflows: [],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: { selectedSchemas: ['Pet'], applyNamingConvention: false },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('Pet');
      expect(result.classes[0].properties).toHaveLength(2);
      expect(result.classes[0].properties!.map((p) => p.name).sort()).toEqual(['id', 'name']);
    });

    it('infers from workflows when components.schemas is missing', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Todo', version: '1.0.0' },
        sourceDescriptions: [{ name: 'TodoAPI', type: 'openapi', url: 'https://example.com/openapi.json' }],
        workflows: [
          {
            name: 'CreateAndGetTodo',
            steps: [
              {
                name: 'CreateTodo',
                request: {
                  parameters: {
                    body: { title: 'x', dueDate: 'y' },
                  },
                },
              },
            ],
          },
        ],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: {
          selectedSchemas: ['CreateAndGetTodoCreateTodo'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('CreateAndGetTodoCreateTodo');
      expect(result.classes[0].properties!.map((p) => p.name).sort()).toEqual(['dueDate', 'title']);
      expect(result.warnings.some((w) => w.includes('inferred'))).toBe(true);
    });

    it('returns empty classes and warning when no schemas and no inferrable workflows', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Empty', version: '1.0.0' },
        sourceDescriptions: [],
        workflows: [{ workflowId: 'NoBody', steps: [{ stepId: 'NoBodyStep' }] }],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: { selectedSchemas: [], applyNamingConvention: false },
      });
      expect(result.classes).toHaveLength(0);
      expect(result.warnings.length).toBeGreaterThan(0);
    });

    it('respects selectedSchemas and only returns requested classes', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Multi', version: '1.0.0' },
        components: {
          schemas: {
            A: { type: 'object', properties: { a: { type: 'string' } } },
            B: { type: 'object', properties: { b: { type: 'string' } } },
            C: { type: 'object', properties: { c: { type: 'string' } } },
          },
        },
        sourceDescriptions: [],
        workflows: [],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: {
          selectedSchemas: ['A', 'C'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes).toHaveLength(2);
      expect(result.classes.map((c) => c.name).sort()).toEqual(['A', 'C']);
    });

    it('treats empty components.schemas as missing and infers from workflows', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Empty', version: '1.0.0' },
        components: { schemas: {} },
        sourceDescriptions: [],
        workflows: [
          {
            workflowId: 'W',
            steps: [{ stepId: 'S', requestBody: { payload: { x: 1 } } }],
          },
        ],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: {
          selectedSchemas: ['WS'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('WS');
      expect(result.warnings.some((w) => w.includes('inferred'))).toBe(true);
    });

    it('merges arazzo warnings with openapi importer warnings', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Todo', version: '1.0.0' },
        sourceDescriptions: [],
        workflows: [
          {
            name: 'Create',
            steps: [{ name: 'CreateTodo', request: { parameters: { body: { t: 'x' } } } }],
          },
        ],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: {
          selectedSchemas: ['CreateCreateTodo'],
          applyNamingConvention: false,
        },
      });
      expect(result.warnings).toBeDefined();
      expect(Array.isArray(result.warnings)).toBe(true);
      expect(result.warnings.some((w) => w.includes('inferred'))).toBe(true);
    });

    it('applies naming convention when using components.schemas', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Test', version: '1.0.0' },
        components: {
          schemas: {
            snake_case_class: {
              type: 'object',
              properties: {
                my_property: { type: 'string' },
              },
            },
          },
        },
        sourceDescriptions: [],
        workflows: [],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: {
          selectedSchemas: ['snake_case_class'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
        },
      });
      expect(result.classes).toHaveLength(1);
      expect(result.classes[0].name).toBe('SnakeCaseClass');
      expect(result.classes[0].properties!.map((p) => p.name)).toContain('myProperty');
    });

    it('returns multiple classes from components.schemas', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'API', version: '1.0.0' },
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: { id: { type: 'integer' }, email: { type: 'string' } },
            },
            Order: {
              type: 'object',
              properties: { id: { type: 'integer' }, total: { type: 'number' } },
            },
          },
        },
        sourceDescriptions: [],
        workflows: [],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: {
          selectedSchemas: ['User', 'Order'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes).toHaveLength(2);
      const user = result.classes.find((c) => c.name === 'User');
      const order = result.classes.find((c) => c.name === 'Order');
      expect(user?.properties).toHaveLength(2);
      expect(order?.properties).toHaveLength(2);
    });

    it('preserves originalSchemaKey when using components.schemas', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Test', version: '1.0.0' },
        components: {
          schemas: {
            MySchema: { type: 'object', properties: { p: { type: 'string' } } },
          },
        },
        sourceDescriptions: [],
        workflows: [],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: { selectedSchemas: ['MySchema'], applyNamingConvention: false },
      });
      expect(result.classes[0].originalSchemaKey).toBe('MySchema');
    });

    it('handles both workflow inputs and step bodies in one document', () => {
      const doc = {
        arazzo: '1.0.1',
        info: { title: 'Full', version: '1.0.0' },
        sourceDescriptions: [],
        workflows: [
          {
            workflowId: 'Register',
            inputs: {
              type: 'object',
              properties: { email: { type: 'string' }, name: { type: 'string' } },
            },
            steps: [
              {
                stepId: 'Submit',
                requestBody: { payload: { email: 'e', name: 'n', acceptTerms: true } },
              },
            ],
          },
        ],
      };
      const result = arazzoImporter.normalize({
        document: doc,
        options: {
          selectedSchemas: ['RegisterInputs', 'RegisterSubmit'],
          applyNamingConvention: false,
        },
      });
      expect(result.classes).toHaveLength(2);
      const inputs = result.classes.find((c) => c.name === 'RegisterInputs');
      const submit = result.classes.find((c) => c.name === 'RegisterSubmit');
      expect(inputs?.properties?.map((p) => p.name).sort()).toEqual(['email', 'name']);
      expect(submit?.properties?.map((p) => p.name).sort()).toEqual(['acceptTerms', 'email', 'name']);
    });
  });

  describe('arazzoImporter.kind', () => {
    it('has kind "arazzo"', () => {
      expect(arazzoImporter.kind).toBe('arazzo');
    });
  });
});
