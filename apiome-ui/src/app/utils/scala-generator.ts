/**
 * Scala Case Class Generator Utilities
 *
 * Generates Scala case classes from class definitions.
 *
 * Features:
 * - Case classes for immutable data
 * - Option types for nullable fields
 * - Sealed traits for enumerations
 * - Companion objects with JSON codecs
 * - Play JSON or Circe codec support
 * - Proper type mappings
 * - ScalaDoc comments
 */

export type ScalaCodecLibrary = 'play-json' | 'circe' | 'none';

interface ScalaGenerationOptions {
  codecLibrary: ScalaCodecLibrary;
  includeCompanionObjects?: boolean;
  includeValidation?: boolean;
  packageName?: string;
}

/**
 * Maps JSON Schema types to Scala types
 */
function mapTypeToScala(propData: any): string {
  // Handle enum types (will be converted to sealed trait)
  if (propData.enum && Array.isArray(propData.enum)) {
    return 'String'; // Enums handled separately
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
      const itemType = mapTypeToScala(propData.items);
      return `List[${itemType}]`;
    }
    return 'List[Any]';
  }

  // Handle object types (Map)
  if (propData.type === 'object') {
    return 'Map[String, Any]';
  }

  // Handle basic types with format
  switch (propData.type) {
    case 'string':
      if (propData.format === 'date' || propData.format === 'date-time') {
        return 'java.time.Instant';
      }
      if (propData.format === 'uuid') {
        return 'java.util.UUID';
      }
      if (propData.format === 'email' || propData.format === 'uri') {
        return 'String';
      }
      return 'String';
    case 'integer':
      return 'Int';
    case 'number':
      return 'Double';
    case 'boolean':
      return 'Boolean';
    case 'null':
      return 'Option[String]';
    default:
      return 'String';
  }
}

/**
 * Convert name to PascalCase for Scala classes
 */
function toPascalCase(name: string): string {
  return name
    .split(/[-_\s]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join('');
}

/**
 * Convert name to camelCase for Scala fields
 */
function toCamelCase(name: string): string {
  const pascal = toPascalCase(name);
  return pascal.charAt(0).toLowerCase() + pascal.slice(1);
}

/**
 * Generate Scala sealed trait for enum
 */
function generateEnum(className: string, propName: string, enumValues: any[]): string {
  const enumName = `${className}${propName}`; // Use original names
  let scala = `sealed trait ${enumName}\n`;
  scala += `object ${enumName} {\n`;

  enumValues.forEach((value) => {
    const caseName = String(value); // Use original enum value
    scala += `  case object ${caseName} extends ${enumName}\n`;
  });

  scala += `\n  val values: Set[${enumName}] = Set(${enumValues.map(v => String(v)).join(', ')})\n`;
  scala += `\n  def fromString(s: String): Option[${enumName}] = s match {\n`;
  enumValues.forEach((value) => {
    const caseName = String(value);
    scala += `    case "${value}" => Some(${caseName})\n`;
  });
  scala += `    case _ => None\n`;
  scala += `  }\n`;
  scala += `}\n`;

  return scala;
}

/**
 * Generate Play JSON Format for case class
 */
function generatePlayJsonFormat(className: string): string {
  // Use lowercase version of class name for implicit val name
  const formatName = className.charAt(0).toLowerCase() + className.slice(1);
  return `  implicit val ${formatName}Format: Format[${className}] = Json.format[${className}]\n`;
}

/**
 * Generate Circe Encoder/Decoder for case class
 */
function generateCirceCodec(className: string): string {
  // Use lowercase version of class name for implicit val names
  const codecName = className.charAt(0).toLowerCase() + className.slice(1);
  let scala = `  implicit val ${codecName}Encoder: Encoder[${className}] = deriveEncoder[${className}]\n`;
  scala += `  implicit val ${codecName}Decoder: Decoder[${className}] = deriveDecoder[${className}]\n`;
  return scala;
}

/**
 * Generate Scala case class from a class definition
 */
function generateCaseClass(
  cls: any,
  options: ScalaGenerationOptions,
  generatedEnums: Set<string>
): { caseClass: string; enums: string[] } {
  const className = cls.name; // Use original name from database
  const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : (cls.schema || {});
  const topLevelProperties = (cls.properties || []).filter((prop: any) => !prop.parent_id);
  const required = schema.required || [];
  const enumDefinitions: string[] = [];

  let scala = '';

  // Add ScalaDoc if available
  if (cls.description || schema.description) {
    const description = cls.description || schema.description;
    scala += `/**\n * ${description}\n */\n`;
  }

  scala += `case class ${className}(\n`;

  // Generate fields
  const fields: string[] = [];
  topLevelProperties.forEach((prop: any) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {});
    const fieldName = prop.name; // Use original name from database
    const isRequired = required.includes(prop.name) || propData.required;

    // Generate enum if property has enum values
    if (propData.enum && Array.isArray(propData.enum)) {
      const enumName = `${className}${prop.name}`;
      if (!generatedEnums.has(enumName)) {
        enumDefinitions.push(generateEnum(className, prop.name, propData.enum));
        generatedEnums.add(enumName);
      }
    }

    // Add field ScalaDoc
    let fieldDef = '';
    if (prop.description || propData.description) {
      const description = prop.description || propData.description;
      fieldDef += `  /** ${description} */\n`;
    }

    let fieldType = mapTypeToScala(propData);

    // Use enum type if property has enum
    if (propData.enum && Array.isArray(propData.enum)) {
      fieldType = `${className}${prop.name}`;
    }

    // Wrap in Option if not required
    if (!isRequired) {
      fieldType = `Option[${fieldType}]`;
    }

    fieldDef += `  ${fieldName}: ${fieldType}`;
    fields.push(fieldDef);
  });

  if (fields.length === 0) {
    scala += `  // No fields defined\n`;
  } else {
    scala += fields.join(',\n');
    scala += '\n';
  }

  scala += `)\n`;

  // Generate companion object only if codec library is selected
  if (options.includeCompanionObjects && options.codecLibrary !== 'none') {
    scala += `\nobject ${className} {\n`;

    if (options.codecLibrary === 'play-json') {
      scala += generatePlayJsonFormat(className);
    } else if (options.codecLibrary === 'circe') {
      scala += generateCirceCodec(className);
    }

    scala += `}\n`;
  }

  return { caseClass: scala, enums: enumDefinitions };
}

/**
 * Generate imports based on options
 */
function generateImports(options: ScalaGenerationOptions): string {
  let imports = '';

  if (options.codecLibrary === 'play-json') {
    imports += 'import play.api.libs.json._\n';
  } else if (options.codecLibrary === 'circe') {
    imports += 'import io.circe._\n';
    imports += 'import io.circe.generic.semiauto._\n';
  }

  imports += 'import java.time.Instant\n';
  imports += 'import java.util.UUID\n';

  return imports;
}

/**
 * Main function to generate Scala case classes from classes
 */
export function generateScala(
  classes: any[],
  codecLibrary: ScalaCodecLibrary = 'play-json',
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    packageName?: string;
    includeCompanionObjects?: boolean;
  }
): string {
  const fullOptions: ScalaGenerationOptions = {
    codecLibrary,
    includeCompanionObjects: options?.includeCompanionObjects !== false,
    includeValidation: false,
    packageName: options?.packageName || 'com.example.models',
  };

  if (!classes || classes.length === 0) {
    return `// No classes defined\n// Add classes to the canvas to generate Scala case classes`;
  }

  let scala = '';

  // Header comment
  scala += `/**\n`;
  scala += ` * Scala Case Classes Generated from Apiome\n`;
  scala += ` * Project: ${options?.projectName || 'API'}\n`;
  scala += ` * Version: ${options?.version || '1.0'}\n`;
  scala += ` * Generated: ${new Date().toISOString()}\n`;
  scala += ` */\n\n`;

  // Package declaration
  scala += `package ${fullOptions.packageName}\n\n`;

  // Imports
  scala += generateImports(fullOptions);
  scala += '\n';

  // Generate enums and case classes
  const generatedEnums = new Set<string>();
  const caseClassDefinitions: string[] = [];
  const allEnums: string[] = [];

  classes.forEach((cls) => {
    const { caseClass, enums } = generateCaseClass(cls, fullOptions, generatedEnums);
    caseClassDefinitions.push(caseClass);
    allEnums.push(...enums);
  });

  // Add enums first
  if (allEnums.length > 0) {
    scala += '// Enumerations\n';
    allEnums.forEach(enumDef => {
      scala += enumDef + '\n';
    });
  }

  // Add case classes
  scala += '// Case Classes\n';
  caseClassDefinitions.forEach(classDef => {
    scala += classDef + '\n';
  });

  return scala;
}

