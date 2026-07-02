/**
 * HTTP Status Code Descriptions
 *
 * Provides pre-defined descriptions for all HTTP status codes (RFC 9110, RFC 7231, etc.)
 * Used for auto-populating response descriptions based on status code.
 */

export interface HttpStatusInfo {
  code: string;
  description: string;
  category: 'informational' | 'success' | 'redirection' | 'client_error' | 'server_error';
}

/**
 * Comprehensive map of HTTP status codes to their standard descriptions
 */
export const HTTP_STATUS_CODES: Record<string, HttpStatusInfo> = {
  // 1XX Informational
  '100': { code: '100', description: 'Continue', category: 'informational' },
  '101': { code: '101', description: 'Switching Protocols', category: 'informational' },
  '102': { code: '102', description: 'Processing', category: 'informational' },
  '103': { code: '103', description: 'Early Hints', category: 'informational' },

  // 2XX Success
  '200': { code: '200', description: 'OK', category: 'success' },
  '201': { code: '201', description: 'Created', category: 'success' },
  '202': { code: '202', description: 'Accepted', category: 'success' },
  '203': { code: '203', description: 'Non-Authoritative Information', category: 'success' },
  '204': { code: '204', description: 'No Content', category: 'success' },
  '205': { code: '205', description: 'Reset Content', category: 'success' },
  '206': { code: '206', description: 'Partial Content', category: 'success' },
  '207': { code: '207', description: 'Multi-Status', category: 'success' },
  '208': { code: '208', description: 'Already Reported', category: 'success' },
  '226': { code: '226', description: 'IM Used', category: 'success' },

  // 3XX Redirection
  '300': { code: '300', description: 'Multiple Choices', category: 'redirection' },
  '301': { code: '301', description: 'Moved Permanently', category: 'redirection' },
  '302': { code: '302', description: 'Found', category: 'redirection' },
  '303': { code: '303', description: 'See Other', category: 'redirection' },
  '304': { code: '304', description: 'Not Modified', category: 'redirection' },
  '305': { code: '305', description: 'Use Proxy', category: 'redirection' },
  '307': { code: '307', description: 'Temporary Redirect', category: 'redirection' },
  '308': { code: '308', description: 'Permanent Redirect', category: 'redirection' },

  // 4XX Client Errors
  '400': { code: '400', description: 'Bad Request', category: 'client_error' },
  '401': { code: '401', description: 'Unauthorized', category: 'client_error' },
  '402': { code: '402', description: 'Payment Required', category: 'client_error' },
  '403': { code: '403', description: 'Forbidden', category: 'client_error' },
  '404': { code: '404', description: 'Not Found', category: 'client_error' },
  '405': { code: '405', description: 'Method Not Allowed', category: 'client_error' },
  '406': { code: '406', description: 'Not Acceptable', category: 'client_error' },
  '407': { code: '407', description: 'Proxy Authentication Required', category: 'client_error' },
  '408': { code: '408', description: 'Request Timeout', category: 'client_error' },
  '409': { code: '409', description: 'Conflict', category: 'client_error' },
  '410': { code: '410', description: 'Gone', category: 'client_error' },
  '411': { code: '411', description: 'Length Required', category: 'client_error' },
  '412': { code: '412', description: 'Precondition Failed', category: 'client_error' },
  '413': { code: '413', description: 'Content Too Large', category: 'client_error' },
  '414': { code: '414', description: 'URI Too Long', category: 'client_error' },
  '415': { code: '415', description: 'Unsupported Media Type', category: 'client_error' },
  '416': { code: '416', description: 'Range Not Satisfiable', category: 'client_error' },
  '417': { code: '417', description: 'Expectation Failed', category: 'client_error' },
  '418': { code: '418', description: "I'm a teapot", category: 'client_error' },
  '421': { code: '421', description: 'Misdirected Request', category: 'client_error' },
  '422': { code: '422', description: 'Unprocessable Content', category: 'client_error' },
  '423': { code: '423', description: 'Locked', category: 'client_error' },
  '424': { code: '424', description: 'Failed Dependency', category: 'client_error' },
  '425': { code: '425', description: 'Too Early', category: 'client_error' },
  '426': { code: '426', description: 'Upgrade Required', category: 'client_error' },
  '428': { code: '428', description: 'Precondition Required', category: 'client_error' },
  '429': { code: '429', description: 'Too Many Requests', category: 'client_error' },
  '431': { code: '431', description: 'Request Header Fields Too Large', category: 'client_error' },
  '451': { code: '451', description: 'Unavailable For Legal Reasons', category: 'client_error' },

  // 5XX Server Errors
  '500': { code: '500', description: 'Internal Server Error', category: 'server_error' },
  '501': { code: '501', description: 'Not Implemented', category: 'server_error' },
  '502': { code: '502', description: 'Bad Gateway', category: 'server_error' },
  '503': { code: '503', description: 'Service Unavailable', category: 'server_error' },
  '504': { code: '504', description: 'Gateway Timeout', category: 'server_error' },
  '505': { code: '505', description: 'HTTP Version Not Supported', category: 'server_error' },
  '506': { code: '506', description: 'Variant Also Negotiates', category: 'server_error' },
  '507': { code: '507', description: 'Insufficient Storage', category: 'server_error' },
  '508': { code: '508', description: 'Loop Detected', category: 'server_error' },
  '510': { code: '510', description: 'Not Extended', category: 'server_error' },
  '511': { code: '511', description: 'Network Authentication Required', category: 'server_error' },

  // OpenAPI special codes
  'default': { code: 'default', description: 'Default Response', category: 'server_error' },
  '1XX': { code: '1XX', description: 'Informational Response', category: 'informational' },
  '2XX': { code: '2XX', description: 'Successful Response', category: 'success' },
  '3XX': { code: '3XX', description: 'Redirection Response', category: 'redirection' },
  '4XX': { code: '4XX', description: 'Client Error Response', category: 'client_error' },
  '5XX': { code: '5XX', description: 'Server Error Response', category: 'server_error' },
};

/**
 * Get the standard HTTP description for a status code
 * @param statusCode - The HTTP status code (e.g., '200', '404', 'default')
 * @returns The standard description or empty string if not found
 */
export function getHttpStatusDescription(statusCode: string): string {
  const info = HTTP_STATUS_CODES[statusCode];
  if (info) {
    return info.description;
  }

  // Handle wildcard patterns
  const firstChar = statusCode.charAt(0);
  const wildcardCode = `${firstChar}XX`;
  const wildcardInfo = HTTP_STATUS_CODES[wildcardCode];
  if (wildcardInfo) {
    return `${wildcardInfo.description} (${statusCode})`;
  }

  return '';
}

/**
 * Get all status codes for a specific category
 * @param category - The category to filter by
 * @returns Array of status codes in that category
 */
export function getStatusCodesByCategory(category: HttpStatusInfo['category']): HttpStatusInfo[] {
  return Object.values(HTTP_STATUS_CODES).filter(
    (info) => info.category === category && !info.code.includes('X')
  );
}

/**
 * Range and default catch-all values for response node capture (OpenAPI-style).
 * Use "default" for catch-all; use 1XX–5XX for range matching.
 */
export const STATUS_RANGE_AND_DEFAULT = ['default', '1XX', '2XX', '3XX', '4XX', '5XX'] as const;

/**
 * Get commonly used status codes grouped by category
 * Useful for quick selection UIs
 */
export const COMMON_STATUS_CODES: Record<string, string[]> = {
  success: ['200', '201', '202', '204'],
  redirection: ['301', '302', '304', '307', '308'],
  client_error: ['400', '401', '403', '404', '405', '409', '422', '429'],
  server_error: ['500', '502', '503', '504'],
};

/**
 * Check if a status code is valid
 * @param statusCode - The status code to validate
 * @returns true if valid, false otherwise
 */
export function isValidStatusCode(statusCode: string): boolean {
  if (HTTP_STATUS_CODES[statusCode]) {
    return true;
  }

  // Check numeric range
  const num = parseInt(statusCode, 10);
  return !isNaN(num) && num >= 100 && num <= 599;
}

/**
 * Get the category for a status code
 * @param statusCode - The HTTP status code
 * @returns The category or undefined if invalid
 */
export function getStatusCodeCategory(statusCode: string): HttpStatusInfo['category'] | undefined {
  const info = HTTP_STATUS_CODES[statusCode];
  if (info) {
    return info.category;
  }

  const firstChar = statusCode.charAt(0);
  switch (firstChar) {
    case '1': return 'informational';
    case '2': return 'success';
    case '3': return 'redirection';
    case '4': return 'client_error';
    case '5': return 'server_error';
    default: return undefined;
  }
}
