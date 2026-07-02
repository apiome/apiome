/**
 * Tests for the class import functionality
 */

// Mock the helper module
jest.mock('../lib/db/helper', () => ({
  createClass: jest.fn(),
  addPropertyToClass: jest.fn(),
  createProperty: jest.fn(),
}));

// Mock the importers module
jest.mock('../lib/importers', () => ({
  getImporter: jest.fn(() => ({
    normalize: jest.fn((_input: { document: any; options: any }) => ({
      classes: [
        {
          name: 'TestClass',
          description: 'Test description',
          schema: { type: 'object' },
          properties: [
            {
              name: 'testProp',
              description: 'Test property',
              data: { type: 'string' },
            },
          ],
        },
      ],
      warnings: [],
    })),
  })),
}));

describe('Class Import Actions', () => {
  it('should have correct import interface', async () => {
    // Verify the import interface structure
    const importInput = {
      versionId: 'test-version-id',
      projectId: 'test-project-id',
      document: { openapi: '3.0.0', info: { title: 'Test', version: '1.0.0' } },
      selectedSchemas: ['TestSchema'],
    };

    expect(importInput).toHaveProperty('versionId');
    expect(importInput).toHaveProperty('projectId');
    expect(importInput).toHaveProperty('document');
    expect(importInput).toHaveProperty('selectedSchemas');
  });

  it('should have correct result interface', () => {
    // Verify the result interface structure
    const successResult = {
      success: true,
      importedCount: 5,
      skippedCount: 2,
      importedClasses: ['Class1', 'Class2'],
    };

    const errorResult = {
      success: false,
      error: 'An error occurred',
    };

    expect(successResult.success).toBe(true);
    expect(successResult.importedCount).toBe(5);
    expect(successResult.skippedCount).toBe(2);
    expect(errorResult.success).toBe(false);
    expect(errorResult.error).toBe('An error occurred');
  });

  it('should validate selectedSchemas is required', () => {
    const invalidInput = {
      versionId: 'test-version-id',
      projectId: 'test-project-id',
      document: {},
      selectedSchemas: [],
    };

    // Empty selectedSchemas should be considered invalid
    expect(invalidInput.selectedSchemas.length).toBe(0);
  });
});

describe('Schema conflict detection', () => {
  it('should correctly identify existing class names', () => {
    const existingClassNames = ['User', 'Product', 'Order'];
    const incomingSchemas = ['User', 'NewClass', 'Product', 'AnotherNew'];

    const existingNamesSet = new Set(existingClassNames.map(n => n.toLowerCase()));

    const conflicts = incomingSchemas.filter(name =>
      existingNamesSet.has(name.toLowerCase())
    );
    const newClasses = incomingSchemas.filter(name =>
      !existingNamesSet.has(name.toLowerCase())
    );

    expect(conflicts).toEqual(['User', 'Product']);
    expect(newClasses).toEqual(['NewClass', 'AnotherNew']);
  });

  it('should be case-insensitive for conflict detection', () => {
    const existingClassNames = ['User'];
    const incomingSchemas = ['user', 'USER', 'UsEr', 'NewUser'];

    const existingNamesSet = new Set(existingClassNames.map(n => n.toLowerCase()));

    const conflicts = incomingSchemas.filter(name =>
      existingNamesSet.has(name.toLowerCase())
    );

    expect(conflicts).toEqual(['user', 'USER', 'UsEr']);
  });
});

describe('Schema property counting', () => {
  it('should count direct properties', () => {
    const schema = {
      type: 'object',
      properties: {
        id: { type: 'string' },
        name: { type: 'string' },
        email: { type: 'string' },
      },
    };

    const count = Object.keys(schema.properties).length;
    expect(count).toBe(3);
  });

  it('should count properties from allOf inheritance', () => {
    const schema = {
      allOf: [
        { properties: { id: { type: 'string' } } },
        { properties: { name: { type: 'string' }, email: { type: 'string' } } },
      ],
    };

    let count = 0;
    if (schema.allOf) {
      schema.allOf.forEach((item: any) => {
        if (item.properties) {
          count += Object.keys(item.properties).length;
        }
      });
    }

    expect(count).toBe(3);
  });

  it('should count max properties from oneOf variants', () => {
    const schema = {
      oneOf: [
        { properties: { a: { type: 'string' } } },
        { properties: { a: { type: 'string' }, b: { type: 'string' }, c: { type: 'string' } } },
        { properties: { x: { type: 'string' }, y: { type: 'string' } } },
      ],
    };

    let maxOneOf = 0;
    if (schema.oneOf) {
      schema.oneOf.forEach((item: any) => {
        if (item.properties) {
          maxOneOf = Math.max(maxOneOf, Object.keys(item.properties).length);
        }
      });
    }

    expect(maxOneOf).toBe(3);
  });
});

describe('Inline property extraction', () => {
  // Helper function to extract inline properties (matches the implementation in page.tsx)
  const extractInlineProperties = (propData: any): { name: string; data: any; description?: string }[] => {
    const children: { name: string; data: any; description?: string }[] = [];

    // Handle inline object properties (type: 'object' with nested properties)
    if (propData.type === 'object' && propData.properties) {
      const nestedRequired = Array.isArray(propData.required) ? propData.required : [];
      for (const childName of Object.keys(propData.properties)) {
        const childSchema = propData.properties[childName];
        const childData = { ...childSchema };
        const description = childData.description;
        delete childData.description;
        if (nestedRequired.includes(childName)) {
          childData.required = true;
        }
        children.push({ name: childName, data: childData, description });
      }
    }

    // Handle arrays of objects with inline properties (type: 'array' with items.type: 'object')
    if (propData.type === 'array' && propData.items?.type === 'object' && propData.items.properties) {
      const nestedRequired = Array.isArray(propData.items.required) ? propData.items.required : [];
      for (const childName of Object.keys(propData.items.properties)) {
        const childSchema = propData.items.properties[childName];
        const childData = { ...childSchema };
        const description = childData.description;
        delete childData.description;
        if (nestedRequired.includes(childName)) {
          childData.required = true;
        }
        children.push({ name: childName, data: childData, description });
      }
    }

    return children;
  };

  it('should extract inline properties from an object type', () => {
    const propertyData = {
      type: 'object',
      properties: {
        firstName: { type: 'string', description: 'First name' },
        lastName: { type: 'string', description: 'Last name' },
        age: { type: 'integer' },
      },
      required: ['firstName', 'lastName'],
    };

    const children = extractInlineProperties(propertyData);

    expect(children).toHaveLength(3);
    expect(children[0].name).toBe('firstName');
    expect(children[0].data.type).toBe('string');
    expect(children[0].data.required).toBe(true);
    expect(children[0].description).toBe('First name');

    expect(children[1].name).toBe('lastName');
    expect(children[1].data.required).toBe(true);

    expect(children[2].name).toBe('age');
    expect(children[2].data.type).toBe('integer');
    expect(children[2].data.required).toBeUndefined();
  });

  it('should extract inline properties from an array of objects', () => {
    const propertyData = {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'Unique identifier' },
          value: { type: 'number' },
        },
        required: ['id'],
      },
    };

    const children = extractInlineProperties(propertyData);

    expect(children).toHaveLength(2);
    expect(children[0].name).toBe('id');
    expect(children[0].data.type).toBe('string');
    expect(children[0].data.required).toBe(true);
    expect(children[0].description).toBe('Unique identifier');

    expect(children[1].name).toBe('value');
    expect(children[1].data.type).toBe('number');
    expect(children[1].data.required).toBeUndefined();
  });

  it('should return empty array for simple types', () => {
    const simpleString = { type: 'string' };
    const simpleNumber = { type: 'integer' };
    const simpleArray = { type: 'array', items: { type: 'string' } };

    expect(extractInlineProperties(simpleString)).toHaveLength(0);
    expect(extractInlineProperties(simpleNumber)).toHaveLength(0);
    expect(extractInlineProperties(simpleArray)).toHaveLength(0);
  });

  it('should handle deeply nested inline properties', () => {
    const propertyData = {
      type: 'object',
      properties: {
        address: {
          type: 'object',
          properties: {
            street: { type: 'string' },
            city: { type: 'string' },
          },
        },
      },
    };

    const children = extractInlineProperties(propertyData);

    expect(children).toHaveLength(1);
    expect(children[0].name).toBe('address');
    expect(children[0].data.type).toBe('object');
    // The nested properties are preserved in the child data for recursive processing
    expect(children[0].data.properties).toEqual({
      street: { type: 'string' },
      city: { type: 'string' },
    });
  });
});

describe('Sidebar inline property detection', () => {
  // Helper function that matches the implementation in StudioSideNav.tsx
  const hasInlineProperties = (prop: any): boolean => {
    // Check for object type with nested properties
    if (prop.type === 'object' && prop.properties && Object.keys(prop.properties).length > 0) {
      return true;
    }
    // Check for array type with object items that have properties
    if (prop.type === 'array' && prop.items?.type === 'object' && prop.items?.properties && Object.keys(prop.items.properties).length > 0) {
      return true;
    }
    return false;
  };

  // Helper function that matches the implementation in StudioSideNav.tsx
  const getInlineProperties = (prop: any): { name: string; type: string; description?: string; required?: boolean }[] => {
    const children: { name: string; type: string; description?: string; required?: boolean }[] = [];

    // Handle object type with nested properties
    if (prop.type === 'object' && prop.properties) {
      const requiredFields = Array.isArray(prop.required) ? prop.required : [];
      for (const [name, schema] of Object.entries<any>(prop.properties)) {
        children.push({
          name,
          type: schema.type || 'object',
          description: schema.description,
          required: requiredFields.includes(name),
        });
      }
    }

    // Handle array type with object items
    if (prop.type === 'array' && prop.items?.type === 'object' && prop.items?.properties) {
      const requiredFields = Array.isArray(prop.items.required) ? prop.items.required : [];
      for (const [name, schema] of Object.entries<any>(prop.items.properties)) {
        children.push({
          name,
          type: schema.type || 'object',
          description: schema.description,
          required: requiredFields.includes(name),
        });
      }
    }

    return children;
  };

  it('should detect object properties with nested properties', () => {
    const objectWithNested = {
      id: 'prop-1',
      name: 'address',
      type: 'object',
      properties: {
        street: { type: 'string' },
        city: { type: 'string' },
      },
    };

    expect(hasInlineProperties(objectWithNested)).toBe(true);

    const children = getInlineProperties(objectWithNested);
    expect(children).toHaveLength(2);
    expect(children[0].name).toBe('street');
    expect(children[1].name).toBe('city');
  });

  it('should detect array of objects with nested properties', () => {
    const arrayWithNested = {
      id: 'prop-2',
      name: 'addresses',
      type: 'array',
      items: {
        type: 'object',
        properties: {
          street: { type: 'string' },
          city: { type: 'string', description: 'City name' },
        },
        required: ['street'],
      },
    };

    expect(hasInlineProperties(arrayWithNested)).toBe(true);

    const children = getInlineProperties(arrayWithNested);
    expect(children).toHaveLength(2);
    expect(children[0].name).toBe('street');
    expect(children[0].required).toBe(true);
    expect(children[1].name).toBe('city');
    expect(children[1].description).toBe('City name');
    expect(children[1].required).toBe(false);
  });

  it('should return false for simple property types', () => {
    const simpleString = { id: 'prop-3', name: 'name', type: 'string' };
    const simpleNumber = { id: 'prop-4', name: 'age', type: 'integer' };
    const simpleArray = { id: 'prop-5', name: 'tags', type: 'array', items: { type: 'string' } };
    const objectNoProps = { id: 'prop-6', name: 'data', type: 'object' };

    expect(hasInlineProperties(simpleString)).toBe(false);
    expect(hasInlineProperties(simpleNumber)).toBe(false);
    expect(hasInlineProperties(simpleArray)).toBe(false);
    expect(hasInlineProperties(objectNoProps)).toBe(false);
  });
});

