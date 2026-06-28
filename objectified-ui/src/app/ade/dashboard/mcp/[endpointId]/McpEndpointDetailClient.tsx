"use client";

import Link from "next/link";
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
import {
  dashboardContentStackClass,
  dashboardMainClass,
  dashboardPanelPaddedClass,
} from "@/app/components/ade/dashboard/dashboardScreenClasses";
import {
  discoveryFailureMessage,
  isJobSuccess,
  isTerminalJobState,
  type McpDiscoveryJob,
} from "@/app/components/ade/dashboard/mcp/mcpImportFlow";
import {
  formatLastDiscovered,
  mcpAnnotationHints,
  mcpEndpointDetailFromPayload,
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

/** Render one capability item's name/uri/description plus its schema & annotation detail. */
function CapabilityItemCard({
  groupKey,
  item,
}: {
  groupKey: string;
  item: McpCapabilityItem;
}) {
  const hints = mcpAnnotationHints(item);
  const sections = mcpItemDetailSections(item);
  return (
    <div className="border-b border-gray-100 pb-3 last:border-b-0 last:pb-0 dark:border-gray-700">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-gray-900 dark:text-white">
          {item.title ?? item.name}
        </span>
        {hints.map((hint) => (
          <Badge
            key={hint.key}
            variant={hint.value ? "default" : "secondary"}
            title={`${hint.label}: ${hint.value}`}
          >
            {hint.value ? hint.label : `Not ${hint.label.toLowerCase()}`}
          </Badge>
        ))}
      </div>
      <div className="font-mono text-xs text-gray-500 dark:text-gray-400">
        {item.uri ?? item.uri_template ?? item.name}
      </div>
      {item.description ? (
        <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
          {item.description}
        </p>
      ) : null}
      {sections.length > 0 ? (
        <div className="mt-2 space-y-2">
          {sections.map((section) => (
            <details
              key={`${groupKey}:${item.name}:${section.key}`}
              className="rounded-md border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/40"
            >
              <summary className="cursor-pointer select-none px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
                {section.label}
              </summary>
              <pre className="overflow-x-auto px-3 pb-3 text-xs leading-relaxed text-gray-700 dark:text-gray-300">
                <code>{section.json}</code>
              </pre>
            </details>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function McpEndpointDetailClient({ endpointId }: Props) {
  const [endpoint, setEndpoint] = useState<McpEndpointDetail | null>(null);
  const [version, setVersion] = useState<McpVersionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Which control is mid-flight ("discover" | "enabled" | "published"), or null when idle. */
  const [busy, setBusy] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

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
      } else {
        setVersion(null);
      }
    } catch (e) {
      console.error(e);
      if (!mountedRef.current) return;
      setError(e instanceof Error ? e.message : "Could not load endpoint.");
      setEndpoint(null);
      setVersion(null);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [endpointId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** PATCH a mutable toggle (enabled / published) and reflect the returned record. */
  const patchToggle = useCallback(
    async (field: "enabled" | "published", value: boolean, verb: string) => {
      setBusy(field);
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}`, {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [field]: value }),
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

  const itemGroups = version ? mcpGroupItemsByType(version.items) : [];
  const discovering = busy === "discover";

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
                  <span>{endpoint.transport}</span>
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
                      !endpoint.enabled,
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
                      !endpoint.published,
                      endpoint.published ? "unpublished" : "published",
                    )
                  }
                  disabled={busy !== null}
                  title={
                    endpoint.published
                      ? "Remove this endpoint from the published catalog"
                      : "Publish this endpoint to the catalog"
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
                      Quality score
                    </div>
                    <div className="mt-2">
                      <Badge variant={mcpScoreVariant(version?.score ?? null)}>
                        {mcpScoreLabel(version?.score ?? null, version?.grade ?? null)}
                      </Badge>
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
                      {formatLastDiscovered(endpoint.last_discovered_at)}
                    </div>
                  </div>
                </div>

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
                      <div className={`${dashboardPanelPaddedClass} space-y-3`}>
                        {group.items.map((item) => (
                          <CapabilityItemCard
                            key={`${group.key}:${item.name}`}
                            groupKey={group.key}
                            item={item}
                          />
                        ))}
                      </div>
                    </section>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
