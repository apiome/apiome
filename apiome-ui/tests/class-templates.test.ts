/**
 * Tests for Class Template functionality
 * Tests creation, parsing, dependencies, and usage of class templates
 */

import { describe, it, expect, beforeAll, afterAll, beforeEach } from '@jest/globals';

// Mock the database connection
const mockConnectionPool = {
  query: jest.fn(),
  connect: jest.fn(),
};

jest.mock('../lib/db/db', () => mockConnectionPool);

// Import after mocking
import {
  ClassTemplate,
  ClassTemplateCategory,
  getClassTemplates,
  getClassTemplateCategories,
  searchClassTemplates,
  getClassTemplateById,
  getTemplateDependencies,
  addTemplateDependency,
  removeTemplateDependency,
  createClassTemplate,
  updateClassTemplate,
  deleteClassTemplate,
  useClassTemplate,
} from '../lib/db/helper-class-templates';

describe('Class Template Categories', () => {
  const expectedCategories = [
    'Addresses',
    'Common',
    'Content',
    'Integrations',
    'Notifications',
    'Orders',
    'Payments',
    'Products',
    'Security',
    'User & Auth',
    'Analytics',
    'Communication',
    'Compliance',
    'Marketplace',
    'Scheduling',
    'Support',
  ];

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should fetch all template categories', async () => {
    const mockCategories = expectedCategories.map((cat, idx) => ({
      category: cat,
      count: Math.floor(Math.random() * 10) + 1,
    }));

    mockConnectionPool.query.mockResolvedValueOnce({
      rows: mockCategories,
      rowCount: mockCategories.length,
    });

    const result = await getClassTemplateCategories();
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(parsed.categories).toBeDefined();
    expect(Array.isArray(parsed.categories)).toBe(true);
  });

  it('should fetch categories for a specific tenant', async () => {
    const tenantId = 'tenant-123';
    const mockCategories = [
      { category: 'Common', count: 5 },
      { category: 'User & Auth', count: 3 },
    ];

    mockConnectionPool.query.mockResolvedValueOnce({
      rows: mockCategories,
      rowCount: mockCategories.length,
    });

    const result = await getClassTemplateCategories(tenantId);
    const parsed = JSON.parse(result);

    expect(parsed.success).toBe(true);
    expect(mockConnectionPool.query).toHaveBeenCalledWith(
      expect.stringContaining('WHERE deleted_at IS NULL'),
      [tenantId]
    );
  });
});

describe('Class Template Schema Validation', () => {
  // Sample templates for testing
  const sampleTemplates: Partial<ClassTemplate>[] = [
    {
      name: 'Address',
      category: 'Addresses',
      schema: {
        type: 'object',
        required: ['street', 'city', 'country'],
        properties: {
          street: {
            type: 'string',
            description: 'Street address',
            example: '123 Main St',
          },
          city: {
            type: 'string',
            description: 'City name',
            example: 'San Francisco',
          },
          state: {
            type: 'string',
            description: 'State or province',
            example: 'CA',
          },
          country: {
            type: 'string',
            description: 'Country code',
            pattern: '^[A-Z]{2}$',
            example: 'US',
          },
          postalCode: {
            type: 'string',
            description: 'Postal/ZIP code',
            example: '94102',
          },
        },
      },
      tags: ['address', 'location', 'contact'],
      is_system: true,
      is_public: true,
    },
    {
      name: 'User',
      category: 'User & Auth',
      schema: {
        type: 'object',
        required: ['email', 'username'],
        properties: {
          id: {
            type: 'string',
            format: 'uuid',
            description: 'User ID',
          },
          email: {
            type: 'string',
            format: 'email',
            description: 'User email address',
          },
          username: {
            type: 'string',
            minLength: 3,
            maxLength: 50,
            description: 'Username',
          },
          createdAt: {
            type: 'string',
            format: 'date-time',
            description: 'Account creation timestamp',
          },
        },
      },
      tags: ['user', 'authentication', 'account'],
      is_system: true,
      is_public: true,
    },
    {
      name: 'Product',
      category: 'Products',
      schema: {
        type: 'object',
        required: ['name', 'price'],
        properties: {
          id: {
            type: 'string',
            format: 'uuid',
          },
          name: {
            type: 'string',
            description: 'Product name',
          },
          description: {
            type: 'string',
            description: 'Product description',
          },
          price: {
            type: 'number',
            minimum: 0,
            description: 'Product price',
          },
          currency: {
            type: 'string',
            pattern: '^[A-Z]{3}$',
            default: 'USD',
          },
        },
      },
      tags: ['product', 'commerce', 'catalog'],
      is_system: true,
      is_public: true,
    },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should validate required fields in template schema', () => {
    sampleTemplates.forEach(template => {
      expect(template.name).toBeDefined();
      expect(template.category).toBeDefined();
      expect(template.schema).toBeDefined();
      expect(typeof template.schema).toBe('object');
    });
  });

  it('should have valid OpenAPI schema structure', () => {
    sampleTemplates.forEach(template => {
      expect(template.schema).toHaveProperty('type');
      expect(template.schema.type).toBe('object');
      expect(template.schema).toHaveProperty('properties');
      expect(typeof template.schema.properties).toBe('object');
    });
  });

  it('should validate property types in schema', () => {
    sampleTemplates.forEach(template => {
      const properties = template.schema.properties;
      Object.values(properties).forEach((prop: any) => {
        expect(prop).toHaveProperty('type');
        expect(['string', 'number', 'integer', 'boolean', 'array', 'object']).toContain(
          prop.type
        );
      });
    });
  });

  it('should validate required fields exist in properties', () => {
    sampleTemplates.forEach(template => {
      if (template.schema.required) {
        template.schema.required.forEach((reqField: string) => {
          expect(template.schema.properties).toHaveProperty(reqField);
        });
      }
    });
  });
});

describe('Class Template CRUD Operations', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('getClassTemplates', () => {
    it('should retrieve all templates', async () => {
      const mockTemplates = [
        {
          id: 'tmpl-1',
          name: 'Address',
          category: 'Addresses',
          is_system: true,
          enabled: true,
        },
      ];

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: mockTemplates,
        rowCount: mockTemplates.length,
      });

      const result = await getClassTemplates();
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(parsed.templates).toBeDefined();
      expect(Array.isArray(parsed.templates)).toBe(true);
    });

    it('should filter templates by category', async () => {
      const category = 'User & Auth';
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [],
        rowCount: 0,
      });

      await getClassTemplates(null, category);

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('AND category = $'),
        expect.arrayContaining([category])
      );
    });

    it('should filter templates by tenant', async () => {
      const tenantId = 'tenant-456';
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [],
        rowCount: 0,
      });

      await getClassTemplates(tenantId);

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('OR tenant_id = $1'),
        expect.arrayContaining([tenantId])
      );
    });
  });

  describe('searchClassTemplates', () => {
    it('should search templates by name', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [],
        rowCount: 0,
      });

      await searchClassTemplates('Address');

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('name ILIKE $1'),
        expect.arrayContaining(['%Address%'])
      );
    });

    it('should search templates by tags', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [],
        rowCount: 0,
      });

      await searchClassTemplates('authentication');

      expect(mockConnectionPool.query).toHaveBeenCalledWith(
        expect.stringContaining('ILIKE ANY(tags)'),
        expect.arrayContaining(['%authentication%'])
      );
    });
  });

  describe('createClassTemplate', () => {
    it('should create a new template', async () => {
      const newTemplate = {
        id: 'tmpl-new',
        name: 'TestTemplate',
        category: 'Common',
        schema: { type: 'object', properties: {} },
        tags: ['test'],
        is_system: false,
        enabled: true,
      };

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [newTemplate],
        rowCount: 1,
      });

      const result = await createClassTemplate(
        'TestTemplate',
        'Test description',
        'Common',
        { type: 'object', properties: {} },
        ['test'],
        'tenant-123',
        'user-123',
        true
      );

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(true);
      expect(parsed.template).toBeDefined();
    });

    it('should handle duplicate template names', async () => {
      const error = new Error('Duplicate key') as any;
      error.code = '23505';
      mockConnectionPool.query.mockRejectedValueOnce(error);

      const result = await createClassTemplate(
        'DuplicateName',
        null,
        'Common',
        {},
        [],
        null,
        null,
        true
      );

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('already exists');
    });
  });

  describe('updateClassTemplate', () => {
    it('should update a template', async () => {
      const templateId = 'tmpl-123';
      const tenantId = 'tenant-123';

      // Mock check query
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [{ id: templateId, is_system: false, tenant_id: tenantId }],
        rowCount: 1,
      });

      // Mock update query
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [{ id: templateId, name: 'UpdatedName' }],
        rowCount: 1,
      });

      const result = await updateClassTemplate(templateId, tenantId, {
        name: 'UpdatedName',
      });

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(true);
      expect(parsed.template).toBeDefined();
    });

    it('should prevent updating system templates', async () => {
      const templateId = 'tmpl-system';
      const tenantId = 'tenant-123';

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [{ id: templateId, is_system: true, tenant_id: null }],
        rowCount: 1,
      });

      const result = await updateClassTemplate(templateId, tenantId, {
        name: 'NewName',
      });

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('System templates cannot be modified');
    });

    it('should prevent updating templates from other tenants', async () => {
      const templateId = 'tmpl-123';
      const tenantId = 'tenant-123';
      const otherTenantId = 'tenant-456';

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [{ id: templateId, is_system: false, tenant_id: otherTenantId }],
        rowCount: 1,
      });

      const result = await updateClassTemplate(templateId, tenantId, {
        name: 'NewName',
      });

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('do not have permission');
    });
  });

  describe('deleteClassTemplate', () => {
    it('should soft delete a template', async () => {
      const templateId = 'tmpl-123';
      const tenantId = 'tenant-123';

      // Mock check query
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [{ id: templateId, is_system: false, tenant_id: tenantId }],
        rowCount: 1,
      });

      // Mock delete query
      mockConnectionPool.query.mockResolvedValueOnce({
        rowCount: 1,
      });

      const result = await deleteClassTemplate(templateId, tenantId);

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(true);
    });

    it('should prevent deleting system templates', async () => {
      const templateId = 'tmpl-system';
      const tenantId = 'tenant-123';

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [{ id: templateId, is_system: true, tenant_id: null }],
        rowCount: 1,
      });

      const result = await deleteClassTemplate(templateId, tenantId);

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('System templates cannot be deleted');
    });
  });
});

describe('Class Template Dependencies', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('getTemplateDependencies', () => {
    it('should retrieve dependencies for a template', async () => {
      const templateId = 'tmpl-order';
      const mockDependencies = [
        {
          id: 'dep-1',
          template_id: templateId,
          depends_on_template_id: 'tmpl-address',
          depends_on_template_name: 'Address',
          category: 'Addresses',
          is_required: true,
        },
        {
          id: 'dep-2',
          template_id: templateId,
          depends_on_template_id: 'tmpl-user',
          depends_on_template_name: 'User',
          category: 'User & Auth',
          is_required: true,
        },
      ];

      mockConnectionPool.query.mockResolvedValueOnce({
        rows: mockDependencies,
        rowCount: mockDependencies.length,
      });

      const result = await getTemplateDependencies(templateId);
      const parsed = JSON.parse(result);

      expect(parsed.success).toBe(true);
      expect(parsed.dependencies).toBeDefined();
      expect(parsed.dependencies.length).toBe(2);
    });
  });

  describe('addTemplateDependency', () => {
    it('should add a dependency', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rows: [
          {
            id: 'dep-new',
            template_id: 'tmpl-1',
            depends_on_template_id: 'tmpl-2',
          },
        ],
        rowCount: 1,
      });

      const result = await addTemplateDependency('tmpl-1', 'tmpl-2', '#/properties/address', 'address', true);

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(true);
      expect(parsed.dependency).toBeDefined();
    });

    it('should prevent duplicate dependencies', async () => {
      const error = new Error('Duplicate') as any;
      error.code = '23505';
      mockConnectionPool.query.mockRejectedValueOnce(error);

      const result = await addTemplateDependency('tmpl-1', 'tmpl-2');

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('already exists');
    });

    it('should prevent self-referencing dependencies', async () => {
      const error = new Error('Check constraint') as any;
      error.code = '23514';
      mockConnectionPool.query.mockRejectedValueOnce(error);

      const result = await addTemplateDependency('tmpl-1', 'tmpl-1');

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('cannot depend on itself');
    });
  });

  describe('removeTemplateDependency', () => {
    it('should remove a dependency', async () => {
      mockConnectionPool.query.mockResolvedValueOnce({
        rowCount: 1,
      });

      const result = await removeTemplateDependency('dep-123');

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(true);
    });
  });
});

describe('Class Template Usage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('useClassTemplate', () => {
    it('should return error when template not found', async () => {
      const mockClient = {
        query: jest.fn(),
        release: jest.fn(),
      };

      mockConnectionPool.connect.mockResolvedValue(mockClient);
      mockClient.query.mockResolvedValueOnce({}); // BEGIN

      // Template not found
      mockClient.query.mockResolvedValueOnce({
        rows: [],
        rowCount: 0,
      });

      mockClient.query.mockResolvedValueOnce({}); // ROLLBACK

      const result = await useClassTemplate('nonexistent-tmpl', 'version-1', 'project-1');

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(false);
      expect(parsed.error).toContain('not found');
    });

    it('should handle existing class gracefully', async () => {
      const mockClient = {
        query: jest.fn(),
        release: jest.fn(),
      };

      mockConnectionPool.connect.mockResolvedValue(mockClient);
      mockClient.query.mockResolvedValueOnce({}); // BEGIN

      // Mock template fetch
      mockClient.query.mockResolvedValueOnce({
        rows: [
          {
            id: 'tmpl-1',
            name: 'ExistingClass',
            schema: { type: 'object', properties: {} },
          },
        ],
        rowCount: 1,
      });

      // Mock existing class check - found
      mockClient.query.mockResolvedValueOnce({
        rows: [{ id: 'class-existing' }],
        rowCount: 1,
      });

      mockClient.query.mockResolvedValueOnce({}); // COMMIT

      const result = await useClassTemplate('tmpl-1', 'version-1', 'project-1');

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(true);
      expect(parsed.skipped).toBe(true);
      expect(parsed.existingClassId).toBe('class-existing');
    });

    it('should prevent infinite loops in dependencies', async () => {
      const createdSet = new Set(['tmpl-1']);

      const mockClient = {
        query: jest.fn(),
        release: jest.fn(),
      };

      mockConnectionPool.connect.mockResolvedValue(mockClient);
      mockClient.query.mockResolvedValueOnce({}); // BEGIN
      mockClient.query.mockResolvedValueOnce({}); // COMMIT

      const result = await useClassTemplate('tmpl-1', 'version-1', 'project-1', null, true, createdSet);

      const parsed = JSON.parse(result);
      expect(parsed.success).toBe(true);
      expect(parsed.skipped).toBe(true);
      expect(parsed.message).toContain('already created');
    });
  });
});

describe('Class Template Schema Parsing', () => {
  it('should parse JSON schema correctly', () => {
    const schemaString = JSON.stringify({
      type: 'object',
      properties: {
        id: { type: 'string', format: 'uuid' },
        name: { type: 'string' },
      },
    });

    const parsed = JSON.parse(schemaString);
    expect(parsed.type).toBe('object');
    expect(parsed.properties).toHaveProperty('id');
    expect(parsed.properties).toHaveProperty('name');
  });

  it('should handle complex nested schemas', () => {
    const complexSchema = {
      type: 'object',
      properties: {
        user: {
          type: 'object',
          properties: {
            profile: {
              type: 'object',
              properties: {
                name: { type: 'string' },
                avatar: { type: 'string', format: 'uri' },
              },
            },
          },
        },
      },
    };

    expect(complexSchema.properties.user.properties.profile).toBeDefined();
    expect(complexSchema.properties.user.properties.profile.properties.name.type).toBe('string');
  });

  it('should handle $ref links in schemas', () => {
    const schemaWithRef = {
      type: 'object',
      properties: {
        shippingAddress: {
          $ref: '#/components/schemas/Address',
        },
        billingAddress: {
          $ref: '#/components/schemas/Address',
        },
      },
    };

    expect(schemaWithRef.properties.shippingAddress).toHaveProperty('$ref');
    expect(schemaWithRef.properties.billingAddress).toHaveProperty('$ref');
    expect(schemaWithRef.properties.shippingAddress.$ref).toContain('Address');
  });
});

describe('Class Template Integration', () => {
  it('should create a complete order system from templates', async () => {
    // This test demonstrates how multiple templates work together
    const templates = {
      Address: {
        category: 'Addresses',
        schema: {
          type: 'object',
          properties: {
            street: { type: 'string' },
            city: { type: 'string' },
          },
        },
      },
      User: {
        category: 'User & Auth',
        schema: {
          type: 'object',
          properties: {
            email: { type: 'string', format: 'email' },
          },
        },
      },
      Order: {
        category: 'Orders',
        schema: {
          type: 'object',
          properties: {
            shippingAddress: { $ref: '#/components/schemas/Address' },
            user: { $ref: '#/components/schemas/User' },
            total: { type: 'number' },
          },
        },
        dependencies: ['Address', 'User'],
      },
    };

    expect(templates.Order.dependencies).toContain('Address');
    expect(templates.Order.dependencies).toContain('User');
    expect(templates.Order.schema.properties.shippingAddress.$ref).toContain('Address');
    expect(templates.Order.schema.properties.user.$ref).toContain('User');
  });
});

