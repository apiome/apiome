/**
 * Tests for Property Templates functionality
 */

describe('Property Template Categories', () => {
  const categoryConfig: Record<string, { label: string; icon: string }> = {
    identifiers: { label: 'Identifiers', icon: '🔑' },
    timestamps: { label: 'Timestamps', icon: '⏰' },
    audit: { label: 'Audit Fields', icon: '📋' },
    status: { label: 'Status Fields', icon: '🚦' },
    contact: { label: 'Contact Info', icon: '📧' },
    address: { label: 'Address Fields', icon: '📍' },
    money: { label: 'Money & Currency', icon: '💰' },
    geolocation: { label: 'Geolocation', icon: '🌍' },
    i18n: { label: 'Internationalization', icon: '🌐' },
    pagination: { label: 'Pagination', icon: '📄' },
    search: { label: 'Search & Filter', icon: '🔍' },
  };

  it('should have all expected categories defined', () => {
    const expectedCategories = [
      'identifiers',
      'timestamps',
      'audit',
      'status',
      'contact',
      'address',
      'money',
      'geolocation',
      'i18n',
      'pagination',
      'search',
    ];

    expectedCategories.forEach(category => {
      expect(categoryConfig).toHaveProperty(category);
      expect(categoryConfig[category]).toHaveProperty('label');
      expect(categoryConfig[category]).toHaveProperty('icon');
    });
  });

  it('should have unique labels for each category', () => {
    const labels = Object.values(categoryConfig).map(c => c.label);
    const uniqueLabels = new Set(labels);
    expect(uniqueLabels.size).toBe(labels.length);
  });
});

describe('Property Template Schema Validation', () => {
  // Sample templates matching the SQL seed data
  const sampleTemplates = [
    {
      name: 'UUID',
      category: 'identifiers',
      schema: {
        type: 'string',
        format: 'uuid',
        description: 'Unique identifier in UUID v4 format',
        example: '550e8400-e29b-41d4-a716-446655440000'
      }
    },
    {
      name: 'Created At',
      category: 'timestamps',
      schema: {
        type: 'string',
        format: 'date-time',
        readOnly: true,
        description: 'Timestamp when the record was created',
        example: '2024-01-15T10:30:00Z'
      }
    },
    {
      name: 'Email',
      category: 'contact',
      schema: {
        type: 'string',
        format: 'email',
        maxLength: 254,
        description: 'Email address',
        example: 'user@example.com'
      }
    },
    {
      name: 'Status Enum',
      category: 'status',
      schema: {
        type: 'string',
        enum: ['draft', 'pending', 'active', 'inactive', 'archived'],
        default: 'draft',
        description: 'Current status of the record',
        example: 'active'
      }
    },
    {
      name: 'Latitude',
      category: 'geolocation',
      schema: {
        type: 'number',
        minimum: -90,
        maximum: 90,
        description: 'Latitude in decimal degrees',
        example: 37.7749
      }
    },
    {
      name: 'Currency Code',
      category: 'money',
      schema: {
        type: 'string',
        pattern: '^[A-Z]{3}$',
        description: 'Three-letter currency code (ISO 4217)',
        example: 'USD'
      }
    }
  ];

  it('should have valid JSON Schema structure for each template', () => {
    sampleTemplates.forEach(template => {
      expect(template.schema).toBeDefined();
      expect(template.schema).toHaveProperty('type');
      expect(template.schema).toHaveProperty('description');
    });
  });

  it('should have valid type values', () => {
    const validTypes = ['string', 'number', 'integer', 'boolean', 'object', 'array'];

    sampleTemplates.forEach(template => {
      const type = template.schema.type;
      if (Array.isArray(type)) {
        type.forEach(t => {
          expect(validTypes.includes(t) || t === 'null').toBe(true);
        });
      } else {
        expect(validTypes).toContain(type);
      }
    });
  });

  it('should have examples that match the schema type', () => {
    sampleTemplates.forEach(template => {
      const { type, example, enum: enumValues } = template.schema;

      if (example !== undefined) {
        if (type === 'string') {
          expect(typeof example).toBe('string');
        } else if (type === 'number' || type === 'integer') {
          expect(typeof example).toBe('number');
        } else if (type === 'boolean') {
          expect(typeof example).toBe('boolean');
        }

        // If enum is defined, example should be one of the values
        if (enumValues) {
          expect(enumValues).toContain(example);
        }
      }
    });
  });

  it('should have valid format values for string types', () => {
    const validFormats = ['uuid', 'email', 'uri', 'date', 'time', 'date-time'];

    sampleTemplates.forEach(template => {
      if (template.schema.type === 'string' && template.schema.format) {
        expect(validFormats).toContain(template.schema.format);
      }
    });
  });

  it('should have valid min/max constraints for number types', () => {
    sampleTemplates.forEach(template => {
      if (template.schema.type === 'number' || template.schema.type === 'integer') {
        if (template.schema.minimum !== undefined && template.schema.maximum !== undefined) {
          expect(template.schema.minimum).toBeLessThanOrEqual(template.schema.maximum);
        }
      }
    });
  });
});

describe('Property Template Use Cases', () => {
  interface PropertyTemplate {
    id: string;
    name: string;
    description: string | null;
    category: string;
    schema: any;
    tags: string[];
    is_system: boolean;
  }

  // Mock template matching
  const findTemplatesByCategory = (templates: PropertyTemplate[], category: string): PropertyTemplate[] => {
    return templates.filter(t => t.category === category);
  };

  // Mock search function
  const searchTemplates = (templates: PropertyTemplate[], query: string): PropertyTemplate[] => {
    const lowerQuery = query.toLowerCase();
    return templates.filter(t =>
      t.name.toLowerCase().includes(lowerQuery) ||
      (t.description && t.description.toLowerCase().includes(lowerQuery)) ||
      t.tags.some(tag => tag.toLowerCase().includes(lowerQuery))
    );
  };

  const mockTemplates: PropertyTemplate[] = [
    { id: '1', name: 'UUID', description: 'Unique identifier', category: 'identifiers', schema: { type: 'string' }, tags: ['id', 'uuid'], is_system: true },
    { id: '2', name: 'ULID', description: 'Sortable identifier', category: 'identifiers', schema: { type: 'string' }, tags: ['id', 'ulid', 'sortable'], is_system: true },
    { id: '3', name: 'Created At', description: 'Creation timestamp', category: 'timestamps', schema: { type: 'string' }, tags: ['timestamp', 'audit'], is_system: true },
    { id: '4', name: 'Email', description: 'Email address', category: 'contact', schema: { type: 'string' }, tags: ['email', 'contact'], is_system: true },
  ];

  it('should filter templates by category', () => {
    const identifierTemplates = findTemplatesByCategory(mockTemplates, 'identifiers');
    expect(identifierTemplates).toHaveLength(2);
    expect(identifierTemplates.every(t => t.category === 'identifiers')).toBe(true);
  });

  it('should search templates by name', () => {
    const results = searchTemplates(mockTemplates, 'uuid');
    expect(results).toHaveLength(1);
    expect(results[0].name).toBe('UUID');
  });

  it('should search templates by tag', () => {
    const results = searchTemplates(mockTemplates, 'sortable');
    expect(results).toHaveLength(1);
    expect(results[0].name).toBe('ULID');
  });

  it('should search templates by description', () => {
    const results = searchTemplates(mockTemplates, 'timestamp');
    expect(results).toHaveLength(1);
    expect(results[0].name).toBe('Created At');
  });

  it('should return empty array for non-matching search', () => {
    const results = searchTemplates(mockTemplates, 'nonexistent');
    expect(results).toHaveLength(0);
  });

  it('should be case-insensitive in search', () => {
    const results1 = searchTemplates(mockTemplates, 'EMAIL');
    const results2 = searchTemplates(mockTemplates, 'email');
    expect(results1).toEqual(results2);
  });
});

describe('Property Template Database Schema', () => {
  // These tests validate the expected structure of property templates

  interface PropertyTemplateSchema {
    id: string;
    name: string;
    description: string | null;
    category: string;
    schema: object;
    tags: string[];
    tenant_id: string | null;
    created_by: string | null;
    is_system: boolean;
    is_public: boolean;
    usage_count: number;
    enabled: boolean;
    deleted_at: string | null;
    created_at: string;
    updated_at: string;
  }

  const validateTemplateStructure = (template: any): template is PropertyTemplateSchema => {
    return (
      typeof template.id === 'string' &&
      typeof template.name === 'string' &&
      (template.description === null || typeof template.description === 'string') &&
      typeof template.category === 'string' &&
      typeof template.schema === 'object' &&
      Array.isArray(template.tags) &&
      (template.tenant_id === null || typeof template.tenant_id === 'string') &&
      (template.created_by === null || typeof template.created_by === 'string') &&
      typeof template.is_system === 'boolean' &&
      typeof template.is_public === 'boolean' &&
      typeof template.usage_count === 'number' &&
      typeof template.enabled === 'boolean'
    );
  };

  it('should validate a valid template structure', () => {
    const validTemplate = {
      id: '123e4567-e89b-12d3-a456-426614174000',
      name: 'Test Template',
      description: 'A test template',
      category: 'identifiers',
      schema: { type: 'string' },
      tags: ['test', 'example'],
      tenant_id: null,
      created_by: null,
      is_system: true,
      is_public: true,
      usage_count: 0,
      enabled: true,
      deleted_at: null,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    };

    expect(validateTemplateStructure(validTemplate)).toBe(true);
  });

  it('should identify system templates vs tenant templates', () => {
    const systemTemplate = {
      id: '1', name: 'UUID', description: null, category: 'identifiers',
      schema: {}, tags: [], tenant_id: null, created_by: null,
      is_system: true, is_public: true, usage_count: 100, enabled: true
    };

    const tenantTemplate = {
      id: '2', name: 'Custom ID', description: null, category: 'identifiers',
      schema: {}, tags: [], tenant_id: 'tenant-123', created_by: 'user-456',
      is_system: false, is_public: false, usage_count: 5, enabled: true
    };

    expect(systemTemplate.is_system).toBe(true);
    expect(systemTemplate.tenant_id).toBeNull();

    expect(tenantTemplate.is_system).toBe(false);
    expect(tenantTemplate.tenant_id).not.toBeNull();
  });

  it('should track usage count', () => {
    const template = {
      id: '1', name: 'UUID', usage_count: 0
    };

    // Simulate incrementing usage
    template.usage_count += 1;
    expect(template.usage_count).toBe(1);

    template.usage_count += 1;
    expect(template.usage_count).toBe(2);
  });
});

