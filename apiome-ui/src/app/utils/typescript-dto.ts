/**
 * TypeScript DTO Generator Utilities
 *
 * Generates TypeScript interfaces and types from class definitions.
 * Supports:
 * - allOf/oneOf/anyOf compositions
 * - Discriminators for inheritance
 * - Enumerations
 * - Nested objects and arrays
 * - Optional properties
 * - Union types
 */

interface FieldConstraints {
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
  format?: string;
  enum?: any[];
}

/**
 * Converts a name to PascalCase for class/interface names
 */
function toPascalCase(name: string): string {
  return name
    .split(/[-_\s]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

/**
 * Maps JSON Schema types to TypeScript types
 */
function mapTypeToTypeScript(propData: any, className?: string): string {
  // Handle enum types
  if (propData.enum && Array.isArray(propData.enum)) {
    const enumValues = propData.enum.map((v: any) =>
      typeof v === 'string' ? `"${v}"` : v
    ).join(' | ');
    return enumValues;
  }

  // Handle $ref (references to other classes)
  if (propData.$ref) {
    const refParts = propData.$ref.split('/');
    const refClassName = refParts[refParts.length - 1];
    return refClassName;
  }

  // Handle array types
  if (propData.type === 'array') {
    if (propData.items) {
      const itemType = mapTypeToTypeScript(propData.items);
      return `${itemType}[]`;
    }
    return 'any[]';
  }

  // Handle object types (nested objects)
  if (propData.type === 'object') {
    if (propData.properties) {
      return className || 'Record<string, any>';
    }
    return 'Record<string, any>';
  }

  // Handle basic types with format validation
  switch (propData.type) {
    case 'string':
      return 'string';
    case 'integer':
    case 'number':
      return 'number';
    case 'boolean':
      return 'boolean';
    case 'null':
      return 'null';
    default:
      return 'any';
  }
}

/**
 * Checks if a property is required based on the class schema
 */
function isPropertyRequired(propertyName: string, schema: any): boolean {
  if (!schema || !schema.required) return false;
  return Array.isArray(schema.required) && schema.required.includes(propertyName);
}

/**
 * Generates a comment block for a property with constraints
 */
function generatePropertyComment(prop: any, propData: any, indent: string = '  '): string {
  const comments: string[] = [];

  if (prop.description) {
    comments.push(prop.description);
  }

  // Add constraint information
  const constraints: string[] = [];
  if (propData.pattern) constraints.push(`pattern: ${propData.pattern}`);
  if (propData.minLength !== undefined) constraints.push(`minLength: ${propData.minLength}`);
  if (propData.maxLength !== undefined) constraints.push(`maxLength: ${propData.maxLength}`);
  if (propData.minimum !== undefined) constraints.push(`minimum: ${propData.minimum}`);
  if (propData.maximum !== undefined) constraints.push(`maximum: ${propData.maximum}`);
  if (propData.minItems !== undefined) constraints.push(`minItems: ${propData.minItems}`);
  if (propData.maxItems !== undefined) constraints.push(`maxItems: ${propData.maxItems}`);
  if (propData.format) constraints.push(`format: ${propData.format}`);

  if (constraints.length > 0) {
    comments.push(`@constraints ${constraints.join(', ')}`);
  }

  if (comments.length === 0) return '';

  if (comments.length === 1) {
    return `${indent}/** ${comments[0]} */\n`;
  }

  return `${indent}/**\n${comments.map(c => `${indent} * ${c}`).join('\n')}\n${indent} */\n`;
}

/**
 * Generates TypeScript code for a nested object property
 */
function generateNestedInterface(
  prop: any,
  propData: any,
  parentClassName: string,
  childProperties: any[],
  allProperties: any[],
  isArrayItem: boolean = false
): string {
  // Use naming pattern consistent with Python:
  // - For objects: PascalCase of property name
  // - For array items: PascalCase of singular property name + "Item"
  let nestedClassName: string;
  if (isArrayItem) {
    // Remove trailing 's' if present and add 'Item'
    const singularName = prop.name.replace(/s$/, '');
    nestedClassName = toPascalCase(singularName) + 'Item';
  } else {
    nestedClassName = toPascalCase(prop.name);
  }

  let nestedInterfacesCode = ''; // Collect nested interfaces
  let currentInterfaceCode = '';

  // Build child property hierarchy for recursive nested objects
  const childMap = new Map<string, any[]>();
  allProperties.forEach(p => {
    if (p.parent_id && childProperties.some(cp => cp.id === p.parent_id)) {
      if (!childMap.has(p.parent_id)) {
        childMap.set(p.parent_id, []);
      }
      childMap.get(p.parent_id)!.push(p);
    }
  });

  // Get required fields from the nested object's schema
  const requiredFields = propData.required || [];

  // Add description if available
  if (prop.description) {
    currentInterfaceCode += `/**\n * ${prop.description}\n */\n`;
  }

  currentInterfaceCode += `export interface ${nestedClassName} {\n`;

  // Generate properties for nested object
  childProperties.forEach((childProp) => {
    const childData = typeof childProp.data === 'string' ? JSON.parse(childProp.data) : childProp.data;
    const nestedChildren = childMap.get(childProp.id);
    let childType: string;

    // Handle recursive nested objects
    if (nestedChildren && nestedChildren.length > 0) {
      if (childData.type === 'array' && childData.items?.type === 'object') {
        // Generate nested interface for array items - add to nested interfaces
        const nestedCode = generateNestedInterface(childProp, childData.items, nestedClassName, nestedChildren, allProperties, true);
        nestedInterfacesCode += nestedCode;
        // Calculate the nested class name using the same logic
        const singularName = childProp.name.replace(/s$/, '');
        const nestedNestedClassName = toPascalCase(singularName) + 'Item';
        childType = `${nestedNestedClassName}[]`;
      } else if (childData.type === 'object') {
        // Generate nested interface for object - add to nested interfaces
        const nestedCode = generateNestedInterface(childProp, childData, nestedClassName, nestedChildren, allProperties, false);
        nestedInterfacesCode += nestedCode;
        const nestedNestedClassName = toPascalCase(childProp.name);
        childType = nestedNestedClassName;
      } else {
        childType = mapTypeToTypeScript(childData, nestedClassName);
      }
    } else {
      childType = mapTypeToTypeScript(childData, nestedClassName);
    }

    // Determine if property is required
    const isRequired = requiredFields.includes(childProp.name);
    const optional = isRequired ? '' : '?';

    const comment = generatePropertyComment(childProp, childData);
    if (comment) currentInterfaceCode += comment;

    currentInterfaceCode += `  ${childProp.name}${optional}: ${childType};\n`;
  });

  currentInterfaceCode += '}\n\n';

  // Return nested interfaces first, then current interface
  return nestedInterfacesCode + currentInterfaceCode;
}

/**
 * Generates TypeScript code for a class with composition (allOf/oneOf/anyOf)
 */
function generateCompositionType(
  cls: any,
  schema: any,
  compositionType: 'allOf' | 'oneOf' | 'anyOf'
): string {
  let code = '';

  // Add class description if available
  if (cls.description) {
    code += `/**\n * ${cls.description}\n */\n`;
  }

  const compositions = schema[compositionType];
  if (!compositions || !Array.isArray(compositions)) {
    return code;
  }

  const types: string[] = [];

  compositions.forEach((item: any) => {
    if (item.$ref) {
      const refParts = item.$ref.split('/');
      const refClassName = refParts[refParts.length - 1];
      types.push(refClassName);
    } else if (item.type) {
      // Inline schema definition
      types.push(mapTypeToTypeScript(item));
    }
  });

  if (types.length === 0) {
    return code;
  }

  // Generate appropriate type based on composition
  if (compositionType === 'allOf') {
    // Intersection type (combine all types)
    code += `export type ${cls.name} = ${types.join(' & ')};\n\n`;
  } else {
    // Union type (oneOf or anyOf)
    code += `export type ${cls.name} = ${types.join(' | ')};\n\n`;
  }

  return code;
}

/**
 * Generates TypeScript code for a single class
 */
function generateClassInterface(
  cls: any,
  allProperties: any[]
): string {
  let code = '';

  const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : (cls.schema || {});

  // Check for composition types
  if (schema.allOf) {
    return generateCompositionType(cls, schema, 'allOf');
  }
  if (schema.oneOf) {
    return generateCompositionType(cls, schema, 'oneOf');
  }
  if (schema.anyOf) {
    return generateCompositionType(cls, schema, 'anyOf');
  }

  // Build property hierarchy
  const topLevelProps = allProperties.filter(p => !p.parent_id);
  const childMap = new Map<string, any[]>();
  allProperties.forEach(p => {
    if (p.parent_id) {
      if (!childMap.has(p.parent_id)) {
        childMap.set(p.parent_id, []);
      }
      childMap.get(p.parent_id)!.push(p);
    }
  });

  // Generate nested interfaces first
  topLevelProps.forEach((prop) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
    const children = childMap.get(prop.id);

    if (children && children.length > 0) {
      // Check if it's an array of objects or direct object
      if (propData.type === 'array' && propData.items?.type === 'object') {
        code += generateNestedInterface(prop, propData.items, cls.name, children, allProperties, true);
      } else if (propData.type === 'object') {
        code += generateNestedInterface(prop, propData, cls.name, children, allProperties, false);
      }
    }
  });

  // Add class description if available
  if (cls.description) {
    code += `/**\n * ${cls.description}\n */\n`;
  }

  // Generate main interface
  code += `export interface ${cls.name} {\n`;

  // Generate properties
  topLevelProps.forEach((prop) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
    const children = childMap.get(prop.id);
    let propType: string;

    // Determine property type
    if (children && children.length > 0) {
      if (propData.type === 'array') {
        // Use same naming as Python: singular + "Item"
        const singularName = prop.name.replace(/s$/, '');
        const nestedClassName = toPascalCase(singularName) + 'Item';
        propType = `${nestedClassName}[]`;
      } else {
        // Use PascalCase of property name
        const nestedClassName = toPascalCase(prop.name);
        propType = nestedClassName;
      }
    } else {
      propType = mapTypeToTypeScript(propData, cls.name);
    }

    // Determine if property is optional
    const isRequired = isPropertyRequired(prop.name, schema);
    const optional = isRequired ? '' : '?';

    // Add property comment
    const comment = generatePropertyComment(prop, propData);
    if (comment) code += comment;

    code += `  ${prop.name}${optional}: ${propType};\n`;
  });

  code += '}\n\n';

  return code;
}

/**
 * Main function to generate TypeScript DTOs
 *
 * @param classes - Array of class definitions with properties
 * @param options - Optional metadata for the generated code
 * @returns TypeScript code as a string
 */
export function generateTypeScriptDTOs(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
  }
): string {
  // Build header comment
  let code = '/**\n';
  code += ` * ${options?.projectName || 'Data Type Objects'}\n`;
  if (options?.version) {
    code += ` * Version: ${options.version}\n`;
  }
  if (options?.description) {
    code += ` *\n * ${options.description}\n`;
  }
  code += ' *\n * Generated by Apiome Studio\n';
  code += ' */\n\n';

  // Track which classes have been generated
  const generatedClasses = new Set<string>();

  // Sort classes to handle dependencies (referenced classes first)
  const sortedClasses = [...classes];

  // Generate code for each class
  sortedClasses.forEach((cls) => {
    if (!generatedClasses.has(cls.name)) {
      const classCode = generateClassInterface(cls, cls.properties || []);
      code += classCode;
      generatedClasses.add(cls.name);
    }
  });

  // Add a default export with all interfaces
  if (classes.length > 0) {
    code += '// Export all types\n';
    code += 'export type AllTypes = {\n';
    classes.forEach((cls) => {
      code += `  ${cls.name}: ${cls.name};\n`;
    });
    code += '};\n';
  }

  return code;
}

