'use client';

import { useState, useEffect, useCallback, useMemo, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { diffLines, type Change } from 'diff';
import { AppShell } from '../../../../components/AppShell';
import { Breadcrumb } from '../../../../components/Breadcrumb';
import { useTheme, specThemes } from '../../../../components/ThemeProvider';

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
  tenantSlug: string;
  projectSlug: string;
  restApiBaseUrl: string;
  initialV1?: string;
  initialV2?: string;
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
  'bg-gradient-to-r from-emerald-500/10 via-emerald-500/[0.06] to-emerald-500/[0.02] dark:from-emerald-500/15 dark:via-emerald-500/8 dark:to-transparent border-l-[3px] border-l-emerald-500/70';

const DIFF_REMOVED =
  'bg-gradient-to-r from-rose-500/10 via-rose-500/[0.06] to-rose-500/[0.02] dark:from-rose-500/15 dark:via-rose-500/8 dark:to-transparent border-l-[3px] border-l-rose-500/70';

const DIFF_PLACEHOLDER =
  'bg-[repeating-linear-gradient(45deg,transparent_0_6px,rgba(148,163,184,0.08)_6px_12px)] dark:bg-[repeating-linear-gradient(45deg,transparent_0_6px,rgba(71,85,105,0.18)_6px_12px)]';

const DIFF_ROWMono = 'font-mono text-[12px] leading-6';

export function CompareClient({
  project,
  versions,
  tenantSlug,
  projectSlug,
  restApiBaseUrl,
  initialV1,
  initialV2,
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
          <div className="rounded-xl border border-dashed border-zinc-300 bg-white/40 p-12 text-center dark:border-zinc-700 dark:bg-zinc-900/30">
            <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
              Not enough versions
            </h3>
            <p className="mt-1 text-[13px] text-zinc-600 dark:text-zinc-400">
              At least two published versions are required to compare.
            </p>
            <Link
              href={`/tenant/${tenantSlug}/${projectSlug}`}
              className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--brand-soft-text)] hover:text-[var(--brand-hover)]"
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

        <header className="border-b border-zinc-200 pb-4 dark:border-zinc-700">
          <h1 className="flex flex-wrap items-center gap-2 text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--brand)] to-blue-600 shadow-xs">
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
          <p className="mt-2 text-[14px] text-zinc-600 dark:text-zinc-400">
            Schema diff for <span className="font-medium text-zinc-800 dark:text-zinc-200">{project.name}</span> —
            aligned side-by-side rows match additions and removals line-for-line.
          </p>
        </header>

        <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-2 rounded-md border border-rose-200 bg-rose-50/50 px-3 py-1.5 dark:border-rose-800/60 dark:bg-rose-900/10">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-rose-600 dark:text-rose-400">
                  Source
                </span>
                <select
                  value={version1}
                  onChange={(e) => setVersion1(e.target.value)}
                  className="max-w-[12rem] cursor-pointer bg-transparent font-mono text-[13px] font-semibold text-zinc-900 focus:outline-none dark:text-zinc-100"
                  aria-label="Source version"
                >
                  {versions.map((v) => (
                    <option key={v.id} value={v.version_id}>
                      v{v.version_id}
                    </option>
                  ))}
                </select>
              </div>

              <svg className="h-4 w-4 shrink-0 text-zinc-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>

              <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50/50 px-3 py-1.5 dark:border-emerald-800/60 dark:bg-emerald-900/10">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                  Target
                </span>
                <select
                  value={version2}
                  onChange={(e) => setVersion2(e.target.value)}
                  className="max-w-[12rem] cursor-pointer bg-transparent font-mono text-[13px] font-semibold text-zinc-900 focus:outline-none dark:text-zinc-100"
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
                  <span className="hidden h-6 w-px bg-zinc-200 sm:inline-block dark:bg-zinc-700" />
                  <DiffSummaryChip icon="plus" label="added" count={diffStats.added} variant="emerald" />
                  <DiffSummaryChip icon="minus" label="removed" count={diffStats.removed} variant="rose" />
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
          <div className="flex items-center justify-center rounded-xl border border-zinc-200 bg-white p-16 shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-center gap-3">
              <svg className="h-5 w-5 animate-spin text-[var(--brand)]" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-sm text-zinc-600 dark:text-zinc-400">Loading specifications...</span>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-5 dark:border-rose-900/50 dark:bg-rose-950/20">
            <h3 className="text-sm font-semibold text-rose-900 dark:text-rose-200">
              Could not load specifications
            </h3>
            <p className="mt-1 text-[13px] text-rose-800 dark:text-rose-300/90">{error}</p>
          </div>
        )}

        {!loading && !error && spec1 != null && spec2 != null && diffResult.length > 0 && (
          <>
            {viewMode === 'unified' ? (
              <UnifiedDiffPanel changes={diffResult} themeColors={themeColors} />
            ) : (
              <SideBySideDiffPanel
                pairedLines={pairedLines}
                version1={version1}
                version2={version2}
                themeColors={themeColors}
              />
            )}

            <DiffLegend />
          </>
        )}
      </div>
    </AppShell>
  );
}

function SideBySideDiffPanel({
  pairedLines,
  version1,
  version2,
  themeColors,
}: {
  pairedLines: PairedDiffLine[];
  version1: string;
  version2: string;
  themeColors: (typeof specThemes)[keyof typeof specThemes];
}) {
  const neutralStyle = { backgroundColor: themeColors.bgColor, color: themeColors.textColor } as const;

  const halfClass = (kind: PairSide, side: 'left' | 'right'): string => {
    if (kind === 'gap') return DIFF_PLACEHOLDER;
    if (side === 'left' && kind === 'removed') return DIFF_REMOVED;
    if (side === 'right' && kind === 'added') return DIFF_ADDED;
    return '';
  };

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-700 dark:bg-zinc-900/30">
      <div className="max-h-[min(70vh,720px)] min-h-[420px] overflow-auto">
        <div className="sticky top-0 z-10 grid grid-cols-2 border-b border-zinc-200 bg-zinc-50 text-xs dark:border-zinc-700 dark:bg-zinc-800/60">
          <div className="flex items-center gap-2 border-r border-zinc-200 px-4 py-2 dark:border-zinc-700">
            <svg className="h-3.5 w-3.5 shrink-0 text-rose-500" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"
              />
            </svg>
            <span className="font-semibold font-mono text-zinc-800 dark:text-zinc-100">v{version1}</span>
            <span className="text-zinc-400">·</span>
            <span className="font-semibold uppercase tracking-wider text-[10px] text-rose-600 dark:text-rose-400">
              Source
            </span>
          </div>
          <div className="flex items-center gap-2 px-4 py-2">
            <svg className="h-3.5 w-3.5 shrink-0 text-emerald-500" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"
              />
            </svg>
            <span className="font-semibold font-mono text-zinc-800 dark:text-zinc-100">v{version2}</span>
            <span className="text-zinc-400">·</span>
            <span className="font-semibold uppercase tracking-wider text-[10px] text-emerald-600 dark:text-emerald-400">
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
              className="grid grid-cols-2 border-b border-zinc-100 dark:border-zinc-800/80"
              style={{ minHeight: '1.5rem' }}
            >
              <div
                className={`flex min-h-[1.5rem] min-w-0 border-r border-zinc-200 dark:border-zinc-700 ${leftTone}`}
                style={leftNeutral ? neutralStyle : undefined}
              >
                <div
                  className={`w-[2.75rem] shrink-0 select-none border-r py-0.5 pr-2 text-right text-[11px] tabular-nums ${
                    row.leftKind === 'removed'
                      ? 'border-rose-400/25 bg-rose-500/5 text-rose-700/80 dark:border-rose-500/20 dark:text-rose-300/90'
                      : row.leftKind === 'gap'
                      ? 'border-zinc-300/40 bg-black/[0.02] text-zinc-400 dark:border-zinc-600/40 dark:bg-white/[0.03]'
                      : 'border-zinc-200/80 bg-zinc-100/40 text-zinc-500 dark:border-zinc-700/80 dark:bg-zinc-800/40 dark:text-zinc-400'
                  }`}
                >
                  {row.leftNum ?? ''}
                </div>
                <div
                  className={`min-w-0 flex-1 overflow-x-auto whitespace-pre px-3 py-0.5 ${DIFF_ROWMono}`}
                  style={leftNeutral ? neutralStyle : undefined}
                >
                  {row.leftKind === 'removed' && (
                    <span className="mr-2 inline-block w-2 font-semibold text-rose-600 dark:text-rose-400">−</span>
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
                  className={`w-[2.75rem] shrink-0 select-none border-r py-0.5 pr-2 text-right text-[11px] tabular-nums ${
                    row.rightKind === 'added'
                      ? 'border-emerald-400/25 bg-emerald-500/5 text-emerald-800/90 dark:border-emerald-500/20 dark:text-emerald-300/90'
                      : row.rightKind === 'gap'
                      ? 'border-zinc-300/40 bg-black/[0.02] text-zinc-400 dark:border-zinc-600/40 dark:bg-white/[0.03]'
                      : 'border-zinc-200/80 bg-zinc-100/40 text-zinc-500 dark:border-zinc-700/80 dark:bg-zinc-800/40 dark:text-zinc-400'
                  }`}
                >
                  {row.rightNum ?? ''}
                </div>
                <div
                  className={`min-w-0 flex-1 overflow-x-auto whitespace-pre px-3 py-0.5 ${DIFF_ROWMono}`}
                  style={rightNeutral ? neutralStyle : undefined}
                >
                  {row.rightKind === 'added' && (
                    <span className="mr-2 inline-block w-2 font-semibold text-emerald-600 dark:text-emerald-400">+</span>
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
}: {
  changes: Change[];
  themeColors: (typeof specThemes)[keyof typeof specThemes];
}) {
  const neutralStyle = { backgroundColor: themeColors.bgColor, color: themeColors.textColor } as const;
  let oldNum = 0;
  let newNum = 0;

  const rows: ReactNode[] = [];
  changes.forEach((part, partIndex) => {
    const lines = splitDiffLines(part.value);
    lines.forEach((line, lineIndex) => {
      const key = `${partIndex}-${lineIndex}`;
      let oldGutter = '';
      let newGutter = '';
      let rowClass = '';
      let prefix: ReactNode = <span className="mr-3 inline-block w-2 opacity-0">·</span>;

      if (part.removed) {
        oldNum += 1;
        oldGutter = String(oldNum);
        rowClass = DIFF_REMOVED;
        prefix = <span className="mr-2 font-semibold text-rose-600 dark:text-rose-400">−</span>;
      } else if (part.added) {
        newNum += 1;
        newGutter = String(newNum);
        rowClass = DIFF_ADDED;
        prefix = <span className="mr-2 font-semibold text-emerald-600 dark:text-emerald-400">+</span>;
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
          className={`flex min-h-[1.5rem] border-b border-zinc-100 dark:border-zinc-800/80 ${rowClass}`}
          style={!part.added && !part.removed ? neutralStyle : undefined}
        >
          <div
            className={`w-[2.75rem] shrink-0 select-none border-r py-0.5 pr-2 text-right text-[11px] tabular-nums ${
              part.removed
                ? 'border-rose-400/25 bg-rose-500/5 text-rose-800/90 dark:text-rose-300/90'
                : 'border-zinc-200/80 bg-zinc-100/40 text-zinc-500 dark:border-zinc-700/80 dark:bg-zinc-800/40 dark:text-zinc-400'
            }`}
          >
            {oldGutter}
          </div>
          <div
            className={`w-[2.75rem] shrink-0 select-none border-r py-0.5 pr-2 text-right text-[11px] tabular-nums ${
              part.added
                ? 'border-emerald-400/25 bg-emerald-500/5 text-emerald-900/90 dark:text-emerald-300/90'
                : 'border-zinc-200/80 bg-zinc-100/40 text-zinc-500 dark:border-zinc-700/80 dark:bg-zinc-800/40 dark:text-zinc-400'
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
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-700 dark:bg-zinc-900/30">
      <div className="sticky top-0 z-10 flex border-b border-zinc-200 bg-zinc-50 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-400">
        <div className="w-[2.75rem] shrink-0 border-r border-zinc-200 px-2 py-2 dark:border-zinc-700">Old</div>
        <div className="w-[2.75rem] shrink-0 border-r border-zinc-200 px-2 py-2 dark:border-zinc-700">New</div>
        <div className="flex-1 px-3 py-2">Unified</div>
      </div>
      <div className="max-h-[min(70vh,720px)] min-h-[420px] overflow-auto">{rows}</div>
    </div>
  );
}

function DiffLegend() {
  return (
    <div className="flex flex-wrap items-center justify-center gap-6 text-[12px] text-zinc-600 dark:text-zinc-400">
      <div className="flex items-center gap-2">
        <span className={`h-6 w-10 rounded border border-rose-300/70 dark:border-rose-700/60 ${DIFF_REMOVED}`} />
        <span>Removed</span>
      </div>
      <div className="flex items-center gap-2">
        <span className={`h-6 w-10 rounded border border-emerald-300/70 dark:border-emerald-700/60 ${DIFF_ADDED}`} />
        <span>Added</span>
      </div>
      <div className="flex items-center gap-2">
        <span className={`h-6 w-10 rounded border border-zinc-200 dark:border-zinc-600 ${DIFF_PLACEHOLDER}`} />
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
      ? 'border-emerald-200/70 bg-emerald-50 text-emerald-800 dark:border-emerald-800/60 dark:bg-emerald-900/20 dark:text-emerald-300'
      : 'border-rose-200/70 bg-rose-50 text-rose-800 dark:border-rose-800/60 dark:bg-rose-900/20 dark:text-rose-300';
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
      <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
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
    <div className="inline-flex h-8 overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`border-l border-zinc-200 px-3 py-1 text-[12px] font-medium transition-colors first:border-l-0 dark:border-zinc-700 ${
            value === opt.value
              ? 'bg-[var(--brand)] text-white'
              : 'bg-white text-zinc-600 hover:bg-zinc-50 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
