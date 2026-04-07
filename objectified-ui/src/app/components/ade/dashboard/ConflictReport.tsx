'use client';

import { AlertTriangle, FileWarning, Link2Off, Type, Shuffle, Package, Download } from 'lucide-react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../../ui/Collapsible';
import { useState, useCallback } from 'react';

/**
 * Conflict types detected during import (#582–#586, #596).
 * duplicate_schema: same schema name exists with a different definition (#582)
 * property_conflict: incompatible property definitions (#583)
 * reference_conflict: broken or ambiguous references (#584)
 * type_mismatch: incompatible type assignments (#585)
 * semantic_conflict: logically incompatible constraints (#586)
 */
export type ImportConflictKind =
  | 'duplicate_schema'
  | 'property_conflict'
  | 'reference_conflict'
  | 'type_mismatch'
  | 'semantic_conflict';

export interface ImportConflict {
  kind: ImportConflictKind;
  /** Schema or resource name (e.g. class/schema name) */
  schemaName: string;
  /** Short human-readable description */
  message: string;
  /** Optional detail (e.g. property name, path) */
  detail?: string;
  /** What will change if this conflict is resolved (#597) */
  impactIfResolved?: string;
}

const CONFLICT_KIND_LABELS: Record<ImportConflictKind, string> = {
  duplicate_schema: 'Duplicate schema (same name, different definition)',
  property_conflict: 'Property conflict',
  reference_conflict: 'Reference conflict',
  type_mismatch: 'Type mismatch',
  semantic_conflict: 'Semantic conflict',
};

const CONFLICT_KIND_ICONS: Record<ImportConflictKind, typeof Package> = {
  duplicate_schema: Package,
  property_conflict: FileWarning,
  reference_conflict: Link2Off,
  type_mismatch: Type,
  semantic_conflict: Shuffle,
};

/** Default impact description when conflict is resolved (#597). Exported for unit tests. */
export const DEFAULT_IMPACT_IF_RESOLVED: Record<ImportConflictKind, string> = {
  duplicate_schema: 'If renamed: a new class is created and the existing one is unchanged. If overwritten: the existing class is replaced by the imported definition.',
  property_conflict: 'The chosen property definition will be applied; the other will be discarded or merged per strategy.',
  reference_conflict: 'References will be updated or remapped so they point to valid schemas in the project.',
  type_mismatch: 'The chosen type will be applied; property type will be updated in the imported schema.',
  semantic_conflict: 'The chosen constraints or semantics will be applied; conflicting rules will be updated.',
};

/** Options for markdown export (#598). */
export interface ConflictReportMarkdownOptions {
  /** Document title (default: "Import Conflict Report") */
  title?: string;
  /** Export timestamp for header/filename (default: new Date().toISOString()) */
  exportedAt?: string;
}

/**
 * Build a markdown document from the conflict report for review (#598).
 * Exported for tests and reuse.
 */
export function conflictReportToMarkdown(
  conflicts: ImportConflict[],
  options: ConflictReportMarkdownOptions = {}
): string {
  const { title = 'Import Conflict Report', exportedAt = new Date().toISOString() } = options;

  const byKind = conflicts.reduce<Record<ImportConflictKind, number>>(
    (acc, c) => {
      acc[c.kind] = (acc[c.kind] ?? 0) + 1;
      return acc;
    },
    {
      duplicate_schema: 0,
      property_conflict: 0,
      reference_conflict: 0,
      type_mismatch: 0,
      semantic_conflict: 0,
    }
  );

  const lines: string[] = [
    `# ${title}`,
    '',
    `**Exported:** ${exportedAt}`,
    `**Total conflicts:** ${conflicts.length}`,
    '',
    '## Summary by type',
    '',
    '| Conflict type | Count |',
    '|---------------|-------|',
    ...(Object.entries(byKind) as [ImportConflictKind, number][])
      .filter(([, count]) => count > 0)
      .map(([kind, count]) => `| ${CONFLICT_KIND_LABELS[kind]} | ${count} |`),
    '',
    '## Conflicts',
    '',
    '| Schema / Resource | Conflict type | Description | What will change if resolved |',
    '|-------------------|---------------|--------------|------------------------------|',
  ];

  for (const c of conflicts) {
    const impact = c.impactIfResolved ?? DEFAULT_IMPACT_IF_RESOLVED[c.kind];
    const desc = c.detail ? `${c.message}\n\n_${c.detail}_` : c.message;
    const descCell = desc.replace(/\|/g, '\\|').replace(/\n/g, ' ');
    const impactCell = impact.replace(/\|/g, '\\|').replace(/\n/g, ' ');
    lines.push(`| ${c.schemaName} | ${CONFLICT_KIND_LABELS[c.kind]} | ${descCell} | ${impactCell} |`);
  }

  lines.push('');
  return lines.join('\n');
}

/** Default filename for conflict report markdown export (#598). */
export function getConflictReportMarkdownFilename(exportedAt?: string): string {
  const ts = exportedAt ? new Date(exportedAt) : new Date();
  const iso = ts.toISOString().replace(/[:.]/g, '-').slice(0, 19);
  return `conflict-report-${iso}.md`;
}

interface ConflictReportProps {
  conflicts: ImportConflict[];
  /** When true, the report section is expanded by default */
  defaultOpen?: boolean;
  className?: string;
  /** When set, duplicate-schema rows include a control to open the schema diff dialog (#298). */
  onViewDuplicateSchemaDiff?: (schemaName: string) => void;
}

/**
 * Conflict Report (#596): overview of all detected conflicts during import.
 * Renders a summary and a table of conflicts by type and schema.
 */
export function ConflictReport({
  conflicts,
  defaultOpen = true,
  className = '',
  onViewDuplicateSchemaDiff,
}: ConflictReportProps) {
  const [open, setOpen] = useState(defaultOpen);

  const handleExportMarkdown = useCallback(() => {
    const exportedAt = new Date().toISOString();
    const md = conflictReportToMarkdown(conflicts, { exportedAt });
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    try {
      const a = document.createElement('a');
      a.href = url;
      a.download = getConflictReportMarkdownFilename(exportedAt);
      a.click();
    } finally {
      URL.revokeObjectURL(url);
    }
  }, [conflicts]);

  if (conflicts.length === 0) return null;

  const byKind = conflicts.reduce<Record<ImportConflictKind, number>>(
    (acc, c) => {
      acc[c.kind] = (acc[c.kind] ?? 0) + 1;
      return acc;
    },
    {
      duplicate_schema: 0,
      property_conflict: 0,
      reference_conflict: 0,
      type_mismatch: 0,
      semantic_conflict: 0,
    }
  );

  const kindSummary = (Object.entries(byKind) as [ImportConflictKind, number][])
    .filter(([, count]) => count > 0)
    .map(([kind, count]) => ({ kind, count }));

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-xl border border-amber-200 dark:border-amber-800 ${className}`}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="w-full flex items-center justify-between p-4 text-left hover:bg-amber-50/50 dark:hover:bg-amber-900/10 rounded-t-xl transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400">
                <AlertTriangle className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Conflict Report
                </h3>
                <p className="text-sm text-amber-700 dark:text-amber-300 mt-0.5">
                  {conflicts.length} conflict{conflicts.length !== 1 ? 's' : ''} detected — review before importing
                </p>
              </div>
            </div>
            <span className="text-2xl font-bold text-amber-600 dark:text-amber-400 tabular-nums">
              {conflicts.length}
            </span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="border-t border-amber-200 dark:border-amber-800 px-4 pb-4 pt-2">
            {/* Summary by type */}
            <div className="flex flex-wrap gap-2 mb-4">
              {kindSummary.map(({ kind, count }) => {
                const Icon = CONFLICT_KIND_ICONS[kind];
                return (
                  <span
                    key={kind}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-100 dark:bg-amber-900/40 border border-amber-300 dark:border-amber-700 text-xs font-medium text-amber-800 dark:text-amber-200"
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {count} {CONFLICT_KIND_LABELS[kind].toLowerCase()}{count !== 1 ? 's' : ''}
                  </span>
                );
              })}
            </div>

            {/* Export as Markdown (#598) */}
            <div className="mb-4">
              <button
                type="button"
                onClick={handleExportMarkdown}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200 text-sm font-medium hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors"
              >
                <Download className="h-4 w-4" />
                Export as Markdown
              </button>
            </div>

            {/* Impact analysis (#597): what will change if resolved */}
            <div className="mb-4">
              <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                Impact if resolved
              </h4>
              <p className="text-xs text-gray-600 dark:text-gray-400">
                Below, each conflict includes what will change when you resolve it (e.g. by renaming, overwriting, or applying a resolution strategy).
              </p>
            </div>

            {/* Table of conflicts */}
            <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                    <th className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300">
                      Schema / Resource
                    </th>
                    <th className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300">
                      Conflict type
                    </th>
                    <th className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300">
                      Description
                    </th>
                    <th className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300 min-w-[200px]">
                      What will change if resolved
                    </th>
                    {onViewDuplicateSchemaDiff && (
                      <th className="text-left py-2.5 px-3 font-semibold text-gray-700 dark:text-gray-300 whitespace-nowrap">
                        Diff
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {conflicts.map((c, idx) => {
                    const Icon = CONFLICT_KIND_ICONS[c.kind];
                    const impact = c.impactIfResolved ?? DEFAULT_IMPACT_IF_RESOLVED[c.kind];
                    return (
                      <tr
                        key={`${c.schemaName}-${c.kind}-${idx}`}
                        className="border-b border-gray-100 dark:border-gray-800 last:border-0"
                      >
                        <td className="py-2 px-3 font-medium text-gray-900 dark:text-white">
                          {c.schemaName}
                        </td>
                        <td className="py-2 px-3">
                          <span className="inline-flex items-center gap-1.5 text-amber-700 dark:text-amber-300">
                            <Icon className="h-4 w-4 shrink-0" />
                            {CONFLICT_KIND_LABELS[c.kind]}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-gray-600 dark:text-gray-400">
                          {c.message}
                          {c.detail && (
                            <span className="block text-xs text-gray-500 dark:text-gray-500 mt-0.5">
                              {c.detail}
                            </span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-gray-600 dark:text-gray-400 text-xs">
                          {impact}
                        </td>
                        {onViewDuplicateSchemaDiff && (
                          <td className="py-2 px-3">
                            {c.kind === 'duplicate_schema' ? (
                              <button
                                type="button"
                                onClick={() => onViewDuplicateSchemaDiff(c.schemaName)}
                                className="rounded-md border border-indigo-300 bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-800 hover:bg-indigo-100 dark:border-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-200 dark:hover:bg-indigo-900/50"
                              >
                                Schema diff
                              </button>
                            ) : (
                              <span className="text-gray-400 dark:text-gray-600">—</span>
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
