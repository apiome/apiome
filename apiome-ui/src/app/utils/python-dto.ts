/**
 * Python DTO Generator Utilities (Pydantic-based)
 *
 * Generates Pydantic model DTOs from class definitions.
 * Supports:
 * - allOf/oneOf/anyOf compositions
 * - Discriminators for inheritance
 * - Enumerations
 * - Regex patterns
 * - Nested objects and arrays
 * - Field constraints and validation
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
 * Maps JSON Schema types to Python type hints with Pydantic support
 */
function mapTypeToPython(propData: any, className?: string): { type: string; needsImport: Set<string> } {
  const needsImport = new Set<string>();

  // Handle enum types
  if (propData.enum && Array.isArray(propData.enum)) {
    needsImport.add('Literal');
    const enumValues = propData.enum.map((v: any) =>
      typeof v === 'string' ? `"${v}"` : v
    ).join(', ');
    return { type: `Literal[${enumValues}]`, needsImport };
  }

  // Handle $ref (references to other classes)
  if (propData.$ref) {
    const refParts = propData.$ref.split('/');
    const refClassName = refParts[refParts.length - 1];
    return { type: refClassName, needsImport };
  }

  // Handle array types
  if (propData.type === 'array') {
    if (propData.items) {
      const itemResult = mapTypeToPython(propData.items);
      needsImport.add('List');
      itemResult.needsImport.forEach(imp => needsImport.add(imp));
      return { type: `List[${itemResult.type}]`, needsImport };
    }
    needsImport.add('List');
    return { type: 'List[Any]', needsImport };
  }

  // Handle object types (nested objects)
  if (propData.type === 'object') {
    if (propData.properties) {
      return { type: className || 'Dict[str, Any]', needsImport };
    }
    needsImport.add('Dict');
    return { type: 'Dict[str, Any]', needsImport };
  }

  // Handle basic types with format validation
  switch (propData.type) {
    case 'string':
      if (propData.format === 'date') {
        needsImport.add('date');
        return { type: 'date', needsImport };
      }
      if (propData.format === 'date-time') {
        needsImport.add('datetime');
        return { type: 'datetime', needsImport };
      }
      if (propData.format === 'uuid') {
        needsImport.add('UUID');
        return { type: 'UUID', needsImport };
      }
      if (propData.format === 'email') {
        needsImport.add('EmailStr');
        return { type: 'EmailStr', needsImport };
      }
      if (propData.format === 'uri' || propData.format === 'url') {
        needsImport.add('AnyUrl');
        return { type: 'AnyUrl', needsImport };
      }
      return { type: 'str', needsImport };
    case 'integer':
      return { type: 'int', needsImport };
    case 'number':
      return { type: 'float', needsImport };
    case 'boolean':
      return { type: 'bool', needsImport };
    case 'null':
      return { type: 'None', needsImport };
    default:
      return { type: 'Any', needsImport };
  }
}

/**
 * Converts a name to PascalCase for class names
 */
function toPascalCase(name: string): string {
  return name
    .split(/[-_\s]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

/**
 * Converts a name to snake_case for field names
 */
function toSnakeCase(name: string): string {
  return name
    .replace(/([A-Z])/g, '_$1')
    .toLowerCase()
    .replace(/^_/, '');
}

/**
 * Extracts field constraints from property data
 */
function extractConstraints(propData: any): FieldConstraints {
  const constraints: FieldConstraints = {};

  if (propData.pattern) constraints.pattern = propData.pattern;
  if (propData.minLength !== undefined) constraints.minLength = propData.minLength;
  if (propData.maxLength !== undefined) constraints.maxLength = propData.maxLength;
  if (propData.minimum !== undefined) constraints.minimum = propData.minimum;
  if (propData.maximum !== undefined) constraints.maximum = propData.maximum;
  if (propData.minItems !== undefined) constraints.minItems = propData.minItems;
  if (propData.maxItems !== undefined) constraints.maxItems = propData.maxItems;
  if (propData.format) constraints.format = propData.format;
  if (propData.enum) constraints.enum = propData.enum;

  return constraints;
}

/**
 * Generates Pydantic Field() arguments from constraints
 */
function generateFieldArgs(propData: any, isRequired: boolean): string {
  const constraints = extractConstraints(propData);
  const args: string[] = [];

  // Add description
  if (propData.description) {
    args.push(`description="${propData.description.replace(/"/g, '\\"')}"`);
  }

  // Add default value
  if (!isRequired && propData.default === undefined) {
    args.push('default=None');
  } else if (propData.default !== undefined) {
    if (typeof propData.default === 'string') {
      args.push(`default="${propData.default}"`);
    } else if (propData.default === null) {
      args.push('default=None');
    } else {
      args.push(`default=${propData.default}`);
    }
  }

  // Add regex pattern
  if (constraints.pattern) {
    args.push(`pattern=r"${constraints.pattern}"`);
  }

  // String constraints
  if (constraints.minLength !== undefined) {
    args.push(`min_length=${constraints.minLength}`);
  }
  if (constraints.maxLength !== undefined) {
    args.push(`max_length=${constraints.maxLength}`);
  }

  // Numeric constraints
  if (constraints.minimum !== undefined) {
    args.push(`ge=${constraints.minimum}`);
  }
  if (constraints.maximum !== undefined) {
    args.push(`le=${constraints.maximum}`);
  }

  // Array constraints
  if (constraints.minItems !== undefined) {
    args.push(`min_length=${constraints.minItems}`);
  }
  if (constraints.maxItems !== undefined) {
    args.push(`max_length=${constraints.maxItems}`);
  }

  return args.length > 0 ? ` = Field(${args.join(', ')})` : '';
}

/**
 * Generates a Pydantic field with proper type hints and Field() constraints
 */
function generateField(
  prop: any,
  allProperties: any[],
  isRequired: boolean,
  indent: string = '    ',
  globalImports: Set<string>
): { field: string; nestedClasses: string[] } {
  const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : { ...prop.data };
  const fieldName = toSnakeCase(prop.name);
  const nestedClasses: string[] = [];

  // Handle nested object types - check for child properties
  if (propData.type === 'object' && !propData.$ref) {
    const children = allProperties.filter((p: any) => p.parent_id === prop.id);
    if (children.length > 0) {
      const nestedClassName = toPascalCase(prop.name);
      const nestedClass = generateNestedClass(prop, allProperties, nestedClassName, globalImports);
      nestedClasses.push(nestedClass);

      const typeHint = isRequired ? nestedClassName : `Optional[${nestedClassName}]`;
      const fieldArgs = generateFieldArgs(propData, isRequired);

      return {
        field: `${indent}${fieldName}: ${typeHint}${fieldArgs}`,
        nestedClasses
      };
    }
  }

  // Handle array of nested objects - check for child properties
  if (propData.type === 'array' && propData.items?.type === 'object') {
    const children = allProperties.filter((p: any) => p.parent_id === prop.id);
    if (children.length > 0) {
      const nestedClassName = toPascalCase(prop.name.replace(/s$/, '')) + 'Item';
      const nestedClass = generateNestedClassFromChildren(children, allProperties, nestedClassName, globalImports);
      nestedClasses.push(nestedClass);

      globalImports.add('List');
      const typeHint = isRequired ? `List[${nestedClassName}]` : `Optional[List[${nestedClassName}]]`;
      const fieldArgs = generateFieldArgs(propData, isRequired);

      return {
        field: `${indent}${fieldName}: ${typeHint}${fieldArgs}`,
        nestedClasses
      };
    }
  }

  const typeResult = mapTypeToPython(propData, toPascalCase(prop.name));
  typeResult.needsImport.forEach(imp => globalImports.add(imp));

  const typeHint = isRequired ? typeResult.type : `Optional[${typeResult.type}]`;
  const fieldArgs = generateFieldArgs(propData, isRequired);

  return {
    field: `${indent}${fieldName}: ${typeHint}${fieldArgs}`,
    nestedClasses
  };
}

/**
 * Generates a nested Pydantic model from a property with nested properties
 */
function generateNestedClass(
  prop: any,
  allProperties: any[],
  className: string,
  globalImports: Set<string>
): string {
  const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : { ...prop.data };
  const children = allProperties.filter((p: any) => p.parent_id === prop.id);

  let classCode = `class ${className}(BaseModel):\n`;

  if (propData.description) {
    classCode += `    """${propData.description}"""\n`;
  }

  const required = propData.required || [];
  const allNestedClasses: string[] = [];

  if (children.length === 0) {
    classCode += '    pass\n';
  } else {
    children.forEach((child: any) => {
      const isRequired = required.includes(child.name);
      const { field, nestedClasses } = generateField(child, allProperties, isRequired, '    ', globalImports);
      classCode += field + '\n';
      allNestedClasses.push(...nestedClasses);
    });
  }

  // Prepend nested classes
  if (allNestedClasses.length > 0) {
    classCode = allNestedClasses.join('\n\n') + '\n\n' + classCode;
  }

  return classCode;
}

/**
 * Generates a nested Pydantic model from a list of child properties
 */
function generateNestedClassFromChildren(
  children: any[],
  allProperties: any[],
  className: string,
  globalImports: Set<string>
): string {
  let classCode = `class ${className}(BaseModel):\n`;

  const allNestedClasses: string[] = [];

  if (children.length === 0) {
    classCode += '    pass\n';
  } else {
    children.forEach((child: any) => {
      const childData = typeof child.data === 'string' ? JSON.parse(child.data) : child.data;
      const isRequired = childData.required !== false;
      const { field, nestedClasses } = generateField(child, allProperties, isRequired, '    ', globalImports);
      classCode += field + '\n';
      allNestedClasses.push(...nestedClasses);
    });
  }

  // Prepend nested classes
  if (allNestedClasses.length > 0) {
    classCode = allNestedClasses.join('\n\n') + '\n\n' + classCode;
  }

  return classCode;
}

/**
 * Generates a Pydantic model from a class definition with support for compositions
 */
function generateClass(classData: any, globalImports: Set<string>): string {
  const className = classData.name; // Preserve original class name
  const schema = typeof classData.schema === 'string'
    ? JSON.parse(classData.schema)
    : (classData.schema || {});

  const allNestedClasses: string[] = [];
  const topLevelProperties = (classData.properties || []).filter((prop: any) => !prop.parent_id);
  const required = schema.required || [];

  // Handle allOf (inheritance/composition)
  if (schema.allOf && Array.isArray(schema.allOf)) {
    return generateAllOfClass(className, schema, topLevelProperties, classData.properties, globalImports);
  }

  // Handle oneOf (union with discriminator)
  if (schema.oneOf && Array.isArray(schema.oneOf)) {
    globalImports.add('Union');
    return generateOneOfClass(className, schema, topLevelProperties, classData.properties, globalImports);
  }

  // Handle anyOf (union without discriminator)
  if (schema.anyOf && Array.isArray(schema.anyOf)) {
    globalImports.add('Union');
    return generateAnyOfClass(className, schema, topLevelProperties, classData.properties, globalImports);
  }

  // Standard class generation
  let classCode = `class ${className}(BaseModel):\n`;

  // Add docstring if description exists
  if (classData.description || schema.description) {
    const description = classData.description || schema.description;
    classCode += `    """${description}"""\n`;
  }

  // Add discriminator if present
  if (schema.discriminator) {
    const discriminatorField = schema.discriminator.propertyName || 'type';
    classCode += `\n    model_config = ConfigDict(discriminator='${discriminatorField}')\n`;
  }

  if (topLevelProperties.length === 0) {
    classCode += '    pass\n';
  } else {
    topLevelProperties.forEach((prop: any) => {
      const isRequired = required.includes(prop.name);
      const { field, nestedClasses } = generateField(prop, classData.properties || [], isRequired, '    ', globalImports);
      classCode += field + '\n';
      allNestedClasses.push(...nestedClasses);
    });
  }

  // Prepend nested classes
  if (allNestedClasses.length > 0) {
    classCode = allNestedClasses.join('\n\n') + '\n\n' + classCode;
  }

  return classCode;
}

/**
 * Generates a class using allOf composition (inheritance)
 */
function generateAllOfClass(
  className: string,
  schema: any,
  topLevelProperties: any[],
  allProperties: any[],
  globalImports: Set<string>
): string {
  const allNestedClasses: string[] = [];
  const baseClasses: string[] = [];
  const additionalProps: any[] = [];

  // Process allOf array
  schema.allOf.forEach((item: any) => {
    if (item.$ref) {
      // Reference to another class - use as base class
      const refParts = item.$ref.split('/');
      const baseClassName = refParts[refParts.length - 1];
      baseClasses.push(baseClassName);
    } else if (item.properties) {
      // Inline properties - add to this class
      // Note: In real implementation, these would come from class_properties table
    }
  });

  const bases = baseClasses.length > 0 ? baseClasses.join(', ') : 'BaseModel';
  let classCode = `class ${className}(${bases}):\n`;

  if (schema.description) {
    classCode += `    """${schema.description}"""\n`;
  }

  const required = schema.required || [];
  const allProps = [...topLevelProperties, ...additionalProps];

  if (allProps.length === 0) {
    classCode += '    pass\n';
  } else {
    allProps.forEach((prop: any) => {
      const isRequired = required.includes(prop.name);
      const { field, nestedClasses } = generateField(prop, allProperties, isRequired, '    ', globalImports);
      classCode += field + '\n';
      allNestedClasses.push(...nestedClasses);
    });
  }

  if (allNestedClasses.length > 0) {
    classCode = allNestedClasses.join('\n\n') + '\n\n' + classCode;
  }

  return classCode;
}

/**
 * Generates a class using oneOf with discriminator
 */
function generateOneOfClass(
  className: string,
  schema: any,
  topLevelProperties: any[],
  allProperties: any[],
  globalImports: Set<string>
): string {
  const allNestedClasses: string[] = [];
  const unionTypes: string[] = [];

  // Extract discriminator info
  const discriminator = schema.discriminator;
  const discriminatorField = discriminator?.propertyName || 'type';

  // Process oneOf array
  schema.oneOf.forEach((item: any) => {
    if (item.$ref) {
      const refParts = item.$ref.split('/');
      const refClassName = refParts[refParts.length - 1];
      unionTypes.push(refClassName);
    }
  });

  if (unionTypes.length === 0) {
    return `${className} = Any  # oneOf with no valid types`;
  }

  // Create a type alias for the union
  let classCode = `${className} = Union[${unionTypes.join(', ')}]\n`;
  classCode += `# Discriminated union on field: ${discriminatorField}\n`;

  return classCode;
}

/**
 * Generates a class using anyOf (union without discriminator)
 */
function generateAnyOfClass(
  className: string,
  schema: any,
  topLevelProperties: any[],
  allProperties: any[],
  globalImports: Set<string>
): string {
  const unionTypes: string[] = [];

  // Process anyOf array
  schema.anyOf.forEach((item: any) => {
    if (item.$ref) {
      const refParts = item.$ref.split('/');
      const refClassName = refParts[refParts.length - 1];
      unionTypes.push(refClassName);
    } else if (item.type) {
      const typeResult = mapTypeToPython(item);
      typeResult.needsImport.forEach(imp => globalImports.add(imp));
      unionTypes.push(typeResult.type);
    }
  });

  if (unionTypes.length === 0) {
    return `${className} = Any  # anyOf with no valid types`;
  }

  // Create a type alias for the union
  return `${className} = Union[${unionTypes.join(', ')}]\n`;
}

/**
 * Generates Pydantic model DTOs from class definitions
 * @param classes - Array of class data objects with properties
 * @param options - Optional metadata for the generated code
 * @returns Python code as a string
 */
export function generatePythonDTOs(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
  }
): string {
  // Track all imports needed globally
  const globalImports = new Set<string>([
    'Optional',
    'Any',
  ]);

  // Always import Field and ConfigDict from pydantic
  const pydanticImports = new Set<string>(['BaseModel', 'Field', 'ConfigDict']);

  // Pre-scan to determine what imports we need
  classes.forEach((cls) => {
    const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : (cls.schema || {});

    // Check for composition keywords
    if (schema.allOf) globalImports.add('Union');
    if (schema.oneOf) globalImports.add('Union');
    if (schema.anyOf) globalImports.add('Union');

    // Check properties for special types
    (cls.properties || []).forEach((prop: any) => {
      const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;

      // Check for constraints that need Field
      if (propData.pattern || propData.minLength || propData.maxLength ||
          propData.minimum || propData.maximum || propData.minItems || propData.maxItems) {
        // Field is already in pydanticImports
      }

      const typeResult = mapTypeToPython(propData);
      typeResult.needsImport.forEach(imp => {
        if (imp === 'EmailStr' || imp === 'AnyUrl') {
          pydanticImports.add(imp);
        } else if (imp === 'date' || imp === 'datetime') {
          // Will be added to datetime imports
        } else if (imp === 'UUID') {
          // Will be added to uuid imports
        } else {
          globalImports.add(imp);
        }
      });
    });
  });

  // Build imports section
  let code = '"""\n';
  code += `${options?.projectName || 'Data Type Objects'}\n`;
  if (options?.version) {
    code += `Version: ${options.version}\n`;
  }
  if (options?.description) {
    code += `\n${options.description}\n`;
  }
  code += '\nGenerated by Apiome Studio using Pydantic\n';
  code += '"""\n\n';

  // Standard library imports
  const stdImports: string[] = [];

  if (globalImports.has('date') || globalImports.has('datetime')) {
    const dateImports = [];
    if (globalImports.has('datetime')) dateImports.push('datetime');
    if (globalImports.has('date')) dateImports.push('date');
    stdImports.push(`from datetime import ${dateImports.join(', ')}`);
    globalImports.delete('date');
    globalImports.delete('datetime');
  }

  if (globalImports.has('UUID')) {
    stdImports.push('from uuid import UUID');
    globalImports.delete('UUID');
  }

  // Typing imports
  const typingImports = Array.from(globalImports).filter(imp =>
    ['Optional', 'Any', 'Union', 'List', 'Dict', 'Literal'].includes(imp)
  ).sort();

  if (typingImports.length > 0) {
    stdImports.push(`from typing import ${typingImports.join(', ')}`);
  }

  // Pydantic imports
  const pydanticImportList = Array.from(pydanticImports).sort();
  stdImports.push(`from pydantic import ${pydanticImportList.join(', ')}`);

  code += stdImports.join('\n') + '\n\n';

  // Generate classes
  const classDefinitions = classes.map((cls) => generateClass(cls, globalImports));
  code += classDefinitions.join('\n\n');

  return code;
}

