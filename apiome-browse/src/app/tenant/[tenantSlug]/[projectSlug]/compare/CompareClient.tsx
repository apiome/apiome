'use client';

import { useState, useEffect, useCallback, useMemo, useRef, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { diffLines, type Change } from 'diff';
import { AppShell } from '../../../../components/AppShell';
import { Breadcrumb } from '../../../../components/Breadcrumb';
import { useTheme, specThemes } from '../../../../components/ThemeProvider';
import type { PublicVersionChangelogRow } from '../../../../../../lib/changelog/types';
import { findDiffLineIndexForPointer } from '../../../../../../lib/changelog/focus';
import {
  severityBadgeClasses,
  severityDotClasses,
  severityLabel,
} from '../../../../../../lib/changelog/group';

interface Project {
  id: string;
  name: string;
  tenant_name?: string;
}

interface Version {
  id: string;
  version_id: string;
}

type SpecFormat = 'openapi' | 'arazzo' | 'jsonschema';
type ViewMode = 'side-by-side' | 'unified';

interface CompareClientProps {
  project: Project;
  versions: Version[];
  /** Stored publish changelog rows for the project, newest first (CTG-3.2, #4476). */
  changelogs: PublicVersionChangelogRow[];
  tenantSlug: string;
  projectSlug: string;
  restApiBaseUrl: string;
  initialV1?: string;
  initialV2?: string;
  /** JSON Pointer (from a Changes-tab deep link) to scroll the diff to, best effort. */
  initialFocus?: string;
}

/** Normalize diff chunks into lines (handles trailing newline the same way `diff` emits values). */
function splitDiffLines(value: string): string[] {
  if (value === '') return [];
  const lines = value.split('\n');
  if (lines.length > 0 && lines[lines.length - 1] === '') {
    lines.pop();
  }
  return lines;
}

type PairSide = 'removed' | 'added' | 'unchanged' | 'gap';

interface PairedDiffLine {
  leftNum: number | null;
  rightNum: number | null;
  leftText: string;
  rightText: string;
  leftKind: PairSide;
  rightKind: PairSide;
}

/** One paired row per logical line so left/right panes stay vertically aligned. */
function buildPairedDiffLines(changes: Change[]): PairedDiffLine[] {
  const rows: PairedDiffLine[] = [];
  let leftNum = 0;
  let rightNum = 0;

  for (const part of changes) {
    const lines = splitDiffLines(part.value);
    if (part.removed) {
      for (const line of lines) {
        leftNum += 1;
        rows.push({
          leftNum,
          rightNum: null,
          leftText: line,
          rightText: '',
          leftKind: 'removed',
          rightKind: 'gap',
        });
      }
    } else if (part.added) {
      for (const line of lines) {
        rightNum += 1;
        rows.push({
          leftNum: null,
          rightNum,
          leftText: '',
          rightText: line,
          leftKind: 'gap',
          rightKind: 'added',
        });
      }
    } else {
      for (const line of lines) {
        leftNum += 1;
        rightNum += 1;
        rows.push({
          leftNum,
          rightNum,
          leftText: line,
          rightText: line,
          leftKind: 'unchanged',
          rightKind: 'unchanged',
        });
      }
    }
  }

  return rows;
}

function diffLineStats(changes: Change[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const part of changes) {
    const n = splitDiffLines(part.value).length;
    if (part.added) added += n;
    else if (part.removed) removed += n;
  }
  return { added, removed };
}

/** Diff mockup (`mockups/diff/side-by-side.html`): gradient fills + 3px accent border. */
const DIFF_ADDED =
  'bg-gradient-to-r from-emerald-500/10 via-emerald-500/[0.06] to-emerald-500/[0.02] dark:from-emerald-500/15 dark:via-emerald-500/8 dark:to-transparent border-l-[3px] border-l-ok/70';

const DIFF_REMOVED =
  'bg-gradient-to-r from-rose-500/10 via-rose-500/[0.06] to-rose-500/[0.02] dark:from-rose-500/15 dark:via-rose-500/8 dark:to-transparent border-l-[3px] border-l-danger/70';

const DIFF_PLACEHOLDER =
  'bg-[repeating-linear-gradient(45deg,transparent_0_6px,rgba(148,163,184,0.08)_6px_12px)] dark:bg-[repeating-linear-gradient(45deg,transparent_0_6px,rgba(71,85,105,0.18)_6px_12px)]';

const DIFF_ROWMono = 'font-mono text-xs leading-6';

export function CompareClient({
  project,
  versions,
  changelogs,
  tenantSlug,
  projectSlug,
  restApiBaseUrl,
  initialV1,
  initialV2,
  initialFocus,
}: CompareClientProps) {
  const router = useRouter();
  const { specTheme } = useTheme();
  const themeColors = specThemes[specTheme];

  const [format, setFormat] = useState<SpecFormat>('openapi');
  const [version1, setVersion1] = useState(initialV1 || versions[1]?.version_id || '');
  const [version2, setVersion2] = useState(initialV2 || versions[0]?.version_id || '');
  const [spec1, setSpec1] = useState<unknown>(null);
  const [spec2, setSpec2] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('side-by-side');
  const [diffResult, setDiffResult] = useState<Change[]>([]);

  const pairedLines = useMemo(() => buildPairedDiffLines(diffResult), [diffResult]);

  const diffStats = useMemo(() => diffLineStats(diffResult), [diffResult]);

  // The stored classification for the selected pair — the row published as v2 whose recorded
  // baseline is v1. Chips are sourced ONLY from this row; nothing is re-classified client-side.
  const storedChangelog = useMemo(
    () =>
      changelogs.find(
        (row) => row.versionLabel === version2 && row.baselineVersionLabel === version1
      ) ?? null,
    [changelogs, version1, version2]
  );

  // Best-effort focus target for a ?focus=<pointer> deep link: the first diff line that mentions
  // the pointer's last meaningful key. Both view modes enumerate lines in the same order, so one
  // index addresses the row in either panel.
  const focusIndex = useMemo(() => {
    if (!initialFocus || pairedLines.length === 0) return -1;
    const lineTexts = pairedLines.map((row) =>
      row.rightKind === 'gap' ? row.leftText : row.rightText
    );
    return findDiffLineIndexForPointer(lineTexts, initialFocus);
  }, [initialFocus, pairedLines]);

  const focusAppliedRef = useRef(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);

  useEffect(() => {
    if (focusAppliedRef.current || loading || focusIndex < 0) return;
    focusAppliedRef.current = true;
    setHighlightIndex(focusIndex);
    document.getElementById(`diff-row-${focusIndex}`)?.scrollIntoView({ block: 'center' });
    // Fire-and-forget: the highlight fades once, even if the effect never re-runs.
    setTimeout(() => setHighlightIndex(-1), 2500);
  }, [focusIndex, loading]);

  const loadSpecs = useCallback(async () => {
    if (!version1 || !version2) return;
    setLoading(true);
    setError(null);
    try {
      const endpoint = format === 'openapi' ? 'schema' : format === 'arazzo' ? 'arazzo' : 'json';
      const [response1, response2] = await Promise.all([
        fetch(`${restApiBaseUrl}/${endpoint}/${tenantSlug}/${projectSlug}/${version1}`),
        fetch(`${restApiBaseUrl}/${endpoint}/${tenantSlug}/${projectSlug}/${version2}`),
      ]);
      if (!response1.ok || !response2.ok) {
        throw new Error('Failed to load specifications');
      }
      const [data1, data2] = await Promise.all([response1.json(), response2.json()]);
      setSpec1(data1);
      setSpec2(data2);
      const content1 = JSON.stringify(data1, null, 2);
      const content2 = JSON.stringify(data2, null, 2);
      setDiffResult(diffLines(content1, content2));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [version1, version2, format, restApiBaseUrl, tenantSlug, projectSlug]);

  useEffect(() => {
    if (version1 && version2) {
      loadSpecs();
      router.push(`?v1=${version1}&v2=${version2}`, { scroll: false });
    }
  }, [version1, version2, format, loadSpecs, router]);

  if (versions.length < 2) {
    return (
      <AppShell containerSize="wide">
        <div className="space-y-6 py-8">
          <Breadcrumb
            items={[
              { label: project.tenant_name || tenantSlug, href: `/tenant/${tenantSlug}` },
              { label: project.name, href: `/tenant/${tenantSlug}/${projectSlug}` },
              { label: 'Compare' },
            ]}
          />
          <div className="rounded-lg border border-dashed border-border-strong bg-surface/40 p-12 text-center">
            <h3 className="text-xl font-semibold text-fg">
              Not enough versions
            </h3>
            <p className="mt-1 text-sm text-fg-muted">
              At least two published versions are required to compare.
            </p>
            <Link
              href={`/tenant/${tenantSlug}/${projectSlug}`}
              className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-accent-fg hover:text-accent-hover"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
              Back to project
            </Link>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell containerSize="wide">
      <div className="space-y-5 py-8">
        <Breadcrumb
          items={[
            { label: project.tenant_name || tenantSlug, href: `/tenant/${tenantSlug}` },
            { label: project.name, href: `/tenant/${tenantSlug}/${projectSlug}` },
            { label: 'Compare versions' },
          ]}
        />

        <header className="border-b border-border pb-4">
          <h1 className="flex flex-wrap items-center gap-2 text-3xl font-bold tracking-tight text-fg">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-blue-600 shadow-xs">
              <svg className="h-5 w-5 text-white" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"
                />
              </svg>
            </span>
            Compare versions
          </h1>
          <p className="mt-2 text-base text-fg-muted">
            Schema diff for <span className="font-medium text-fg">{project.name}</span> —
            aligned side-by-side rows match additions and removals line-for-line.
          </p>
        </header>

        <div className="rounded-lg border border-border bg-surface p-4 shadow-xs">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft/50 px-3 py-1.5">
                <span className="text-2xs font-semibold uppercase tracking-wider text-danger-fg">
                  Source
                </span>
                <select
                  value={version1}
                  onChange={(e) => setVersion1(e.target.value)}
                  className="max-w-[12rem] cursor-pointer bg-transparent font-mono text-sm font-semibold text-fg focus:outline-none"
                  aria-label="Source version"
                >
                  {versions.map((v) => (
                    <option key={v.id} value={v.version_id}>
                      v{v.version_id}
                    </option>
                  ))}
                </select>
              </div>

              <svg className="h-4 w-4 shrink-0 text-fg-subtle" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>

              <div className="flex items-center gap-2 rounded-md border border-ok/30 bg-ok-soft/50 px-3 py-1.5">
                <span className="text-2xs font-semibold uppercase tracking-wider text-ok-fg">
                  Target
                </span>
                <select
                  value={version2}
                  onChange={(e) => setVersion2(e.target.value)}
                  className="max-w-[12rem] cursor-pointer bg-transparent font-mono text-sm font-semibold text-fg focus:outline-none"
                  aria-label="Target version"
                >
                  {versions.map((v) => (
                    <option key={v.id} value={v.version_id}>
                      v{v.version_id}
                    </option>
                  ))}
                </select>
              </div>

              {!loading && !error && diffResult.length > 0 && (
                <>
                  <span className="hidden h-6 w-px bg-inset sm:inline-block" />
                  <DiffSummaryChip icon="plus" label="added" count={diffStats.added} variant="emerald" />
                  <DiffSummaryChip icon="minus" label="removed" count={diffStats.removed} variant="rose" />
                </>
              )}

              {/* Stored classification for this exact pair (CTG-3.2) — never re-derived here. */}
              {storedChangelog && (
                <>
                  {(storedChangelog.changelog?.counts?.breaking ?? 0) > 0 && (
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium ${severityBadgeClasses('breaking')}`}
                    >
                      <span className={`h-1.5 w-1.5 rounded-full ${severityDotClasses('breaking')}`}></span>
                      {storedChangelog.changelog?.counts?.breaking} breaking
                    </span>
                  )}
                  {storedChangelog.maxSeverity && (
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium ${severityBadgeClasses(storedChangelog.maxSeverity)}`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${severityDotClasses(storedChangelog.maxSeverity)}`}
                      ></span>
                      {severityLabel(storedChangelog.maxSeverity)} changes
                    </span>
                  )}
                </>
              )}
            </div>

            <div className="flex flex-wrap items-end gap-2">
              <Field label="Format">
                <Segmented
                  value={format}
                  options={[
                    { value: 'openapi', label: 'OpenAPI' },
                    { value: 'arazzo', label: 'Arazzo' },
                    { value: 'jsonschema', label: 'JSON Schema' },
                  ]}
                  onChange={(v) => setFormat(v as SpecFormat)}
                />
              </Field>
              <Field label="View">
                <Segmented
                  value={viewMode}
                  options={[
                    { value: 'side-by-side', label: 'Side by side' },
                    { value: 'unified', label: 'Unified' },
                  ]}
                  onChange={(v) => setViewMode(v as ViewMode)}
                />
              </Field>
            </div>
          </div>
        </div>

        {loading && (
          <div className="flex items-center justify-center rounded-lg border border-border bg-surface p-16 shadow-xs">
            <div className="flex items-center gap-3">
              <svg className="h-5 w-5 animate-spin text-accent-fg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-base text-fg-muted">Loading specifications...</span>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-danger/30 bg-danger-soft/60 p-5">
            <h3 className="text-base font-semibold text-danger-fg">
              Could not load specifications
            </h3>
            <p className="mt-1 text-sm text-danger-fg">{error}</p>
          </div>
        )}

        {!loading && !error && spec1 != null && spec2 != null && diffResult.length > 0 && (
          <>
            {viewMode === 'unified' ? (
              <UnifiedDiffPanel
                changes={diffResult}
                themeColors={themeColors}
                highlightIndex={highlightIndex}
              />
            ) : (
              <SideBySideDiffPanel
                pairedLines={pairedLines}
                version1={version1}
                version2={version2}
                themeColors={themeColors}
                highlightIndex={highlightIndex}
              />
            )}

            <DiffLegend />
          </>
        )}
      </div>
    </AppShell>
  );
}

/** Ring drawn over the row a ?focus deep link resolved to, cleared after a short beat. */
const DIFF_FOCUS_RING = 'ring-2 ring-inset ring-honey';

function SideBySideDiffPanel({
  pairedLines,
  version1,
  version2,
  themeColors,
  highlightIndex,
}: {
  pairedLines: PairedDiffLine[];
  version1: string;
  version2: string;
  themeColors: (typeof specThemes)[keyof typeof specThemes];
  highlightIndex: number;
}) {
  const neutralStyle = { backgroundColor: themeColors.bgColor, color: themeColors.textColor } as const;

  const halfClass = (kind: PairSide, side: 'left' | 'right'): string => {
    if (kind === 'gap') return DIFF_PLACEHOLDER;
    if (side === 'left' && kind === 'removed') return DIFF_REMOVED;
    if (side === 'right' && kind === 'added') return DIFF_ADDED;
    return '';
  };

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-xs">
      <div className="max-h-[min(70vh,720px)] min-h-[420px] overflow-auto">
        <div className="sticky top-0 z-10 grid grid-cols-2 border-b border-border bg-subtle text-xs">
          <div className="flex items-center gap-2 border-r border-border px-4 py-2">
            <svg className="h-3.5 w-3.5 shrink-0 text-danger-fg" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"
              />
            </svg>
            <span className="font-semibold font-mono text-fg">v{version1}</span>
            <span className="text-fg-subtle">·</span>
            <span className="font-semibold uppercase tracking-wider text-2xs text-danger-fg">
              Source
            </span>
          </div>
          <div className="flex items-center gap-2 px-4 py-2">
            <svg className="h-3.5 w-3.5 shrink-0 text-ok-fg" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"
              />
            </svg>
            <span className="font-semibold font-mono text-fg">v{version2}</span>
            <span className="text-fg-subtle">·</span>
            <span className="font-semibold uppercase tracking-wider text-2xs text-ok-fg">
              Target
            </span>
          </div>
        </div>

        {pairedLines.map((row, i) => {
          const leftTone = halfClass(row.leftKind, 'left');
          const rightTone = halfClass(row.rightKind, 'right');
          const leftNeutral = row.leftKind === 'unchanged';
          const rightNeutral = row.rightKind === 'unchanged';

          return (
            <div
              key={i}
              id={`diff-row-${i}`}
              className={`grid grid-cols-2 border-b border-border ${
                i === highlightIndex ? DIFF_FOCUS_RING : ''
              }`}
              style={{ minHeight: '1.5rem' }}
            >
              <div
                className={`flex min-h-[1.5rem] min-w-0 border-r border-border ${leftTone}`}
                style={leftNeutral ? neutralStyle : undefined}
              >
                <div
                  className={`w-[2.75rem] shrink-0 select-none border-r py-0.5 pr-2 text-right text-2xs tabular-nums ${
                    row.leftKind === 'removed'
                      ? 'border-danger/25 bg-danger/5 text-danger-fg/80'
                      : row.leftKind === 'gap'
                      ? 'border-border-strong/40 bg-overlay text-fg-subtle'
                      : 'border-border/80 bg-subtle/40 text-fg-muted'
                  }`}
                >
                  {row.leftNum ?? ''}
                </div>
                <div
                  className={`min-w-0 flex-1 overflow-x-auto whitespace-pre px-3 py-0.5 ${DIFF_ROWMono}`}
                  style={leftNeutral ? neutralStyle : undefined}
                >
                  {row.leftKind === 'removed' && (
                    <span className="mr-2 inline-block w-2 font-semibold text-danger-fg">−</span>
                  )}
                  {row.leftKind === 'unchanged' && <span className="mr-3 inline-block opacity-0">·</span>}
                  {row.leftKind === 'gap' ? '\u00A0' : row.leftText || '\u00A0'}
                </div>
              </div>

              <div
                className={`flex min-h-[1.5rem] min-w-0 ${rightTone}`}
                style={rightNeutral ? neutralStyle : undefined}
              >
                <div
                  className={`w-[2.75rem] shrink-0 select-none border-r py-0.5 pr-2 text-right text-2xs tabular-nums ${
                    row.rightKind === 'added'
                      ? 'border-ok/25 bg-ok/5 text-ok-fg/90'
                      : row.rightKind === 'gap'
                      ? 'border-border-strong/40 bg-overlay text-fg-subtle'
                      : 'border-border/80 bg-subtle/40 text-fg-muted'
                  }`}
                >
                  {row.rightNum ?? ''}
                </div>
                <div
                  className={`min-w-0 flex-1 overflow-x-auto whitespace-pre px-3 py-0.5 ${DIFF_ROWMono}`}
                  style={rightNeutral ? neutralStyle : undefined}
                >
                  {row.rightKind === 'added' && (
                    <span className="mr-2 inline-block w-2 font-semibold text-ok-fg">+</span>
                  )}
                  {row.rightKind === 'unchanged' && <span className="mr-3 inline-block opacity-0">·</span>}
                  {row.rightKind === 'gap' ? '\u00A0' : row.rightText || '\u00A0'}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function UnifiedDiffPanel({
  changes,
  themeColors,
  highlightIndex,
}: {
  changes: Change[];
  themeColors: (typeof specThemes)[keyof typeof specThemes];
  highlightIndex: number;
}) {
  const neutralStyle = { backgroundColor: themeColors.bgColor, color: themeColors.textColor } as const;
  let oldNum = 0;
  let newNum = 0;
  // Row counter matching buildPairedDiffLines' enumeration, so one focus index fits both views.
  let rowIndex = -1;

  const rows: ReactNode[] = [];
  changes.forEach((part, partIndex) => {
    const lines = splitDiffLines(part.value);
    lines.forEach((line, lineIndex) => {
      const key = `${partIndex}-${lineIndex}`;
      rowIndex += 1;
      const thisRowIndex = rowIndex;
      let oldGutter = '';
      let newGutter = '';
      let rowClass = '';
      let prefix: ReactNode = <span className="mr-3 inline-block w-2 opacity-0">·</span>;

      if (part.removed) {
        oldNum += 1;
        oldGutter = String(oldNum);
        rowClass = DIFF_REMOVED;
        prefix = <span className="mr-2 font-semibold text-danger-fg">−</span>;
      } else if (part.added) {
        newNum += 1;
        newGutter = String(newNum);
        rowClass = DIFF_ADDED;
        prefix = <span className="mr-2 font-semibold text-ok-fg">+</span>;
      } else {
        oldNum += 1;
        newNum += 1;
        oldGutter = String(oldNum);
        newGutter = String(newNum);
        prefix = <span className="mr-3 inline-block opacity-0">·</span>;
      }

      rows.push(
        <div
          key={key}
          id={`diff-row-${thisRowIndex}`}
          className={`flex min-h-[1.5rem] border-b border-border ${rowClass} ${
            thisRowIndex === highlightIndex ? DIFF_FOCUS_RING : ''
          }`}
          style={!part.added && !part.removed ? neutralStyle : undefined}
        >
          <div
            className={`w-[2.75rem] shrink-0 select-none border-r py-0.5 pr-2 text-right text-2xs tabular-nums ${
              part.removed
                ? 'border-danger/25 bg-danger/5 text-danger-fg/90'
                : 'border-border/80 bg-subtle/40 text-fg-muted'
            }`}
          >
            {oldGutter}
          </div>
          <div
            className={`w-[2.75rem] shrink-0 select-none border-r py-0.5 pr-2 text-right text-2xs tabular-nums ${
              part.added
                ? 'border-ok/25 bg-ok/5 text-ok-fg/90'
                : 'border-border/80 bg-subtle/40 text-fg-muted'
            }`}
          >
            {newGutter}
          </div>
          <div
            className={`min-w-0 flex-1 overflow-x-auto whitespace-pre px-3 py-0.5 ${DIFF_ROWMono}`}
            style={!part.added && !part.removed ? neutralStyle : undefined}
          >
            {prefix}
            {line || '\u00A0'}
          </div>
        </div>
      );
    });
  });

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-xs">
      <div className="sticky top-0 z-10 flex border-b border-border bg-subtle text-2xs font-semibold uppercase tracking-wider text-fg-muted">
        <div className="w-[2.75rem] shrink-0 border-r border-border px-2 py-2">Old</div>
        <div className="w-[2.75rem] shrink-0 border-r border-border px-2 py-2">New</div>
        <div className="flex-1 px-3 py-2">Unified</div>
      </div>
      <div className="max-h-[min(70vh,720px)] min-h-[420px] overflow-auto">{rows}</div>
    </div>
  );
}

function DiffLegend() {
  return (
    <div className="flex flex-wrap items-center justify-center gap-6 text-xs text-fg-muted">
      <div className="flex items-center gap-2">
        <span className={`h-6 w-10 rounded-xs border border-danger/70 ${DIFF_REMOVED}`} />
        <span>Removed</span>
      </div>
      <div className="flex items-center gap-2">
        <span className={`h-6 w-10 rounded-xs border border-ok/70 ${DIFF_ADDED}`} />
        <span>Added</span>
      </div>
      <div className="flex items-center gap-2">
        <span className={`h-6 w-10 rounded-xs border border-border ${DIFF_PLACEHOLDER}`} />
        <span>Padding (other side)</span>
      </div>
    </div>
  );
}

function DiffSummaryChip({
  icon,
  label,
  count,
  variant,
}: {
  icon: 'plus' | 'minus';
  label: string;
  count: number;
  variant: 'emerald' | 'rose';
}) {
  const cls =
    variant === 'emerald'
      ? 'border-ok/70 bg-ok-soft text-ok-fg'
      : 'border-danger/70 bg-danger-soft text-danger-fg';
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium ${cls}`}
    >
      {icon === 'plus' ? (
        <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
        </svg>
      ) : (
        <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M20 12H4" />
        </svg>
      )}
      <span className="tabular-nums">{count.toLocaleString()}</span>
      <span className="hidden sm:inline">{label}</span>
    </span>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-2xs font-semibold uppercase tracking-wider text-fg-muted">
        {label}
      </span>
      {children}
    </label>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex h-8 overflow-hidden rounded-md border border-border">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`border-l border-border px-3 py-1 text-xs font-medium transition-colors first:border-l-0 ${
            value === opt.value
              ? 'bg-accent text-fg-on-accent'
              : 'bg-surface text-fg-muted hover:bg-subtle'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
