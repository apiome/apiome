"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlignJustify,
  ChevronsDownUp,
  ChevronsUpDown,
  Columns2,
  GitCompareArrows,
  History,
  Loader2,
} from "lucide-react";
import { Badge } from "@/app/components/ui/Badge";
import { Checkbox } from "@/app/components/ui/Checkbox";
import { LoadingState } from "@/app/components/ui/LoadingState";
import { EmptyState } from "@/app/components/ui/EmptyState";
import { McpDisclosure } from "@/app/components/ui/mcp/McpDisclosure";
import { McpJsonViewer } from "@/app/components/ui/mcp/McpJsonViewer";
import {
  McpJsonDiffViewer,
  type McpDiffMode,
} from "@/app/components/ui/mcp/McpJsonDiffViewer";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/app/components/ui/Select";
import { dashboardPanelPaddedClass } from "@/app/components/ade/dashboard/dashboardScreenClasses";
import { mcpScoreLabel, mcpScoreVariant } from "@/app/components/ade/dashboard/mcp/mcpBrowseUi";
import {
  mcpChangeBeforeAfter,
  mcpChangeCountParts,
  mcpChangeItemPath,
  mcpChangeStyle,
  mcpCompareHeader,
  mcpOrderedPair,
  mcpToggleSelection,
  mcpVersionDateTag,
  mcpVersionListFromPayload,
  mcpVersionCompareFromPayload,
  mcpVersionSeqLabel,
  type McpVersionChange,
  type McpVersionCompare,
  type McpVersionSummary,
} from "@/app/components/ade/dashboard/mcp/mcpVersionsUi";

interface Props {
  endpointId: string;
}

/** localStorage key remembering the preferred diff layout (side-by-side vs unified). */
const DIFF_MODE_STORAGE_KEY = "mcp-versions-diff-mode";

/** Default selection: the two newest snapshots (so the diff opens on the latest change). */
function defaultSelection(versions: McpVersionSummary[]): string[] {
  if (versions.length >= 2) return [versions[0].id, versions[1].id];
  if (versions.length === 1) return [versions[0].id];
  return [];
}

/**
 * The JSON detail under one change row. A modification renders a real base→target diff (split or
 * unified per the panel's layout toggle); an addition or removal has only one side, so it renders
 * that side's definition as a plain read-only block. All editors mount lazily on first expand.
 */
function ChangeDetail({
  change,
  diffMode,
  defaultOpen,
}: {
  change: McpVersionChange;
  diffMode: McpDiffMode;
  /** Seed open state (from the panel's expand-all control); the row stays toggleable after. */
  defaultOpen: boolean;
}) {
  const { before, after } = mcpChangeBeforeAfter(change);
  if (before !== null && after !== null) {
    const lineCount = Math.max(before.split("\n").length, after.split("\n").length);
    return (
      <McpDisclosure
        label="Diff"
        icon={<GitCompareArrows className="h-3.5 w-3.5 shrink-0 text-indigo-500" aria-hidden />}
        meta={`${lineCount} ${lineCount === 1 ? "line" : "lines"}`}
        defaultOpen={defaultOpen}
        className="bg-white dark:bg-gray-900/40"
      >
        <McpJsonDiffViewer
          original={before}
          modified={after}
          mode={diffMode}
          className="rounded-none border-0"
        />
      </McpDisclosure>
    );
  }
  const only = before ?? after;
  if (only === null) return null;
  const lineCount = only.split("\n").length;
  return (
    <McpDisclosure
      label={before !== null ? "Removed definition" : "Added definition"}
      meta={`${lineCount} ${lineCount === 1 ? "line" : "lines"}`}
      defaultOpen={defaultOpen}
      className="bg-white dark:bg-gray-900/40"
    >
      <McpJsonViewer value={only} className="rounded-none border-0" />
    </McpDisclosure>
  );
}

/** One color-coded change row (added=green / removed=red / modified=blue). */
function ChangeRow({
  change,
  diffMode,
  detailKey,
  detailDefaultOpen,
}: {
  change: McpVersionChange;
  diffMode: McpDiffMode;
  /** Remount key for the detail disclosure — bumped by expand/collapse-all to reseed open state. */
  detailKey: string;
  detailDefaultOpen: boolean;
}) {
  const style = mcpChangeStyle(change.change_type);
  const fields = change.change_type === "modified" ? change.detail.fields ?? [] : [];
  return (
    <div className={`rounded-md p-3 ${style.rowClass}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={style.badgeVariant} title={style.label}>
          <span aria-hidden>{style.sign}</span> {style.label}
        </Badge>
        <span className="font-mono text-sm text-gray-900 dark:text-gray-100">
          {mcpChangeItemPath(change)}
        </span>
        {fields.length > 0 ? (
          <span className="text-xs text-gray-600 dark:text-gray-300">
            {fields.map((field) => field.field).join(", ")} changed
          </span>
        ) : null}
      </div>
      <div className="mt-2">
        <ChangeDetail
          key={detailKey}
          change={change}
          diffMode={diffMode}
          defaultOpen={detailDefaultOpen}
        />
      </div>
    </div>
  );
}

/** The side-by-side / unified layout switch for the diff panel. */
function DiffModeToggle({
  mode,
  onChange,
}: {
  mode: McpDiffMode;
  onChange: (mode: McpDiffMode) => void;
}) {
  const options: Array<{ value: McpDiffMode; label: string; icon: typeof Columns2 }> = [
    { value: "split", label: "Side-by-side", icon: Columns2 },
    { value: "unified", label: "Unified", icon: AlignJustify },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="Diff layout"
      className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5 dark:border-gray-700 dark:bg-gray-800"
    >
      {options.map((opt) => {
        const selected = mode === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(opt.value)}
            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              selected
                ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/60 dark:text-indigo-300"
                : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            <opt.icon className="h-3.5 w-3.5" aria-hidden />
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** One row of the version timeline with a checkbox to tick it into the compare selection. */
function TimelineRow({
  version,
  checked,
  onToggle,
}: {
  version: McpVersionSummary;
  checked: boolean;
  onToggle: (id: string) => void;
}) {
  const checkboxId = `mcp-version-${version.id}`;
  return (
    <label
      htmlFor={checkboxId}
      className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors ${
        checked
          ? "border-indigo-400 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-900/20"
          : "border-gray-200 hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800/60"
      }`}
    >
      <Checkbox
        id={checkboxId}
        checked={checked}
        onCheckedChange={() => onToggle(version.id)}
        className="mt-0.5"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-gray-900 dark:text-white">
            {mcpVersionSeqLabel(version.version_seq)}
          </span>
          {version.is_current ? <Badge variant="success">Current</Badge> : null}
          <Badge variant={mcpScoreVariant(version.score)}>
            {mcpScoreLabel(version.score, version.grade)}
          </Badge>
        </div>
        <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {mcpVersionDateTag(version)}
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 text-xs">
          <span className="text-green-600 dark:text-green-400">
            +{version.change_counts.added}
          </span>
          <span className="text-red-600 dark:text-red-400">
            −{version.change_counts.removed}
          </span>
          <span className="text-blue-600 dark:text-blue-400">
            ~{version.change_counts.modified}
          </span>
        </div>
      </div>
    </label>
  );
}

/** The compare-bar selectors (base / target) wired to the same selection model as the timeline. */
function CompareBar({
  versions,
  baseId,
  targetId,
  onPick,
}: {
  versions: McpVersionSummary[];
  baseId: string | null;
  targetId: string | null;
  onPick: (slot: 0 | 1, id: string) => void;
}) {
  const optionLabel = (version: McpVersionSummary) =>
    `${mcpVersionSeqLabel(version.version_seq)} · ${mcpVersionDateTag(version)}`;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
      <div>
        <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
          Base version
        </label>
        <Select value={baseId ?? undefined} onValueChange={(value) => onPick(0, value)}>
          <SelectTrigger aria-label="Base version">
            <SelectValue placeholder="Select base…" />
          </SelectTrigger>
          <SelectContent>
            {versions.map((version) => (
              <SelectItem key={version.id} value={version.id}>
                {optionLabel(version)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="hidden pb-2 text-gray-400 sm:block" aria-hidden>
        <GitCompareArrows className="h-5 w-5" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
          Target version
        </label>
        <Select value={targetId ?? undefined} onValueChange={(value) => onPick(1, value)}>
          <SelectTrigger aria-label="Target version">
            <SelectValue placeholder="Select target…" />
          </SelectTrigger>
          <SelectContent>
            {versions.map((version) => (
              <SelectItem key={version.id} value={version.id}>
                {optionLabel(version)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

/** The rendered diff for the selected pair: header, change counts, and color-coded rows. */
function DiffPanel({
  compare,
  comparing,
  error,
  hasSelection,
  diffMode,
  expandAll,
  expandGeneration,
}: {
  compare: McpVersionCompare | null;
  comparing: boolean;
  error: string | null;
  hasSelection: boolean;
  diffMode: McpDiffMode;
  /** Whether the expand-all control last asked for open (seeds each row's disclosure). */
  expandAll: boolean;
  /** Bumped on every expand/collapse-all click so the disclosures remount into the new state. */
  expandGeneration: number;
}) {
  if (!hasSelection) {
    return (
      <EmptyState
        variant="compact"
        icon={<GitCompareArrows className="h-8 w-8 text-white" aria-hidden />}
        title="Pick two versions"
        description="Choose a base and a target — from the selectors or by ticking two versions in the timeline — to see exactly what changed."
      />
    );
  }
  if (comparing && !compare) {
    return <LoadingState minHeightClassName="min-h-[160px]" message="Computing diff…" />;
  }
  if (error) {
    return (
      <EmptyState
        variant="compact"
        icon={<GitCompareArrows className="h-8 w-8 text-white" aria-hidden />}
        title="Diff unavailable"
        description={error}
      />
    );
  }
  if (!compare) return null;

  const identical = !compare.fingerprint_changed && compare.changes.length === 0;
  return (
    <div className="space-y-3" aria-busy={comparing}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-mono text-lg font-semibold text-gray-900 dark:text-white">
          {mcpCompareHeader(compare)}
        </h4>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          {mcpChangeCountParts(compare).map((part) => (
            <span key={part.key} className={part.colorClass}>
              {part.label}
            </span>
          ))}
        </div>
      </div>
      {identical ? (
        <EmptyState
          variant="compact"
          icon={<GitCompareArrows className="h-8 w-8 text-white" aria-hidden />}
          title="Identical surface"
          description="These two versions expose the same capabilities and metadata — nothing changed between them."
        />
      ) : (
        <div className="space-y-2">
          {compare.changes.map((change) => (
            <ChangeRow
              key={`${change.item_type}:${change.item_name}`}
              change={change}
              diffMode={diffMode}
              detailKey={`gen-${expandGeneration}`}
              detailDefaultOpen={expandAll}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function McpVersionHistory({ endpointId }: Props) {
  const [versions, setVersions] = useState<McpVersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Up to two ticked version ids, in pick order (chronological order is derived for the diff). */
  const [selection, setSelection] = useState<string[]>([]);
  const [compare, setCompare] = useState<McpVersionCompare | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  /** Diff layout (side-by-side vs unified), remembered across visits. */
  const [diffMode, setDiffMode] = useState<McpDiffMode>(() =>
    typeof window !== "undefined" && window.localStorage.getItem(DIFF_MODE_STORAGE_KEY) === "unified"
      ? "unified"
      : "split",
  );
  /** Expand-all state: the seed every diff disclosure remounts into when the generation bumps. */
  const [expandAll, setExpandAll] = useState(false);
  const [expandGeneration, setExpandGeneration] = useState(0);
  const mountedRef = useRef(true);

  const toggleExpandAll = useCallback(() => {
    setExpandAll((prev) => !prev);
    setExpandGeneration((gen) => gen + 1);
  }, []);

  const changeDiffMode = useCallback((mode: McpDiffMode) => {
    setDiffMode(mode);
    try {
      window.localStorage.setItem(DIFF_MODE_STORAGE_KEY, mode);
    } catch {
      // Storage unavailable (private mode / quota) — the toggle still works for this visit.
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/versions`, {
          credentials: "include",
          cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        const list = mcpVersionListFromPayload(data);
        if (!active) return;
        setVersions(list);
        setSelection(defaultSelection(list));
      } catch (e) {
        if (!active) return;
        setError(e instanceof Error ? e.message : "Could not load version history.");
        setVersions([]);
        setSelection([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId]);

  /** Chronologically ordered base→target for the current selection (auto-swaps older→newer). */
  const pair = useMemo(() => mcpOrderedPair(selection, versions), [selection, versions]);
  const baseId = pair?.base.id ?? null;
  const targetId = pair?.target.id ?? null;

  const runCompare = useCallback(
    async (base: string, target: string) => {
      setComparing(true);
      setCompareError(null);
      try {
        const res = await fetch(
          `/api/mcp/endpoints/${endpointId}/versions/compare?base=${encodeURIComponent(
            base,
          )}&target=${encodeURIComponent(target)}`,
          { credentials: "include", cache: "no-store" },
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        const parsed = mcpVersionCompareFromPayload(data);
        if (!mountedRef.current) return;
        if (!parsed) throw new Error("Malformed compare response.");
        setCompare(parsed);
      } catch (e) {
        if (!mountedRef.current) return;
        setCompare(null);
        setCompareError(e instanceof Error ? e.message : "Could not compare versions.");
      } finally {
        if (mountedRef.current) setComparing(false);
      }
    },
    [endpointId],
  );

  useEffect(() => {
    if (!baseId || !targetId) {
      setCompare(null);
      setCompareError(null);
      return;
    }
    void runCompare(baseId, targetId);
  }, [baseId, targetId, runCompare]);

  const toggleVersion = useCallback((id: string) => {
    setSelection((prev) => mcpToggleSelection(prev, id));
  }, []);

  /** Set one selector slot (0 = base, 1 = target), preserving the other slot's pick. */
  const pickSlot = useCallback((slot: 0 | 1, id: string) => {
    setSelection((prev) => {
      const slots: [string | null, string | null] = [prev[0] ?? null, prev[1] ?? null];
      slots[slot] = id;
      return slots.filter((value): value is string => Boolean(value));
    });
  }, []);

  if (loading) {
    return <LoadingState minHeightClassName="min-h-[220px]" message="Loading version history…" />;
  }
  if (error || versions.length === 0) {
    return (
      <EmptyState
        variant="compact"
        icon={<History className="h-8 w-8 text-white" aria-hidden />}
        title="No version history"
        description={
          error ?? "This endpoint has no recorded version snapshots yet. Run discovery to create one."
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <section className={dashboardPanelPaddedClass}>
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
          <GitCompareArrows className="h-4 w-4 text-indigo-500" aria-hidden />
          Compare versions
        </h3>
        <CompareBar versions={versions} baseId={baseId} targetId={targetId} onPick={pickSlot} />
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        <section>
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
            <History className="h-4 w-4 text-indigo-500" aria-hidden />
            Timeline
            <Badge variant="secondary">{versions.length}</Badge>
          </h3>
          <div className="space-y-2">
            {versions.map((version) => (
              <TimelineRow
                key={version.id}
                version={version}
                checked={selection.includes(version.id)}
                onToggle={toggleVersion}
              />
            ))}
          </div>
        </section>

        <section>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
              {comparing ? (
                <Loader2 className="h-4 w-4 animate-spin text-indigo-500" aria-hidden />
              ) : (
                <GitCompareArrows className="h-4 w-4 text-indigo-500" aria-hidden />
              )}
              Diff
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={toggleExpandAll}
                disabled={!compare || compare.changes.length === 0}
                title={expandAll ? "Collapse every change's detail" : "Expand every change's detail"}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400 dark:hover:text-gray-100"
              >
                {expandAll ? (
                  <ChevronsDownUp className="h-3.5 w-3.5" aria-hidden />
                ) : (
                  <ChevronsUpDown className="h-3.5 w-3.5" aria-hidden />
                )}
                {expandAll ? "Collapse all" : "Expand all"}
              </button>
              <DiffModeToggle mode={diffMode} onChange={changeDiffMode} />
            </div>
          </div>
          <div className={dashboardPanelPaddedClass}>
            <DiffPanel
              compare={compare}
              comparing={comparing}
              error={compareError}
              hasSelection={selection.length > 0}
              diffMode={diffMode}
              expandAll={expandAll}
              expandGeneration={expandGeneration}
            />
          </div>
        </section>
      </div>
    </div>
  );
}
