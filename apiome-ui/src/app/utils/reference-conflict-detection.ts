/**
 * Detect reference conflicts (#584): broken or ambiguous references in OpenAPI/JSON Schema.
 * - Broken: $ref points to a schema that does not exist in the document.
 * - Ambiguous: external $ref (URL not resolved), or ref to a schema not selected for import.
 */

import type { ImportConflict } from '../components/ade/dashboard/ConflictReport';

/** In-document $ref path prefix for OpenAPI 3 */
const COMPONENTS_SCHEMAS = '#/components/schemas/';
/** In-document $ref path prefix for OpenAPI 2 (Swagger) */
const DEFINITIONS = '#/definitions/';

export interface ReferenceConflictInput {
  /** OpenAPI document (components.schemas or definitions) */
  document: any;
  /** Schema names to consider (e.g. all or selected) */
  schemaNames: string[];
  /**
   * When provided, refs that point to a schema not in this set are reported as ambiguous
   * (reference would be broken after partial import).
   */
  selectedSchemaNames?: string[];
}

interface RefOccurrence {
  ref: string;
  refName: string;
  /** Whether ref is in-document (#/components/schemas/X or #/definitions/X) */
  inDocument: boolean;
  /** Target schema name when inDocument (last path segment) */
  targetName: string | null;
}

/**
 * Collect all $ref values from a schema (recursive), with full ref string and parsed target name.
 */
function collectRefs(schema: unknown): RefOccurrence[] {
  const result: RefOccurrence[] = [];

  const walk = (obj: unknown) => {
    if (obj == null || typeof obj !== 'object') return;

    if (
      typeof obj === 'object' &&
      '$ref' in obj &&
      typeof (obj as { $ref: unknown }).$ref === 'string'
    ) {
      const ref = (obj as { $ref: string }).$ref;
      let inDocument = false;
      let targetName: string | null = null;
      if (ref.startsWith(COMPONENTS_SCHEMAS) || ref.startsWith(DEFINITIONS)) {
        inDocument = true;
        targetName = ref.split('/').pop() ?? null;
      }
      result.push({ ref, refName: ref.split('/').pop() ?? ref, inDocument, targetName });
      return;
    }

    const rec = obj as Record<string, unknown>;
    for (const key of Object.keys(rec)) {
      walk(rec[key]);
    }
  };

  walk(schema);
  return result;
}

/**
 * Build the set of schema names that exist in the document (OpenAPI 3 and/or 2).
 */
function getAvailableSchemaNames(document: any): Set<string> {
  const names = new Set<string>();
  const comp = document?.components?.schemas;
  const defs = document?.definitions;
  if (comp && typeof comp === 'object') {
    Object.keys(comp).forEach((k) => names.add(k));
  }
  if (defs && typeof defs === 'object') {
    Object.keys(defs).forEach((k) => names.add(k));
  }
  return names;
}

/** The references of one schema that will not resolve after import (#584). */
export interface ReferenceConflict {
  /** The schema whose properties hold the references. */
  schema: string;
  /** In-document targets (`#/components/schemas/X`, `#/definitions/X`) the document does not define. */
  broken: string[];
  /** `http(s)://` references, which the import keeps as written and never fetches. */
  external: string[];
  /** Defined targets left out of the import (only when `selectedSchemaNames` is given). */
  notSelected: string[];
}

/**
 * Find the references of each schema that will not resolve after import (#584), deduplicated.
 *
 * @param input The document, the schemas to check, and optionally the selection.
 * @returns One entry per schema with at least one broken, external or unselected reference, in the
 *   order of `schemaNames`.
 */
export function findReferenceConflicts(input: ReferenceConflictInput): ReferenceConflict[] {
  const { document, schemaNames, selectedSchemaNames } = input;
  const schemas = document?.components?.schemas || document?.definitions || {};
  const available = getAvailableSchemaNames(document);
  const selectedSet =
    selectedSchemaNames && selectedSchemaNames.length > 0 ? new Set(selectedSchemaNames) : null;

  const found: ReferenceConflict[] = [];
  for (const schemaName of new Set(schemaNames)) {
    const schema = schemas[schemaName];
    if (!schema) continue;
    const broken = new Set<string>();
    const external = new Set<string>();
    const notSelected = new Set<string>();
    for (const { ref, inDocument, targetName } of collectRefs(schema)) {
      if (ref.startsWith('http://') || ref.startsWith('https://')) {
        external.add(ref);
      } else if (inDocument && targetName !== null) {
        if (!available.has(targetName)) broken.add(targetName);
        else if (selectedSet && !selectedSet.has(targetName)) notSelected.add(targetName);
      }
    }
    if (broken.size + external.size + notSelected.size > 0) {
      found.push({ schema: schemaName, broken: [...broken], external: [...external], notSelected: [...notSelected] });
    }
  }
  return found;
}

/**
 * Detect reference conflicts (#584): broken and ambiguous references.
 * Returns one ImportConflict per schema and kind (broken, external, not selected).
 */
export function detectReferenceConflicts(input: ReferenceConflictInput): ImportConflict[] {
  const conflicts: ImportConflict[] = [];
  for (const { schema: schemaName, broken, external, notSelected } of findReferenceConflicts(input)) {
    if (broken.length > 0) {
      const detail =
        broken.length <= 3
          ? `Missing: ${broken.join(', ')}`
          : `Missing: ${broken.slice(0, 2).join(', ')} and ${broken.length - 2} more`;
      conflicts.push({
        kind: 'reference_conflict',
        schemaName,
        message: `Schema references non-existent schema(s).`,
        detail,
        impactIfResolved:
          'References will be updated or remapped so they point to valid schemas in the project.',
      });
    }
    if (external.length > 0) {
      const detail =
        external.length === 1
          ? external[0]
          : `${external.length} external URL(s) (e.g. ${external[0].slice(0, 40)}…)`;
      conflicts.push({
        kind: 'reference_conflict',
        schemaName,
        message: `Schema contains external $ref (URL); not resolved during import.`,
        detail,
        impactIfResolved:
          'Replace external references with in-document schemas or ensure the referenced URL is available.',
      });
    }
    if (notSelected.length > 0) {
      const detail =
        notSelected.length <= 3
          ? `Not selected for import: ${notSelected.join(', ')}`
          : `Not selected: ${notSelected.slice(0, 2).join(', ')} and ${notSelected.length - 2} more`;
      conflicts.push({
        kind: 'reference_conflict',
        schemaName,
        message: `Schema references type(s) not selected for import; reference may be broken after import.`,
        detail,
        impactIfResolved:
          'Select the referenced schemas for import, or the reference will need to be updated manually.',
      });
    }
  }
  return conflicts;
}
