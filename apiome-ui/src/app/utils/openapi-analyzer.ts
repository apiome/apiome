/**
 * OpenAPI Specification Analyzer
 * Analyzes OpenAPI specifications and provides quality metrics
 */

import YAML from 'yaml';
import { convertSwaggerToOpenAPI, isSwagger2 } from './swagger-converter';
import { convertJsonSchemaToOpenAPI, isJsonSchema } from './jsonschema-converter';
import { convertGraphQLToOpenAPI, isGraphQL, isGraphQLIntrospection, convertGraphQLIntrospectionToOpenAPI } from './graphql-converter';
import { convertOpenAPI30ToOpenAPI31, isOpenAPI30 } from './openapi30-converter';
import { convertOpenAPI32ToOpenAPI31, isOpenAPI32, OpenAPI32UnsupportedConstruct } from './openapi32-converter';
import { convertAsyncAPIToOpenAPI, isAsyncAPI } from './asyncapi-converter';
import { convertRAMLToOpenAPI, isRAML } from './raml-converter';
import { convertProtobufToOpenAPI, isProtobuf } from './protobuf-converter';
import { convertAvroToOpenAPI, isAvroSchemaObject } from './avro-converter';
import { convertThriftToOpenAPI, isThrift } from './thrift-converter';
import { inferArazzoSchemasFromWorkflows } from '../../../lib/importers/arazzo';
import { letterGradeFromOverallPercent } from './numeric-score-tier';

export interface AnalysisResult {
  isValid: boolean;
  format: 'openapi' | 'swagger' | 'jsonschema' | 'graphql' | 'arazzo' | 'raml' | 'asyncapi' | 'protobuf' | 'avro' | 'thrift' | 'unknown';
  version: string;
  syntax: 'json' | 'yaml' | 'graphql' | 'protobuf' | 'thrift';
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
    /** Weighted breakdown — max points per category sum to 100 (#247) */
    categories: QualityScoreCategories;
    /** Same as categories.documentation.percent */
    completeness: number;
    /** Raw naming/patterns score (feeds Design Quality) */
    consistency: number;
    /** Same as categories.apiBestPractices.percent */
    bestPractices: number;
    security: number;
    performance: number;
    issues: QualityIssue[];
  };

  // Issues
  errors: AnalysisIssue[];
  warnings: AnalysisIssue[];

  /** Features in the spec that are not or only partially supported by import (#573) */
  unsupportedFeatures: UnsupportedFeature[];

  // Parsed document
  document: any;
}

export interface AnalysisIssue {
  type: 'error' | 'warning';
  message: string;
  path?: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
}

/** Issue categories aligned with weighted quality breakdown (#247) */
export type QualityScoreCategoryId =
  | 'designQuality'
  | 'documentation'
  | 'apiBestPractices'
  | 'security'
  | 'performance';

export interface QualityCategoryScore {
  id: QualityScoreCategoryId;
  label: string;
  description: string;
  percent: number;
  maxPoints: number;
  points: number;
}

export type QualityScoreCategories = Record<QualityScoreCategoryId, QualityCategoryScore>;

export interface QualityIssue {
  category: QualityScoreCategoryId;
  message: string;
  suggestion: string;
  path: string;
  line?: number;
  severity: 'high' | 'medium' | 'low';
}

const QUALITY_CATEGORY_META: Record<
  QualityScoreCategoryId,
  { label: string; description: string; maxPoints: number }
> = {
  designQuality: {
    label: 'Design Quality',
    description: 'Naming conventions, consistency, reusability',
    maxPoints: 30
  },
  documentation: {
    label: 'Documentation',
    description: 'Descriptions, examples, external docs',
    maxPoints: 20
  },
  apiBestPractices: {
    label: 'API Best Practices',
    description: 'RESTful patterns, HTTP methods, status codes',
    maxPoints: 25
  },
  security: {
    label: 'Security',
    description: 'Authentication, authorization, input validation',
    maxPoints: 15
  },
  performance: {
    label: 'Performance',
    description: 'Pagination, filtering, caching headers',
    maxPoints: 10
  }
};

function buildCategoryScore(id: QualityScoreCategoryId, percent: number): QualityCategoryScore {
  const meta = QUALITY_CATEGORY_META[id];
  const clamped = Math.max(0, Math.min(100, Math.round(percent)));
  return {
    id,
    label: meta.label,
    description: meta.description,
    percent: clamped,
    maxPoints: meta.maxPoints,
    points: Math.round((clamped / 100) * meta.maxPoints)
  };
}

function zeroQualityScore(): AnalysisResult['qualityScore'] {
  const ids: QualityScoreCategoryId[] = [
    'designQuality',
    'documentation',
    'apiBestPractices',
    'security',
    'performance'
  ];
  const categories = Object.fromEntries(ids.map((id) => [id, buildCategoryScore(id, 0)])) as QualityScoreCategories;
  return {
    overall: 0,
    grade: 'F',
    categories,
    completeness: 0,
    consistency: 0,
    bestPractices: 0,
    security: 0,
    performance: 0,
    issues: []
  };
}

/**
 * Describes a feature present in the spec that is not (or only partially) supported by the import.
 * Used for pre-import compatibility check (#573).
 */
export interface UnsupportedFeature {
  id: string;
  label: string;
  description: string;
  path?: string;
  count?: number;
  severity: 'warning' | 'info';
}

/**
 * Detect file format (JSON, YAML, GraphQL, or Protobuf)
 */
function detectSyntax(content: string): 'json' | 'yaml' | 'graphql' | 'protobuf' | 'thrift' {
  const trimmed = content.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    return 'json';
  }
  // Check for Protobuf (.proto) before Thrift/GraphQL
  if (isProtobuf(trimmed)) {
    return 'protobuf';
  }
  // Check for Thrift IDL (.thrift) — #240
  if (isThrift(trimmed)) {
    return 'thrift';
  }
  // Check for GraphQL SDL patterns
  if (isGraphQL(trimmed)) {
    return 'graphql';
  }
  return 'yaml';
}

/**
 * Parse content based on detected format
 */
function parseContent(content: string, syntax: 'json' | 'yaml' | 'graphql' | 'protobuf' | 'thrift'): { valid: boolean; data: any; error?: string; isGraphQL?: boolean } {
  try {
    if (syntax === 'json') {
      const data = JSON.parse(content);
      return { valid: true, data };
    } else if (syntax === 'graphql') {
      // For GraphQL, we return a marker object - actual parsing happens in conversion
      return { valid: true, data: { __graphql_sdl: content }, isGraphQL: true };
    } else if (syntax === 'protobuf') {
      // For Protobuf, we return a marker object - actual parsing happens in conversion
      return { valid: true, data: { __protobuf_content: content } };
    } else if (syntax === 'thrift') {
      // For Thrift IDL, we return a marker object - actual parsing happens in conversion (#240)
      return { valid: true, data: { __thrift_content: content } };
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
  format: 'openapi' | 'swagger' | 'jsonschema' | 'graphql' | 'arazzo' | 'raml' | 'asyncapi' | 'protobuf' | 'avro' | 'thrift' | 'unknown';
  version: string;
  supported: boolean;
  displayName: string;
}

/**
 * Highest OpenAPI 3.x minor version this importer recognizes and routes natively (OA1, #3498).
 *
 * 3.0 → converted to 3.1; 3.1 / 3.2 → imported natively. Newer 3.x minors are still accepted
 * (routed to the importer at OpenAPI 3.1 fidelity) but flagged with a non-blocking warning so
 * they degrade gracefully as the OpenAPI spec evolves instead of being hard-rejected.
 */
export const MAX_KNOWN_OPENAPI_MINOR = 2;

/**
 * Classification of an OpenAPI `openapi` version string.
 */
export interface OpenAPIVersionClassification {
  /** The 3.x minor version number, or null when the version is not in the 3.x line. */
  minor: number | null;
  /** Whether the version is part of the OpenAPI 3.x line (e.g. 3.0, 3.1, 3.2, 3.9). */
  isThreeX: boolean;
  /** Whether the 3.x minor is within the recognized range (<= MAX_KNOWN_OPENAPI_MINOR). */
  isKnownMinor: boolean;
}

/**
 * Classify an OpenAPI `openapi` version string into its 3.x minor and support tier (OA1, #3498).
 *
 * @param version - the raw `openapi` field value (e.g. "3.2.0").
 * @returns the parsed minor number plus 3.x / known-minor flags. Non-3.x and malformed
 *   versions yield `{ minor: null, isThreeX: false, isKnownMinor: false }`.
 */
export function classifyOpenAPIVersion(version: string): OpenAPIVersionClassification {
  const match = typeof version === 'string' ? /^3\.(\d+)/.exec(version.trim()) : null;
  const minor = match ? parseInt(match[1], 10) : null;
  const isThreeX = minor !== null;
  const isKnownMinor = minor !== null && minor <= MAX_KNOWN_OPENAPI_MINOR;
  return { minor, isThreeX, isKnownMinor };
}

/**
 * Detect specification format and version
 */
function detectFormat(doc: any): FormatDetectionResult {
  // GraphQL SDL (marked by parseContent)
  if (doc.__graphql_sdl) {
    return {
      format: 'graphql',
      version: 'SDL',
      supported: true,
      displayName: 'GraphQL Schema'
    };
  }

  // Protobuf (.proto) — #238
  if (doc.__protobuf_content) {
    return {
      format: 'protobuf',
      version: 'proto2/3',
      supported: true,
      displayName: 'Protocol Buffers (converted to OpenAPI 3.1.x for import)'
    };
  }

  // Thrift IDL (.thrift) — #240
  if (doc.__thrift_content) {
    return {
      format: 'thrift',
      version: 'IDL',
      supported: true,
      displayName: 'Apache Thrift (converted to OpenAPI 3.1.x for import)'
    };
  }

  // Apache Avro (.avsc JSON schema) — #239
  if (isAvroSchemaObject(doc)) {
    return {
      format: 'avro',
      version: '1.x',
      supported: true,
      displayName: 'Apache Avro (converted to OpenAPI 3.1.x for import)'
    };
  }

  // OpenAPI 3.x
  if (doc.openapi) {
    const version = doc.openapi;
    const { minor, isThreeX, isKnownMinor } = classifyOpenAPIVersion(version);
    // Any 3.x document is accepted (OA1, #3498). 3.0.x is converted to 3.1.x; 3.1.x / 3.2.x
    // import natively. Unknown future 3.x minors are accepted at OpenAPI 3.1 fidelity rather
    // than hard-rejected, so the importer degrades gracefully as the spec evolves.
    const isSupported = isThreeX;
    let displayName = `OpenAPI ${version}`;

    if (minor === 0) {
      displayName = `OpenAPI ${version} (will be converted to OpenAPI 3.1.x)`;
    } else if (isThreeX && !isKnownMinor) {
      displayName = `OpenAPI ${version} (unrecognized 3.x minor — imported at OpenAPI 3.1 fidelity)`;
    } else if (!isThreeX) {
      displayName = `OpenAPI ${version} (unsupported version)`;
    }

    return {
      format: 'openapi',
      version: version,
      supported: isSupported,
      displayName
    };
  }

  // Swagger 2.x (OpenAPI 2.0) - now supported with conversion
  if (doc.swagger) {
    return {
      format: 'swagger',
      version: doc.swagger,
      supported: true,
      displayName: `Swagger ${doc.swagger} (will be converted to OpenAPI 3.1.x)`
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

  // Arazzo 1.0.x - supported for import (#299)
  if (doc.arazzo) {
    const version = doc.arazzo;
    const supported = version.startsWith('1.0');
    return {
      format: 'arazzo',
      version,
      supported,
      displayName: supported ? `Arazzo ${version}` : `Arazzo ${version} (unsupported version)`
    };
  }

  // RAML - detect by version header pattern (typically in YAML content) — #237
  // RAML files typically start with #%RAML version; supported via conversion to OpenAPI 3.1
  if (doc['#%RAML'] || (typeof doc === 'object' && doc.title && (doc.baseUri || doc.version))) {
    const ramlVersion = doc['#%RAML'] || '1.0';
    return {
      format: 'raml',
      version: ramlVersion,
      supported: true,
      displayName: `RAML ${ramlVersion} (converted to OpenAPI 3.1.x for import)`
    };
  }

  // AsyncAPI (2.x and 3.x supported for import via conversion to OpenAPI 3.1–like doc)
  if (doc.asyncapi) {
    const version = doc.asyncapi;
    const isSupported = version.startsWith('2.') || version.startsWith('3.');
    return {
      format: 'asyncapi',
      version,
      supported: isSupported,
      displayName: isSupported
        ? `AsyncAPI ${version} (schemas imported as OpenAPI 3.1.x)`
        : `AsyncAPI ${version} (unsupported version)`
    };
  }

  // GraphQL introspection result
  if (isGraphQLIntrospection(doc)) {
    return {
      format: 'graphql',
      version: 'introspection',
      supported: true,
      displayName: 'GraphQL Introspection Result'
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
 * Description coverage (schemas, properties, operations)
 */
function calculateDescriptionCoverageWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  let score = 0;
  let total = 0;
  const issues: QualityIssue[] = [];

  const schemas = doc.components?.schemas || doc.definitions || {};
  const schemaPath = doc.components?.schemas ? 'components/schemas' : 'definitions';

  Object.entries(schemas).forEach(([schemaName, schema]: [string, any]) => {
    total++;
    if (schema.description) {
      score++;
    } else {
      issues.push({
        category: 'documentation',
        message: `Schema "${schemaName}" is missing a description`,
        suggestion: `Add a description field to explain what this schema represents`,
        path: `${schemaPath}/${schemaName}`,
        severity: 'medium'
      });
    }

    if (schema.properties) {
      Object.entries(schema.properties).forEach(([propName, prop]: [string, any]) => {
        total++;
        if (prop.description) {
          score++;
        } else {
          issues.push({
            category: 'documentation',
            message: `Property "${propName}" in "${schemaName}" is missing a description`,
            suggestion: `Add a description to explain what this property represents`,
            path: `${schemaPath}/${schemaName}/properties/${propName}`,
            severity: 'low'
          });
        }
      });
    }
  });

  if (doc.paths) {
    Object.entries(doc.paths).forEach(([pathName, pathItem]: [string, any]) => {
      Object.entries(pathItem).forEach(([method, operation]: [string, any]) => {
        if (['get', 'post', 'put', 'patch', 'delete'].includes(method)) {
          total++;
          if (operation.summary || operation.description) {
            score++;
          } else {
            issues.push({
              category: 'documentation',
              message: `Operation ${method.toUpperCase()} ${pathName} is missing a summary/description`,
              suggestion: `Add a summary or description to explain what this endpoint does`,
              path: `paths/${pathName}/${method}`,
              severity: 'medium'
            });
          }
        }
      });
    });
  }

  return {
    score: total > 0 ? Math.round((score / total) * 100) : 100,
    issues
  };
}

/**
 * Example coverage: at least one illustrative example per schema where properties exist
 */
function calculateExampleCoverageWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  const issues: QualityIssue[] = [];
  const schemas = doc.components?.schemas || doc.definitions || {};
  const schemaPath = doc.components?.schemas ? 'components/schemas' : 'definitions';
  const entries = Object.entries(schemas);
  if (entries.length === 0) {
    return { score: 100, issues: [] };
  }

  let score = 0;
  entries.forEach(([schemaName, schema]: [string, any]) => {
    const schemaEx =
      schema.example !== undefined ||
      (schema.examples && Object.keys(schema.examples).length > 0);
    let propWithExample = 0;
    let propTotal = 0;
    if (schema.properties) {
      Object.values(schema.properties).forEach((prop: any) => {
        propTotal++;
        if (prop.example !== undefined || (prop.examples && Object.keys(prop.examples).length > 0)) {
          propWithExample++;
        }
      });
    }
    const hasEx = schemaEx || (propTotal > 0 && propWithExample / propTotal >= 0.34);
    if (hasEx) {
      score++;
    } else {
      issues.push({
        category: 'documentation',
        message: `Schema "${schemaName}" has few or no examples`,
        suggestion: 'Add schema-level or property examples to illustrate payloads',
        path: `${schemaPath}/${schemaName}`,
        severity: 'low'
      });
    }
  });

  return {
    score: Math.round((score / entries.length) * 100),
    issues
  };
}

/**
 * External documentation (externalDocs, tag externalDocs)
 */
function calculateExternalDocsCoverageWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  const issues: QualityIssue[] = [];
  let score = 100;
  const pathCount = doc.paths ? Object.keys(doc.paths).length : 0;

  if (!doc.externalDocs?.url && pathCount > 10) {
    score -= 25;
    issues.push({
      category: 'documentation',
      message: 'externalDocs is not defined',
      suggestion: 'Link to external documentation (e.g. developer portal or README)',
      path: 'externalDocs',
      severity: 'low'
    });
  }

  if (Array.isArray(doc.tags) && pathCount > 10) {
    const withoutExt = doc.tags.filter((t: any) => t && !t.externalDocs?.url);
    if (doc.tags.length > 0 && withoutExt.length === doc.tags.length) {
      score -= 10;
      issues.push({
        category: 'documentation',
        message: 'Tags do not reference external documentation',
        suggestion: 'Add externalDocs URLs on tags when sections have docs outside the spec',
        path: 'tags',
        severity: 'low'
      });
    }
  }

  return { score: Math.max(0, Math.min(100, score)), issues };
}

/** Documentation dimension: descriptions, examples, external docs (#247) */
function calculateDocumentationWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  const a = calculateDescriptionCoverageWithIssues(doc);
  const b = calculateExampleCoverageWithIssues(doc);
  const c = calculateExternalDocsCoverageWithIssues(doc);
  return {
    score: Math.round((a.score + b.score + c.score) / 3),
    issues: [...a.issues, ...b.issues, ...c.issues]
  };
}

function calculateCompletenessWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  return calculateDocumentationWithIssues(doc);
}

/**
 * Calculate consistency score with detailed issues
 */
function calculateConsistencyWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  const schemas = doc.components?.schemas || doc.definitions || {};
  const schemaNames = Object.keys(schemas);
  const schemaPath = doc.components?.schemas ? 'components/schemas' : 'definitions';
  const issues: QualityIssue[] = [];

  if (schemaNames.length === 0) return { score: 100, issues: [] };

  let score = 100;

  // Check for consistent naming (PascalCase)
  schemaNames.forEach(name => {
    if (!/^[A-Z][a-zA-Z0-9]*$/.test(name)) {
      score -= 5;
      issues.push({
        category: 'designQuality',
        message: `Schema name "${name}" does not follow PascalCase convention`,
        suggestion: `Rename to "${name.charAt(0).toUpperCase()}${name.slice(1).replace(/[_-](\w)/g, (_, c) => c.toUpperCase())}"`,
        path: `${schemaPath}/${name}`,
        severity: 'low'
      });
    }
  });

  // Check property naming consistency
  Object.entries(schemas).forEach(([schemaName, schema]: [string, any]) => {
    if (schema.properties) {
      const propNames = Object.keys(schema.properties);
      const hasCamelCase = propNames.some(n => /^[a-z][a-zA-Z0-9]*$/.test(n));
      const hasSnakeCase = propNames.some(n => /^[a-z][a-z0-9_]*$/.test(n) && n.includes('_'));

      if (hasCamelCase && hasSnakeCase) {
        score -= 5;
        issues.push({
          category: 'designQuality',
          message: `Schema "${schemaName}" has mixed property naming conventions (camelCase and snake_case)`,
          suggestion: `Use consistent naming convention for all properties - prefer camelCase`,
          path: `${schemaPath}/${schemaName}/properties`,
          severity: 'medium'
        });
      }
    }
  });

  return { score: Math.max(0, Math.min(100, score)), issues };
}

/**
 * Schema reuse via $ref / components (design quality)
 */
function calculateReusabilityWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  const issues: QualityIssue[] = [];
  const schemas = doc.components?.schemas || doc.definitions || {};
  const schemaNames = Object.keys(schemas);
  if (schemaNames.length < 2) {
    return { score: 100, issues: [] };
  }

  let refCount = 0;
  function countRefs(obj: any): void {
    if (!obj || typeof obj !== 'object') return;
    if (typeof obj.$ref === 'string') refCount++;
    Object.values(obj).forEach(countRefs);
  }
  countRefs(doc);

  if (refCount < 2) {
    issues.push({
      category: 'designQuality',
      message: 'Limited reuse of shared components via $ref',
      suggestion: 'Reference shared schemas from components/schemas instead of duplicating inline structures',
      path: 'components/schemas',
      severity: 'low'
    });
    return { score: 65, issues };
  }

  return { score: 100, issues };
}

/**
 * API best practices: REST surface, HTTP methods, status codes (#247)
 */
function calculateBestPracticesWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  let score = 100;
  const issues: QualityIssue[] = [];

  // Check for info section
  if (!doc.info) {
    score -= 20;
    issues.push({
      category: 'apiBestPractices',
      message: 'Missing "info" section',
      suggestion: 'Add an info section with title, version, and description',
      path: 'info',
      severity: 'high'
    });
  } else {
    if (!doc.info.version) {
      score -= 10;
      issues.push({
        category: 'apiBestPractices',
        message: 'Missing API version in info section',
        suggestion: 'Add a version field (e.g., "1.0.0") to the info section',
        path: 'info/version',
        severity: 'high'
      });
    }
    if (!doc.info.title) {
      score -= 10;
      issues.push({
        category: 'apiBestPractices',
        message: 'Missing API title in info section',
        suggestion: 'Add a title field to describe your API',
        path: 'info/title',
        severity: 'high'
      });
    }
    if (!doc.info.description) {
      score -= 5;
      issues.push({
        category: 'apiBestPractices',
        message: 'Missing API description in info section',
        suggestion: 'Add a description to explain what your API does',
        path: 'info/description',
        severity: 'medium'
      });
    }
    if (!doc.info.contact) {
      score -= 5;
      issues.push({
        category: 'apiBestPractices',
        message: 'Missing contact information',
        suggestion: 'Add contact info (name, email, url) for API support',
        path: 'info/contact',
        severity: 'low'
      });
    }
    if (!doc.info.license) {
      score -= 5;
      issues.push({
        category: 'apiBestPractices',
        message: 'Missing license information',
        suggestion: 'Add a license field to specify the API license',
        path: 'info/license',
        severity: 'low'
      });
    }
  }

  // Check for tags
  const schemas = doc.components?.schemas || doc.definitions || {};
  if (Object.keys(schemas).length > 0 && !doc.tags) {
    score -= 10;
    issues.push({
      category: 'apiBestPractices',
      message: 'No tags defined for API organization',
      suggestion: 'Add tags to group and organize your API endpoints',
      path: 'tags',
      severity: 'medium'
    });
  }

  // Check for servers
  if (!doc.servers || doc.servers.length === 0) {
    score -= 5;
    issues.push({
      category: 'apiBestPractices',
      message: 'No servers defined',
      suggestion: 'Add server URLs to specify where your API is hosted',
      path: 'servers',
      severity: 'low'
    });
  }

  // Successful HTTP status codes on operations
  if (doc.paths) {
    Object.entries(doc.paths).forEach(([pathName, pathItem]: [string, any]) => {
      Object.entries(pathItem).forEach(([method, operation]: [string, any]) => {
        if (!['get', 'post', 'put', 'patch', 'delete', 'head', 'options'].includes(method)) return;
        const responses = operation.responses || {};
        const has2xx = Object.keys(responses).some((code) => {
          const normalizedCode = code.trim().toUpperCase();
          return normalizedCode === '2XX' || /^2\d\d$/.test(normalizedCode);
        });
        if (!has2xx) {
          score -= 8;
          issues.push({
            category: 'apiBestPractices',
            message: `Operation ${method.toUpperCase()} ${pathName} has no 2xx response documented`,
            suggestion: 'Document at least one successful response (e.g. 200, 201, 204)',
            path: `paths/${pathName}/${method}/responses`,
            severity: 'medium'
          });
        }
      });
    });
  }

  return { score: Math.max(0, score), issues };
}

/**
 * Calculate security score with detailed issues
 */
function calculateSecurityWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  let score = 100;
  const issues: QualityIssue[] = [];

  const hasSecuritySchemes = doc.components?.securitySchemes || doc.securityDefinitions;
  const hasPaths = doc.paths && Object.keys(doc.paths).length > 0;

  if (!hasSecuritySchemes) {
    if (hasPaths) {
      score = 50;
      issues.push({
        category: 'security',
        message: 'No security schemes defined',
        suggestion: 'Add security schemes (OAuth2, API Key, Bearer, etc.) to protect your API',
        path: 'components/securitySchemes',
        severity: 'high'
      });
    }
  } else {
    // Check if security is applied globally or per-operation
    if (!doc.security && hasPaths) {
      score -= 20;
      issues.push({
        category: 'security',
        message: 'Security schemes defined but not applied globally',
        suggestion: 'Add a global security requirement or apply security per-operation',
        path: 'security',
        severity: 'medium'
      });
    }
  }

  // Check for HTTPS in servers
  if (doc.servers) {
    const insecureServers = doc.servers.filter((s: any) =>
      s.url && s.url.startsWith('http://') && !s.url.includes('localhost')
    );
    if (insecureServers.length > 0) {
      score -= 10;
      issues.push({
        category: 'security',
        message: 'Non-HTTPS server URLs detected',
        suggestion: 'Use HTTPS for all production server URLs',
        path: 'servers',
        severity: 'high'
      });
    }
  }

  // Input validation: request bodies should have validatable schemas
  if (doc.paths) {
    Object.entries(doc.paths).forEach(([pathName, pathItem]: [string, any]) => {
      Object.entries(pathItem).forEach(([method, operation]: [string, any]) => {
        if (!['post', 'put', 'patch'].includes(method)) return;
        const rb = operation.requestBody;
        if (!rb?.content) return;
        const mediaEntries = Object.values(rb.content) as any[];
        const schemas = mediaEntries
          .map((media) => media?.schema)
          .filter((schema) => !!schema);

        if (schemas.length === 0) {
          score -= 10;
          issues.push({
            category: 'security',
            message: `Request body for ${method.toUpperCase()} ${pathName} has no schema`,
            suggestion: 'Provide a schema under content types so inputs can be validated',
            path: `paths/${pathName}/${method}/requestBody`,
            severity: 'high'
          });
          return;
        }

        const hasConcreteSchema = schemas.some((s) =>
          !!(
            s.$ref ||
            s.type ||
            s.properties ||
            s.allOf ||
            s.oneOf ||
            s.anyOf ||
            s.items
          )
        );

        if (!hasConcreteSchema) {
          score -= 8;
          issues.push({
            category: 'security',
            message: `Request body schema for ${method.toUpperCase()} ${pathName} is not concrete enough for validation`,
            suggestion: 'Use type/properties, composition, or $ref to describe the payload',
            path: `paths/${pathName}/${method}/requestBody`,
            severity: 'medium'
          });
        }
      });
    });
  }

  return { score: Math.max(0, score), issues };
}

const PAGINATION_PARAM = /^(limit|offset|page|cursor|pageSize|per_page|page_size)$/i;
const FILTER_PARAM = /^(filter|q|query|search|tags)$/i;

/**
 * Pagination, filtering, caching headers (#247)
 */
function calculatePerformanceWithIssues(doc: any): { score: number; issues: QualityIssue[] } {
  const issues: QualityIssue[] = [];
  if (!doc.paths || Object.keys(doc.paths).length === 0) {
    return { score: 100, issues: [] };
  }

  let score = 100;
  let getOps = 0;
  let getsWithPaginationHint = 0;
  let getsWithFilterHint = 0;
  let anyCacheHeader = false;

  Object.entries(doc.paths).forEach(([pathName, pathItem]: [string, any]) => {
    Object.entries(pathItem).forEach(([method, operation]: [string, any]) => {
      if (method !== 'get') return;
      getOps++;
      const params = [
        ...(operation.parameters || []),
        ...(pathItem.parameters || [])
      ];
      const names = params.map((p: any) => p?.name).filter(Boolean);
      if (names.some((n: string) => PAGINATION_PARAM.test(n))) {
        getsWithPaginationHint++;
      }
      if (names.some((n: string) => FILTER_PARAM.test(n))) {
        getsWithFilterHint++;
      }

      const responses = operation.responses || {};
      for (const res of Object.values(responses) as any[]) {
        const hdrs = res?.headers;
        if (!hdrs) continue;
        const keys = Object.keys(hdrs).map((k) => k.toLowerCase());
        if (
          keys.some(
            (k) =>
              k === 'cache-control' ||
              k === 'etag' ||
              k === 'expires' ||
              k === 'last-modified'
          )
        ) {
          anyCacheHeader = true;
        }
      }
    });
  });

  if (getOps >= 2 && getsWithPaginationHint === 0) {
    score -= 25;
    issues.push({
      category: 'performance',
      message: 'List-style GET operations should document pagination query parameters',
      suggestion: 'Add parameters such as limit, offset, page, or cursor for large collections',
      path: 'paths',
      severity: 'medium'
    });
  }

  if (getOps >= 1 && getsWithFilterHint === 0) {
    score -= 15;
    issues.push({
      category: 'performance',
      message: 'No filtering or search query parameters documented for GET operations',
      suggestion: 'Consider filter, q, search, or domain-specific filters where applicable',
      path: 'paths',
      severity: 'low'
    });
  }

  if (getOps >= 1 && !anyCacheHeader) {
    score -= 20;
    issues.push({
      category: 'performance',
      message: 'Responses do not document cache-related headers',
      suggestion: 'Where appropriate, document Cache-Control, ETag, or Expires on responses',
      path: 'paths',
      severity: 'low'
    });
  }

  return { score: Math.max(0, Math.min(100, score)), issues };
}

/**
 * Calculate completeness score (legacy wrapper)
 */
function calculateCompleteness(doc: any): number {
  return calculateCompletenessWithIssues(doc).score;
}

/**
 * Calculate consistency score (legacy wrapper)
 */
function calculateConsistency(doc: any): number {
  return calculateConsistencyWithIssues(doc).score;
}

/**
 * Calculate best practices score (legacy wrapper)
 */
function calculateBestPractices(doc: any): number {
  return calculateBestPracticesWithIssues(doc).score;
}

/**
 * Calculate security score (legacy wrapper)
 */
function calculateSecurity(doc: any): number {
  return calculateSecurityWithIssues(doc).score;
}

/**
 * Weighted overall quality score (#247)
 */
function calculateQualityScore(doc: any): AnalysisResult['qualityScore'] {
  const documentationResult = calculateDocumentationWithIssues(doc);
  const consistencyResult = calculateConsistencyWithIssues(doc);
  const reusabilityResult = calculateReusabilityWithIssues(doc);
  const apiBestPracticesResult = calculateBestPracticesWithIssues(doc);
  const securityResult = calculateSecurityWithIssues(doc);
  const performanceResult = calculatePerformanceWithIssues(doc);

  const designQualityPercent = Math.round(
    (consistencyResult.score + reusabilityResult.score) / 2
  );

  const categories: QualityScoreCategories = {
    designQuality: buildCategoryScore('designQuality', designQualityPercent),
    documentation: buildCategoryScore('documentation', documentationResult.score),
    apiBestPractices: buildCategoryScore('apiBestPractices', apiBestPracticesResult.score),
    security: buildCategoryScore('security', securityResult.score),
    performance: buildCategoryScore('performance', performanceResult.score)
  };

  const overall = Math.min(
    100,
    categories.designQuality.points +
      categories.documentation.points +
      categories.apiBestPractices.points +
      categories.security.points +
      categories.performance.points
  );

  const issues: QualityIssue[] = [
    ...documentationResult.issues,
    ...consistencyResult.issues,
    ...reusabilityResult.issues,
    ...apiBestPracticesResult.issues,
    ...securityResult.issues,
    ...performanceResult.issues
  ];

  const grade = letterGradeFromOverallPercent(overall);

  return {
    overall,
    grade,
    categories,
    completeness: documentationResult.score,
    consistency: consistencyResult.score,
    bestPractices: apiBestPracticesResult.score,
    security: securityResult.score,
    performance: performanceResult.score,
    issues
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

  // Check OpenAPI version handling (OA1, #3498). 3.1.x is native and produces no warning.
  if (doc.openapi) {
    const { minor, isThreeX, isKnownMinor } = classifyOpenAPIVersion(doc.openapi);
    if (minor === 0) {
      // 3.0.x: converted to 3.1.x for import.
      warnings.push({
        type: 'warning',
        message: `OpenAPI ${doc.openapi} was automatically converted to OpenAPI 3.1.x format for import.`,
        path: 'openapi',
        severity: 'low'
      });
    } else if (isThreeX && minor !== null && minor > 1 && isKnownMinor) {
      // 3.2.x (recognized post-3.1 minor): accepted and normalized for import — informational only.
      warnings.push({
        type: 'warning',
        message: `OpenAPI ${doc.openapi} was normalized to OpenAPI 3.1 fidelity for import. Newer 3.2 keywords are accepted but not yet transformed.`,
        path: 'openapi',
        severity: 'low'
      });
    } else if (isThreeX && !isKnownMinor) {
      // Unknown future 3.x minor (e.g. 3.9.0): non-blocking warning, not a hard error.
      warnings.push({
        type: 'warning',
        message: `OpenAPI ${doc.openapi} is newer than the recognized 3.${MAX_KNOWN_OPENAPI_MINOR}.x range; it was accepted and imported at OpenAPI 3.1 fidelity. Some newer features may not be fully represented.`,
        path: 'openapi',
        severity: 'medium'
      });
    } else if (!isThreeX) {
      // Non-3.x (e.g. 4.0.0): unsupported.
      warnings.push({
        type: 'warning',
        message: `OpenAPI ${doc.openapi} is not supported. Please use OpenAPI 3.0.x, 3.1.x, or 3.2.x.`,
        path: 'openapi',
        severity: 'high'
      });
    }
  }

  // Check for Swagger 2.x (OpenAPI 2.0) - now supported but add info message
  if (doc.swagger) {
    warnings.push({
      type: 'warning',
      message: `Swagger ${doc.swagger} (OpenAPI 2.0) was automatically converted to OpenAPI 3.1.x format for import.`,
      path: 'swagger',
      severity: 'low'
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
 * Identify deprecated constructs in the specification (#575).
 * Returns entries suitable for the pre-import compatibility / deprecated feature warning.
 */
function identifyDeprecatedConstructs(doc: any): UnsupportedFeature[] {
  const features: UnsupportedFeature[] = [];
  if (!doc || typeof doc !== 'object') return features;

  const schemas = doc.components?.schemas || doc.definitions || {};
  const schemaPath = doc.components?.schemas ? 'components/schemas' : 'definitions';

  // Deprecated operations (paths.*.get/post/... .deprecated)
  let deprecatedOpCount = 0;
  if (doc.paths) {
    const methods = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'] as const;
    Object.values(doc.paths).forEach((pathItem: any) => {
      if (!pathItem || typeof pathItem !== 'object') return;
      methods.forEach((method) => {
        const op = pathItem[method];
        if (op?.deprecated === true) deprecatedOpCount++;
      });
    });
  }
  if (deprecatedOpCount > 0) {
    features.push({
      id: 'deprecated-operations',
      label: 'Deprecated operations',
      description: 'Some path operations are marked deprecated. Consider migrating callers before removing.',
      path: 'paths',
      count: deprecatedOpCount,
      severity: 'warning'
    });
  }

  // Deprecated parameters (in path items or operations)
  let deprecatedParamCount = 0;
  function countDeprecatedParams(params: any[] | undefined) {
    if (!Array.isArray(params)) return;
    params.forEach((p: any) => {
      if (p && p.deprecated === true) deprecatedParamCount++;
    });
  }
  if (doc.paths) {
    Object.values(doc.paths).forEach((pathItem: any) => {
      if (!pathItem || typeof pathItem !== 'object') return;
      countDeprecatedParams(pathItem.parameters);
      ['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'].forEach((method) => {
        const op = pathItem[method];
        if (op?.parameters) countDeprecatedParams(op.parameters);
      });
    });
  }
  if (doc.components?.parameters) {
    Object.values(doc.components.parameters).forEach((p: any) => {
      if (p?.deprecated === true) deprecatedParamCount++;
    });
  }
  if (deprecatedParamCount > 0) {
    features.push({
      id: 'deprecated-parameters',
      label: 'Deprecated parameters',
      description: 'Some parameters are marked deprecated. Consider migrating to alternatives.',
      path: 'paths',
      count: deprecatedParamCount,
      severity: 'warning'
    });
  }

  // Deprecated schemas or schema properties (deprecated: true)
  let deprecatedSchemaCount = 0;
  let deprecatedPropertyCount = 0;
  function countDeprecatedInSchema(obj: any, inProperty: boolean) {
    if (!obj || typeof obj !== 'object') return;
    if (obj.deprecated === true) {
      if (inProperty) deprecatedPropertyCount++;
      else deprecatedSchemaCount++;
    }
    if (obj.properties && typeof obj.properties === 'object') {
      Object.values(obj.properties).forEach((p: any) => countDeprecatedInSchema(p, true));
    }
    if (Array.isArray(obj.allOf)) obj.allOf.forEach((s: any) => countDeprecatedInSchema(s, inProperty));
    if (Array.isArray(obj.oneOf)) obj.oneOf.forEach((s: any) => countDeprecatedInSchema(s, inProperty));
    if (Array.isArray(obj.anyOf)) obj.anyOf.forEach((s: any) => countDeprecatedInSchema(s, inProperty));
    if (obj.items) countDeprecatedInSchema(obj.items, inProperty);
  }
  Object.values(schemas).forEach((schema: any) => countDeprecatedInSchema(schema, false));
  if (deprecatedSchemaCount > 0) {
    features.push({
      id: 'deprecated-schemas',
      label: 'Deprecated schemas',
      description: 'Some schemas are marked deprecated. Consider replacing with a supported schema.',
      path: schemaPath,
      count: deprecatedSchemaCount,
      severity: 'warning'
    });
  }
  if (deprecatedPropertyCount > 0) {
    features.push({
      id: 'deprecated-properties',
      label: 'Deprecated schema properties',
      description: 'Some schema properties are marked deprecated. Consider migrating to alternative fields.',
      path: schemaPath,
      count: deprecatedPropertyCount,
      severity: 'warning'
    });
  }

  // nullable (deprecated in OpenAPI 3.1 in favor of type: [..., "null"])
  let nullableCount = 0;
  function countNullable(obj: any): void {
    if (!obj || typeof obj !== 'object') return;
    if (obj.nullable === true) nullableCount++;
    Object.values(obj).forEach(countNullable);
  }
  Object.values(schemas).forEach(countNullable);
  if (nullableCount > 0) {
    features.push({
      id: 'deprecated-nullable',
      label: 'Deprecated nullable keyword',
      description: 'The nullable keyword is deprecated in OpenAPI 3.1. Prefer type: [<type>, "null"] instead.',
      path: schemaPath,
      count: nullableCount,
      severity: 'warning'
    });
  }

  return features;
}

/**
 * Map a carried-forward OpenAPI 3.2 construct (OA2, #3499) to the analyzer's
 * unsupported-feature shape for the pre-import compatibility check.
 */
function toUnsupportedFeature(construct: OpenAPI32UnsupportedConstruct): UnsupportedFeature {
  return {
    id: `openapi32-${construct.id}`,
    label: construct.label,
    description: construct.description,
    count: construct.count,
    severity: construct.severity
  };
}

/**
 * Identify features in the specification that are not or only partially supported by the import.
 * Used for pre-import compatibility check (#573).
 */
function identifyUnsupportedFeatures(doc: any): UnsupportedFeature[] {
  const features: UnsupportedFeature[] = [];
  if (!doc || typeof doc !== 'object') return features;

  const schemas = doc.components?.schemas || doc.definitions || {};
  const schemaPath = doc.components?.schemas ? 'components/schemas' : 'definitions';

  // Deprecated constructs (#575): flag deprecated operations, parameters, schemas, nullable
  features.push(...identifyDeprecatedConstructs(doc));

  // Custom extensions (x-): listed for pre-import compatibility (#574)
  const customExtensions = findCustomExtensions(doc);
  if (customExtensions.length > 0) {
    features.push({
      id: 'custom-extensions',
      label: 'Custom extensions (x-)',
      description: 'The following x- prefixed vendor extensions were detected. They are not part of the OpenAPI standard and are not imported.',
      count: customExtensions.length,
      severity: 'info'
    });
  }

  // External references: not resolved during import
  const refs = findReferences(doc);
  const externalRefs = findExternalReferences(refs);
  if (externalRefs.length > 0) {
    features.push({
      id: 'external-refs',
      label: 'External references',
      description: 'References to external URLs are not resolved during import. Only in-document $refs are followed.',
      count: externalRefs.length,
      severity: 'warning'
    });
  }

  // Schemas that are oneOf/anyOf only (no properties): import yields no properties
  let variantOnlyCount = 0;
  const variantSchemaNames: string[] = [];
  Object.entries(schemas).forEach(([name, schema]: [string, any]) => {
    if (!schema) return;
    const hasProps = schema.properties && Object.keys(schema.properties).length > 0;
    const hasAllOfWithInline = schema.allOf && Array.isArray(schema.allOf) &&
      schema.allOf.some((item: any) => item && !item.$ref && item.properties);
    if ((schema.oneOf || schema.anyOf) && !hasProps && !hasAllOfWithInline) {
      variantOnlyCount++;
      variantSchemaNames.push(name);
    }
  });
  if (variantOnlyCount > 0) {
    features.push({
      id: 'oneof-anyof-only',
      label: 'Variant-type schemas (oneOf/anyOf only)',
      description: `Schemas that only use oneOf/anyOf without inline properties will import with no properties. (e.g. ${variantSchemaNames.slice(0, 3).join(', ')}${variantSchemaNames.length > 3 ? '…' : ''})`,
      path: schemaPath,
      count: variantOnlyCount,
      severity: 'warning'
    });
  }

  // Conditional schemas (if/then/else): skipped by importer
  let conditionalCount = 0;
  function countConditional(obj: any): void {
    if (!obj || typeof obj !== 'object') return;
    if (obj.if !== undefined) conditionalCount++;
    Object.values(obj).forEach(countConditional);
  }
  Object.values(schemas).forEach(countConditional);
  if (conditionalCount > 0) {
    features.push({
      id: 'conditional-schemas',
      label: 'Conditional schemas (if/then/else)',
      description: 'JSON Schema if/then/else rules are not imported; only static property definitions are used.',
      count: conditionalCount,
      severity: 'info'
    });
  }

  // patternProperties: not mapped by importer
  let patternPropsCount = 0;
  function countPatternProps(obj: any): void {
    if (!obj || typeof obj !== 'object') return;
    if (obj.patternProperties && Object.keys(obj.patternProperties).length > 0) patternPropsCount++;
    Object.values(obj).forEach(countPatternProps);
  }
  Object.values(schemas).forEach(countPatternProps);
  if (patternPropsCount > 0) {
    features.push({
      id: 'pattern-properties',
      label: 'patternProperties',
      description: 'JSON Schema patternProperties are not imported; only named properties are supported.',
      count: patternPropsCount,
      severity: 'info'
    });
  }

  // Discriminator: not mapped to class model
  let discriminatorCount = 0;
  Object.values(schemas).forEach((schema: any) => {
    if (schema?.discriminator) discriminatorCount++;
  });
  if (discriminatorCount > 0) {
    features.push({
      id: 'discriminator',
      label: 'Discriminator',
      description: 'Discriminator mapping is not imported; polymorphism is represented only via schema structure.',
      path: schemaPath,
      count: discriminatorCount,
      severity: 'info'
    });
  }

  // Callbacks (OpenAPI 3: operation.callbacks)
  let callbackCount = 0;
  if (doc.paths) {
    Object.values(doc.paths).forEach((pathItem: any) => {
      if (!pathItem || typeof pathItem !== 'object') return;
      for (const method of ['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace']) {
        const op = pathItem[method];
        if (op?.callbacks && Object.keys(op.callbacks).length > 0) callbackCount++;
      }
    });
  }
  if (callbackCount > 0) {
    features.push({
      id: 'callbacks',
      label: 'Callbacks',
      description: 'Callback operations in paths are not imported as part of schema import.',
      path: 'paths',
      count: callbackCount,
      severity: 'info'
    });
  }

  // Webhooks (OpenAPI 3.1)
  const webhookCount = doc.webhooks ? Object.keys(doc.webhooks).length : 0;
  if (webhookCount > 0) {
    features.push({
      id: 'webhooks',
      label: 'Webhooks',
      description: 'Webhooks section is not imported; only components/schemas are imported.',
      path: 'webhooks',
      count: webhookCount,
      severity: 'info'
    });
  }

  // readOnly / writeOnly: may not be preserved in property model
  let readWriteOnlyCount = 0;
  function countReadWriteOnly(obj: any): void {
    if (!obj || typeof obj !== 'object') return;
    if (obj.readOnly === true || obj.writeOnly === true) readWriteOnlyCount++;
    Object.values(obj).forEach(countReadWriteOnly);
  }
  Object.values(schemas).forEach(countReadWriteOnly);
  if (readWriteOnlyCount > 0) {
    features.push({
      id: 'readonly-writeonly',
      label: 'readOnly / writeOnly',
      description: 'Property readOnly/writeOnly hints may not be preserved in the imported class model.',
      count: readWriteOnlyCount,
      severity: 'info'
    });
  }

  return features;
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
      qualityScore: zeroQualityScore(),
      errors: [{
        type: 'error',
        message: `Syntax error: ${parseResult.error}`,
        severity: 'critical'
      }],
      warnings: [],
      unsupportedFeatures: [],
      document: null
    };
  }

  let doc = parseResult.data;
  let conversionWarnings: AnalysisIssue[] = [];
  // 3.2-only constructs carried forward by the OA2 normalization layer (#3499),
  // surfaced as unsupported features for the pre-import compatibility check.
  let openapi32Constructs: UnsupportedFeature[] = [];

  // Convert Swagger 2.x to OpenAPI 3.1.x if needed
  if (isSwagger2(doc)) {
    const conversionResult = convertSwaggerToOpenAPI(doc);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'swagger',
        version: doc.swagger || '2.0',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: false,
        formatDisplayName: `Swagger ${doc.swagger || '2.0'} (conversion failed)`,
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: `Swagger conversion failed: ${conversionResult.error}`,
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    // Use the converted document for analysis
    doc = conversionResult.document;

    // Add conversion warnings
    conversionWarnings = conversionResult.warnings.map(warning => ({
      type: 'warning' as const,
      message: warning,
      severity: 'low' as const
    }));
  }

  // Convert OpenAPI 3.0.x to OpenAPI 3.1.x if needed
  if (isOpenAPI30(doc)) {
    const conversionResult = convertOpenAPI30ToOpenAPI31(doc);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'openapi',
        version: doc.openapi || '3.0',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: false,
        formatDisplayName: `OpenAPI ${doc.openapi || '3.0'} (conversion failed)`,
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: `OpenAPI 3.0 conversion failed: ${conversionResult.error}`,
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    // Use the converted document for analysis
    doc = conversionResult.document;

    // Add conversion warnings
    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Normalize OpenAPI 3.2.0 for the pre-import compatibility check (OA2, #3499).
  // The doc is left as-is (so the version display and OA1 version note are preserved);
  // the converter is run only to collect the 3.2-only constructs it would carry forward,
  // which are surfaced below as unsupported features.
  if (isOpenAPI32(doc)) {
    const conversionResult = convertOpenAPI32ToOpenAPI31(doc);
    if (conversionResult.success) {
      openapi32Constructs = conversionResult.unsupportedConstructs.map(toUnsupportedFeature);
      conversionWarnings = [
        ...conversionWarnings,
        ...conversionResult.warnings.map(warning => ({
          type: 'warning' as const,
          message: warning,
          severity: 'low' as const
        }))
      ];
    }
  }

  // Convert Apache Avro (.avsc) to OpenAPI 3.1–like document for import (#239) — before JSON Schema so Avro records are not mistaken for JSON Schema
  if (isAvroSchemaObject(doc)) {
    const conversionResult = convertAvroToOpenAPI(doc, fileName);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'avro',
        version: '1.x',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: true,
        formatDisplayName: 'Apache Avro (conversion failed)',
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: conversionResult.error ?? 'Avro conversion failed',
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    doc = conversionResult.document;

    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Convert JSON Schema to OpenAPI 3.1.x if needed
  if (isJsonSchema(doc)) {
    const conversionResult = convertJsonSchemaToOpenAPI(doc, fileName);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'jsonschema',
        version: doc.$schema || 'unknown',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: false,
        formatDisplayName: 'JSON Schema (conversion failed)',
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: `JSON Schema conversion failed: ${conversionResult.error}`,
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    // Use the converted document for analysis
    doc = conversionResult.document;

    // Add conversion warnings
    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Convert GraphQL SDL to OpenAPI 3.1.x if needed
  if (doc.__graphql_sdl) {
    const graphqlContent = doc.__graphql_sdl;
    const conversionResult = convertGraphQLToOpenAPI(graphqlContent, fileName);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'graphql',
        version: 'SDL',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: false,
        formatDisplayName: 'GraphQL Schema (conversion failed)',
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: `GraphQL conversion failed: ${conversionResult.error}`,
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    // Use the converted document for analysis
    doc = conversionResult.document;

    // Add conversion warnings
    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Convert GraphQL introspection result to OpenAPI 3.1.x if needed
  if (isGraphQLIntrospection(doc)) {
    const conversionResult = convertGraphQLIntrospectionToOpenAPI(doc, fileName);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'graphql',
        version: 'introspection',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: false,
        formatDisplayName: 'GraphQL Introspection (conversion failed)',
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: `GraphQL introspection conversion failed: ${conversionResult.error}`,
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    // Use the converted document for analysis
    doc = conversionResult.document;

    // Add conversion warnings
    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Convert AsyncAPI 2.x / 3.x to OpenAPI 3.1–like document for import (#236)
  if (isAsyncAPI(doc)) {
    const conversionResult = convertAsyncAPIToOpenAPI(doc, fileName);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'asyncapi',
        version: doc.asyncapi || 'unknown',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: false,
        formatDisplayName: `AsyncAPI ${doc.asyncapi || 'unknown'} (conversion failed)`,
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: conversionResult.error ?? 'AsyncAPI conversion failed',
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    doc = conversionResult.document;

    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Convert RAML 0.8 / 1.0 to OpenAPI 3.1–like document for import (#237)
  if (isRAML(doc)) {
    const conversionResult = convertRAMLToOpenAPI(doc, fileName);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'raml',
        version: doc['#%RAML'] || '1.0',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: true,
        formatDisplayName: `RAML ${doc['#%RAML'] || '1.0'} (conversion failed)`,
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: conversionResult.error ?? 'RAML conversion failed',
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    doc = conversionResult.document;

    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Convert Protobuf (.proto) to OpenAPI 3.1–like document for import (#238)
  if (doc.__protobuf_content) {
    const protobufContent = doc.__protobuf_content;
    const conversionResult = convertProtobufToOpenAPI(protobufContent, fileName);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'protobuf',
        version: 'proto2/3',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: true,
        formatDisplayName: 'Protocol Buffers (conversion failed)',
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: conversionResult.error ?? 'Protobuf conversion failed',
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    doc = conversionResult.document;

    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Convert Thrift IDL (.thrift) to OpenAPI 3.1–like document for import (#240)
  if (doc.__thrift_content) {
    const thriftContent = doc.__thrift_content;
    const conversionResult = convertThriftToOpenAPI(thriftContent, fileName);

    if (!conversionResult.success) {
      return {
        isValid: false,
        format: 'thrift',
        version: 'IDL',
        syntax,
        syntaxValid: true,
        schemaValid: false,
        formatSupported: true,
        formatDisplayName: 'Apache Thrift (conversion failed)',
        metrics: {
          schemaCount: 0,
          propertyCount: 0,
          referenceCount: 0,
          pathCount: 0,
          externalReferences: [],
          circularReferences: [],
          customExtensions: [],
          compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 }
        },
        qualityScore: zeroQualityScore(),
        errors: [{
          type: 'error',
          message: conversionResult.error ?? 'Thrift conversion failed',
          severity: 'critical'
        }],
        warnings: [],
        unsupportedFeatures: [],
        document: null
      };
    }

    doc = conversionResult.document;

    conversionWarnings = [
      ...conversionWarnings,
      ...conversionResult.warnings.map(warning => ({
        type: 'warning' as const,
        message: warning,
        severity: 'low' as const
      }))
    ];
  }

  // Detect format (will now show OpenAPI 3.1.0 for converted specs)
  const formatDetection = detectFormat(doc);

  // For Arazzo without components.schemas, inject inferred schemas so metrics and preview work (#299)
  if (formatDetection.format === 'arazzo') {
    const inferred = inferArazzoSchemasFromWorkflows(doc);
    if (Object.keys(inferred).length > 0 && !doc.components?.schemas) {
      doc = { ...doc, components: { ...doc.components, schemas: inferred } };
    }
  }

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

  // Combine conversion warnings with analysis warnings
  const allWarnings = [...conversionWarnings, ...warnings];

  // Identify unsupported features for import compatibility (#573)
  // Append any 3.2-only constructs carried forward by the OA2 normalization layer (#3499).
  const unsupportedFeatures = [...identifyUnsupportedFeatures(doc), ...openapi32Constructs];

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
    warnings: allWarnings,
    unsupportedFeatures,
    document: doc
  };
}

/**
 * Quick metadata preview result
 */
export interface FileMetadataPreview {
  syntaxValid: boolean;
  syntax: 'json' | 'yaml' | 'graphql' | 'protobuf' | 'thrift';
  format: 'openapi' | 'swagger' | 'jsonschema' | 'graphql' | 'arazzo' | 'raml' | 'asyncapi' | 'protobuf' | 'avro' | 'thrift' | 'unknown';
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
    title: doc.info?.title || doc.title,
    description: doc.info?.description || doc.description,
    specVersion: doc.info?.version
  };
}
