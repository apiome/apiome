/**
 * Python Dataclass Generator Utilities
 *
 * Generates Python dataclasses from class definitions.
 * Supports:
 * - Standard library dataclasses (Python 3.7+)
 * - Type hints
 * - Default values and factories
 * - Frozen (immutable) classes
 * - Post-init validation
 * - Nested objects and arrays
 */

interface DataclassOptions {
  frozen?: boolean;
  slots?: boolean;
  includeValidation?: boolean;
  includeJsonHelpers?: boolean;
}

/**
 * Maps JSON Schema types to Python type hints
 */
function mapTypeToPythonDataclass(propData: any): { type: string; needsImport: Set<string> } {
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
      const itemResult = mapTypeToPythonDataclass(propData.items);
      needsImport.add('List');
      itemResult.needsImport.forEach(imp => needsImport.add(imp));
      return { type: `List[${itemResult.type}]`, needsImport };
    }
    needsImport.add('List');
    return { type: 'List[Any]', needsImport };
  }

  // Handle object types (nested objects)
  if (propData.type === 'object') {
    needsImport.add('Dict');
    return { type: 'Dict[str, Any]', needsImport };
  }

  // Handle basic types with format
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
 * Generates validation code for __post_init__
 */
function generateValidationCode(properties: any[]): string {
  const validations: string[] = [];

  properties.forEach((prop: any) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
    const propName = prop.name;

    // String validations
    if (propData.minLength !== undefined && propData.type === 'string') {
      validations.push(
        `        if self.${propName} is not None and len(self.${propName}) < ${propData.minLength}:\n` +
        `            raise ValueError(f"${propName} must be at least ${propData.minLength} characters")`
      );
    }
    if (propData.maxLength !== undefined && propData.type === 'string') {
      validations.push(
        `        if self.${propName} is not None and len(self.${propName}) > ${propData.maxLength}:\n` +
        `            raise ValueError(f"${propName} must be at most ${propData.maxLength} characters")`
      );
    }

    // Numeric validations
    if (propData.minimum !== undefined && (propData.type === 'integer' || propData.type === 'number')) {
      validations.push(
        `        if self.${propName} is not None and self.${propName} < ${propData.minimum}:\n` +
        `            raise ValueError(f"${propName} must be at least ${propData.minimum}")`
      );
    }
    if (propData.maximum !== undefined && (propData.type === 'integer' || propData.type === 'number')) {
      validations.push(
        `        if self.${propName} is not None and self.${propName} > ${propData.maximum}:\n` +
        `            raise ValueError(f"${propName} must be at most ${propData.maximum}")`
      );
    }

    // Array validations
    if (propData.minItems !== undefined && propData.type === 'array') {
      validations.push(
        `        if self.${propName} is not None and len(self.${propName}) < ${propData.minItems}:\n` +
        `            raise ValueError(f"${propName} must have at least ${propData.minItems} items")`
      );
    }
    if (propData.maxItems !== undefined && propData.type === 'array') {
      validations.push(
        `        if self.${propName} is not None and len(self.${propName}) > ${propData.maxItems}:\n` +
        `            raise ValueError(f"${propName} must have at most ${propData.maxItems} items")`
      );
    }

    // Pattern validation
    if (propData.pattern && propData.type === 'string') {
      validations.push(
        `        if self.${propName} is not None:\n` +
        `            import re\n` +
        `            if not re.match(r"${propData.pattern.replace(/"/g, '\\"')}", self.${propName}):\n` +
        `                raise ValueError(f"${propName} does not match required pattern")`
      );
    }
  });

  if (validations.length === 0) {
    return '';
  }

  return `\n    def __post_init__(self):\n${validations.join('\n')}\n`;
}

/**
 * Generates Python dataclass code from class definitions
 */
export function generatePythonDataclasses(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    frozen?: boolean;
    slots?: boolean;
    includeValidation?: boolean;
    includeJsonHelpers?: boolean;
  }
): string {
  const globalImports = new Set<string>(['Optional', 'Any']);
  const dataclassParams: string[] = [];

  if (options?.frozen) dataclassParams.push('frozen=True');
  if (options?.slots) dataclassParams.push('slots=True');

  // Pre-scan for imports
  classes.forEach((cls) => {
    (cls.properties || []).forEach((prop: any) => {
      const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
      const typeResult = mapTypeToPythonDataclass(propData);
      typeResult.needsImport.forEach(imp => globalImports.add(imp));
    });
  });

  // Build header
  let code = '"""\n';
  code += `${options?.projectName || 'Data Classes'}\n`;
  if (options?.version) code += `Version: ${options.version}\n`;
  if (options?.description) code += `\n${options.description}\n`;
  code += '\nGenerated by Objectified Studio using Python Dataclasses\n';
  code += '"""\n\n';

  // Imports
  code += 'from dataclasses import dataclass';
  if (options?.includeJsonHelpers) {
    code += ', field, asdict';
  }
  code += '\n';

  // Typing imports
  const typingImports = Array.from(globalImports).filter(imp =>
    ['Optional', 'Any', 'List', 'Dict', 'Literal'].includes(imp)
  );
  if (typingImports.length > 0) {
    code += `from typing import ${typingImports.join(', ')}\n`;
  }

  // Date/time imports
  if (globalImports.has('date') || globalImports.has('datetime')) {
    const dateImports = [];
    if (globalImports.has('datetime')) dateImports.push('datetime');
    if (globalImports.has('date')) dateImports.push('date');
    code += `from datetime import ${dateImports.join(', ')}\n`;
  }

  // UUID import
  if (globalImports.has('UUID')) {
    code += 'from uuid import UUID\n';
  }

  code += '\n\n';

  // Generate each class
  classes.forEach((cls, index) => {
    if (index > 0) code += '\n\n';

    const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : (cls.schema || {});

    // Class header with decorator
    const decoratorParams = dataclassParams.length > 0 ? `(${dataclassParams.join(', ')})` : '';
    code += `@dataclass${decoratorParams}\n`;
    code += `class ${cls.name}:\n`;

    // Class docstring
    if (cls.description || schema.description) {
      code += `    """${cls.description || schema.description}"""\n\n`;
    }

    // Generate fields
    if (!cls.properties || cls.properties.length === 0) {
      code += '    pass\n';
    } else {
      cls.properties.forEach((prop: any) => {
        const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
        const typeResult = mapTypeToPythonDataclass(propData);
        const isOptional = !propData.required;
        const pythonType = isOptional ? `Optional[${typeResult.type}]` : typeResult.type;

        // Field definition
        code += `    ${prop.name}: ${pythonType}`;

        // Default value
        if (isOptional) {
          code += ' = None';
        } else if (propData.default !== undefined) {
          if (typeof propData.default === 'string') {
            code += ` = "${propData.default}"`;
          } else if (Array.isArray(propData.default)) {
            code += ` = field(default_factory=list)`;
          } else if (typeof propData.default === 'object') {
            code += ` = field(default_factory=dict)`;
          } else {
            code += ` = ${propData.default}`;
          }
        }

        // Comment with description and constraints
        const comments: string[] = [];
        if (prop.description || propData.description) {
          comments.push(prop.description || propData.description);
        }
        if (propData.minLength || propData.maxLength) {
          comments.push(`Length: ${propData.minLength || 0}-${propData.maxLength || '∞'}`);
        }
        if (propData.minimum !== undefined || propData.maximum !== undefined) {
          comments.push(`Range: ${propData.minimum || '-∞'} to ${propData.maximum || '∞'}`);
        }
        if (comments.length > 0) {
          code += `  # ${comments.join(', ')}`;
        }

        code += '\n';
      });

      // Add __post_init__ for validation if requested
      if (options?.includeValidation) {
        const validationCode = generateValidationCode(cls.properties);
        if (validationCode) {
          code += validationCode;
        }
      }
    }

    // Add JSON helper methods if requested
    if (options?.includeJsonHelpers) {
      code += '\n    def to_dict(self) -> dict:\n';
      code += '        """Convert to dictionary"""\n';
      code += '        return asdict(self)\n';
      code += '\n    @classmethod\n';
      code += '    def from_dict(cls, data: dict):\n';
      code += '        """Create from dictionary"""\n';
      code += '        return cls(**data)\n';
    }
  });

  return code;
}

