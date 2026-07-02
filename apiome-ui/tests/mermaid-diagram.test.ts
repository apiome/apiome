/**
 * Tests for Mermaid diagram generation
 */

// Helper function to extract class name from $ref path
function extractClassNameFromRef(ref: string): string | null {
  if (!ref) return null;
  const parts = ref.split('/');
  return parts[parts.length - 1] || null;
}

// Simplified version of the Mermaid generation logic for testing
function generateMermaidDiagram(classes: any[]): string {
  const lines: string[] = ['classDiagram'];
  const classNameToId = new Map(classes.map(cls => [cls.name, cls.id]));

  // Add class definitions
  classes.forEach((cls) => {
    const className = cls.name.replace(/[^a-zA-Z0-9_]/g, '_'); // Sanitize for Mermaid

    lines.push(`    class ${className} {`);

    // Add properties
    if (cls.properties && cls.properties.length > 0) {
      cls.properties.forEach((prop: any) => {
        const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;

        // Handle nullable type arrays
        let baseType = propData.type;
        let isNullable = false;
        if (Array.isArray(propData.type)) {
          isNullable = propData.type.includes('null');
          baseType = propData.type.find((t: string) => t !== 'null') || 'any';
        }
        let propType = baseType || 'any';

        // Handle array types
        if (baseType === 'array' && propData.items) {
          if (propData.items.$ref) {
            const refClass = extractClassNameFromRef(propData.items.$ref);
            propType = `${refClass}[]`;
          } else if (propData.items.type) {
            propType = `${propData.items.type}[]`;
          }
        }
        // Handle simple $ref types
        else if (propData.$ref) {
          propType = extractClassNameFromRef(propData.$ref) || 'Object';
        }

        // Add nullable indicator
        const displayType = isNullable ? `${propType}?` : propType;
        lines.push(`        +${displayType} ${prop.name}`);
      });
    } else {
      lines.push(`        // No properties`);
    }

    lines.push(`    }`);
  });

  // Add relationships
  classes.forEach((cls) => {
    const sourceClassName = cls.name.replace(/[^a-zA-Z0-9_]/g, '_');

    if (cls.properties) {
      cls.properties.forEach((prop: any) => {
        const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;

        // Check for direct $ref
        if (propData.$ref) {
          const refClassName = extractClassNameFromRef(propData.$ref);
          if (refClassName && classNameToId.has(refClassName)) {
            const targetClassName = refClassName.replace(/[^a-zA-Z0-9_]/g, '_');
            lines.push(`    ${sourceClassName} "1" --> ${targetClassName} : ${prop.name}`);
          }
        }
        // Check for array with $ref items
        else if (propData.type === 'array' && propData.items?.$ref) {
          const refClassName = extractClassNameFromRef(propData.items.$ref);
          if (refClassName && classNameToId.has(refClassName)) {
            const targetClassName = refClassName.replace(/[^a-zA-Z0-9_]/g, '_');
            lines.push(`    ${sourceClassName} "*" -- "1" ${targetClassName} : ${prop.name}`);
          }
        }
      });
    }
  });

  return lines.join('\n');
}

describe('Mermaid Diagram Generation', () => {
  it('should generate basic classDiagram header', () => {
    const result = generateMermaidDiagram([]);
    expect(result).toBe('classDiagram');
  });

  it('should generate class definition with properties', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'User',
        properties: [
          { name: 'id', data: { type: 'string' } },
          { name: 'email', data: { type: 'string' } },
          { name: 'age', data: { type: 'integer' } },
        ],
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('classDiagram');
    expect(result).toContain('class User {');
    expect(result).toContain('+string id');
    expect(result).toContain('+string email');
    expect(result).toContain('+integer age');
    expect(result).toContain('}');
  });

  it('should handle nullable types with array notation', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'Person',
        properties: [
          { name: 'nickname', data: { type: ['string', 'null'] } },
        ],
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('+string? nickname');
  });

  it('should handle array types', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'Blog',
        properties: [
          { name: 'tags', data: { type: 'array', items: { type: 'string' } } },
        ],
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('+string[] tags');
  });

  it('should handle $ref types', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'Order',
        properties: [
          { name: 'customer', data: { $ref: '#/components/schemas/Customer' } },
        ],
      },
      {
        id: 'class-2',
        name: 'Customer',
        properties: [
          { name: 'name', data: { type: 'string' } },
        ],
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('+Customer customer');
    expect(result).toContain('Order "1" --> Customer : customer');
  });

  it('should handle array of $ref types', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'Team',
        properties: [
          { name: 'members', data: { type: 'array', items: { $ref: '#/components/schemas/Member' } } },
        ],
      },
      {
        id: 'class-2',
        name: 'Member',
        properties: [
          { name: 'name', data: { type: 'string' } },
        ],
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('+Member[] members');
    expect(result).toContain('Team "*" -- "1" Member : members');
  });

  it('should sanitize class names with special characters', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'My-Class.Name',
        properties: [
          { name: 'value', data: { type: 'string' } },
        ],
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('class My_Class_Name {');
    expect(result).not.toContain('My-Class.Name');
  });

  it('should show "No properties" comment for empty classes', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'EmptyClass',
        properties: [],
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('class EmptyClass {');
    expect(result).toContain('// No properties');
  });

  it('should handle classes with no properties array', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'MinimalClass',
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('class MinimalClass {');
    expect(result).toContain('// No properties');
  });

  it('should handle stringified property data', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'TestClass',
        properties: [
          { name: 'field', data: JSON.stringify({ type: 'boolean' }) },
        ],
      },
    ];

    const result = generateMermaidDiagram(classes);

    expect(result).toContain('+boolean field');
  });

  it('should generate multiple classes and relationships', () => {
    const classes = [
      {
        id: 'class-1',
        name: 'Author',
        properties: [
          { name: 'name', data: { type: 'string' } },
          { name: 'books', data: { type: 'array', items: { $ref: '#/components/schemas/Book' } } },
        ],
      },
      {
        id: 'class-2',
        name: 'Book',
        properties: [
          { name: 'title', data: { type: 'string' } },
          { name: 'author', data: { $ref: '#/components/schemas/Author' } },
        ],
      },
    ];

    const result = generateMermaidDiagram(classes);

    // Verify both classes are present
    expect(result).toContain('class Author {');
    expect(result).toContain('class Book {');

    // Verify properties
    expect(result).toContain('+string name');
    expect(result).toContain('+Book[] books');
    expect(result).toContain('+string title');
    expect(result).toContain('+Author author');

    // Verify relationships
    expect(result).toContain('Author "*" -- "1" Book : books');
    expect(result).toContain('Book "1" --> Author : author');
  });
});

describe('extractClassNameFromRef', () => {
  it('should extract class name from standard OpenAPI ref', () => {
    expect(extractClassNameFromRef('#/components/schemas/User')).toBe('User');
  });

  it('should extract class name from Swagger 2.0 ref', () => {
    expect(extractClassNameFromRef('#/definitions/Pet')).toBe('Pet');
  });

  it('should return null for empty ref', () => {
    expect(extractClassNameFromRef('')).toBe(null);
  });

  it('should handle refs with deep nesting', () => {
    expect(extractClassNameFromRef('#/components/schemas/nested/deep/MyClass')).toBe('MyClass');
  });
});

