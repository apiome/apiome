"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  GitCompareArrows,
  History,
  Layers,
  LayoutGrid,
  LineChart,
  ListTree,
  Gauge,
  Loader2,
  Share2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Timer,
} from "lucide-react";
import { Badge } from "@/app/components/ui/Badge";
import { LoadingState } from "@/app/components/ui/LoadingState";
import { EmptyState } from "@/app/components/ui/EmptyState";
import { ServerProfileCard } from "@/app/components/ui/mcp/ServerProfileCard";
import { CapabilityGraphPanel } from "@/app/components/ui/mcp/CapabilityGraphPanel";
import { ToolComplexityPanel } from "@/app/components/ui/mcp/ToolComplexityPanel";
import { SafetyPosturePanel } from "@/app/components/ui/mcp/SafetyPosturePanel";
import { DocCoveragePanel } from "@/app/components/ui/mcp/DocCoveragePanel";
import { CapabilityChurnPanel } from "@/app/components/ui/mcp/CapabilityChurnPanel";
import { CapabilityPresenceMatrixPanel } from "@/app/components/ui/mcp/CapabilityPresenceMatrixPanel";
import { GradeSurfaceTrendPanel } from "@/app/components/ui/mcp/GradeSurfaceTrendPanel";
import { ChangedSinceDigestPanel } from "@/app/components/ui/mcp/ChangedSinceDigestPanel";
import { DiscoveryHealthPanel } from "@/app/components/ui/mcp/DiscoveryHealthPanel";
import { ToolLatencyPanel } from "@/app/components/ui/mcp/ToolLatencyPanel";
import {
  ScoreBreakdownPanel,
  type McpScoreNavigateToItem,
} from "@/app/components/ui/mcp/ScoreBreakdownPanel";
import { dashboardPanelPaddedClass } from "@/app/components/ade/dashboard/dashboardScreenClasses";
import {
  mcpVersionDetailFromPayload,
  type McpCapabilityItem,
  type McpEndpointDetail,
  type McpVersionDetail,
} from "@/app/components/ade/dashboard/mcp/mcpBrowseUi";
import {
  mcpVersionDateTag,
  mcpVersionListFromPayload,
  mcpVersionSeqLabel,
  type McpVersionSummary,
} from "@/app/components/ade/dashboard/mcp/mcpVersionsUi";
import {
  mcpInsightSurfaceFromPayload,
  mcpServerProfileFrom,
  mcpTypeCountTiles,
  type McpInsightSurface,
} from "@/app/components/ade/dashboard/mcp/mcpInsightUi";
import {
  mcpInsightGraphFromPayload,
  type McpCapabilityGraph,
} from "@/app/components/ade/dashboard/mcp/mcpCapabilityGraphUi";
import {
  mcpEvolutionSeriesFromPayload,
  type McpEvolutionPoint,
} from "@/app/components/ade/dashboard/mcp/mcpEvolutionUi";
import {
  mcpDigestFromPayload,
  type McpEndpointDigest,
} from "@/app/components/ade/dashboard/mcp/mcpDigestUi";
import {
  mcpReliabilityHealthFromPayload,
  mcpToolReliabilityFromPayload,
  type McpDiscoveryHealth,
  type McpToolReliability,
} from "@/app/components/ade/dashboard/mcp/mcpReliabilityUi";
import {
  mcpLintReportFromPayload,
  type McpLintReport,
} from "@/app/components/ade/dashboard/mcp/mcpLintUi";

interface Props {
  endpointId: string;
  /** The endpoint's current snapshot, used as the version selector's default when present. */
  currentVersionId: string | null;
  /**
   * The loaded endpoint record, threaded from the detail page so the profile-card header can show
   * endpoint-level facts (transport, discovery health, catalog name) the version summary lacks.
   * Optional so the tab still renders (with a degraded card) when it is not supplied.
   */
  endpoint?: McpEndpointDetail | null;
  /**
   * The current version's server `instructions`, threaded from the detail page. Rendered by the
   * profile card only while the current snapshot is selected (instructions are snapshot-specific and
   * the version summary does not carry historical ones).
   */
  currentInstructions?: string | null;
  /**
   * Deep-link a snapshot's churn column to its diff: called with a `version_id` when a column in the
   * churn timeline is activated. The detail page handles it by switching to the Versions tab and
   * selecting that version against its predecessor (MCAT-16.1 → MCAT-10.3). Optional so the tab still
   * works standalone (the columns simply become inert when no handler is supplied).
   */
  onOpenVersionDiff?: (versionId: string) => void;
  /**
   * Deep-link a lint finding (from the score-breakdown panel) to its offending capability item on the
   * Capabilities tab. The detail page handles it by switching to the Capabilities tab and scrolling to
   * the item (the same handler the Lint & Score tab uses). Optional so the tab still works standalone
   * (the finding paths simply render as inert text when no handler is supplied).
   */
  onNavigateToItem?: McpScoreNavigateToItem;
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
    // "Server profile" (MCAT-15.1) lands as the ServerProfileCard header above the sections; the
    // "Capability relationship graph" (MCAT-15.2), "Tool schema shape & complexity" (MCAT-15.3), and
    // "Safety & annotation posture" (MCAT-15.4) now all land as live panels in this section's body,
    // so this section has no reserved slots left.
    reserved: [],
  },
  {
    key: "evolution",
    title: "Surface evolution",
    subtitle: "How the server has changed across discovery snapshots.",
    icon: Activity,
    // "Capability churn timeline" (MCAT-16.1), "Capability lifespan / presence matrix" (MCAT-16.2),
    // and "Grade & surface-size trend" (MCAT-16.4) now all land as live panels in this section's
    // body, so this section has no reserved slots left.
    reserved: [],
  },
  {
    key: "reliability",
    title: "Reliability & trust",
    subtitle: "Whether the server is healthy, fast, and trustworthy.",
    icon: ShieldCheck,
    // "Discovery health & availability timeline" (MCAT-17.1) and the "Tool latency & error-rate
    // panel" (MCAT-17.2) now both land as live panels in this section's body; the trust-radar panel
    // is still reserved for 17.4.
    reserved: [
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

/**
 * The live baseline the scaffold renders for the selected snapshot: total-capability headline and the
 * per-kind count tiles. This is the real 14.2 data proving the lazy fetch and version-selector
 * re-fetch work; the 15.x panels build richer views on the same source (documentation coverage now
 * lives in its own {@link DocCoveragePanel} below, so the baseline no longer duplicates those meters).
 * Handles its own loading / error / empty (zero-capability) states so a slow or missing surface never
 * blanks the whole tab.
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
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {tiles.map((tile) => (
            <CountTile key={tile.key} label={tile.label} value={tile.value} />
          ))}
        </div>
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
    <section id={`insight-${section.key}`} className="scroll-mt-24">
      <div className="mb-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
          <Icon className="h-4 w-4 text-indigo-500" aria-hidden />
          {section.title}
        </h3>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{section.subtitle}</p>
      </div>
      {children ? <div className="mb-4">{children}</div> : null}
      {section.reserved.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {section.reserved.map((panel) => (
            <ReservedPanel key={panel.key} panel={panel} />
          ))}
        </div>
      ) : null}
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
 * @param endpointId          The MCP endpoint whose insight to show.
 * @param currentVersionId    The endpoint's current snapshot id, used as the selector's default.
 * @param endpoint            The loaded endpoint record, for the profile-card header (optional).
 * @param currentInstructions The current version's server instructions, for the profile card.
 * @param onOpenVersionDiff   Deep-link a churn column to its diff in the Versions tab (optional).
 * @param onNavigateToItem    Deep-link a lint finding to its capability item (optional).
 */
export default function McpEndpointInsight({
  endpointId,
  currentVersionId,
  endpoint = null,
  currentInstructions = null,
  onOpenVersionDiff,
  onNavigateToItem,
}: Props) {
  const [versions, setVersions] = useState<McpVersionSummary[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(true);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  /** The snapshot currently summarized; drives the surface fetch below. */
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [surface, setSurface] = useState<McpInsightSurface | null>(null);
  const [surfaceLoading, setSurfaceLoading] = useState(false);
  const [surfaceError, setSurfaceError] = useState<string | null>(null);
  const [graph, setGraph] = useState<McpCapabilityGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  /** The selected snapshot's capability items, for the safety panel's per-tool annotation matrix. */
  const [items, setItems] = useState<McpCapabilityItem[] | null>(null);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
  /** The endpoint's configured `auth_type` (endpoint-level, loaded once), for the safety cross-reference. */
  const [authType, setAuthType] = useState<string | null>(null);
  /** The endpoint's per-version evolution series (endpoint-level, loaded once), for the churn timeline. */
  const [evolution, setEvolution] = useState<McpEvolutionPoint[] | null>(null);
  const [evolutionLoading, setEvolutionLoading] = useState(true);
  const [evolutionError, setEvolutionError] = useState<string | null>(null);
  /**
   * Every snapshot's full surface (endpoint-level, loaded once after the version list), for the
   * presence matrix — it reconstructs each capability's lifespan from the per-version capability
   * items, which only the version-detail read carries.
   */
  const [matrixVersions, setMatrixVersions] = useState<McpVersionDetail[] | null>(null);
  const [matrixLoading, setMatrixLoading] = useState(true);
  const [matrixError, setMatrixError] = useState<string | null>(null);
  /** The caller's per-user "changed since last view" digest (endpoint-level, loaded once). */
  const [digest, setDigest] = useState<McpEndpointDigest | null>(null);
  const [digestLoading, setDigestLoading] = useState(true);
  const [digestError, setDigestError] = useState<string | null>(null);
  /** The endpoint's discovery health & availability timeline (endpoint-level, loaded once). */
  const [health, setHealth] = useState<McpDiscoveryHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);
  /**
   * The endpoint's per-tool latency & error-rate breakdown (MCAT-17.2), parsed from the *same*
   * reliability fetch as the discovery health above — it shares that fetch's loading / error state.
   */
  const [tools, setTools] = useState<McpToolReliability | null>(null);
  /**
   * The selected snapshot's lint report (MCAT-17.3), fetched per-snapshot from the same lint route the
   * Lint & Score tab uses, so the score-breakdown panel decomposes the grade of whichever version the
   * selector shows. Re-fetched on selector change like the surface / graph / items reads.
   */
  const [report, setReport] = useState<McpLintReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  /** Guards the one-time seen-marker advance so it fires once per load, after the digest is read. */
  const viewRecordedRef = useRef(false);
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

  // Fetch the capability relationship graph (MCAT-15.2) for the selected snapshot in parallel with the
  // surface metrics; the edge inference is done server-side and this only renders the result.
  const loadGraph = useCallback(
    async (versionId: string) => {
      setGraphLoading(true);
      setGraphError(null);
      try {
        const res = await fetch(
          `/api/mcp/endpoints/${endpointId}/insight/graph?version_id=${encodeURIComponent(versionId)}`,
          { credentials: "include", cache: "no-store" },
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        const parsed = mcpInsightGraphFromPayload(data);
        if (!mountedRef.current) return;
        if (!parsed) throw new Error("Malformed graph response.");
        setGraph(parsed.graph);
      } catch (e) {
        if (!mountedRef.current) return;
        setGraph(null);
        setGraphError(e instanceof Error ? e.message : "Could not load graph.");
      } finally {
        if (mountedRef.current) setGraphLoading(false);
      }
    },
    [endpointId],
  );

  useEffect(() => {
    if (!selectedVersionId) {
      setGraph(null);
      setGraphError(null);
      return;
    }
    void loadGraph(selectedVersionId);
  }, [selectedVersionId, loadGraph]);

  // Fetch the selected snapshot's full capability items (MCAT-15.4) — the safety panel needs the
  // per-tool `annotations` the surface metrics roll up but do not itemize. Re-runs on selector change.
  const loadItems = useCallback(
    async (versionId: string) => {
      setItemsLoading(true);
      setItemsError(null);
      try {
        const res = await fetch(
          `/api/mcp/endpoints/${endpointId}/versions/${encodeURIComponent(versionId)}`,
          { credentials: "include", cache: "no-store" },
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        const detail = mcpVersionDetailFromPayload(data);
        if (!mountedRef.current) return;
        if (!detail) throw new Error("Malformed version response.");
        setItems(detail.items);
      } catch (e) {
        if (!mountedRef.current) return;
        setItems(null);
        setItemsError(e instanceof Error ? e.message : "Could not load capabilities.");
      } finally {
        if (mountedRef.current) setItemsLoading(false);
      }
    },
    [endpointId],
  );

  useEffect(() => {
    if (!selectedVersionId) {
      setItems(null);
      setItemsError(null);
      return;
    }
    void loadItems(selectedVersionId);
  }, [selectedVersionId, loadItems]);

  // Fetch the selected snapshot's lint report (MCAT-17.3) for the score-breakdown panel. This is the
  // same read the Lint & Score tab uses; the panel reconstructs the grade's point breakdown from the
  // report's findings. Re-runs on selector change so switching snapshots re-scores the breakdown.
  const loadReport = useCallback(
    async (versionId: string) => {
      setReportLoading(true);
      setReportError(null);
      try {
        const res = await fetch(
          `/api/mcp/endpoints/${endpointId}/versions/${encodeURIComponent(versionId)}/lint`,
          { credentials: "include", cache: "no-store" },
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        const parsed = mcpLintReportFromPayload(data);
        if (!mountedRef.current) return;
        if (!parsed) throw new Error("Malformed lint report.");
        setReport(parsed);
      } catch (e) {
        if (!mountedRef.current) return;
        setReport(null);
        setReportError(e instanceof Error ? e.message : "Could not load the score breakdown.");
      } finally {
        if (mountedRef.current) setReportLoading(false);
      }
    },
    [endpointId],
  );

  useEffect(() => {
    if (!selectedVersionId) {
      setReport(null);
      setReportError(null);
      return;
    }
    void loadReport(selectedVersionId);
  }, [selectedVersionId, loadReport]);

  // Fetch the endpoint's redacted credential status once (auth is endpoint-level, not per-snapshot)
  // so the safety panel can flag destructive tools reachable with no auth. A failed/absent status
  // leaves `authType` null, which the panel treats as "auth unknown" (never a false no-auth alarm).
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/credentials`, {
          credentials: "include",
          cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!active) return;
        const credential = (data && typeof data === "object" ? data.credential : null) as
          | { auth_type?: unknown }
          | null;
        const resolved =
          credential && typeof credential.auth_type === "string" ? credential.auth_type : null;
        setAuthType(res.ok ? resolved : null);
      } catch {
        if (active) setAuthType(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId]);

  // Fetch the whole per-version evolution series once (it is endpoint-level, not per-snapshot) for the
  // churn timeline. A never-discovered endpoint yields an empty series (a 200), which the panel renders
  // as its "no history yet" state rather than an error.
  useEffect(() => {
    let active = true;
    setEvolutionLoading(true);
    setEvolutionError(null);
    (async () => {
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/insight/evolution`, {
          credentials: "include",
          cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        if (!active) return;
        setEvolution(mcpEvolutionSeriesFromPayload(data));
      } catch (e) {
        if (!active) return;
        setEvolution(null);
        setEvolutionError(e instanceof Error ? e.message : "Could not load evolution history.");
      } finally {
        if (active) setEvolutionLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId]);

  // Load the caller's "changed since last view" digest once (endpoint-level), then advance their
  // seen-marker to the current version *after* the digest is read — so the digest reflects the
  // pre-advance "since your last visit" delta, and the next visit reads relative to this one. A
  // never-discovered endpoint yields a digest with no current version, so no marker is advanced.
  useEffect(() => {
    let active = true;
    setDigestLoading(true);
    setDigestError(null);
    viewRecordedRef.current = false;
    (async () => {
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/insight/digest`, {
          credentials: "include",
          cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        if (!active) return;
        const parsed = mcpDigestFromPayload(data);
        setDigest(parsed);
        // Advance the marker to the version the user is now seeing, once, after reading the digest.
        if (parsed?.current_version_id && !viewRecordedRef.current) {
          viewRecordedRef.current = true;
          void fetch(`/api/mcp/endpoints/${endpointId}/views`, {
            method: "POST",
            credentials: "include",
            cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ version_id: parsed.current_version_id }),
          }).catch(() => {});
        }
      } catch (e) {
        if (!active) return;
        setDigest(null);
        setDigestError(e instanceof Error ? e.message : "Could not load the digest.");
      } finally {
        if (active) setDigestLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId]);

  // Fetch the endpoint's reliability aggregates once (endpoint-level, not per-snapshot) for the
  // reliability section — it feeds both the discovery health timeline (MCAT-17.1) and the per-tool
  // latency & error-rate panel (MCAT-17.2) from a single read. A never-discovered / never-tested
  // endpoint yields an empty timeline and empty tool list (a 200), which each panel renders as its
  // own "no data yet" state rather than an error.
  useEffect(() => {
    let active = true;
    setHealthLoading(true);
    setHealthError(null);
    (async () => {
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/insight/reliability`, {
          credentials: "include",
          cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        if (!active) return;
        setHealth(mcpReliabilityHealthFromPayload(data));
        setTools(mcpToolReliabilityFromPayload(data));
      } catch (e) {
        if (!active) return;
        setHealth(null);
        setTools(null);
        setHealthError(e instanceof Error ? e.message : "Could not load reliability.");
      } finally {
        if (active) setHealthLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId]);

  // Fetch every snapshot's full surface once the version list is known — the presence matrix
  // reconstructs each capability's lifespan from the per-version capability items, which the list
  // summary omits. The reads run in parallel; a snapshot whose detail fails to load is dropped so the
  // matrix still renders from the snapshots that did load rather than blanking on a single failure.
  useEffect(() => {
    if (versionsLoading) return;
    if (versions.length === 0) {
      setMatrixVersions([]);
      setMatrixLoading(false);
      setMatrixError(null);
      return;
    }
    let active = true;
    setMatrixLoading(true);
    setMatrixError(null);
    (async () => {
      try {
        const results = await Promise.all(
          versions.map(async (v) => {
            try {
              const res = await fetch(
                `/api/mcp/endpoints/${endpointId}/versions/${encodeURIComponent(v.id)}`,
                { credentials: "include", cache: "no-store" },
              );
              if (!res.ok) return null;
              const data = await res.json().catch(() => ({}));
              return mcpVersionDetailFromPayload(data);
            } catch {
              return null;
            }
          }),
        );
        if (!active) return;
        const details = results.filter((d): d is McpVersionDetail => d !== null);
        if (details.length === 0) {
          setMatrixVersions(null);
          setMatrixError("Could not load any version snapshots for the presence matrix.");
        } else {
          setMatrixVersions(details);
        }
      } catch (e) {
        if (!active) return;
        setMatrixVersions(null);
        setMatrixError(e instanceof Error ? e.message : "Could not load presence matrix.");
      } finally {
        if (active) setMatrixLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId, versions, versionsLoading]);

  const selectedVersion = useMemo(
    () => versions.find((v) => v.id === selectedVersionId) ?? null,
    [versions, selectedVersionId],
  );

  // Assemble the at-a-glance server profile (MCAT-15.1) for the selected snapshot. Instructions are
  // snapshot-specific and the version summary omits them, so we only surface the threaded current
  // instructions while the current snapshot is selected.
  const profile = useMemo(
    () =>
      mcpServerProfileFrom({
        endpoint,
        version: selectedVersion,
        surface,
        instructions: selectedVersion?.is_current ? currentInstructions : null,
      }),
    [endpoint, selectedVersion, surface, currentInstructions],
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

      {/* "Changed since last view" digest (MCAT-16.5) — a per-user welcome-back summary at the top of
          the tab. Loaded endpoint-level; reading it advances the user's seen-marker (once) so the
          next visit reads relative to the version they are seeing now. */}
      <div className={dashboardPanelPaddedClass}>
        <div className="mb-3">
          <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
            <History className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
            Changed since your last view
          </h4>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            What changed on this server&apos;s surface since you last looked — and how breaking it is.
          </p>
        </div>
        <ChangedSinceDigestPanel
          digest={digest}
          loading={digestLoading}
          error={digestError}
          onReviewChanges={(versionId) => onOpenVersionDiff?.(versionId)}
        />
      </div>

      {/* At-a-glance server identity (MCAT-15.1) — the Insight tab header. */}
      <ServerProfileCard profile={profile} trustHref="#insight-reliability" />

      {INSIGHT_SECTIONS.map((section) => {
        let body: React.ReactNode = null;
        if (section.key === "surface") {
          body = (
            <div className="space-y-4">
              <SurfaceBaseline surface={surface} loading={surfaceLoading} error={surfaceError} />
              {/* Capability relationship graph (MCAT-15.2) — a live panel in the surface section body. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <Share2 className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Capability relationship graph
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    How tools, resources, and prompts relate — edges inferred from concrete signals.
                  </p>
                </div>
                <CapabilityGraphPanel graph={graph} loading={graphLoading} error={graphError} />
              </div>
              {/* Tool schema "shape" & complexity cards (MCAT-15.3) — a live panel in the surface section
                  body. It reads the same surface fetch as the baseline above, which already owns the
                  surface loading/error surfacing, so the whole sub-panel is hidden on a surface error to
                  avoid showing the same message twice. */}
              {surfaceError ? null : (
                <div className={dashboardPanelPaddedClass}>
                  <div className="mb-3">
                    <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                      <ListTree className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                      Tool schema shape &amp; complexity
                    </h4>
                    <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                      How hard each tool is to call — parameters, required/optional split, nesting, and
                      schema features — with a distribution across the server&apos;s tools.
                    </p>
                  </div>
                  <ToolComplexityPanel
                    tools={surface ? surface.metrics.tool_complexity : null}
                    loading={surfaceLoading}
                    error={null}
                  />
                </div>
              )}
              {/* Safety & annotation posture (MCAT-15.4) — the read-only vs destructive matrix, its
                  posture summary, and the destructive+no-auth cross-reference. It reads the snapshot's
                  full capability items (its own fetch) and the endpoint's auth type. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <ShieldAlert className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Safety &amp; annotation posture
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    Read-only vs destructive tools from their behavioural hints, cross-referenced with
                    whether the endpoint requires auth.
                  </p>
                </div>
                <SafetyPosturePanel
                  items={items}
                  authType={authType}
                  loading={itemsLoading}
                  error={itemsError}
                />
              </div>
              {/* Documentation & schema coverage (MCAT-15.5) — the gauge row (% described / titled /
                  params documented / output-schema adoption), each drill-down-able to the specific
                  under-documented items. Reads the same snapshot capability items as the safety panel. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <BookOpen className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Documentation &amp; schema coverage
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    How well this snapshot is documented — descriptions, titles, parameter docs, and
                    output-schema adoption — each meter linking to the items that fall short.
                  </p>
                </div>
                <DocCoveragePanel items={items} loading={itemsLoading} error={itemsError} />
              </div>
            </div>
          );
        } else if (section.key === "evolution") {
          body = (
            <div className="space-y-4">
              {/* Capability churn timeline (MCAT-16.1) — the stacked added/removed/modified-per-version
                  chart. Each column deep-links to that snapshot's diff via the detail page's handler. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <GitCompareArrows className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Capability churn timeline
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    How much the surface changed per snapshot — added, removed, and modified
                    capabilities over time, each column linking to that release&apos;s diff.
                  </p>
                </div>
                <CapabilityChurnPanel
                  series={evolution}
                  loading={evolutionLoading}
                  error={evolutionError}
                  onSelectVersion={(versionId) => onOpenVersionDiff?.(versionId)}
                />
              </div>
              {/* Capability lifespan / presence matrix (MCAT-16.2) — the per-capability "gantt of the
                  surface": which tools/resources existed in which snapshot, and whether they are
                  stable, new, volatile, or removed. Columns deep-link to the diff like the churn chart. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <LayoutGrid className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Capability lifespan &amp; presence
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    When each capability existed across snapshots — a presence matrix revealing
                    volatile vs long-lived tools, resources, and prompts.
                  </p>
                </div>
                <CapabilityPresenceMatrixPanel
                  versions={matrixVersions}
                  loading={matrixLoading}
                  error={matrixError}
                  onSelectVersion={(versionId) => onOpenVersionDiff?.(versionId)}
                />
              </div>
              {/* Grade & surface-size trend (MCAT-16.4) — the quality-score and capability-count trends
                  across snapshots, with breaking-change markers (MCAT-16.3) overlaid and each breaking
                  release deep-linking to its diff. Reads the same evolution series as the churn chart. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <LineChart className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Grade &amp; surface-size trend
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    Whether the server is improving — its quality score and capability count over
                    snapshots, with breaking-change releases marked. Unscored snapshots are gapped, not
                    zeroed.
                  </p>
                </div>
                <GradeSurfaceTrendPanel
                  series={evolution}
                  loading={evolutionLoading}
                  error={evolutionError}
                  onSelectVersion={(versionId) => onOpenVersionDiff?.(versionId)}
                />
              </div>
            </div>
          );
        } else if (section.key === "reliability") {
          body = (
            <div className="space-y-4">
              {/* Discovery health & availability timeline (MCAT-17.1) — the recent discovery-job
                  outcomes over time, a windowed availability %, and the endpoint's backoff /
                  quarantine state. Loaded endpoint-level from insight/reliability. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <Activity className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Discovery health &amp; availability
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    Whether the server has been reachable over time — each recent discovery
                    attempt&apos;s outcome, an availability percentage, and whether it is currently
                    quarantined after repeated failures.
                  </p>
                </div>
                <DiscoveryHealthPanel
                  health={health}
                  loading={healthLoading}
                  error={healthError}
                />
              </div>
              {/* Tool latency & error-rate panel (MCAT-17.2) — per-tool p50/p95/p99 latency and
                  error ratio, a latency distribution, and the slowest / flakiest tool rankings over
                  a recent window. Parsed from the same insight/reliability read as the health panel. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <Timer className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Tool latency &amp; error rate
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    How fast and how reliable each tool is when called — p50/p95/p99 latency and
                    error ratio per tool, a latency distribution, and the slowest and flakiest tools.
                  </p>
                </div>
                <ToolLatencyPanel
                  reliability={tools}
                  loading={healthLoading}
                  error={healthError}
                />
              </div>
              {/* Score & lint breakdown (MCAT-17.3) — decomposes the selected snapshot's quality grade
                  into the points each rule group deducted and the findings behind them, each finding
                  deep-linking to the offending capability. Reads the same per-version lint report the
                  Lint & Score tab uses; complements that tab rather than replacing it. */}
              <div className={dashboardPanelPaddedClass}>
                <div className="mb-3">
                  <h4 className="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-white">
                    <Gauge className="h-3.5 w-3.5 text-indigo-500" aria-hidden />
                    Score &amp; lint breakdown
                  </h4>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    Where this snapshot&apos;s quality grade comes from — the points each rule group
                    (naming, structure, annotations, security, hygiene) deducted and the findings
                    behind them, each linking to the capability it flags.
                  </p>
                </div>
                <ScoreBreakdownPanel
                  report={report}
                  loading={reportLoading}
                  error={reportError}
                  onNavigateToItem={onNavigateToItem}
                />
              </div>
            </div>
          );
        }
        return (
          <InsightSection key={section.key} section={section}>
            {body}
          </InsightSection>
        );
      })}
    </div>
  );
}
