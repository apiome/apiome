"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  Layers,
  Loader2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/app/components/ui/Badge";
import { LoadingState } from "@/app/components/ui/LoadingState";
import { EmptyState } from "@/app/components/ui/EmptyState";
import { dashboardPanelPaddedClass } from "@/app/components/ade/dashboard/dashboardScreenClasses";
import {
  mcpVersionDateTag,
  mcpVersionListFromPayload,
  mcpVersionSeqLabel,
  type McpVersionSummary,
} from "@/app/components/ade/dashboard/mcp/mcpVersionsUi";
import {
  mcpCoverageStats,
  mcpInsightSurfaceFromPayload,
  mcpTypeCountTiles,
  type McpInsightSurface,
} from "@/app/components/ade/dashboard/mcp/mcpInsightUi";

interface Props {
  endpointId: string;
  /** The endpoint's current snapshot, used as the version selector's default when present. */
  currentVersionId: string | null;
}

/**
 * A reserved panel slot in the Insight grid — a titled, dashed placeholder that a later epic's
 * visualization replaces in place. The scaffold (14.4) lays out the section framework; the 15.x /
 * 16.x / 17.x panels fill these slots, so the shape of the tab is stable before its charts land.
 */
interface ReservedPanelDef {
  key: string;
  title: string;
  /** One-line description of what the finished panel will show. */
  hint: string;
}

/** One section of the Insight grid: an icon + heading and the panels it hosts. */
interface InsightSectionDef {
  key: string;
  title: string;
  subtitle: string;
  icon: typeof BarChart3;
  /** Reserved slots this section will grow; the capability-surface section also renders a live baseline. */
  reserved: ReservedPanelDef[];
}

/**
 * The Insight tab's section framework. Titles and reserved-panel slots mirror the roadmap: capability
 * surface (Epic 15), surface evolution (Epic 16), and reliability & trust (Epic 17). Keeping the
 * layout declarative means each downstream panel lands by swapping one reserved slot for its chart.
 */
const INSIGHT_SECTIONS: InsightSectionDef[] = [
  {
    key: "surface",
    title: "Capability surface",
    subtitle: "What this snapshot exposes and how well it is documented.",
    icon: Layers,
    reserved: [
      { key: "profile", title: "Server profile", hint: "Identity, protocol, and trust at a glance." },
      { key: "graph", title: "Capability relationship graph", hint: "How tools, resources, and prompts relate." },
      { key: "safety", title: "Safety & annotation posture", hint: "Read-only vs destructive tools, cross-referenced with auth." },
    ],
  },
  {
    key: "evolution",
    title: "Surface evolution",
    subtitle: "How the server has changed across discovery snapshots.",
    icon: Activity,
    reserved: [
      { key: "churn", title: "Capability churn timeline", hint: "Added, removed, and modified per version." },
      { key: "trend", title: "Grade & surface-size trend", hint: "Quality and capability counts over time." },
    ],
  },
  {
    key: "reliability",
    title: "Reliability & trust",
    subtitle: "Whether the server is healthy, fast, and trustworthy.",
    icon: ShieldCheck,
    reserved: [
      { key: "health", title: "Discovery health timeline", hint: "Success, failure, and backoff over time." },
      { key: "latency", title: "Latency & error-rate panel", hint: "p50/p95/p99 latency and error ratio per tool." },
      { key: "trust", title: "Composite trust radar", hint: "Quality, safety, docs, stability, responsiveness." },
    ],
  },
];

/** Option label for a version in the selector: its sequence label plus its date/tag. */
function versionOptionLabel(version: McpVersionSummary): string {
  return `${mcpVersionSeqLabel(version.version_seq)} · ${mcpVersionDateTag(version)}`;
}

/** The snapshot selector — a native, accessible `<select>` that drives an insight re-fetch on change. */
function VersionSelector({
  versions,
  value,
  disabled,
  onChange,
}: {
  versions: McpVersionSummary[];
  value: string | null;
  disabled: boolean;
  onChange: (versionId: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor="mcp-insight-version"
        className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400"
      >
        Snapshot
      </label>
      <select
        id="mcp-insight-version"
        value={value ?? undefined}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border border-gray-300 bg-white px-2.5 text-sm text-gray-900 transition-colors hover:border-indigo-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:border-indigo-700"
      >
        {versions.map((version) => (
          <option key={version.id} value={version.id}>
            {versionOptionLabel(version)}
            {version.is_current ? " (current)" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

/** A single count tile (capability kind → count) in the surface baseline. */
function CountTile({ label, value }: { label: string; value: number }) {
  return (
    <div className={dashboardPanelPaddedClass}>
      <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900 dark:text-white">
        {value}
      </div>
    </div>
  );
}

/** A single documentation-coverage meter (label, percentage bar, and the raw have/of counts). */
function CoverageMeter({
  label,
  pct,
  have,
  of,
}: {
  label: string;
  pct: number;
  have: number;
  of: number;
}) {
  return (
    <div className={dashboardPanelPaddedClass}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
          {label}
        </span>
        <span className="text-sm font-semibold tabular-nums text-gray-900 dark:text-white">
          {pct}%
        </span>
      </div>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div className="h-full rounded-full bg-indigo-500" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 tabular-nums">
        {have} / {of}
      </div>
    </div>
  );
}

/**
 * The live baseline the scaffold renders for the selected snapshot: total-capability headline, the
 * per-kind count tiles, and the documentation-coverage meters. This is the real 14.2 data proving
 * the lazy fetch and version-selector re-fetch work; the 15.x panels build richer views on the same
 * source. Handles its own loading / error / empty (zero-capability) states so a slow or missing
 * surface never blanks the whole tab.
 */
function SurfaceBaseline({
  surface,
  loading,
  error,
}: {
  surface: McpInsightSurface | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading && !surface) {
    return <LoadingState minHeightClassName="min-h-[140px]" message="Loading insight…" />;
  }
  if (error) {
    return (
      <EmptyState
        variant="compact"
        icon={<BarChart3 className="h-8 w-8 text-white" aria-hidden />}
        title="Insight unavailable"
        description={error}
      />
    );
  }
  if (!surface) return null;

  const tiles = mcpTypeCountTiles(surface.metrics.type_counts);
  const coverage = mcpCoverageStats(surface.metrics);
  const total = surface.metrics.type_counts.total;

  return (
    <div className="space-y-4" aria-busy={loading}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-gray-600 dark:text-gray-300">
          <span className="text-lg font-semibold text-gray-900 dark:text-white tabular-nums">
            {total}
          </span>{" "}
          {total === 1 ? "capability" : "capabilities"} in this snapshot
        </span>
        {surface.is_current ? <Badge variant="success">Current</Badge> : null}
      </div>

      {total === 0 ? (
        <EmptyState
          variant="compact"
          icon={<Layers className="h-8 w-8 text-white" aria-hidden />}
          title="No capabilities"
          description="This snapshot declares no tools, resources, or prompts to summarize."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {tiles.map((tile) => (
              <CountTile key={tile.key} label={tile.label} value={tile.value} />
            ))}
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {coverage.map((stat) => (
              <CoverageMeter
                key={stat.key}
                label={stat.label}
                pct={stat.pct}
                have={stat.have}
                of={stat.of}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** A reserved, not-yet-filled panel slot — a dashed card naming the visualization that will land here. */
function ReservedPanel({ panel }: { panel: ReservedPanelDef }) {
  return (
    <div className="flex flex-col rounded-lg border border-dashed border-gray-300 bg-gray-50/60 p-4 dark:border-gray-700 dark:bg-gray-800/40">
      <div className="flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-200">
        <Sparkles className="h-3.5 w-3.5 text-indigo-400" aria-hidden />
        {panel.title}
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{panel.hint}</p>
      <span className="mt-2 inline-flex w-fit items-center rounded-full bg-gray-200 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:bg-gray-700 dark:text-gray-300">
        Coming soon
      </span>
    </div>
  );
}

/** One section of the grid: header, an optional live baseline, and its reserved panel slots. */
function InsightSection({
  section,
  children,
}: {
  section: InsightSectionDef;
  children?: React.ReactNode;
}) {
  const Icon = section.icon;
  return (
    <section>
      <div className="mb-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
          <Icon className="h-4 w-4 text-indigo-500" aria-hidden />
          {section.title}
        </h3>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{section.subtitle}</p>
      </div>
      {children ? <div className="mb-4">{children}</div> : null}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {section.reserved.map((panel) => (
          <ReservedPanel key={panel.key} panel={panel} />
        ))}
      </div>
    </section>
  );
}

/**
 * The MCP endpoint "Insight" tab (V2-MCP-28.4 / MCAT-14.4).
 *
 * The home for the server-profile, evolution, and reliability visualizations Epics 15–17 fill. This
 * scaffold lays out the responsive panel grid + section headers, a snapshot version selector, and a
 * live baseline of the 14.2 capability-surface metrics — with loading, empty, and error states —
 * proving the plumbing before the rich charts land. Because it is rendered inside a Radix tab that
 * unmounts when inactive, its data fetch is naturally lazy: nothing loads until the tab is opened.
 *
 * @param endpointId        The MCP endpoint whose insight to show.
 * @param currentVersionId  The endpoint's current snapshot id, used as the selector's default.
 */
export default function McpEndpointInsight({ endpointId, currentVersionId }: Props) {
  const [versions, setVersions] = useState<McpVersionSummary[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(true);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  /** The snapshot currently summarized; drives the surface fetch below. */
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [surface, setSurface] = useState<McpInsightSurface | null>(null);
  const [surfaceLoading, setSurfaceLoading] = useState(false);
  const [surfaceError, setSurfaceError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Load the version list once (on first mount / tab open) to populate the selector, then default
  // the selection to the endpoint's current snapshot — or the newest one when there is no current.
  useEffect(() => {
    let active = true;
    setVersionsLoading(true);
    setVersionsError(null);
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
        const preferred =
          (currentVersionId && list.find((v) => v.id === currentVersionId)?.id) ||
          list[0]?.id ||
          null;
        setSelectedVersionId(preferred);
      } catch (e) {
        if (!active) return;
        setVersionsError(e instanceof Error ? e.message : "Could not load snapshots.");
        setVersions([]);
        setSelectedVersionId(null);
      } finally {
        if (active) setVersionsLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId, currentVersionId]);

  // Fetch the capability-surface insight for the selected snapshot; re-runs whenever the selector
  // changes. The `version_id` query views any historical snapshot (current is implicit but we always
  // pass it so switching back to current re-fetches deterministically).
  const loadSurface = useCallback(
    async (versionId: string) => {
      setSurfaceLoading(true);
      setSurfaceError(null);
      try {
        const res = await fetch(
          `/api/mcp/endpoints/${endpointId}/insight/surface?version_id=${encodeURIComponent(versionId)}`,
          { credentials: "include", cache: "no-store" },
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        const parsed = mcpInsightSurfaceFromPayload(data);
        if (!mountedRef.current) return;
        if (!parsed) throw new Error("Malformed insight response.");
        setSurface(parsed);
      } catch (e) {
        if (!mountedRef.current) return;
        setSurface(null);
        setSurfaceError(e instanceof Error ? e.message : "Could not load insight.");
      } finally {
        if (mountedRef.current) setSurfaceLoading(false);
      }
    },
    [endpointId],
  );

  useEffect(() => {
    if (!selectedVersionId) {
      setSurface(null);
      setSurfaceError(null);
      return;
    }
    void loadSurface(selectedVersionId);
  }, [selectedVersionId, loadSurface]);

  const selectedVersion = useMemo(
    () => versions.find((v) => v.id === selectedVersionId) ?? null,
    [versions, selectedVersionId],
  );

  if (versionsLoading) {
    return <LoadingState minHeightClassName="min-h-[220px]" message="Loading insight…" />;
  }

  // Never-discovered (or unreadable) endpoint: there is no snapshot to summarize — a helpful empty
  // state, not a broken grid.
  if (versionsError || versions.length === 0) {
    return (
      <EmptyState
        variant="compact"
        icon={<BarChart3 className="h-8 w-8 text-white" aria-hidden />}
        title="No insight yet"
        description={
          versionsError ??
          "This endpoint has never been discovered, so there is no capability surface to visualize. Run discovery to populate its insight."
        }
      />
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
          {surfaceLoading ? (
            <Loader2 className="h-4 w-4 animate-spin text-indigo-500" aria-hidden />
          ) : (
            <BarChart3 className="h-4 w-4 text-indigo-500" aria-hidden />
          )}
          <span>
            Insight for{" "}
            <span className="font-medium text-gray-900 dark:text-white">
              {selectedVersion ? mcpVersionSeqLabel(selectedVersion.version_seq) : "—"}
            </span>
          </span>
        </div>
        <VersionSelector
          versions={versions}
          value={selectedVersionId}
          disabled={surfaceLoading}
          onChange={setSelectedVersionId}
        />
      </div>

      {INSIGHT_SECTIONS.map((section) => (
        <InsightSection key={section.key} section={section}>
          {section.key === "surface" ? (
            <SurfaceBaseline surface={surface} loading={surfaceLoading} error={surfaceError} />
          ) : null}
        </InsightSection>
      ))}
    </div>
  );
}
