/**
 * Java POJO Generator Utilities
 *
 * Generates Java Plain Old Java Objects (POJOs) from class definitions.
 * Supports:
 * - Standard Java beans with getters/setters
 * - Builder pattern
 * - Validation annotations (Jakarta/Javax)
 * - Jackson annotations for JSON
 * - Lombok annotations
 * - Record classes (Java 14+)
 * - Field constraints and validation
 */

interface JavaPojoOptions {
  useBuilder?: boolean;
  useLombok?: boolean;
  useRecords?: boolean;
  includeValidation?: boolean;
  validationProvider?: 'jakarta' | 'javax';
  includeJackson?: boolean;
}

/**
 * Maps JSON Schema types to Java types
 */
function mapTypeToJava(propData: any): { type: string; needsImport: Set<string> } {
  const needsImport = new Set<string>();

  // Handle enum types
  if (propData.enum && Array.isArray(propData.enum)) {
    // Enums would need to be generated separately
    return { type: 'String', needsImport };
  }

  // Handle $ref (references to other classes)
  if (propData.$ref) {
    const refParts = propData.$ref.split('/');
    const refClassName = refParts[refParts.length - 1];
    return { type: refClassName, needsImport };
  }

  // Handle array types
  if (propData.type === 'array') {
    needsImport.add('java.util.List');
    if (propData.items) {
      const itemResult = mapTypeToJava(propData.items);
      itemResult.needsImport.forEach(imp => needsImport.add(imp));
      return { type: `List<${itemResult.type}>`, needsImport };
    }
    return { type: 'List<Object>', needsImport };
  }

  // Handle object types (nested objects)
  if (propData.type === 'object') {
    needsImport.add('java.util.Map');
    return { type: 'Map<String, Object>', needsImport };
  }

  // Handle basic types with format
  switch (propData.type) {
    case 'string':
      if (propData.format === 'date') {
        needsImport.add('java.time.LocalDate');
        return { type: 'LocalDate', needsImport };
      }
      if (propData.format === 'date-time') {
        needsImport.add('java.time.OffsetDateTime');
        return { type: 'OffsetDateTime', needsImport };
      }
      if (propData.format === 'uuid') {
        needsImport.add('java.util.UUID');
        return { type: 'UUID', needsImport };
      }
      return { type: 'String', needsImport };
    case 'integer':
      if (propData.format === 'int64') {
        return { type: 'Long', needsImport };
      }
      return { type: 'Integer', needsImport };
    case 'number':
      if (propData.format === 'float') {
        return { type: 'Float', needsImport };
      }
      if (propData.format === 'double') {
        return { type: 'Double', needsImport };
      }
      needsImport.add('java.math.BigDecimal');
      return { type: 'BigDecimal', needsImport };
    case 'boolean':
      return { type: 'Boolean', needsImport };
    default:
      return { type: 'Object', needsImport };
  }
}

/**
 * Generates validation annotations for a field
 */
function generateValidationAnnotations(
  propData: any,
  validationProvider: 'jakarta' | 'javax',
  indent: string = '    '
): string[] {
  const annotations: string[] = [];
  const prefix = validationProvider === 'jakarta' ? 'jakarta' : 'javax';

  // Required field
  if (propData.required) {
    annotations.push(`${indent}@NotNull`);
  }

  // String validations
  if (propData.type === 'string') {
    if (propData.minLength !== undefined || propData.maxLength !== undefined) {
      const min = propData.minLength !== undefined ? propData.minLength : 0;
      const max = propData.maxLength !== undefined ? propData.maxLength : 'Integer.MAX_VALUE';
      annotations.push(`${indent}@Size(min = ${min}, max = ${max})`);
    }
    if (propData.pattern) {
      const escapedPattern = propData.pattern.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
      annotations.push(`${indent}@Pattern(regexp = "${escapedPattern}")`);
    }
    if (propData.format === 'email') {
      annotations.push(`${indent}@Email`);
    }
  }

  // Numeric validations
  if (propData.type === 'integer' || propData.type === 'number') {
    if (propData.minimum !== undefined) {
      annotations.push(`${indent}@Min(${propData.minimum})`);
    }
    if (propData.maximum !== undefined) {
      annotations.push(`${indent}@Max(${propData.maximum})`);
    }
    if (propData.exclusiveMinimum !== undefined) {
      annotations.push(`${indent}@DecimalMin(value = "${propData.exclusiveMinimum}", inclusive = false)`);
    }
    if (propData.exclusiveMaximum !== undefined) {
      annotations.push(`${indent}@DecimalMax(value = "${propData.exclusiveMaximum}", inclusive = false)`);
    }
  }

  // Array validations
  if (propData.type === 'array') {
    if (propData.minItems !== undefined || propData.maxItems !== undefined) {
      const min = propData.minItems !== undefined ? propData.minItems : 0;
      const max = propData.maxItems !== undefined ? propData.maxItems : 'Integer.MAX_VALUE';
      annotations.push(`${indent}@Size(min = ${min}, max = ${max})`);
    }
  }

  return annotations;
}

/**
 * Generates getter method
 */
function generateGetter(propName: string, propType: string, javaFieldName: string): string {
  const methodName = propType === 'Boolean'
    ? `is${propName.charAt(0).toUpperCase()}${propName.slice(1)}`
    : `get${propName.charAt(0).toUpperCase()}${propName.slice(1)}`;

  return `    public ${propType} ${methodName}() {\n        return ${javaFieldName};\n    }\n`;
}

/**
 * Generates setter method
 */
function generateSetter(propName: string, propType: string, javaFieldName: string): string {
  const methodName = `set${propName.charAt(0).toUpperCase()}${propName.slice(1)}`;
  return `    public void ${methodName}(${propType} ${javaFieldName}) {\n        this.${javaFieldName} = ${javaFieldName};\n    }\n`;
}

/**
 * Converts property name to Java field name (camelCase)
 */
function toJavaFieldName(name: string): string {
  // Convert snake_case or kebab-case to camelCase
  return name.replace(/[_-]([a-z])/g, (_, letter) => letter.toUpperCase());
}

/**
 * Converts property name to Java class name (PascalCase)
 */
function toJavaClassName(name: string): string {
  const camelCase = toJavaFieldName(name);
  return camelCase.charAt(0).toUpperCase() + camelCase.slice(1);
}

/**
 * Checks if a property has nested object properties
 */
function hasNestedProperties(propData: any): boolean {
  return propData.type === 'object' && propData.properties && Object.keys(propData.properties).length > 0;
}

/**
 * Checks if array items have nested object properties
 */
function hasNestedArrayItems(propData: any): boolean {
  return propData.type === 'array' &&
         propData.items &&
         propData.items.type === 'object' &&
         propData.items.properties &&
         Object.keys(propData.items.properties).length > 0;
}

/**
 * Generates a complete nested inner class for an object
 */
function generateNestedClass(
  className: string,
  properties: any,
  options: {
    useLombok: boolean;
    useRecords: boolean;
    includeValidation: boolean;
    validationProvider: 'jakarta' | 'javax';
    includeJackson: boolean;
    indent: string;
  }
): string {
  let code = '';
  const indent = options.indent;
  const fieldIndent = indent + '    ';

  // Javadoc
  code += `${indent}/**\n`;
  code += `${indent} * ${className} nested class\n`;
  code += `${indent} */\n`;

  // Jackson annotation
  if (options.includeJackson) {
    code += `${indent}@JsonInclude(JsonInclude.Include.NON_NULL)\n`;
  }

  // Lombok annotations
  if (options.useLombok) {
    code += `${indent}@Data\n`;
    code += `${indent}@NoArgsConstructor\n`;
    code += `${indent}@AllArgsConstructor\n`;
  }

  // Convert properties object to array format
  const propArray = Object.entries(properties).map(([key, value]) => ({
    name: key,
    data: value
  }));

  // Collect nested classes within this nested class (recursive nesting)
  const innerNestedClasses = new Map<string, any>();

  // Class declaration
  if (options.useRecords && !options.useLombok) {
    // Record style
    code += `${indent}public static record ${className}(\n`;

    propArray.forEach((prop, propIndex) => {
      const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
      const typeResult = mapTypeToJavaWithNested(propData, prop.name, innerNestedClasses);
      const javaFieldName = toJavaFieldName(prop.name);

      // Validation annotations
      if (options.includeValidation) {
        const validations = generateValidationAnnotations(propData, options.validationProvider, fieldIndent);
        validations.forEach(annotation => code += annotation + '\n');
      }

      // Jackson annotation
      if (options.includeJackson && javaFieldName !== prop.name) {
        code += `${fieldIndent}@JsonProperty("${prop.name}")\n`;
      }

      code += `${fieldIndent}${typeResult.type} ${javaFieldName}`;
      if (propIndex < propArray.length - 1) code += ',';
      code += '\n';
    });

    code += `${indent}) {\n`;

    // Generate nested classes inside this record (recursive)
    if (innerNestedClasses.size > 0) {
      code += '\n';
      innerNestedClasses.forEach((nestedProps, nestedClassName) => {
        code += generateNestedClass(nestedClassName, nestedProps, {
          ...options,
          indent: indent + '    '
        });
      });
    }

    code += `${indent}}\n`;
  } else {
    // Regular class style
    code += `${indent}public static class ${className} {\n\n`;

    // Fields
    propArray.forEach((prop) => {
      const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
      const typeResult = mapTypeToJavaWithNested(propData, prop.name, innerNestedClasses);
      const javaFieldName = toJavaFieldName(prop.name);

      // Validation annotations
      if (options.includeValidation && !options.useLombok) {
        const validations = generateValidationAnnotations(propData, options.validationProvider, fieldIndent);
        validations.forEach(annotation => code += annotation + '\n');
      }

      // Jackson annotation
      if (options.includeJackson && javaFieldName !== prop.name) {
        code += `${fieldIndent}@JsonProperty("${prop.name}")\n`;
      }

      // Field declaration
      code += `${fieldIndent}private ${typeResult.type} ${javaFieldName};\n\n`;
    });

    // Generate getters and setters if not using Lombok
    if (!options.useLombok) {
      // Build property type map with nested types
      const propertyTypes = new Map<string, string>();
      propArray.forEach((prop) => {
        const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
        const tempNested = new Map<string, any>();
        const typeResult = mapTypeToJavaWithNested(propData, prop.name, tempNested);
        propertyTypes.set(prop.name, typeResult.type);
      });

      propArray.forEach((prop) => {
        const javaFieldName = toJavaFieldName(prop.name);
        const propType = propertyTypes.get(prop.name) || 'Object';

        // Getter
        const getterPrefix = propType === 'Boolean' ? 'is' : 'get';
        const methodName = getterPrefix + prop.name.charAt(0).toUpperCase() + toJavaFieldName(prop.name).slice(1);
        code += `${fieldIndent}public ${propType} ${methodName}() {\n`;
        code += `${fieldIndent}    return ${javaFieldName};\n`;
        code += `${fieldIndent}}\n\n`;

        // Setter
        const setterName = 'set' + prop.name.charAt(0).toUpperCase() + toJavaFieldName(prop.name).slice(1);
        code += `${fieldIndent}public void ${setterName}(${propType} ${javaFieldName}) {\n`;
        code += `${fieldIndent}    this.${javaFieldName} = ${javaFieldName};\n`;
        code += `${fieldIndent}}\n\n`;
      });
    }

    // Generate recursive nested classes
    if (innerNestedClasses.size > 0) {
      code += '\n';
      innerNestedClasses.forEach((nestedProps, nestedClassName) => {
        code += generateNestedClass(nestedClassName, nestedProps, {
          ...options,
          indent: indent + '    '
        });
      });
    }

    code += `${indent}}\n`;
  }

  code += '\n';
  return code;
}

/**
 * Maps type for nested objects, returning inner class name if needed
 */
function mapTypeToJavaWithNested(
  propData: any,
  propName: string,
  nestedClasses: Map<string, any>
): { type: string; needsImport: Set<string> } {
  const needsImport = new Set<string>();

  // Check for nested object with properties
  if (hasNestedProperties(propData)) {
    const innerClassName = toJavaClassName(propName);
    nestedClasses.set(innerClassName, propData.properties);
    return { type: innerClassName, needsImport };
  }

  // Check for array of nested objects
  if (hasNestedArrayItems(propData)) {
    const innerClassName = toJavaClassName(propName) + 'Item';
    nestedClasses.set(innerClassName, propData.items.properties);
    needsImport.add('java.util.List');
    return { type: `List<${innerClassName}>`, needsImport };
  }

  // Fall back to normal type mapping
  return mapTypeToJava(propData);
}

/**
 * Generates Java POJO classes
 */
export function generateJavaPojos(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    packageName?: string;
    useBuilder?: boolean;
    useLombok?: boolean;
    useRecords?: boolean;
    includeValidation?: boolean;
    validationProvider?: 'jakarta' | 'javax';
    includeJackson?: boolean;
  }
): string {
  const packageName = options?.packageName || 'com.example.models';
  const useLombok = options?.useLombok || false;
  const useRecords = options?.useRecords || false;
  const useBuilder = options?.useBuilder || false;
  const includeValidation = options?.includeValidation || false;
  const validationProvider = options?.validationProvider || 'jakarta';
  const includeJackson = options?.includeJackson || true;

  const globalImports = new Set<string>();
  const validationImports = new Set<string>();

  // Pre-scan for imports
  classes.forEach((cls) => {
    (cls.properties || []).forEach((prop: any) => {
      const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
      const typeResult = mapTypeToJava(propData);
      typeResult.needsImport.forEach(imp => {
        if (imp.startsWith('java.') || imp.startsWith('javax.') || imp.startsWith('jakarta.')) {
          globalImports.add(imp);
        }
      });

      // Check for validation annotations
      if (includeValidation) {
        if (propData.required) validationImports.add('NotNull');
        if (propData.minLength !== undefined || propData.maxLength !== undefined ||
            propData.minItems !== undefined || propData.maxItems !== undefined) {
          validationImports.add('Size');
        }
        if (propData.pattern) validationImports.add('Pattern');
        if (propData.format === 'email') validationImports.add('Email');
        if (propData.minimum !== undefined) validationImports.add('Min');
        if (propData.maximum !== undefined) validationImports.add('Max');
        if (propData.exclusiveMinimum !== undefined) validationImports.add('DecimalMin');
        if (propData.exclusiveMaximum !== undefined) validationImports.add('DecimalMax');
      }
    });
  });

  // Build code
  let code = '/**\n';
  code += ` * ${options?.projectName || 'Data Objects'}\n`;
  if (options?.version) code += ` * Version: ${options.version}\n`;
  if (options?.description) code += ` *\n * ${options.description}\n`;
  code += ' *\n * Generated by Apiome Studio\n';
  code += ' */\n';
  code += `package ${packageName};\n\n`;

  // Standard imports
  const sortedImports = Array.from(globalImports).sort();
  if (sortedImports.length > 0) {
    sortedImports.forEach(imp => {
      code += `import ${imp};\n`;
    });
    code += '\n';
  }

  // Validation imports
  if (includeValidation && validationImports.size > 0) {
    const validationPackage = validationProvider === 'jakarta'
      ? 'jakarta.validation.constraints'
      : 'javax.validation.constraints';
    Array.from(validationImports).sort().forEach(imp => {
      code += `import ${validationPackage}.${imp};\n`;
    });
    code += '\n';
  }

  // Jackson imports
  if (includeJackson) {
    code += 'import com.fasterxml.jackson.annotation.JsonProperty;\n';
    code += 'import com.fasterxml.jackson.annotation.JsonInclude;\n';
    code += '\n';
  }

  // Lombok imports
  if (useLombok) {
    code += 'import lombok.Data;\n';
    if (useBuilder) code += 'import lombok.Builder;\n';
    code += 'import lombok.NoArgsConstructor;\n';
    code += 'import lombok.AllArgsConstructor;\n';
    code += '\n';
  }

  // Generate each class
  classes.forEach((cls, index) => {
    if (index > 0) code += '\n';

    const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : (cls.schema || {});
    const className = cls.name;

    // Javadoc
    code += '/**\n';
    code += ` * ${cls.description || schema.description || className}\n`;
    code += ' */\n';

    // Jackson annotation
    if (includeJackson) {
      code += '@JsonInclude(JsonInclude.Include.NON_NULL)\n';
    }

    // Lombok annotations
    if (useLombok) {
      code += '@Data\n';
      if (useBuilder) code += '@Builder\n';
      code += '@NoArgsConstructor\n';
      code += '@AllArgsConstructor\n';
    }

    // Collect nested classes for this class
    const nestedClasses = new Map<string, any>();

    // Class declaration
    if (useRecords && !useLombok) {
      // Java 14+ Record
      code += `public record ${className}(\n`;

      if (cls.properties && cls.properties.length > 0) {
        cls.properties.forEach((prop: any, propIndex: number) => {
          const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
          const typeResult = mapTypeToJavaWithNested(propData, prop.name, nestedClasses);
          const javaFieldName = toJavaFieldName(prop.name);

          // Validation annotations (in compact form for records)
          if (includeValidation) {
            const validations = generateValidationAnnotations(propData, validationProvider, '    ');
            validations.forEach(annotation => code += annotation + '\n');
          }

          // Jackson annotation
          if (includeJackson && javaFieldName !== prop.name) {
            code += `    @JsonProperty("${prop.name}")\n`;
          }

          code += `    ${typeResult.type} ${javaFieldName}`;
          if (propIndex < cls.properties.length - 1) code += ',';
          code += '\n';
        });
      }

      code += ') {\n';

      // Generate nested classes inside record
      if (nestedClasses.size > 0) {
        code += '\n';
        nestedClasses.forEach((nestedProps, nestedClassName) => {
          code += generateNestedClass(nestedClassName, nestedProps, {
            useLombok,
            useRecords,
            includeValidation,
            validationProvider,
            includeJackson,
            indent: '    '
          });
        });
      }

      code += '}\n';
    } else {
      // Regular class
      code += `public class ${className} {\n\n`;

      if (!cls.properties || cls.properties.length === 0) {
        code += '    // No properties defined\n';
      } else {
        // Fields
        cls.properties.forEach((prop: any) => {
          const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
          const typeResult = mapTypeToJavaWithNested(propData, prop.name, nestedClasses);
          const javaFieldName = toJavaFieldName(prop.name);

          // Validation annotations
          if (includeValidation && !useLombok) {
            const validations = generateValidationAnnotations(propData, validationProvider);
            validations.forEach(annotation => code += annotation + '\n');
          }

          // Jackson annotation
          if (includeJackson && javaFieldName !== prop.name) {
            code += `    @JsonProperty("${prop.name}")\n`;
          }

          // Field declaration
          code += `    private ${typeResult.type} ${javaFieldName};`;

          // Inline comment
          if (prop.description || propData.description) {
            code += ` // ${prop.description || propData.description}`;
          }
          code += '\n\n';
        });

        // Generate getters and setters if not using Lombok
        if (!useLombok) {
          // Need to regenerate types with nested detection for getters/setters
          const propertyTypes = new Map<string, string>();
          cls.properties.forEach((prop: any) => {
            const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
            const tempNested = new Map<string, any>();
            const typeResult = mapTypeToJavaWithNested(propData, prop.name, tempNested);
            propertyTypes.set(prop.name, typeResult.type);
          });

          cls.properties.forEach((prop: any) => {
            const javaFieldName = toJavaFieldName(prop.name);
            const propType = propertyTypes.get(prop.name) || 'Object';

            code += generateGetter(prop.name, propType, javaFieldName);
            code += '\n';
            code += generateSetter(prop.name, propType, javaFieldName);
            code += '\n';
          });

          // toString method
          code += '    @Override\n';
          code += '    public String toString() {\n';
          code += `        return "${className}{" +\n`;
          cls.properties.forEach((prop: any, idx: number) => {
            const javaFieldName = toJavaFieldName(prop.name);
            const comma = idx < cls.properties.length - 1 ? ' + ", " +' : ' +';
            code += `                "${javaFieldName}=" + ${javaFieldName}${comma}\n`;
          });
          code += '                "}";\n';
          code += '    }\n';
        }
      }

      // Generate nested inner classes
      if (nestedClasses.size > 0) {
        code += '\n';
        nestedClasses.forEach((nestedProps, nestedClassName) => {
          code += generateNestedClass(nestedClassName, nestedProps, {
            useLombok,
            useRecords,
            includeValidation,
            validationProvider,
            includeJackson,
            indent: '    '
          });
        });
      }

      code += '}\n';
    }
  });

  return code;
}

