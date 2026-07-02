export type ImportSourceKind = 'openapi' | 'arazzo' | 'unknown';

export interface NormalizedProperty {
  name: string;
  data: any;
  description?: string | null;
  children?: NormalizedProperty[];
}

export interface NormalizedClass {
  name: string;
  /** Original schema key (e.g. components/schemas key) for $ref resolution when name is mapped (#753) */
  originalSchemaKey?: string;
  description?: string | null;
  schema?: any;
  properties: NormalizedProperty[];
}

/** Naming convention for classes (e.g. PascalCase) and properties (e.g. camelCase) during import (#581) */
export type NamingConvention = 'PascalCase' | 'camelCase' | 'snake_case' | 'kebab-case' | 'none';

export interface NormalizeOptions {
  selectedSchemas: string[];
  /** When true, apply naming convention to class and property names */
  applyNamingConvention?: boolean;
  /** Convention for class names (default: PascalCase) */
  classNamingConvention?: NamingConvention;
  /** Convention for property names (default: camelCase) */
  propertyNamingConvention?: NamingConvention;
  /** Optional map: schema key → class name. Applied before naming convention (#753). */
  classNameMap?: Record<string, string>;
  /** Optional prefix applied to every class name after naming convention (#755). */
  classPrefix?: string;
  /** Optional suffix applied to every class name after naming convention (#755). */
  classSuffix?: string;
  /**
   * Optional type mapping: external type key → internal JSON Schema for property data (#757).
   * Key format: "type" or "type:format" (e.g. "string", "string:date-time", "integer:int32").
   * When present, properties with that external type are replaced with the internal schema (required preserved).
   */
  typeMapping?: Record<string, any>;
  /**
   * Optional default values during import (#758). Key = external type key (e.g. "string", "integer").
   * When a property has no `default` in the spec, the value for its type key is applied as the property default.
   */
  defaultValues?: Record<string, any>;
  /**
   * Optional required field overrides during import (#759). Key = schema key (e.g. components/schemas key),
   * value = map of property name -> boolean (true = required, false = optional). Applied before naming convention.
   */
  requiredOverrides?: Record<string, Record<string, boolean>>;
  /**
   * Optional property description overrides during import (#760). Key = schema key (e.g. components/schemas key),
   * value = map of property name -> description string. Empty string clears the description. Applied before naming convention.
   */
  descriptionOverrides?: Record<string, Record<string, string>>;
  /**
   * When true, auto-generate example values for properties that do not have an example (#761).
   */
  generateExamples?: boolean;
}

export interface NormalizeResult {
  classes: NormalizedClass[];
  warnings: string[];
}

export interface Importer {
  kind: ImportSourceKind;
  normalize(input: { document: any; options: NormalizeOptions }): NormalizeResult;
}

const registry = new Map<ImportSourceKind, Importer>();

export function registerImporter(importer: Importer): void {
  registry.set(importer.kind, importer);
}

export function getImporter(kind: ImportSourceKind): Importer | undefined {
  return registry.get(kind);
}

import { openApiImporter } from './openapi';
import { arazzoImporter } from './arazzo';

registerImporter(openApiImporter);
registerImporter(arazzoImporter);

export { openApiImporter, arazzoImporter };

