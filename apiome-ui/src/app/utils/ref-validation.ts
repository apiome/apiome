/**
 * Schema $ref Validation Utilities
 *
 * Validates that $ref values in OpenAPI/JSON Schema follow the correct format
 * and reference complete schemas, not individual properties.
 *
 * Part of Ticket #818 implementation.
 */

export interface RefValidationResult {
  valid: boolean;
  errors: RefValidationError[];
}

export interface RefValidationError {
  path: string;
  ref: string;
  message: string;
}

/**
 * Validates that a $ref string follows the correct format
 * @param ref - The $ref string to validate
 * @returns true if valid, false otherwise
 */
export function isValidSchemaRef(ref: string): boolean {
  if (!ref || typeof ref !== 'string') {
    return false;
  }

  // Must start with #/components/schemas/ (OpenAPI) or #/$defs/ (JSON Schema)
  const hasValidPrefix = ref.startsWith('#/components/schemas/') || ref.startsWith('#/$defs/');
  if (!hasValidPrefix) {
    return false;
  }

  // Must not contain /properties/ (indicates property-level reference)
  if (ref.includes('/properties/')) {
    return false;
  }

  // Must not contain #/properties/ (alternate invalid pattern)
  if (ref.includes('#/properties/')) {
    return false;
  }

  // Should match pattern: #/components/schemas/ClassName or #/$defs/ClassName
  // ClassName should be PascalCase (starts with uppercase)
  const openApiPattern = /^#\/components\/schemas\/[A-Z][a-zA-Z0-9]*$/;
  const jsonSchemaPattern = /^#\/\$defs\/[A-Z][a-zA-Z0-9]*$/;

  return openApiPattern.test(ref) || jsonSchemaPattern.test(ref);
}

/**
 * Recursively validates all $ref values in a schema object
 * @param schema - The schema object to validate
 * @param path - Current path in the object (for error reporting)
 * @returns Validation result with any errors found
 */
export function validateSchemaRefs(
  schema: any,
  path: string = 'root'
): RefValidationResult {
  const errors: RefValidationError[] = [];

  const traverse = (obj: any, currentPath: string) => {
    if (!obj || typeof obj !== 'object') {
      return;
    }

    // Check if this object has a $ref property
    if (obj.$ref && typeof obj.$ref === 'string') {
      if (!isValidSchemaRef(obj.$ref)) {
        errors.push({
          path: currentPath,
          ref: obj.$ref,
          message: determineErrorMessage(obj.$ref)
        });
      }
    }

    // Recursively check all properties
    if (Array.isArray(obj)) {
      obj.forEach((item, index) => {
        traverse(item, `${currentPath}[${index}]`);
      });
    } else {
      Object.keys(obj).forEach(key => {
        if (typeof obj[key] === 'object' && obj[key] !== null) {
          traverse(obj[key], `${currentPath}.${key}`);
        }
      });
    }
  };

  traverse(schema, path);

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Determines the appropriate error message for an invalid $ref
 */
function determineErrorMessage(ref: string): string {
  if (ref.includes('/properties/')) {
    return `Invalid $ref: References individual property instead of complete schema. Use "#/components/schemas/ClassName" instead.`;
  }

  if (ref.includes('#/properties/')) {
    return `Invalid $ref: Uses property fragment identifier. Use "#/components/schemas/ClassName" instead.`;
  }

  if (!ref.startsWith('#/components/schemas/') && !ref.startsWith('#/$defs/')) {
    return `Invalid $ref: Must start with "#/components/schemas/" (OpenAPI) or "#/$defs/" (JSON Schema).`;
  }

  return `Invalid $ref format: "${ref}". Expected format: "#/components/schemas/ClassName"`;
}

/**
 * Validates an OpenAPI specification's schemas section
 * @param openApiDoc - The OpenAPI document to validate
 * @returns Validation result
 */
export function validateOpenAPISchemas(openApiDoc: any): RefValidationResult {
  if (!openApiDoc?.components?.schemas) {
    return {
      valid: true,
      errors: []
    };
  }

  const allErrors: RefValidationError[] = [];

  // Validate each schema in components/schemas
  Object.keys(openApiDoc.components.schemas).forEach(schemaName => {
    const schema = openApiDoc.components.schemas[schemaName];
    const result = validateSchemaRefs(schema, `components.schemas.${schemaName}`);

    if (!result.valid) {
      allErrors.push(...result.errors);
    }
  });

  return {
    valid: allErrors.length === 0,
    errors: allErrors
  };
}

/**
 * Formats validation errors for display
 * @param errors - Array of validation errors
 * @returns Formatted error string
 */
export function formatValidationErrors(errors: RefValidationError[]): string {
  if (errors.length === 0) {
    return 'No errors found.';
  }

  const lines = [
    `Found ${errors.length} $ref validation error(s):`,
    ''
  ];

  errors.forEach((error, index) => {
    lines.push(`${index + 1}. ${error.path}`);
    lines.push(`   $ref: ${error.ref}`);
    lines.push(`   ${error.message}`);
    lines.push('');
  });

  return lines.join('\n');
}

/**
 * Extracts all $ref values from a schema (for debugging/analysis)
 * @param schema - Schema object to analyze
 * @returns Array of all $ref values found
 */
export function extractAllRefs(schema: any): string[] {
  const refs: string[] = [];

  const traverse = (obj: any) => {
    if (!obj || typeof obj !== 'object') {
      return;
    }

    if (obj.$ref && typeof obj.$ref === 'string') {
      refs.push(obj.$ref);
    }

    if (Array.isArray(obj)) {
      obj.forEach(item => traverse(item));
    } else {
      Object.values(obj).forEach(value => {
        if (typeof value === 'object' && value !== null) {
          traverse(value);
        }
      });
    }
  };

  traverse(schema);
  return refs;
}

/**
 * Gets statistics about $ref usage in a schema
 * @param schema - Schema object to analyze
 * @returns Statistics object
 */
export function getRefStats(schema: any): {
  total: number;
  valid: number;
  invalid: number;
  uniqueRefs: number;
} {
  const allRefs = extractAllRefs(schema);
  const uniqueRefs = new Set(allRefs);
  const validRefs = allRefs.filter(ref => isValidSchemaRef(ref));

  return {
    total: allRefs.length,
    valid: validRefs.length,
    invalid: allRefs.length - validRefs.length,
    uniqueRefs: uniqueRefs.size
  };
}
