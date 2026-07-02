'use client';

import type { ImportNamingConvention, ImportOptions } from './PreviewPanel';

/**
 * Which option groups to render.
 * - `naming`: apply-naming-convention toggle, class/property convention selects, class prefix/suffix.
 * - `flags`: generate-examples, dry-run, incremental-mode checkboxes.
 */
export type ImportOptionsSection = 'naming' | 'flags';

interface ImportOptionsFormProps {
  /** Current import options being edited. */
  options: ImportOptions;
  /** Apply a single option change. Mirrors PreviewPanel's handleOptionChange(key, value). */
  onOptionChange: <K extends keyof ImportOptions>(key: K, value: ImportOptions[K]) => void;
  /** Option groups to render, in order. Defaults to both `naming` then `flags`. */
  sections?: ImportOptionsSection[];
  /** Hide the dry-run checkbox (e.g. when the caller drives dry-run separately). */
  showDryRun?: boolean;
  /** Hide the incremental-mode checkbox. */
  showIncrementalMode?: boolean;
}

/**
 * Shared import-options editor used by both the Projects dashboard import dialog
 * (`PreviewPanel`) and the repository file import flow (`RepositoryFileImportMapping`).
 *
 * It owns no state: the parent holds the `ImportOptions` and applies each change
 * via `onOptionChange`, keeping a single source of truth. Markup/classes mirror
 * the original PreviewPanel layout so the dashboard import is visually unchanged.
 */
export function ImportOptionsForm({
  options,
  onOptionChange,
  sections = ['naming', 'flags'],
  showDryRun = true,
  showIncrementalMode = true,
}: ImportOptionsFormProps) {
  return (
    <>
      {sections.includes('naming') && (
        /* Naming convention enforcement (#581) */
        <div className="col-span-4 flex flex-col gap-3 pt-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={options.applyNamingConvention ?? true}
              onChange={(e) => onOptionChange('applyNamingConvention', e.target.checked)}
              className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
            />
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Apply naming convention
            </span>
          </label>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Convert class and property names to match your chosen conventions (e.g. PascalCase for classes, camelCase for properties).
          </p>
          {(options.applyNamingConvention ?? true) && (
            <div className="flex flex-wrap gap-4 pl-6">
              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Classes</label>
                <select
                  value={options.classNamingConvention ?? 'PascalCase'}
                  onChange={(e) => onOptionChange('classNamingConvention', e.target.value as ImportNamingConvention)}
                  className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                >
                  <option value="PascalCase">PascalCase</option>
                  <option value="camelCase">camelCase</option>
                  <option value="snake_case">snake_case</option>
                  <option value="kebab-case">kebab-case</option>
                  <option value="none">None (keep original)</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Properties</label>
                <select
                  value={options.propertyNamingConvention ?? 'camelCase'}
                  onChange={(e) => onOptionChange('propertyNamingConvention', e.target.value as ImportNamingConvention)}
                  className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                >
                  <option value="PascalCase">PascalCase</option>
                  <option value="camelCase">camelCase</option>
                  <option value="snake_case">snake_case</option>
                  <option value="kebab-case">kebab-case</option>
                  <option value="none">None (keep original)</option>
                </select>
              </div>
            </div>
          )}
          <div className="flex flex-wrap gap-4 pl-6 pt-2 border-t border-gray-100 dark:border-gray-700 mt-3 pt-3">
            <div className="flex-1 min-w-[140px]">
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Class name prefix</label>
              <input
                type="text"
                value={options.classPrefix ?? ''}
                onChange={(e) => onOptionChange('classPrefix', e.target.value)}
                placeholder="e.g. Api"
                className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
              />
            </div>
            <div className="flex-1 min-w-[140px]">
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Class name suffix</label>
              <input
                type="text"
                value={options.classSuffix ?? ''}
                onChange={(e) => onOptionChange('classSuffix', e.target.value)}
                placeholder="e.g. Dto"
                className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
              />
            </div>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 pl-6 mt-1">
            Prefix and suffix are applied to every imported class name (e.g. Api + User + Dto → ApiUserDto).
          </p>
        </div>
      )}

      {sections.includes('flags') && (
        <>
          {/* Generate examples for properties without examples (#761) */}
          <div className="col-span-4 flex items-start gap-3 pt-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={options.generateExamples ?? false}
                onChange={(e) => onOptionChange('generateExamples', e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
              />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Generate examples
              </span>
            </label>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Auto-generate example values for properties that don&apos;t have one (string, number, date, etc.).
            </p>
          </div>

          {showDryRun && (
            /* Dry run: preview without committing */
            <div className="col-span-4 flex items-start gap-3 pt-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.dryRun ?? false}
                  onChange={(e) => onOptionChange('dryRun', e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
                />
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Dry run (preview only)
                </span>
              </label>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Simulate the import and show what would be created. No project or data is saved.
              </p>
            </div>
          )}

          {showIncrementalMode && (
            /* Incremental mode: skip failures */
            <div className="col-span-4 flex items-start gap-3 pt-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={options.incrementalMode ?? false}
                  onChange={(e) => onOptionChange('incrementalMode', e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
                />
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Incremental mode (skip failures)
                </span>
              </label>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Import all available classes and skip any that fail. Changes are saved as each class is imported; no single transaction.
              </p>
            </div>
          )}
        </>
      )}
    </>
  );
}
