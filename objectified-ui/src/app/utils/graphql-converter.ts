/**
 * GraphQL Schema to OpenAPI 3.1.x Converter
 *
 * Converts GraphQL Schema Definition Language (SDL) documents to OpenAPI 3.1.x format
 * for compatibility with the Objectified import system.
 *
 * Supports:
 * - Type definitions (type, input, interface, enum, union, scalar)
 * - Field arguments
 * - Nullability (nullable vs non-null)
 * - Lists/Arrays
 * - Descriptions/Comments
 * - Directives (as extensions)
 */

/**
 * Result of a GraphQL to OpenAPI conversion
 */
export interface GraphQLConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

/**
 * GraphQL type kinds
 */
type GraphQLTypeKind = 'SCALAR' | 'OBJECT' | 'INTERFACE' | 'UNION' | 'ENUM' | 'INPUT_OBJECT' | 'LIST' | 'NON_NULL';

/**
 * Parsed GraphQL type reference
 */
interface GraphQLTypeRef {
  kind: GraphQLTypeKind;
  name?: string;
  ofType?: GraphQLTypeRef;
}

/**
 * Parsed GraphQL field
 */
interface GraphQLField {
  name: string;
  description?: string;
  type: GraphQLTypeRef;
  arguments?: GraphQLArgument[];
  directives?: GraphQLDirective[];
}

/**
 * Parsed GraphQL argument
 */
interface GraphQLArgument {
  name: string;
  description?: string;
  type: GraphQLTypeRef;
  defaultValue?: any;
}

/**
 * Parsed GraphQL directive
 */
interface GraphQLDirective {
  name: string;
  arguments?: Record<string, any>;
}

/**
 * Parsed GraphQL type definition
 */
interface GraphQLTypeDef {
  kind: 'type' | 'input' | 'interface' | 'enum' | 'union' | 'scalar';
  name: string;
  description?: string;
  fields?: GraphQLField[];
  enumValues?: Array<{ name: string; description?: string }>;
  interfaces?: string[];
  possibleTypes?: string[];
  directives?: GraphQLDirective[];
}

/**
 * Built-in GraphQL scalar types and their OpenAPI equivalents
 */
const GRAPHQL_SCALAR_MAPPINGS: Record<string, any> = {
  'String': { type: 'string' },
  'Int': { type: 'integer', format: 'int32' },
  'Float': { type: 'number', format: 'double' },
  'Boolean': { type: 'boolean' },
  'ID': { type: 'string', description: 'GraphQL ID scalar' },
  // Common custom scalars
  'DateTime': { type: 'string', format: 'date-time' },
  'Date': { type: 'string', format: 'date' },
  'Time': { type: 'string', format: 'time' },
  'JSON': { type: 'object', additionalProperties: true },
  'JSONObject': { type: 'object', additionalProperties: true },
  'BigInt': { type: 'integer', format: 'int64' },
  'Long': { type: 'integer', format: 'int64' },
  'UUID': { type: 'string', format: 'uuid' },
  'URL': { type: 'string', format: 'uri' },
  'Email': { type: 'string', format: 'email' },
  'Decimal': { type: 'string', pattern: '^-?\\d+\\.?\\d*$' },
  'Currency': { type: 'string', pattern: '^[A-Z]{3}$' },
  'Void': { type: 'null' },
  'Upload': { type: 'string', format: 'binary' },
};

/**
 * Converts a GraphQL SDL document to OpenAPI 3.1.x format
 *
 * @param graphqlContent - The GraphQL SDL content as a string
 * @param filename - Optional filename to derive schema name from
 * @returns The converted OpenAPI 3.1.x document with conversion metadata
 */
export function convertGraphQLToOpenAPI(
  graphqlContent: string,
  filename?: string
): GraphQLConversionResult {
  const warnings: string[] = [];

  try {
    // Validate input
    if (!graphqlContent || typeof graphqlContent !== 'string') {
      return {
        success: false,
        document: null,
        error: 'Invalid GraphQL content: expected a string',
        warnings: []
      };
    }

    const trimmedContent = graphqlContent.trim();
    if (!trimmedContent) {
      return {
        success: false,
        document: null,
        error: 'Empty GraphQL content',
        warnings: []
      };
    }

    // Parse the GraphQL SDL
    const types = parseGraphQLSDL(trimmedContent, warnings);

    if (types.length === 0) {
      return {
        success: false,
        document: null,
        error: 'No type definitions found in GraphQL schema',
        warnings
      };
    }

    // Create OpenAPI 3.1.0 base structure
    const title = extractTitle(types, filename);
    const openApiDoc: any = {
      openapi: '3.1.0',
      info: {
        title,
        version: '1.0.0',
        description: 'Converted from GraphQL Schema'
      },
      components: {
        schemas: {}
      }
    };

    // Track custom scalars
    const customScalars = new Set<string>();

    // First pass: collect custom scalars
    for (const typeDef of types) {
      if (typeDef.kind === 'scalar' && !GRAPHQL_SCALAR_MAPPINGS[typeDef.name]) {
        customScalars.add(typeDef.name);
        warnings.push(`Custom scalar "${typeDef.name}" will be treated as string`);
      }
    }

    // Second pass: convert types to OpenAPI schemas
    for (const typeDef of types) {
      // Skip built-in types
      if (isBuiltInType(typeDef.name)) {
        continue;
      }

      const schema = convertTypeToSchema(typeDef, types, customScalars, warnings);
      if (schema) {
        openApiDoc.components.schemas[typeDef.name] = schema;
      }
    }

    if (Object.keys(openApiDoc.components.schemas).length === 0) {
      return {
        success: false,
        document: null,
        error: 'No convertible types found in GraphQL schema',
        warnings
      };
    }

    return {
      success: true,
      document: openApiDoc,
      warnings
    };
  } catch (error) {
    return {
      success: false,
      document: null,
      error: `Conversion failed: ${error instanceof Error ? error.message : String(error)}`,
      warnings
    };
  }
}

/**
 * Check if a type is a built-in GraphQL type
 */
function isBuiltInType(name: string): boolean {
  return ['Query', 'Mutation', 'Subscription', '__Schema', '__Type', '__TypeKind',
          '__Field', '__InputValue', '__EnumValue', '__Directive', '__DirectiveLocation'].includes(name);
}

/**
 * Extract a title from the types or filename
 */
function extractTitle(types: GraphQLTypeDef[], filename?: string): string {
  // Look for a type with a @title directive or description
  for (const type of types) {
    if (type.kind === 'type' && type.name === 'Query' && type.description) {
      return type.description.split('\n')[0].trim();
    }
  }

  if (filename) {
    const name = filename
      .replace(/\.(graphql|gql|graphqls)$/i, '')
      .replace(/[-_]/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
    return name;
  }

  return 'GraphQL Schema';
}

/**
 * Parse GraphQL SDL into type definitions
 */
function parseGraphQLSDL(content: string, warnings: string[]): GraphQLTypeDef[] {
  const types: GraphQLTypeDef[] = [];

  // Remove comments but preserve descriptions (triple quotes and # preceding type)
  let processedContent = content;

  // Extract type definitions using regex
  // This is a simplified parser - for production, use graphql-js

  // Match type definitions
  const typePattern = /(?:"""([\s\S]*?)"""\s*)?(?:"([^"]*?)"\s*)?(type|input|interface|enum|union|scalar)\s+(\w+)(?:\s+implements\s+([\w\s,&]+))?(?:\s*@\w+(?:\([^)]*\))?)*\s*(?:\{([\s\S]*?)\})?/g;

  let match;
  while ((match = typePattern.exec(processedContent)) !== null) {
    const [, tripleQuoteDesc, singleQuoteDesc, kind, name, implementsClause, body] = match;
    const description = tripleQuoteDesc?.trim() || singleQuoteDesc?.trim();

    const typeDef: GraphQLTypeDef = {
      kind: kind as GraphQLTypeDef['kind'],
      name,
      description
    };

    // Parse implements
    if (implementsClause) {
      typeDef.interfaces = implementsClause.split(/[,&]/).map(s => s.trim()).filter(Boolean);
    }

    // Parse body based on kind
    if (body) {
      if (kind === 'enum') {
        typeDef.enumValues = parseEnumValues(body);
      } else if (kind === 'union') {
        typeDef.possibleTypes = body.split('|').map(s => s.trim()).filter(Boolean);
      } else if (kind !== 'scalar') {
        typeDef.fields = parseFields(body, warnings);
      }
    }

    // Handle union without braces
    if (kind === 'union' && !body) {
      // Look for = Type1 | Type2 pattern after the definition
      const unionPattern = new RegExp(`union\\s+${name}\\s*=\\s*([\\w\\s|]+?)(?:type|input|interface|enum|union|scalar|$)`);
      const unionMatch = processedContent.match(unionPattern);
      if (unionMatch) {
        typeDef.possibleTypes = unionMatch[1].split('|').map(s => s.trim()).filter(Boolean);
      }
    }

    types.push(typeDef);
  }

  // Parse standalone unions (union Name = Type1 | Type2)
  // This pattern handles unions that aren't caught by the main pattern
  const standaloneUnionPattern = /(?:"""([\s\S]*?)"""\s*)?union\s+(\w+)\s*=\s*([^"\n]+?)(?=\s*\n|$)/gm;
  while ((match = standaloneUnionPattern.exec(processedContent)) !== null) {
    const [, description, name, types_str] = match;
    // Check if we already have this union with possibleTypes
    const existingUnion = types.find(t => t.name === name && t.kind === 'union');
    if (existingUnion && (!existingUnion.possibleTypes || existingUnion.possibleTypes.length === 0)) {
      // Update the existing union with the possible types
      existingUnion.possibleTypes = types_str.split('|').map(s => s.trim()).filter(Boolean);
      if (description) {
        existingUnion.description = description.trim();
      }
    } else if (!existingUnion) {
      types.push({
        kind: 'union',
        name,
        description: description?.trim(),
        possibleTypes: types_str.split('|').map(s => s.trim()).filter(Boolean)
      });
    }
  }

  return types;
}

/**
 * Parse enum values from body
 */
function parseEnumValues(body: string): Array<{ name: string; description?: string }> {
  const values: Array<{ name: string; description?: string }> = [];
  const lines = body.split('\n');

  let currentDescription: string | undefined;

  for (const line of lines) {
    const trimmed = line.trim();

    // Skip empty lines
    if (!trimmed) continue;

    // Check for description (triple quote or single line)
    const tripleQuoteMatch = trimmed.match(/^"""(.*?)"""$/);
    const singleQuoteMatch = trimmed.match(/^"(.*?)"$/);
    const hashCommentMatch = trimmed.match(/^#\s*(.*)$/);

    if (tripleQuoteMatch) {
      currentDescription = tripleQuoteMatch[1].trim();
      continue;
    }
    if (singleQuoteMatch) {
      currentDescription = singleQuoteMatch[1].trim();
      continue;
    }
    if (hashCommentMatch) {
      currentDescription = hashCommentMatch[1].trim();
      continue;
    }

    // Parse enum value
    const valueMatch = trimmed.match(/^(\w+)/);
    if (valueMatch) {
      values.push({
        name: valueMatch[1],
        description: currentDescription
      });
      currentDescription = undefined;
    }
  }

  return values;
}

/**
 * Parse fields from body
 */
function parseFields(body: string, warnings: string[]): GraphQLField[] {
  const fields: GraphQLField[] = [];

  // Split by lines and process
  const lines = body.split('\n');
  let currentDescription: string | undefined;
  let multilineDescription: string[] = [];
  let inMultilineDescription = false;

  for (const line of lines) {
    const trimmed = line.trim();

    // Skip empty lines
    if (!trimmed) continue;

    // Handle multiline descriptions
    if (trimmed.startsWith('"""')) {
      if (inMultilineDescription) {
        // End of multiline description
        inMultilineDescription = false;
        currentDescription = multilineDescription.join('\n').trim();
        multilineDescription = [];
      } else if (trimmed.endsWith('"""') && trimmed.length > 6) {
        // Single line triple quote description
        currentDescription = trimmed.slice(3, -3).trim();
      } else {
        // Start of multiline description
        inMultilineDescription = true;
        const content = trimmed.slice(3);
        if (content) multilineDescription.push(content);
      }
      continue;
    }

    if (inMultilineDescription) {
      if (trimmed.endsWith('"""')) {
        multilineDescription.push(trimmed.slice(0, -3));
        inMultilineDescription = false;
        currentDescription = multilineDescription.join('\n').trim();
        multilineDescription = [];
      } else {
        multilineDescription.push(trimmed);
      }
      continue;
    }

    // Check for single line description
    const singleQuoteMatch = trimmed.match(/^"(.*?)"$/);
    if (singleQuoteMatch) {
      currentDescription = singleQuoteMatch[1].trim();
      continue;
    }

    // Skip comments
    if (trimmed.startsWith('#')) {
      currentDescription = trimmed.slice(1).trim();
      continue;
    }

    // Parse field
    const fieldMatch = trimmed.match(/^(\w+)(?:\s*\(([\s\S]*?)\))?\s*:\s*(.+?)(?:\s*@|$)/);
    if (fieldMatch) {
      const [, fieldName, args, typeStr] = fieldMatch;

      const field: GraphQLField = {
        name: fieldName,
        description: currentDescription,
        type: parseTypeRef(typeStr.trim())
      };

      // Parse arguments if present
      if (args) {
        field.arguments = parseArguments(args, warnings);
      }

      fields.push(field);
      currentDescription = undefined;
    }
  }

  return fields;
}

/**
 * Parse field arguments
 */
function parseArguments(argsStr: string, warnings: string[]): GraphQLArgument[] {
  const args: GraphQLArgument[] = [];

  // Split by comma, but be careful of nested types
  const argDefs = splitArguments(argsStr);

  for (const argDef of argDefs) {
    const trimmed = argDef.trim();
    if (!trimmed) continue;

    // Match: name: Type = defaultValue
    const argMatch = trimmed.match(/^(?:"([^"]*?)"\s*)?(\w+)\s*:\s*([^=]+?)(?:\s*=\s*(.+))?$/);
    if (argMatch) {
      const [, description, name, typeStr, defaultValue] = argMatch;
      args.push({
        name,
        description: description?.trim(),
        type: parseTypeRef(typeStr.trim()),
        defaultValue: defaultValue ? parseDefaultValue(defaultValue.trim()) : undefined
      });
    }
  }

  return args;
}

/**
 * Split arguments string handling nested brackets
 */
function splitArguments(argsStr: string): string[] {
  const args: string[] = [];
  let current = '';
  let depth = 0;

  for (const char of argsStr) {
    if (char === '[' || char === '(') {
      depth++;
      current += char;
    } else if (char === ']' || char === ')') {
      depth--;
      current += char;
    } else if (char === ',' && depth === 0) {
      args.push(current.trim());
      current = '';
    } else {
      current += char;
    }
  }

  if (current.trim()) {
    args.push(current.trim());
  }

  return args;
}

/**
 * Parse a default value string
 */
function parseDefaultValue(value: string): any {
  if (value === 'null') return null;
  if (value === 'true') return true;
  if (value === 'false') return false;
  if (/^-?\d+$/.test(value)) return parseInt(value, 10);
  if (/^-?\d+\.\d+$/.test(value)) return parseFloat(value);
  if (value.startsWith('"') && value.endsWith('"')) {
    return value.slice(1, -1);
  }
  // Enum value or complex value - return as string
  return value;
}

/**
 * Parse a type reference string into a structured type
 */
function parseTypeRef(typeStr: string): GraphQLTypeRef {
  const trimmed = typeStr.trim();

  // Non-null type (ends with !)
  if (trimmed.endsWith('!')) {
    return {
      kind: 'NON_NULL',
      ofType: parseTypeRef(trimmed.slice(0, -1))
    };
  }

  // List type (wrapped in [])
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
    return {
      kind: 'LIST',
      ofType: parseTypeRef(trimmed.slice(1, -1))
    };
  }

  // Named type
  return {
    kind: 'SCALAR', // Will be corrected during conversion based on actual type
    name: trimmed
  };
}

/**
 * Convert a GraphQL type definition to an OpenAPI schema
 */
function convertTypeToSchema(
  typeDef: GraphQLTypeDef,
  allTypes: GraphQLTypeDef[],
  customScalars: Set<string>,
  warnings: string[]
): any {
  switch (typeDef.kind) {
    case 'type':
    case 'input':
      return convertObjectType(typeDef, allTypes, customScalars, warnings);

    case 'interface':
      return convertInterfaceType(typeDef, allTypes, customScalars, warnings);

    case 'enum':
      return convertEnumType(typeDef);

    case 'union':
      return convertUnionType(typeDef, warnings);

    case 'scalar':
      return convertScalarType(typeDef, customScalars);

    default:
      warnings.push(`Unknown type kind: ${typeDef.kind}`);
      return null;
  }
}

/**
 * Convert object/input type to OpenAPI schema
 */
function convertObjectType(
  typeDef: GraphQLTypeDef,
  allTypes: GraphQLTypeDef[],
  customScalars: Set<string>,
  warnings: string[]
): any {
  const schema: any = {
    type: 'object',
    description: typeDef.description
  };

  // Handle interfaces (allOf)
  if (typeDef.interfaces && typeDef.interfaces.length > 0) {
    const allOf: any[] = typeDef.interfaces.map(intf => ({
      $ref: `#/components/schemas/${intf}`
    }));

    // Add the type's own properties
    const ownSchema: any = { type: 'object' };
    if (typeDef.fields && typeDef.fields.length > 0) {
      const { properties, required } = convertFields(typeDef.fields, allTypes, customScalars, warnings);
      if (Object.keys(properties).length > 0) {
        ownSchema.properties = properties;
      }
      if (required.length > 0) {
        ownSchema.required = required;
      }
    }

    allOf.push(ownSchema);

    return {
      description: typeDef.description,
      allOf
    };
  }

  // No interfaces - simple object
  if (typeDef.fields && typeDef.fields.length > 0) {
    const { properties, required } = convertFields(typeDef.fields, allTypes, customScalars, warnings);
    if (Object.keys(properties).length > 0) {
      schema.properties = properties;
    }
    if (required.length > 0) {
      schema.required = required;
    }
  }

  return schema;
}

/**
 * Convert interface type to OpenAPI schema
 */
function convertInterfaceType(
  typeDef: GraphQLTypeDef,
  allTypes: GraphQLTypeDef[],
  customScalars: Set<string>,
  warnings: string[]
): any {
  const schema: any = {
    type: 'object',
    description: typeDef.description,
    'x-graphql-interface': true
  };

  if (typeDef.fields && typeDef.fields.length > 0) {
    const { properties, required } = convertFields(typeDef.fields, allTypes, customScalars, warnings);
    if (Object.keys(properties).length > 0) {
      schema.properties = properties;
    }
    if (required.length > 0) {
      schema.required = required;
    }
  }

  return schema;
}

/**
 * Convert enum type to OpenAPI schema
 */
function convertEnumType(typeDef: GraphQLTypeDef): any {
  const schema: any = {
    type: 'string',
    description: typeDef.description
  };

  if (typeDef.enumValues && typeDef.enumValues.length > 0) {
    schema.enum = typeDef.enumValues.map(v => v.name);

    // Add descriptions as x-enum-descriptions if any values have descriptions
    const descriptions = typeDef.enumValues
      .filter(v => v.description)
      .map(v => ({ value: v.name, description: v.description }));

    if (descriptions.length > 0) {
      schema['x-enum-descriptions'] = descriptions;
    }
  }

  return schema;
}

/**
 * Convert union type to OpenAPI schema
 */
function convertUnionType(typeDef: GraphQLTypeDef, warnings: string[]): any {
  if (!typeDef.possibleTypes || typeDef.possibleTypes.length === 0) {
    warnings.push(`Union "${typeDef.name}" has no possible types`);
    return { type: 'object' };
  }

  return {
    description: typeDef.description,
    oneOf: typeDef.possibleTypes.map(t => ({
      $ref: `#/components/schemas/${t}`
    }))
  };
}

/**
 * Convert scalar type to OpenAPI schema
 */
function convertScalarType(typeDef: GraphQLTypeDef, customScalars: Set<string>): any {
  // Check if it's a known scalar
  if (GRAPHQL_SCALAR_MAPPINGS[typeDef.name]) {
    return {
      ...GRAPHQL_SCALAR_MAPPINGS[typeDef.name],
      description: typeDef.description
    };
  }

  // Custom scalar - treat as string
  return {
    type: 'string',
    description: typeDef.description || `Custom GraphQL scalar: ${typeDef.name}`,
    'x-graphql-scalar': typeDef.name
  };
}

/**
 * Convert fields to OpenAPI properties
 */
function convertFields(
  fields: GraphQLField[],
  allTypes: GraphQLTypeDef[],
  customScalars: Set<string>,
  warnings: string[]
): { properties: Record<string, any>; required: string[] } {
  const properties: Record<string, any> = {};
  const required: string[] = [];

  for (const field of fields) {
    const { schema, isRequired } = convertTypeRef(field.type, allTypes, customScalars, warnings);

    const property: any = { ...schema };
    if (field.description) {
      property.description = field.description;
    }

    // Add argument info as extension if present
    if (field.arguments && field.arguments.length > 0) {
      property['x-graphql-arguments'] = field.arguments.map(arg => ({
        name: arg.name,
        description: arg.description,
        type: typeRefToString(arg.type),
        defaultValue: arg.defaultValue
      }));
    }

    properties[field.name] = property;

    if (isRequired) {
      required.push(field.name);
    }
  }

  return { properties, required };
}

/**
 * Convert a type reference to an OpenAPI schema
 */
function convertTypeRef(
  typeRef: GraphQLTypeRef,
  allTypes: GraphQLTypeDef[],
  customScalars: Set<string>,
  warnings: string[]
): { schema: any; isRequired: boolean } {
  let isRequired = false;

  // Handle non-null wrapper
  if (typeRef.kind === 'NON_NULL') {
    isRequired = true;
    if (typeRef.ofType) {
      const result = convertTypeRef(typeRef.ofType, allTypes, customScalars, warnings);
      return { schema: result.schema, isRequired: true };
    }
  }

  // Handle list
  if (typeRef.kind === 'LIST') {
    if (typeRef.ofType) {
      const innerResult = convertTypeRef(typeRef.ofType, allTypes, customScalars, warnings);
      return {
        schema: {
          type: 'array',
          items: innerResult.schema
        },
        isRequired
      };
    }
  }

  // Named type
  if (typeRef.name) {
    // Check if it's a built-in scalar
    if (GRAPHQL_SCALAR_MAPPINGS[typeRef.name]) {
      return {
        schema: { ...GRAPHQL_SCALAR_MAPPINGS[typeRef.name] },
        isRequired
      };
    }

    // Check if it's a custom scalar
    if (customScalars.has(typeRef.name)) {
      return {
        schema: {
          type: 'string',
          'x-graphql-scalar': typeRef.name
        },
        isRequired
      };
    }

    // Reference to another type
    return {
      schema: { $ref: `#/components/schemas/${typeRef.name}` },
      isRequired
    };
  }

  // Fallback
  return { schema: { type: 'string' }, isRequired };
}

/**
 * Convert type reference back to string for display
 */
function typeRefToString(typeRef: GraphQLTypeRef): string {
  if (typeRef.kind === 'NON_NULL' && typeRef.ofType) {
    return typeRefToString(typeRef.ofType) + '!';
  }
  if (typeRef.kind === 'LIST' && typeRef.ofType) {
    return '[' + typeRefToString(typeRef.ofType) + ']';
  }
  return typeRef.name || 'Unknown';
}

/**
 * Check if content looks like a GraphQL schema
 */
export function isGraphQL(content: string): boolean {
  if (!content || typeof content !== 'string') {
    return false;
  }

  const trimmed = content.trim();

  // Check for common GraphQL keywords
  const graphqlPatterns = [
    /^\s*type\s+\w+/m,
    /^\s*input\s+\w+/m,
    /^\s*interface\s+\w+/m,
    /^\s*enum\s+\w+/m,
    /^\s*union\s+\w+/m,
    /^\s*scalar\s+\w+/m,
    /^\s*schema\s*\{/m,
    /^\s*extend\s+type\s+/m,
    /^\s*directive\s+@/m,
  ];

  return graphqlPatterns.some(pattern => pattern.test(trimmed));
}

/**
 * Check if content is a GraphQL document (parsed object)
 * This handles the case where content has been parsed as JSON/YAML
 * but is actually a GraphQL introspection result
 */
export function isGraphQLIntrospection(doc: any): boolean {
  if (!doc || typeof doc !== 'object') {
    return false;
  }

  // Check for introspection query result
  if (doc.__schema && doc.__schema.types) {
    return true;
  }

  // Check for data wrapper
  if (doc.data && doc.data.__schema && doc.data.__schema.types) {
    return true;
  }

  return false;
}

/**
 * Convert GraphQL introspection result to OpenAPI
 */
export function convertGraphQLIntrospectionToOpenAPI(
  introspectionResult: any,
  filename?: string
): GraphQLConversionResult {
  const warnings: string[] = [];

  try {
    const schema = introspectionResult.__schema || introspectionResult.data?.__schema;

    if (!schema || !schema.types) {
      return {
        success: false,
        document: null,
        error: 'Invalid GraphQL introspection result',
        warnings: []
      };
    }

    // Create OpenAPI document
    const openApiDoc: any = {
      openapi: '3.1.0',
      info: {
        title: filename ? filename.replace(/\.(json|graphql)$/i, '') : 'GraphQL Schema',
        version: '1.0.0',
        description: 'Converted from GraphQL introspection result'
      },
      components: {
        schemas: {}
      }
    };

    // Convert types
    for (const type of schema.types) {
      // Skip built-in types
      if (type.name.startsWith('__') || isBuiltInType(type.name)) {
        continue;
      }

      const converted = convertIntrospectionType(type, warnings);
      if (converted) {
        openApiDoc.components.schemas[type.name] = converted;
      }
    }

    if (Object.keys(openApiDoc.components.schemas).length === 0) {
      return {
        success: false,
        document: null,
        error: 'No convertible types found in GraphQL introspection result',
        warnings
      };
    }

    return {
      success: true,
      document: openApiDoc,
      warnings
    };
  } catch (error) {
    return {
      success: false,
      document: null,
      error: `Conversion failed: ${error instanceof Error ? error.message : String(error)}`,
      warnings
    };
  }
}

/**
 * Convert an introspection type to OpenAPI schema
 */
function convertIntrospectionType(type: any, warnings: string[]): any {
  switch (type.kind) {
    case 'OBJECT':
    case 'INPUT_OBJECT':
      return convertIntrospectionObjectType(type, warnings);

    case 'INTERFACE':
      return convertIntrospectionInterfaceType(type, warnings);

    case 'ENUM':
      return {
        type: 'string',
        description: type.description,
        enum: type.enumValues?.map((v: any) => v.name) || []
      };

    case 'UNION':
      return {
        description: type.description,
        oneOf: type.possibleTypes?.map((t: any) => ({
          $ref: `#/components/schemas/${t.name}`
        })) || []
      };

    case 'SCALAR':
      if (GRAPHQL_SCALAR_MAPPINGS[type.name]) {
        return { ...GRAPHQL_SCALAR_MAPPINGS[type.name], description: type.description };
      }
      return {
        type: 'string',
        description: type.description || `Custom scalar: ${type.name}`,
        'x-graphql-scalar': type.name
      };

    default:
      warnings.push(`Unknown introspection type kind: ${type.kind}`);
      return null;
  }
}

/**
 * Convert introspection object type
 */
function convertIntrospectionObjectType(type: any, warnings: string[]): any {
  const schema: any = {
    type: 'object',
    description: type.description
  };

  if (type.fields && type.fields.length > 0) {
    const properties: Record<string, any> = {};
    const required: string[] = [];

    for (const field of type.fields) {
      const { schema: propSchema, isRequired } = convertIntrospectionTypeRef(field.type);
      properties[field.name] = {
        ...propSchema,
        description: field.description
      };
      if (isRequired) {
        required.push(field.name);
      }
    }

    if (Object.keys(properties).length > 0) {
      schema.properties = properties;
    }
    if (required.length > 0) {
      schema.required = required;
    }
  }

  // Handle inputFields for INPUT_OBJECT
  if (type.inputFields && type.inputFields.length > 0) {
    const properties: Record<string, any> = {};
    const required: string[] = [];

    for (const field of type.inputFields) {
      const { schema: propSchema, isRequired } = convertIntrospectionTypeRef(field.type);
      properties[field.name] = {
        ...propSchema,
        description: field.description
      };
      if (isRequired) {
        required.push(field.name);
      }
    }

    if (Object.keys(properties).length > 0) {
      schema.properties = properties;
    }
    if (required.length > 0) {
      schema.required = required;
    }
  }

  return schema;
}

/**
 * Convert introspection interface type
 */
function convertIntrospectionInterfaceType(type: any, warnings: string[]): any {
  const schema = convertIntrospectionObjectType(type, warnings);
  schema['x-graphql-interface'] = true;
  return schema;
}

/**
 * Convert introspection type reference
 */
function convertIntrospectionTypeRef(typeRef: any): { schema: any; isRequired: boolean } {
  if (!typeRef) {
    return { schema: { type: 'string' }, isRequired: false };
  }

  if (typeRef.kind === 'NON_NULL') {
    const result = convertIntrospectionTypeRef(typeRef.ofType);
    return { schema: result.schema, isRequired: true };
  }

  if (typeRef.kind === 'LIST') {
    const innerResult = convertIntrospectionTypeRef(typeRef.ofType);
    return {
      schema: { type: 'array', items: innerResult.schema },
      isRequired: false
    };
  }

  // Named type
  if (typeRef.name) {
    if (GRAPHQL_SCALAR_MAPPINGS[typeRef.name]) {
      return { schema: { ...GRAPHQL_SCALAR_MAPPINGS[typeRef.name] }, isRequired: false };
    }
    return { schema: { $ref: `#/components/schemas/${typeRef.name}` }, isRequired: false };
  }

  return { schema: { type: 'string' }, isRequired: false };
}

