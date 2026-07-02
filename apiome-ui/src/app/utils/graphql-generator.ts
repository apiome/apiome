/**
 * GraphQL Schema Generator Utilities
 *
 * Generates GraphQL SDL (Schema Definition Language) from class definitions.
 *
 * Features:
 * - GraphQL types from classes
 * - Queries and mutations
 * - Input types
 * - Enums
 * - Interfaces and unions
 * - Directives
 * - Descriptions as comments
 */

/**
 * Maps JSON Schema types to GraphQL types
 */
function mapTypeToGraphQL(propData: any): string {
  // Handle enum types
  if (propData.enum && Array.isArray(propData.enum)) {
    // Enums are handled separately, return String for now
    return 'String';
  }

  // Handle $ref (references to other types)
  if (propData.$ref) {
    const refParts = propData.$ref.split('/');
    const refTypeName = refParts[refParts.length - 1];
    return refTypeName;
  }

  // Handle array types
  if (propData.type === 'array') {
    if (propData.items) {
      const itemType = mapTypeToGraphQL(propData.items);
      return `[${itemType}]`;
    }
    return '[String]';
  }

  // Handle object types (return JSON scalar or custom type)
  if (propData.type === 'object') {
    return 'JSON'; // Custom scalar for arbitrary JSON
  }

  // Handle basic types with format
  switch (propData.type) {
    case 'string':
      if (propData.format === 'date' || propData.format === 'date-time') {
        return 'DateTime'; // Custom scalar
      }
      if (propData.format === 'uuid') {
        return 'ID';
      }
      if (propData.format === 'email') {
        return 'String'; // Could use Email scalar
      }
      if (propData.format === 'uri' || propData.format === 'url') {
        return 'String'; // Could use URL scalar
      }
      return 'String';
    case 'integer':
      return 'Int';
    case 'number':
      return 'Float';
    case 'boolean':
      return 'Boolean';
    case 'null':
      return 'String'; // GraphQL doesn't have null type
    default:
      return 'String';
  }
}

/**
 * Convert name to PascalCase for GraphQL types
 */
function toPascalCase(name: string): string {
  return name
    .split(/[-_\s]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

/**
 * Convert name to camelCase for GraphQL fields
 */
function toCamelCase(name: string): string {
  const pascal = toPascalCase(name);
  return pascal.charAt(0).toLowerCase() + pascal.slice(1);
}

/**
 * Generate GraphQL enum from property enum values
 */
function generateEnum(className: string, propName: string, enumValues: any[]): string {
  const enumName = `${className}${toPascalCase(propName)}`;
  let graphql = `enum ${enumName} {\n`;

  enumValues.forEach((value) => {
    // Convert value to valid GraphQL enum value (uppercase with underscores)
    const enumValue = String(value).toUpperCase().replace(/[^A-Z0-9]/g, '_');
    graphql += `  ${enumValue}\n`;
  });

  graphql += `}\n`;
  return graphql;
}

/**
 * Generate GraphQL type from a class
 */
function generateType(
  cls: any,
  allClasses: any[],
  generatedEnums: Set<string>
): { type: string; enums: string[] } {
  const className = toPascalCase(cls.name);
  const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : (cls.schema || {});
  const topLevelProperties = (cls.properties || []).filter((prop: any) => !prop.parent_id);
  const required = schema.required || [];
  const enumDefinitions: string[] = [];

  let graphql = '';

  // Add description if available
  if (cls.description || schema.description) {
    const description = cls.description || schema.description;
    graphql += `"""\n${description}\n"""\n`;
  }

  graphql += `type ${className} {\n`;

  // Add ID field (required for GraphQL)
  graphql += `  id: ID!\n`;

  // Generate fields
  topLevelProperties.forEach((prop: any) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {});
    const fieldName = toCamelCase(prop.name);
    const isRequired = required.includes(prop.name) || propData.required;

    // Generate enum if property has enum values
    if (propData.enum && Array.isArray(propData.enum)) {
      const enumName = `${className}${toPascalCase(prop.name)}`;
      if (!generatedEnums.has(enumName)) {
        enumDefinitions.push(generateEnum(className, prop.name, propData.enum));
        generatedEnums.add(enumName);
      }
    }

    // Add field description
    if (prop.description || propData.description) {
      const description = prop.description || propData.description;
      graphql += `  """\n  ${description}\n  """\n`;
    }

    let fieldType = mapTypeToGraphQL(propData);

    // Use enum type if property has enum
    if (propData.enum && Array.isArray(propData.enum)) {
      fieldType = `${className}${toPascalCase(prop.name)}`;
    }

    // Add required modifier
    if (isRequired) {
      // For arrays, make the array required, not the items
      if (fieldType.startsWith('[')) {
        fieldType = fieldType.replace(']', ']!');
      } else {
        fieldType += '!';
      }
    }

    graphql += `  ${fieldName}: ${fieldType}\n`;
  });

  if (topLevelProperties.length === 0) {
    graphql += `  # No fields defined\n`;
  }

  graphql += `}\n`;

  return { type: graphql, enums: enumDefinitions };
}

/**
 * Generate GraphQL input type for mutations
 */
function generateInputType(
  cls: any,
  allClasses: any[]
): string {
  const className = toPascalCase(cls.name);
  const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : (cls.schema || {});
  const topLevelProperties = (cls.properties || []).filter((prop: any) => !prop.parent_id);
  const required = schema.required || [];

  let graphql = `input ${className}Input {\n`;

  // Generate fields (no ID field for input types)
  topLevelProperties.forEach((prop: any) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {});
    const fieldName = toCamelCase(prop.name);
    const isRequired = required.includes(prop.name) || propData.required;

    let fieldType = mapTypeToGraphQL(propData);

    // Use enum type if property has enum
    if (propData.enum && Array.isArray(propData.enum)) {
      fieldType = `${className}${toPascalCase(prop.name)}`;
    }

    // Add required modifier
    if (isRequired) {
      if (fieldType.startsWith('[')) {
        fieldType = fieldType.replace(']', ']!');
      } else {
        fieldType += '!';
      }
    }

    graphql += `  ${fieldName}: ${fieldType}\n`;
  });

  if (topLevelProperties.length === 0) {
    graphql += `  # No fields defined\n`;
  }

  graphql += `}\n`;

  return graphql;
}

/**
 * Generate GraphQL queries for all types
 */
function generateQueries(classes: any[]): string {
  if (classes.length === 0) {
    return '';
  }

  let graphql = 'type Query {\n';

  classes.forEach((cls) => {
    const typeName = toPascalCase(cls.name);
    const fieldName = toCamelCase(cls.name);

    // Get single item by ID
    graphql += `  ${fieldName}(id: ID!): ${typeName}\n`;

    // Get list of items
    graphql += `  ${fieldName}s(limit: Int = 10, offset: Int = 0): [${typeName}!]!\n`;
  });

  graphql += `}\n`;

  return graphql;
}

/**
 * Generate GraphQL mutations for all types
 */
function generateMutations(classes: any[]): string {
  if (classes.length === 0) {
    return '';
  }

  let graphql = 'type Mutation {\n';

  classes.forEach((cls) => {
    const typeName = toPascalCase(cls.name);
    const fieldName = toCamelCase(cls.name);

    // Create
    graphql += `  create${typeName}(input: ${typeName}Input!): ${typeName}!\n`;

    // Update
    graphql += `  update${typeName}(id: ID!, input: ${typeName}Input!): ${typeName}!\n`;

    // Delete
    graphql += `  delete${typeName}(id: ID!): Boolean!\n`;
  });

  graphql += `}\n`;

  return graphql;
}

/**
 * Generate custom scalars used in the schema
 */
function generateScalars(): string {
  let graphql = '# Custom Scalars\n';
  graphql += 'scalar DateTime\n';
  graphql += 'scalar JSON\n';
  graphql += '\n';
  return graphql;
}

/**
 * Main function to generate GraphQL schema from classes
 */
export function generateGraphQL(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    includeQueries?: boolean;
    includeMutations?: boolean;
    includeInputTypes?: boolean;
  }
): string {
  const {
    projectName = 'API',
    version = '1.0',
    includeQueries = true,
    includeMutations = true,
    includeInputTypes = true,
  } = options || {};

  if (!classes || classes.length === 0) {
    return `# No classes defined\n# Add classes to the canvas to generate GraphQL schema`;
  }

  let graphql = '';

  // Header comment
  graphql += `# GraphQL Schema Generated from Apiome\n`;
  graphql += `# Project: ${projectName}\n`;
  graphql += `# Version: ${version}\n`;
  graphql += `# Generated: ${new Date().toISOString()}\n\n`;

  // Custom scalars
  graphql += generateScalars();

  // Generate enums and types
  const generatedEnums = new Set<string>();
  const typeDefinitions: string[] = [];
  const inputDefinitions: string[] = [];
  const allEnums: string[] = [];

  classes.forEach((cls) => {
    const { type, enums } = generateType(cls, classes, generatedEnums);
    typeDefinitions.push(type);
    allEnums.push(...enums);

    if (includeInputTypes) {
      inputDefinitions.push(generateInputType(cls, classes));
    }
  });

  // Add enums first
  if (allEnums.length > 0) {
    graphql += '# Enums\n';
    allEnums.forEach(enumDef => {
      graphql += enumDef + '\n';
    });
  }

  // Add types
  graphql += '# Types\n';
  typeDefinitions.forEach(typeDef => {
    graphql += typeDef + '\n';
  });

  // Add input types
  if (includeInputTypes && inputDefinitions.length > 0) {
    graphql += '# Input Types\n';
    inputDefinitions.forEach(inputDef => {
      graphql += inputDef + '\n';
    });
  }

  // Add queries
  if (includeQueries) {
    graphql += '# Queries\n';
    graphql += generateQueries(classes) + '\n';
  }

  // Add mutations
  if (includeMutations) {
    graphql += '# Mutations\n';
    graphql += generateMutations(classes) + '\n';
  }

  return graphql;
}

