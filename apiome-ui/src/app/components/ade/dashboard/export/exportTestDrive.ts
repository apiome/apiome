/**
 * The Review step's **Test drive** tabs, from the target registry — MFX-44.1 (#4367).
 *
 * Which tools can test drive an emitted artifact is registry data: each target's descriptor carries
 * `test_tools` (`GET /export/targets`), declared by its emitter in apiome-rest. This module turns that
 * list into tabs without knowing any target — so a new emitter that declares tools needs no change
 * here — and knows only which tool *kinds* this build can draw (each kind's renderer lives in the
 * Studio). A kind it cannot draw yet is left out rather than shown empty.
 *
 * Server-side tools (`mock-server`, `toolchain`) carry their availability on this server; a tab whose
 * every tool is unavailable is shown disabled with the server's reason, never hidden.
 */

/** A tool kind the registry declares (open-ended: a newer server may declare kinds this build lacks). */
export type ExportTestToolKind =
  | 'swagger-ui'
  | 'redoc'
  | 'graphiql'
  | 'asyncapi-render'
  | 'mock-server'
  | 'toolchain'
  | (string & {});

/** One test-drive tool of a target (mirrors Python `ExportTestTool`). */
export interface ExportTestTool {
  /** The tool kind, e.g. `swagger-ui` or `toolchain`. */
  kind: ExportTestToolKind;
  /** The tab / row label, e.g. `Swagger UI` or `buf lint`. */
  label: string;
  /** Kind-specific parameters, e.g. a toolchain check's `tool` and `check`. */
  params?: Record<string, unknown>;
  /** Whether the tool runs on the server rather than in the browser. */
  server_side: boolean;
  /** Whether the tool can run here. Absent is treated as `true`. */
  available?: boolean;
  /** Why a server-side tool cannot run on this server. */
  unavailable_reason?: string | null;
}

/** One tab of the strip: every tool of one kind. */
export interface TestDriveTab {
  /** The kind; also the tab's id. */
  kind: ExportTestToolKind;
  /** The tab label: the tool's own, or the kind's plural for several tools of one kind. */
  label: string;
  /** The tools on this tab, in registry order. */
  tools: ExportTestTool[];
  /** Whether any tool on the tab can run here. */
  available: boolean;
  /** Why none can (the distinct reasons, joined), or null when the tab is available. */
  reason: string | null;
}

/** The label of a tab holding several tools of one kind. */
const PLURAL_LABELS: Record<string, string> = { toolchain: 'Toolchain checks' };

/** Whether a tool can run here (`available` absent counts as yes, for older servers). */
export function toolAvailable(tool: ExportTestTool): boolean {
  return tool.available !== false;
}

/**
 * The Test drive tabs for a target's tools.
 *
 * @param tools The target descriptor's `test_tools` (absent on older servers).
 * @param drawable The kinds this build has a renderer for.
 * @returns One tab per drawable kind, in the order the registry first lists it; empty when none.
 */
export function testDriveTabs(
  tools: readonly ExportTestTool[] | null | undefined,
  drawable: ReadonlySet<string>,
): TestDriveTab[] {
  const byKind = new Map<string, ExportTestTool[]>();
  for (const tool of tools ?? []) {
    if (!drawable.has(tool.kind)) continue;
    byKind.set(tool.kind, [...(byKind.get(tool.kind) ?? []), tool]);
  }
  return [...byKind.entries()].map(([kind, group]) => {
    const available = group.some(toolAvailable);
    const reasons = [...new Set(group.map((tool) => tool.unavailable_reason).filter((r): r is string => Boolean(r)))];
    return {
      kind,
      label: group.length === 1 ? group[0].label : (PLURAL_LABELS[kind] ?? group[0].label),
      tools: group,
      available,
      reason: available ? null : reasons.join(' ') || 'Unavailable on this server.',
    };
  });
}

/**
 * The tab to show first: the first available one.
 *
 * @param tabs The strip's tabs.
 * @returns Its kind, or null when no tab can be opened.
 */
export function initialTestDriveTab(tabs: readonly TestDriveTab[]): ExportTestToolKind | null {
  return tabs.find((tab) => tab.available)?.kind ?? null;
}
