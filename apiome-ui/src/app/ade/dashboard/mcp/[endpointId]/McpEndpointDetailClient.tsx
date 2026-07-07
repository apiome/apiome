"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  FileText,
  Globe,
  Loader2,
  Lock,
  Power,
  PowerOff,
  RefreshCw,
  Server,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/app/components/ui/Badge";
import { Button } from "@/app/components/ui/Button";
import { LoadingState } from "@/app/components/ui/LoadingState";
import { EmptyState } from "@/app/components/ui/EmptyState";
import { McpBadge } from "@/app/components/ui/mcp/McpBadge";
import { McpDisclosure } from "@/app/components/ui/mcp/McpDisclosure";
import { McpJsonViewer } from "@/app/components/ui/mcp/McpJsonViewer";
import { RecencyPill } from "@/app/components/ui/mcp/RecencyPill";
import {
  DetailTabs,
  DetailTabsContent,
  DetailTabsList,
} from "@/app/components/ui/mcp/DetailTabs";
import McpVersionHistory from "./McpVersionHistory";
import McpEndpointInsight from "./McpEndpointInsight";
import McpLintReport, { McpGradeSummary } from "./McpLintReport";
import McpEndpointSettings from "./McpEndpointSettings";
import {
  formatTeardownSummary,
  type McpTeardownSummary,
} from "@/app/components/ade/dashboard/mcp/mcpSettingsForm";
import {
  dashboardContentStackClass,
  dashboardMainClass,
  dashboardPanelPaddedClass,
} from "@/app/components/ade/dashboard/dashboardScreenClasses";
import {
  mcpCapabilityAnchorId,
  mcpLintReportFromPayload,
  mcpLintTierCounts,
  type McpLintReport as McpLintReportData,
} from "@/app/components/ade/dashboard/mcp/mcpLintUi";
import {
  MCP_DETAIL_TABS,
  mcpCapabilityAnnotationBadge,
  mcpTransportBadge,
  mcpVisibilityBadge,
} from "@/app/components/ade/dashboard/mcp/mcpUiPrimitives";
import {
  discoveryFailureMessage,
  isJobSuccess,
  isTerminalJobState,
  type McpDiscoveryJob,
} from "@/app/components/ade/dashboard/mcp/mcpImportFlow";
import {
  mcpAnnotationHints,
  mcpEndpointDetailFromPayload,
  mcpPublishTogglePatch,
  mcpGroupItemsByType,
  mcpItemDetailSections,
  mcpScoreLabel,
  mcpScoreVariant,
  mcpVersionDetailFromPayload,
  type McpCapabilityItem,
  type McpEndpointDetail,
  type McpVersionDetail,
} from "@/app/components/ade/dashboard/mcp/mcpBrowseUi";

interface Props {
  endpointId: string;
}

/** Cap on discovery polling so a stuck job can never spin forever (≈ 60s at 1.5s/poll). */
const DISCOVERY_POLL_INTERVAL_MS = 1500;
const DISCOVERY_MAX_POLLS = 40;

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * One collapsible JSON detail (input/output schema or annotations) under a capability item. The
 * Monaco viewer is heavyweight, so the disclosure mounts it only after the first expand.
 */
function CapabilityDetailSection({ label, json }: { label: string; json: string }) {
  const lineCount = json ? json.split("\n").length : 1;
  return (
    <McpDisclosure label={label} meta={`${lineCount} ${lineCount === 1 ? "line" : "lines"}`}>
      <McpJsonViewer value={json} className="rounded-none border-0" />
    </McpDisclosure>
  );
}

/** Render one capability item's name/uri/description plus its schema & annotation detail. */
function CapabilityItemCard({
  groupKey,
  item,
  anchorId,
  highlighted,
}: {
  groupKey: string;
  item: McpCapabilityItem;
  /** Stable DOM id so lint findings can deep-link to this item. */
  anchorId: string;
  /** True while this item is the target of a just-followed lint deep-link (transient ring). */
  highlighted: boolean;
}) {
  const hints = mcpAnnotationHints(item);
  const sections = mcpItemDetailSections(item);
  return (
    <div
      id={anchorId}
      className={`scroll-mt-24 rounded-lg border p-4 transition-colors ${
        highlighted
          ? "border-indigo-400 bg-indigo-50 ring-2 ring-indigo-400 dark:bg-indigo-900/20 dark:ring-indigo-500"
          : "border-gray-200 bg-white hover:border-indigo-200 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-indigo-800"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-gray-900 dark:text-white">
          {item.title ?? item.name}
        </span>
        {/* Only assert behavioural hints the server set to true, as tone-coded capability badges
            (readOnly green / idempotent blue / destructive red / openWorld amber). */}
        {hints.map((hint) => {
          const badge = mcpCapabilityAnnotationBadge(hint.key, hint.value);
          if (!badge) return null;
          return (
            <McpBadge key={hint.key} tone={badge.tone} title={`${hint.label}: ${hint.value}`}>
              {badge.label}
            </McpBadge>
          );
        })}
      </div>
      <div className="mt-0.5 font-mono text-xs text-gray-500 dark:text-gray-400">
        {item.uri ?? item.uri_template ?? item.name}
      </div>
      {item.description ? (
        <p className="mt-1.5 text-sm text-gray-600 dark:text-gray-300">
          {item.description}
        </p>
      ) : null}
      {sections.length > 0 ? (
        <div className="mt-3 space-y-2">
          {sections.map((section) => (
            <CapabilityDetailSection
              key={`${groupKey}:${item.name}:${section.key}`}
              label={section.label}
              json={section.json}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function McpEndpointDetailClient({ endpointId }: Props) {
  const router = useRouter();
  const [endpoint, setEndpoint] = useState<McpEndpointDetail | null>(null);
  const [version, setVersion] = useState<McpVersionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Which control is mid-flight ("discover" | "enabled" | "published"), or null when idle. */
  const [busy, setBusy] = useState<string | null>(null);
  /** Current version's lint report (drives the Overview summary + the Lint & Score tab). */
  const [lintReport, setLintReport] = useState<McpLintReportData | null>(null);
  const [lintLoading, setLintLoading] = useState(false);
  const [lintError, setLintError] = useState<string | null>(null);
  /** Controlled tab so a lint finding can switch to "capabilities" and scroll to its item. */
  const [activeTab, setActiveTab] = useState("capabilities");
  /** Anchor a pending deep-link wants to scroll to once the Capabilities tab has mounted. */
  const [pendingAnchor, setPendingAnchor] = useState<string | null>(null);
  /** The item currently highlighted by a followed deep-link (cleared after a short delay). */
  const [highlightedAnchor, setHighlightedAnchor] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  /** Fetch the lint report for a version; tolerated as best-effort (a failure shows in the tab). */
  const loadLint = useCallback(
    async (versionId: string) => {
      setLintLoading(true);
      setLintError(null);
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/versions/${versionId}/lint`, {
          credentials: "include",
          cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.error === "string" ? data.error : res.statusText);
        }
        if (!mountedRef.current) return;
        setLintReport(mcpLintReportFromPayload(data));
      } catch (e) {
        if (!mountedRef.current) return;
        setLintReport(null);
        setLintError(e instanceof Error ? e.message : "Could not load lint report.");
      } finally {
        if (mountedRef.current) setLintLoading(false);
      }
    },
    [endpointId],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const epRes = await fetch(`/api/mcp/endpoints/${endpointId}`, {
        credentials: "include",
      });
      const epData = await epRes.json().catch(() => ({}));
      if (!epRes.ok) {
        throw new Error(
          typeof epData.error === "string" ? epData.error : epRes.statusText,
        );
      }
      const ep = mcpEndpointDetailFromPayload(epData);
      if (!mountedRef.current) return;
      setEndpoint(ep);

      if (ep?.current_version_id) {
        const vRes = await fetch(
          `/api/mcp/endpoints/${endpointId}/versions/${ep.current_version_id}`,
          { credentials: "include" },
        );
        const vData = await vRes.json().catch(() => ({}));
        if (!mountedRef.current) return;
        setVersion(vRes.ok ? mcpVersionDetailFromPayload(vData) : null);
        await loadLint(ep.current_version_id);
      } else {
        setVersion(null);
        setLintReport(null);
        setLintError(null);
      }
    } catch (e) {
      console.error(e);
      if (!mountedRef.current) return;
      setError(e instanceof Error ? e.message : "Could not load endpoint.");
      setEndpoint(null);
      setVersion(null);
      setLintReport(null);
      setLintError(null);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [endpointId, loadLint]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * PATCH one or more mutable fields (enable/disable or publish/unpublish) and reflect the
   * returned record. `busyKey` drives the per-button spinner; `fields` is the patch body —
   * publishing sends `published` *and* `visibility` together so the endpoint actually becomes
   * publicly discoverable (the public catalog view requires both, MCAT-9.6).
   */
  const patchToggle = useCallback(
    async (busyKey: "enabled" | "published", fields: Record<string, unknown>, verb: string) => {
      setBusy(busyKey);
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}`, {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(fields),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(
            typeof data.error === "string" ? data.error : res.statusText,
          );
        }
        const updated = mcpEndpointDetailFromPayload(data);
        if (!mountedRef.current) return;
        if (updated) setEndpoint(updated);
        toast.success(`Endpoint ${verb}.`);
      } catch (e) {
        if (mountedRef.current) {
          toast.error(e instanceof Error ? e.message : `Could not ${verb}.`);
        }
      } finally {
        if (mountedRef.current) setBusy(null);
      }
    },
    [endpointId],
  );

  /** Kick off a fresh discovery run and poll it to completion, then reload the surface. */
  const rediscover = useCallback(async () => {
    setBusy("discover");
    try {
      const res = await fetch(`/api/mcp/endpoints/${endpointId}/discover`, {
        method: "POST",
        credentials: "include",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof data.error === "string" ? data.error : res.statusText,
        );
      }
      let job = (data.job ?? null) as McpDiscoveryJob | null;
      const jobId = job?.id;
      if (!jobId) throw new Error("Discovery did not start.");

      for (
        let attempt = 0;
        job && !isTerminalJobState(job.state) && attempt < DISCOVERY_MAX_POLLS;
        attempt += 1
      ) {
        await delay(DISCOVERY_POLL_INTERVAL_MS);
        if (!mountedRef.current) return;
        const jr = await fetch(
          `/api/mcp/endpoints/${endpointId}/discover/${jobId}`,
          { credentials: "include", cache: "no-store" },
        );
        const jd = await jr.json().catch(() => ({}));
        if (!jr.ok) {
          throw new Error(
            typeof jd.error === "string" ? jd.error : jr.statusText,
          );
        }
        job = (jd.job ?? null) as McpDiscoveryJob | null;
      }

      if (isJobSuccess(job)) {
        if (mountedRef.current) toast.success("Discovery complete.");
        await load();
      } else if (job && !isTerminalJobState(job.state)) {
        throw new Error("Discovery is still running — check back shortly.");
      } else {
        throw new Error(discoveryFailureMessage(job));
      }
    } catch (e) {
      if (mountedRef.current) {
        toast.error(e instanceof Error ? e.message : "Discovery failed.");
      }
    } finally {
      if (mountedRef.current) setBusy(null);
    }
  }, [endpointId, load]);

  /** Reflect a Settings-tab identity edit or enable/disable toggle in the header & summary. */
  const handleSettingsSaved = useCallback((updated: McpEndpointDetail) => {
    setEndpoint(updated);
  }, []);

  /** After a Settings-tab delete, surface the teardown summary and return to the catalog. */
  const handleSettingsDeleted = useCallback(
    (summary: McpTeardownSummary) => {
      toast.success(`Endpoint deleted. ${formatTeardownSummary(summary)}`);
      router.push("/ade/dashboard/mcp");
    },
    [router],
  );

  /** Follow a lint finding to its capability item: switch to the Capabilities tab and scroll to it. */
  const navigateToItem = useCallback((itemType: string, name: string) => {
    setPendingAnchor(mcpCapabilityAnchorId(itemType, name));
    setActiveTab("capabilities");
  }, []);

  // Once the Capabilities tab is active and its content has mounted, scroll the pending target
  // into view and highlight it. Runs after commit so the anchor element exists.
  useEffect(() => {
    if (activeTab !== "capabilities" || !pendingAnchor) return;
    const el = document.getElementById(pendingAnchor);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlightedAnchor(pendingAnchor);
    }
    setPendingAnchor(null);
  }, [activeTab, pendingAnchor]);

  // Clear the deep-link highlight after a short, self-cancelling delay.
  useEffect(() => {
    if (!highlightedAnchor) return undefined;
    const timer = setTimeout(() => setHighlightedAnchor(null), 2500);
    return () => clearTimeout(timer);
  }, [highlightedAnchor]);

  const itemGroups = version ? mcpGroupItemsByType(version.items) : [];
  const discovering = busy === "discover";
  const lintCounts = lintReport ? mcpLintTierCounts(lintReport.findings) : null;

  return (
    <>
      <header className="border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        <div className="px-6 py-4">
          <Link
            href="/ade/dashboard/mcp"
            className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-400"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Back to MCP Catalog
          </Link>
          <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h2 className="flex items-center gap-2 text-2xl font-bold text-gray-900 dark:text-white">
                <Server
                  className="h-6 w-6 text-indigo-600 dark:text-indigo-400"
                  aria-hidden
                />
                {endpoint?.name ?? "MCP Endpoint"}
              </h2>
              {endpoint ? (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                  <span>{endpoint.endpoint_url}</span>
                  <span aria-hidden>·</span>
                  <McpBadge tone={mcpTransportBadge(endpoint.transport).tone}>
                    {mcpTransportBadge(endpoint.transport).label}
                  </McpBadge>
                  <McpBadge tone={mcpVisibilityBadge(endpoint.visibility).tone}>
                    {mcpVisibilityBadge(endpoint.visibility).label}
                  </McpBadge>
                  <RecencyPill timestamp={endpoint.last_discovered_at} />
                  <Badge variant={endpoint.enabled ? "success" : "secondary"}>
                    {endpoint.enabled ? "Enabled" : "Disabled"}
                  </Badge>
                  <Badge variant={endpoint.published ? "default" : "outline"}>
                    {endpoint.published ? "Published" : "Unpublished"}
                  </Badge>
                </div>
              ) : null}
            </div>
            {endpoint ? (
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => void rediscover()}
                  disabled={busy !== null}
                  title="Re-run discovery against this endpoint"
                >
                  {discovering ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <RefreshCw className="h-4 w-4" aria-hidden />
                  )}
                  {discovering ? "Discovering…" : "Re-discover"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    void patchToggle(
                      "enabled",
                      { enabled: !endpoint.enabled },
                      endpoint.enabled ? "disabled" : "enabled",
                    )
                  }
                  disabled={busy !== null}
                  title={
                    endpoint.enabled
                      ? "Stop scheduled discovery for this endpoint"
                      : "Resume scheduled discovery for this endpoint"
                  }
                >
                  {busy === "enabled" ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : endpoint.enabled ? (
                    <PowerOff className="h-4 w-4" aria-hidden />
                  ) : (
                    <Power className="h-4 w-4" aria-hidden />
                  )}
                  {endpoint.enabled ? "Disable" : "Enable"}
                </Button>
                <Button
                  type="button"
                  variant={endpoint.published ? "outline" : "default"}
                  size="sm"
                  onClick={() =>
                    void patchToggle(
                      "published",
                      // Publish sets published AND visibility='public' together (public catalog
                      // requires both); unpublish reverts to private. See mcpPublishTogglePatch.
                      mcpPublishTogglePatch(endpoint.published),
                      endpoint.published ? "unpublished" : "published",
                    )
                  }
                  disabled={busy !== null}
                  title={
                    endpoint.published
                      ? "Remove this endpoint from the public catalog (make it private)"
                      : "Publish this endpoint to the public catalog so it's listed in the browser"
                  }
                >
                  {busy === "published" ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : endpoint.published ? (
                    <Lock className="h-4 w-4" aria-hidden />
                  ) : (
                    <Globe className="h-4 w-4" aria-hidden />
                  )}
                  {endpoint.published ? "Unpublish" : "Publish"}
                </Button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className={dashboardMainClass} aria-busy={loading}>
        <div className={dashboardContentStackClass}>
          <div className="px-6 pb-8 pt-4">
            {loading ? (
              <LoadingState
                minHeightClassName="min-h-[220px]"
                message="Loading endpoint…"
              />
            ) : error || !endpoint ? (
              <EmptyState
                icon={<Server className="h-10 w-10 text-white" aria-hidden />}
                title="Endpoint unavailable"
                description={
                  error ?? "This MCP endpoint could not be found in your catalog."
                }
              />
            ) : (
              <div className="space-y-6">
                {/* Version & score summary */}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className={dashboardPanelPaddedClass}>
                    <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                      Quality grade
                    </div>
                    <div className="mt-2">
                      {lintReport ? (
                        <McpGradeSummary
                          score={lintReport.score}
                          grade={lintReport.grade}
                          mustCount={lintCounts?.must ?? 0}
                          shouldCount={lintCounts?.should ?? 0}
                        />
                      ) : (
                        <Badge variant={mcpScoreVariant(version?.score ?? null)}>
                          {mcpScoreLabel(version?.score ?? null, version?.grade ?? null)}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <div className={dashboardPanelPaddedClass}>
                    <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                      Current version
                    </div>
                    <div className="mt-2 text-lg font-semibold text-gray-900 dark:text-white">
                      {version
                        ? version.version_tag ?? `v${version.version_seq}`
                        : "—"}
                    </div>
                  </div>
                  <div className={dashboardPanelPaddedClass}>
                    <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                      Server
                    </div>
                    <div className="mt-2 text-sm text-gray-900 dark:text-white">
                      {version?.server_title ?? version?.server_name ?? "—"}
                      {version?.server_version ? ` (${version.server_version})` : ""}
                    </div>
                    {version?.protocol_version ? (
                      <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                        MCP protocol {version.protocol_version}
                      </div>
                    ) : null}
                  </div>
                  <div className={dashboardPanelPaddedClass}>
                    <div className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                      Last discovered
                    </div>
                    <div className="mt-2 text-sm text-gray-900 dark:text-white">
                      <RecencyPill timestamp={endpoint.last_discovered_at} prefix="" hideIcon />
                    </div>
                  </div>
                </div>

                <DetailTabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
                  <DetailTabsList
                    items={MCP_DETAIL_TABS}
                    only={["capabilities", "insight", "versions", "lint", "settings"]}
                  />

                  <DetailTabsContent value="capabilities" className="space-y-6">
                {/* Server instructions */}
                {version?.instructions ? (
                  <section>
                    <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
                      <FileText className="h-4 w-4 text-indigo-500" aria-hidden />
                      Instructions
                    </h3>
                    <div className={dashboardPanelPaddedClass}>
                      <p className="whitespace-pre-wrap text-sm text-gray-600 dark:text-gray-300">
                        {version.instructions}
                      </p>
                    </div>
                  </section>
                ) : null}

                {/* Capabilities: tools / resources / resource templates / prompts */}
                {!version ? (
                  <EmptyState
                    variant="compact"
                    icon={<Wrench className="h-8 w-8 text-white" aria-hidden />}
                    title="Not yet discovered"
                    description="This endpoint has no current version snapshot. Run discovery to populate its tools, resources, and prompts."
                  />
                ) : itemGroups.length === 0 ? (
                  <EmptyState
                    variant="compact"
                    icon={<Wrench className="h-8 w-8 text-white" aria-hidden />}
                    title="No capabilities"
                    description="The current version snapshot declares no tools, resources, or prompts."
                  />
                ) : (
                  itemGroups.map((group) => (
                    <section key={group.key}>
                      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
                        {group.key === "prompt" ? (
                          <FileText className="h-4 w-4 text-indigo-500" aria-hidden />
                        ) : (
                          <Wrench className="h-4 w-4 text-indigo-500" aria-hidden />
                        )}
                        {group.label}
                        <Badge variant="secondary">{group.items.length}</Badge>
                      </h3>
                      <div className="space-y-3">
                        {group.items.map((item) => {
                          const anchorId = mcpCapabilityAnchorId(item.item_type, item.name);
                          return (
                            <CapabilityItemCard
                              key={`${group.key}:${item.name}`}
                              groupKey={group.key}
                              item={item}
                              anchorId={anchorId}
                              highlighted={highlightedAnchor === anchorId}
                            />
                          );
                        })}
                      </div>
                    </section>
                  ))
                )}
                  </DetailTabsContent>

                  <DetailTabsContent value="insight">
                    <McpEndpointInsight
                      endpointId={endpointId}
                      currentVersionId={endpoint.current_version_id ?? null}
                      endpoint={endpoint}
                      currentInstructions={version?.instructions ?? null}
                    />
                  </DetailTabsContent>

                  <DetailTabsContent value="lint">
                    <McpLintReport
                      report={lintReport}
                      loading={lintLoading}
                      error={lintError}
                      onNavigateToItem={navigateToItem}
                    />
                  </DetailTabsContent>

                  <DetailTabsContent value="versions">
                    <McpVersionHistory endpointId={endpointId} />
                  </DetailTabsContent>

                  <DetailTabsContent value="settings">
                    <McpEndpointSettings
                      endpoint={endpoint}
                      onSaved={handleSettingsSaved}
                      onDeleted={handleSettingsDeleted}
                    />
                  </DetailTabsContent>
                </DetailTabs>
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
