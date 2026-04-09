/**
 * Git-like merge preview helpers: compare OpenAPI snapshots and classify conflicts.
 */

import { compareSchemas, type DiffSummary } from './schema-diff';

/** Compare target vs source specs: merge source into target; blocking = modified + removed paths. */
export function classifyMergeDiff(summary: DiffSummary): {
  canAutoMerge: boolean;
  conflictPaths: string[];
  addedSchemaNames: string[];
} {
  const conflictPaths = [
    ...summary.modified.map((d) => d.path),
    ...summary.removed.map((d) => d.path),
  ];
  const addedSchemaNames = summary.added
    .filter((d) => d.itemType === 'schema' && d.path.startsWith('schemas.'))
    .map((d) => d.path.replace(/^schemas\./, ''));
  return {
    canAutoMerge: conflictPaths.length === 0,
    conflictPaths,
    addedSchemaNames,
  };
}

export async function mergePreviewFromSpecs(targetSpecJson: string, sourceSpecJson: string): Promise<{
  summary: DiffSummary;
  classification: ReturnType<typeof classifyMergeDiff>;
}> {
  const summary = compareSchemas(targetSpecJson, sourceSpecJson);
  return { summary, classification: classifyMergeDiff(summary) };
}
