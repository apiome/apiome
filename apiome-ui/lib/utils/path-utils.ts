/**
 * Convert a string to proper camelCase, handling snake_case, kebab-case, and preserving existing camelCase
 * e.g., "user-id" -> "userId"
 * e.g., "user_id" -> "userId"
 * e.g., "userId" -> "userId"
 * e.g., "user-name-id" -> "userNameId"
 */
function toCamelCase(str: string): string {
  // Remove any non-alphanumeric characters and split into words
  // This handles: snake_case, kebab-case, and spaces
  const parts = str.split(/[-_\s]+/);

  if (parts.length === 0) return '';

  // If only one part and it already has mixed case (camelCase), preserve it
  if (parts.length === 1) {
    const part = parts[0];
    if (!part) return '';

    // If it has mixed case (likely already camelCase), keep it but ensure first letter is lowercase
    if (part !== part.toLowerCase() && part !== part.toUpperCase()) {
      return part.charAt(0).toLowerCase() + part.slice(1);
    }

    // Otherwise, just return it lowercase
    return part.toLowerCase();
  }

  // First part stays lowercase, rest get capitalized first letter
  return parts.map((part, index) => {
    if (!part) return '';

    // For the first part, keep it lowercase
    if (index === 0) {
      return part.toLowerCase();
    }

    // For subsequent parts, capitalize first letter and keep rest as-is to preserve camelCase
    // But if the part is all lowercase or all uppercase, normalize it
    if (part === part.toLowerCase() || part === part.toUpperCase()) {
      return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
    }

    // If it has mixed case (likely already camelCase), just capitalize first letter
    return part.charAt(0).toUpperCase() + part.slice(1);
  }).join('');
}

/**
 * Convert to PascalCase (camelCase with first letter capitalized)
 */
function toPascalCase(str: string): string {
  const camel = toCamelCase(str);
  if (!camel) return '';
  return camel.charAt(0).toUpperCase() + camel.slice(1);
}

/**
 * Generate an operation ID from path and operation verb
 * e.g., "/api/users" + "GET" = "getApiUsers"
 * e.g., "/user/{userId}" + "GET" = "getUserByUserId"
 * e.g., "/user/{user-id}" + "GET" = "getUserByUserId"
 * e.g., "/user/{user_id}" + "GET" = "getUserByUserId"
 * e.g., "/user/{userId}/{tenantId}" + "GET" = "getUserByUserIdAndTenantId"
 */
export function generateOperationId(pathname: string, operation: string): string {
  // Remove leading/trailing slashes and split by /
  const pathParts = pathname
    .replace(/^\/+|\/+$/g, '')
    .split('/')
    .filter(part => part.length > 0);

  // Separate regular path parts from parameters
  const regularParts: string[] = [];
  const parameterParts: string[] = [];

  pathParts.forEach(part => {
    // Check if this is a path parameter (enclosed in curly braces)
    if (part.startsWith('{') && part.endsWith('}')) {
      // Extract parameter name without braces
      const paramName = part.slice(1, -1);
      parameterParts.push(paramName);
    } else {
      regularParts.push(part);
    }
  });

  // Convert regular path parts to camelCase
  const camelCasePath = regularParts
    .map((part, index) => {
      // Remove special characters
      const cleaned = part.replace(/[^a-zA-Z0-9-_]/g, '');
      // First part lowercase, rest PascalCase
      return index === 0 ? toCamelCase(cleaned) : toPascalCase(cleaned);
    })
    .join('');

  // Convert parameter parts to PascalCase and join with "And"
  let parameterSuffix = '';
  if (parameterParts.length > 0) {
    const pascalCaseParams = parameterParts.map(param => {
      // Remove special characters but keep hyphens and underscores for parsing
      const cleaned = param.replace(/[^a-zA-Z0-9-_]/g, '');
      return toPascalCase(cleaned);
    });

    // Join with "And" between parameters
    parameterSuffix = 'By' + pascalCaseParams.join('And');
  }

  // Build the final operation ID
  const basePath = camelCasePath ? camelCasePath.charAt(0).toUpperCase() + camelCasePath.slice(1) : '';
  const operationVerb = operation.toLowerCase();

  return operationVerb + basePath + parameterSuffix;
}

