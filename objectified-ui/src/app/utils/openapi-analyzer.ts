/**
 * OpenAPI Specification Analyzer
 * Analyzes OpenAPI specifications and provides quality metrics
 */

import YAML from 'yaml';

export interface AnalysisResult {
  isValid: boolean;
  format: 'openapi' | 'swagger' | 'jsonschema' | 'arazzo' | 'raml' | 'asyncapi' | 'unknown';
  version: string;
  syntax: 'json' | 'yaml';
  syntaxValid: boolean;
  schemaValid: boolean;
  formatSupported: boolean;
  formatDisplayName: string;

  // Metrics
  metrics: {
    schemaCount: number;
    propertyCount: number;
    referenceCount: number;
    pathCount: number;
    externalReferences: string[];
    circularReferences: string[];
    customExtensions: string[];
    compositionSchemas: {
      allOf: number;
      oneOf: number;
      anyOf: number;
    };
  };

  // Quality Score
  qualityScore: {
    overall: number;
    grade: 'A' | 'B' | 'C' | 'D' | 'F';
    completeness: number;
    consistency: number;
    bestPractices: number;
    security: number;
  };

  // Issues
  errors: AnalysisIssue[];
  warnings: AnalysisIssue[];

  // Parsed document
  document: any;
}

export interface AnalysisIssue {
  type: 'error' | 'warning';
  message: string;
  path?: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
}

/**
 * Detect file format (JSON or YAML)
 */
function detectSyntax(content: string): 'json' | 'yaml' {
  const trimmed = content.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    return 'json';
  }
  return 'yaml';
}

/**
 * Parse content based on detected format
 */
function parseContent(content: string, syntax: 'json' | 'yaml'): { valid: boolean; data: any; error?: string } {
  try {
    if (syntax === 'json') {
      const data = JSON.parse(content);
      return { valid: true, data };
    } else {
      const data = YAML.parse(content);
      return { valid: true, data };
    }
  } catch (error) {
    return {
      valid: false,
      data: null,
      error: error instanceof Error ? error.message : 'Parse error'
    };
  }
}

/**
 * Format detection result with support status
 */
interface FormatDetectionResult {
  format: 'openapi' | 'swagger' | 'jsonschema' | 'arazzo' | 'raml' | 'asyncapi' | 'unknown';
  version: string;
  supported: boolean;
  displayName: string;
}

/**
 * Detect specification format and version
 */
function detectFormat(doc: any): FormatDetectionResult {
  // OpenAPI 3.x
  if (doc.openapi) {
    const version = doc.openapi;
    // Only OpenAPI 3.1.x is fully supported
    const isSupported = version.startsWith('3.1');
    let displayName = `OpenAPI ${version}`;

    if (!isSupported) {
      if (version.startsWith('3.0')) {
        displayName = `OpenAPI ${version} (not yet supported - upgrade to 3.1.x recommended)`;
      } else {
        displayName = `OpenAPI ${version} (unsupported version)`;
      }
    }

    return {
      format: 'openapi',
      version: version,
      supported: isSupported,
      displayName
    };
  }

  // Swagger 2.x (OpenAPI 2.0)
  if (doc.swagger) {
    return {
      format: 'swagger',
      version: doc.swagger,
      supported: false,
      displayName: `Swagger ${doc.swagger} (not yet supported - upgrade to OpenAPI 3.1.x recommended)`
    };
  }

  // JSON Schema
  if (doc.$schema) {
    return {
      format: 'jsonschema',
      version: doc.$schema,
      supported: true,
      displayName: 'JSON Schema'
    };
  }

  // Arazzo - not yet supported for import
  if (doc.arazzo) {
    return {
      format: 'arazzo',
      version: doc.arazzo,
      supported: false,
      displayName: `Arazzo ${doc.arazzo}`
    };
  }

  // RAML - detect by version header pattern (typically in YAML content)
  // RAML files typically start with #%RAML version
  if (doc['#%RAML'] || (typeof doc === 'object' && doc.title && doc.baseUri && doc.version)) {
    const ramlVersion = doc['#%RAML'] || '1.0';
    return {
      format: 'raml',
      version: ramlVersion,
      supported: false,
      displayName: `RAML ${ramlVersion}`
    };
  }

  // AsyncAPI
  if (doc.asyncapi) {
    return {
      format: 'asyncapi',
      version: doc.asyncapi,
      supported: false,
      displayName: `AsyncAPI ${doc.asyncapi}`
    };
  }

  return {
    format: 'unknown',
    version: 'unknown',
    supported: false,
    displayName: 'Unknown Format'
  };
}

/**
 * Count schemas in the document
 */
function countSchemas(doc: any): number {
  if (doc.components?.schemas) {
    return Object.keys(doc.components.schemas).length;
  }
  if (doc.definitions) {
    return Object.keys(doc.definitions).length;
  }
  return 0;
}

/**
 * Count total properties across all schemas
 */
function countProperties(doc: any): number {
  let count = 0;
  const schemas = doc.components?.schemas || doc.definitions || {};

  Object.values(schemas).forEach((schema: any) => {
    if (schema.properties) {
      count += Object.keys(schema.properties).length;
    }
  });

  return count;
}

/**
 * Find all $ref references in the document
 */
function findReferences(obj: any, refs: Set<string> = new Set()): Set<string> {
  if (!obj || typeof obj !== 'object') return refs;

  if (obj.$ref && typeof obj.$ref === 'string') {
    refs.add(obj.$ref);
  }

  Object.values(obj).forEach(value => {
    findReferences(value, refs);
  });

  return refs;
}

/**
 * Detect external references (URLs)
 */
function findExternalReferences(refs: Set<string>): string[] {
  return Array.from(refs).filter(ref =>
    ref.startsWith('http://') || ref.startsWith('https://')
  );
}

/**
 * Detect circular references
 */
function detectCircularReferences(doc: any): string[] {
  const circular: string[] = [];
  const schemas = doc.components?.schemas || doc.definitions || {};

  function checkSchema(schemaName: string, visited: Set<string> = new Set()): boolean {
    if (visited.has(schemaName)) {
      circular.push(schemaName);
      return true;
    }

    visited.add(schemaName);
    const schema = schemas[schemaName];

    if (!schema) return false;

    const refs = new Set<string>();
    findReferences(schema, refs);

    for (const ref of refs) {
      const refName = ref.split('/').pop();
      if (refName && schemas[refName]) {
        checkSchema(refName, new Set(visited));
      }
    }

    return false;
  }

  Object.keys(schemas).forEach(schemaName => {
    checkSchema(schemaName);
  });

  return [...new Set(circular)];
}

/**
 * Detect schemas using composition keywords (allOf, oneOf, anyOf)
 */
function detectCompositionSchemas(doc: any): { allOf: number; oneOf: number; anyOf: number } {
  const schemas = doc.components?.schemas || doc.definitions || {};
  let allOfCount = 0;
  let oneOfCount = 0;
  let anyOfCount = 0;

  Object.values(schemas).forEach((schema: any) => {
    if (schema.allOf) allOfCount++;
    if (schema.oneOf) oneOfCount++;
    if (schema.anyOf) anyOfCount++;
  });

  return { allOf: allOfCount, oneOf: oneOfCount, anyOf: anyOfCount };
}

/**
 * Find custom extensions (x- prefixed fields)
 */
function findCustomExtensions(doc: any): string[] {
  const extensions = new Set<string>();

  function findExtensions(obj: any) {
    if (!obj || typeof obj !== 'object') return;

    Object.keys(obj).forEach(key => {
      if (key.startsWith('x-')) {
        extensions.add(key);
      }
      findExtensions(obj[key]);
    });
  }

  findExtensions(doc);
  return Array.from(extensions);
}

/**
 * Count paths in the specification
 */
function countPaths(doc: any): number {
  return doc.paths ? Object.keys(doc.paths).length : 0;
}

/**
 * Calculate completeness score
 */
function calculateCompleteness(doc: any): number {
  let score = 0;
  let total = 0;

  const schemas = doc.components?.schemas || doc.definitions || {};

  // Check for descriptions
  Object.values(schemas).forEach((schema: any) => {
    total++;
    if (schema.description) score++;

    if (schema.properties) {
      Object.values(schema.properties).forEach((prop: any) => {
        total++;
        if (prop.description) score++;
      });
    }
  });

  return total > 0 ? Math.round((score / total) * 100) : 100;
}

/**
 * Calculate consistency score (naming conventions, patterns)
 */
function calculateConsistency(doc: any): number {
  const schemas = doc.components?.schemas || doc.definitions || {};
  const schemaNames = Object.keys(schemas);

  if (schemaNames.length === 0) return 100;

  let score = 100;

  // Check for consistent naming (PascalCase)
  const nonPascalCase = schemaNames.filter(name => {
    return !/^[A-Z][a-zA-Z0-9]*$/.test(name);
  });

  if (nonPascalCase.length > 0) {
    score -= Math.min(30, nonPascalCase.length * 5);
  }

  return Math.max(0, score);
}

/**
 * Calculate best practices score
 */
function calculateBestPractices(doc: any): number {
  let score = 100;

  // Check for info section
  if (!doc.info) score -= 20;
  if (!doc.info?.version) score -= 10;
  if (!doc.info?.title) score -= 10;

  // Check for tags
  const schemas = doc.components?.schemas || doc.definitions || {};
  if (Object.keys(schemas).length > 0 && !doc.tags) {
    score -= 10;
  }

  return Math.max(0, score);
}

/**
 * Calculate security score
 */
function calculateSecurity(doc: any): number {
  let score = 100;

  // Check for security schemes
  if (doc.components?.securitySchemes || doc.securityDefinitions) {
    score = 100;
  } else if (doc.paths && Object.keys(doc.paths).length > 0) {
    score = 50; // Has paths but no security
  }

  return score;
}

/**
 * Calculate overall quality score
 */
function calculateQualityScore(doc: any): {
  overall: number;
  grade: 'A' | 'B' | 'C' | 'D' | 'F';
  completeness: number;
  consistency: number;
  bestPractices: number;
  security: number;
} {
  const completeness = calculateCompleteness(doc);
  const consistency = calculateConsistency(doc);
  const bestPractices = calculateBestPractices(doc);
  const security = calculateSecurity(doc);

  const overall = Math.round((completeness + consistency + bestPractices + security) / 4);

  let grade: 'A' | 'B' | 'C' | 'D' | 'F';
  if (overall >= 90) grade = 'A';
  else if (overall >= 80) grade = 'B';
  else if (overall >= 70) grade = 'C';
  else if (overall >= 60) grade = 'D';
  else grade = 'F';

  return {
    overall,
    grade,
    completeness,
    consistency,
    bestPractices,
    security
  };
}

/**
 * Validate against meta-schema (basic check)
 */
function validateMetaSchema(doc: any, format: string): { valid: boolean; errors: AnalysisIssue[] } {
  const errors: AnalysisIssue[] = [];

  if (format === 'openapi') {
    if (!doc.openapi) {
      errors.push({
        type: 'error',
        message: 'Missing required "openapi" field',
        severity: 'critical'
      });
    }
    if (!doc.info) {
      errors.push({
        type: 'error',
        message: 'Missing required "info" field',
        severity: 'critical'
      });
    }
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Find warnings in the specification
 */
function findWarnings(doc: any): AnalysisIssue[] {
  const warnings: AnalysisIssue[] = [];
  const schemas = doc.components?.schemas || doc.definitions || {};

  // Check for unsupported OpenAPI versions
  if (doc.openapi && !doc.openapi.startsWith('3.1')) {
    if (doc.openapi.startsWith('3.0')) {
      warnings.push({
        type: 'warning',
        message: `OpenAPI ${doc.openapi} is detected but not yet supported for import. Please upgrade to OpenAPI 3.1.x for full compatibility.`,
        path: 'openapi',
        severity: 'high'
      });
    } else {
      warnings.push({
        type: 'warning',
        message: `OpenAPI ${doc.openapi} is not supported. Please upgrade to OpenAPI 3.1.x.`,
        path: 'openapi',
        severity: 'high'
      });
    }
  }

  // Check for Swagger 2.x (OpenAPI 2.0)
  if (doc.swagger) {
    warnings.push({
      type: 'warning',
      message: `Swagger ${doc.swagger} (OpenAPI 2.0) is detected but not yet supported for import. Please upgrade to OpenAPI 3.1.x for full compatibility.`,
      path: 'swagger',
      severity: 'high'
    });
  }

  // Check for missing descriptions
  Object.entries(schemas).forEach(([name, schema]: [string, any]) => {
    if (!schema.description) {
      warnings.push({
        type: 'warning',
        message: `${name} schema is missing description`,
        path: `schemas.${name}`,
        severity: 'low'
      });
    }
  });

  // Check for deprecated items
  if (doc.paths) {
    Object.entries(doc.paths).forEach(([path, methods]: [string, any]) => {
      Object.entries(methods).forEach(([method, operation]: [string, any]) => {
        if (operation.deprecated) {
          warnings.push({
            type: 'warning',
            message: `Deprecated: ${method.toUpperCase()} ${path}`,
            path: `paths.${path}.${method}`,
            severity: 'medium'
          });
        }
      });
    });
  }

  return warnings;
}

/**
 * Main analysis function
 */
export async function analyzeSpecification(fileContent: string, fileName: string): Promise<AnalysisResult> {
  // Detect syntax
  const syntax = detectSyntax(fileContent);

  // Parse content
  const parseResult = parseContent(fileContent, syntax);

  if (!parseResult.valid) {
    return {
      isValid: false,
      format: 'unknown',
      version: 'unknown',
      syntax,
      syntaxValid: false,
      schemaValid: false,
      formatSupported: false,
      formatDisplayName: 'Unknown Format',
      metrics: {
        schemaCount: 0,
        propertyCount: 0,
        referenceCount: 0,
        pathCount: 0,
        externalReferences: [],
        circularReferences: [],
        customExtensions: [],
        compositionSchemas: {
          allOf: 0,
          oneOf: 0,
          anyOf: 0
        }
      },
      qualityScore: {
        overall: 0,
        grade: 'F',
        completeness: 0,
        consistency: 0,
        bestPractices: 0,
        security: 0
      },
      errors: [{
        type: 'error',
        message: `Syntax error: ${parseResult.error}`,
        severity: 'critical'
      }],
      warnings: [],
      document: null
    };
  }

  const doc = parseResult.data;

  // Detect format
  const formatDetection = detectFormat(doc);

  // Validate meta-schema
  const validation = validateMetaSchema(doc, formatDetection.format);

  // Collect metrics
  const refs = findReferences(doc);
  const metrics = {
    schemaCount: countSchemas(doc),
    propertyCount: countProperties(doc),
    referenceCount: refs.size,
    pathCount: countPaths(doc),
    externalReferences: findExternalReferences(refs),
    circularReferences: detectCircularReferences(doc),
    customExtensions: findCustomExtensions(doc),
    compositionSchemas: detectCompositionSchemas(doc)
  };

  // Calculate quality score
  const qualityScore = calculateQualityScore(doc);

  // Find warnings
  const warnings = findWarnings(doc);

  return {
    isValid: validation.valid,
    format: formatDetection.format,
    version: formatDetection.version,
    syntax,
    syntaxValid: true,
    schemaValid: validation.valid,
    formatSupported: formatDetection.supported,
    formatDisplayName: formatDetection.displayName,
    metrics,
    qualityScore,
    errors: validation.errors,
    warnings,
    document: doc
  };
}

/**
 * Quick metadata preview result
 */
export interface FileMetadataPreview {
  syntaxValid: boolean;
  syntax: 'json' | 'yaml';
  format: 'openapi' | 'swagger' | 'jsonschema' | 'arazzo' | 'raml' | 'asyncapi' | 'unknown';
  version: string;
  formatDisplayName: string;
  formatSupported: boolean;
  title?: string;
  description?: string;
  specVersion?: string;
  parseError?: string;
}

/**
 * Quick metadata extraction - faster than full analysis
 * Used to show file info immediately after selection
 */
export function extractFileMetadata(content: string): FileMetadataPreview {
  const syntax = detectSyntax(content);
  const parseResult = parseContent(content, syntax);

  if (!parseResult.valid) {
    return {
      syntaxValid: false,
      syntax,
      format: 'unknown',
      version: 'unknown',
      formatDisplayName: 'Unknown Format',
      formatSupported: false,
      parseError: parseResult.error
    };
  }

  const doc = parseResult.data;
  const formatDetection = detectFormat(doc);

  return {
    syntaxValid: true,
    syntax,
    format: formatDetection.format,
    version: formatDetection.version,
    formatDisplayName: formatDetection.displayName,
    formatSupported: formatDetection.supported,
    title: doc.info?.title,
    description: doc.info?.description,
    specVersion: doc.info?.version
  };
}
