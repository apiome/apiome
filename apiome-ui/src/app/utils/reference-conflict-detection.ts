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

/**
 * Detect reference conflicts (#584): broken and ambiguous references.
 * Returns one ImportConflict per schema that has at least one broken or ambiguous reference.
 */
export function detectReferenceConflicts(input: ReferenceConflictInput): ImportConflict[] {
  const { document, schemaNames, selectedSchemaNames } = input;
  const schemas = document?.components?.schemas || document?.definitions || {};
  const available = getAvailableSchemaNames(document);
  const selectedSet =
    selectedSchemaNames && selectedSchemaNames.length > 0
      ? new Set(selectedSchemaNames)
      : null;

  const conflicts: ImportConflict[] = [];
  const nameSet = new Set(schemaNames);

  for (const schemaName of nameSet) {
    const schema = schemas[schemaName];
    if (!schema) continue;

    const refs = collectRefs(schema);
    const broken: string[] = [];
    const external: string[] = [];
    const notSelected: string[] = [];

    for (const { ref, inDocument, targetName } of refs) {
      if (ref.startsWith('http://') || ref.startsWith('https://')) {
        external.push(ref);
        continue;
      }
      if (inDocument && targetName !== null) {
        if (!available.has(targetName)) {
          broken.push(targetName);
        } else if (selectedSet && !selectedSet.has(targetName)) {
          notSelected.push(targetName);
        }
      }
    }

    // Dedupe for cleaner messages
    const brokenUnique = [...new Set(broken)];
    const externalUnique = [...new Set(external)];
    const notSelectedUnique = [...new Set(notSelected)];

    if (brokenUnique.length > 0) {
      const detail =
        brokenUnique.length <= 3
          ? `Missing: ${brokenUnique.join(', ')}`
          : `Missing: ${brokenUnique.slice(0, 2).join(', ')} and ${brokenUnique.length - 2} more`;
      conflicts.push({
        kind: 'reference_conflict',
        schemaName,
        message: `Schema references non-existent schema(s).`,
        detail,
        impactIfResolved:
          'References will be updated or remapped so they point to valid schemas in the project.',
      });
    }
    if (externalUnique.length > 0) {
      const detail =
        externalUnique.length === 1
          ? externalUnique[0]
          : `${externalUnique.length} external URL(s) (e.g. ${externalUnique[0].slice(0, 40)}…)`;
      conflicts.push({
        kind: 'reference_conflict',
        schemaName,
        message: `Schema contains external $ref (URL); not resolved during import.`,
        detail,
        impactIfResolved:
          'Replace external references with in-document schemas or ensure the referenced URL is available.',
      });
    }
    if (notSelectedUnique.length > 0) {
      const detail =
        notSelectedUnique.length <= 3
          ? `Not selected for import: ${notSelectedUnique.join(', ')}`
          : `Not selected: ${notSelectedUnique.slice(0, 2).join(', ')} and ${notSelectedUnique.length - 2} more`;
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
