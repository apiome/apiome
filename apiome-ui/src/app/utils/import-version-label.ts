/**
 * Resolution strategy "Create version" (#590): import as a sub-version instead of failing.
 *
 * When an import lands as a new version of an existing project at a version label the project
 * already has (`1.0.0`), it is added as the next free **sub-version** instead — `1.0.0b`, then
 * `1.0.0c` … — so nothing existing is touched and the import does not fail on the duplicate.
 *
 * Shared by the import wizard's Changes step (which says which label the import will use) and the
 * importer (`lib/db/import-helper.ts`), which checks again at commit time in case the label was
 * taken in between. Pure: no React, no database.
 */

/** The letters a sub-version suffix is spelled from. `a` is the implicit original, so suffixes start at `b`. */
const LETTERS = 'abcdefghijklmnopqrstuvwxyz';

/**
 * The `n`-th sub-version suffix, starting at `b`: 0 → `b`, 24 → `z`, 25 → `bb`, 26 → `bc` …
 *
 * After `z` the suffix grows a letter (spreadsheet-column style, from `b`), so it never runs out and
 * a later sub-version always has a longer or later suffix.
 *
 * @param n Zero-based index.
 * @returns The suffix.
 */
export function subVersionSuffix(n: number): string {
  // Base-25 over b…z, so every suffix is made of the letters after `a`.
  let index = n;
  let suffix = '';
  do {
    suffix = LETTERS[1 + (index % 25)] + suffix;
    index = Math.floor(index / 25) - 1;
  } while (index >= 0);
  return suffix;
}

/**
 * The stem a sub-version is built on: the label without a sub-version suffix it already carries.
 *
 * `1.0.0b` → `1.0.0`, so importing `1.0.0b` again gives `1.0.0c` rather than `1.0.0bb`. Only a run
 * of lower-case letters after a digit counts as a suffix; `v2-beta` or `latest` are kept whole.
 *
 * @param label The requested version label.
 * @returns The stem.
 */
export function subVersionStem(label: string): string {
  const match = /^(.*\d)[a-z]+$/.exec(label);
  return match ? match[1] : label;
}

/**
 * The label an import at `requested` should use, given the labels the project already has.
 *
 * @param requested The version label the import asked for (trimmed).
 * @param taken The project's existing version labels.
 * @returns `requested` itself when it is free; otherwise the first free `<stem>b`, `<stem>c` …
 */
export function nextFreeVersionLabel(requested: string, taken: Iterable<string>): string {
  const label = requested.trim();
  const used = new Set(Array.from(taken, (t) => t.trim()));
  if (!used.has(label)) return label;
  const stem = subVersionStem(label);
  for (let n = 0; ; n += 1) {
    const candidate = `${stem}${subVersionSuffix(n)}`;
    if (!used.has(candidate)) return candidate;
  }
}

/** What the Changes step says about the version the import will create. */
export interface ImportVersionPlan {
  /** The label the reader asked for on Preview. */
  requested: string;
  /** The label the import will use: `requested`, or the sub-version that replaces it. */
  label: string;
  /** True when `requested` is already a version of the project. */
  taken: boolean;
}

/**
 * Plan the version label for an import into an existing project.
 *
 * @param requested The label from Preview.
 * @param existingLabels The project's live version labels (REST `existing_version_labels`).
 * @returns The plan.
 */
export function planImportVersion(requested: string, existingLabels: readonly string[] | undefined): ImportVersionPlan {
  const label = nextFreeVersionLabel(requested, existingLabels ?? []);
  return { requested: requested.trim(), label, taken: label !== requested.trim() };
}
