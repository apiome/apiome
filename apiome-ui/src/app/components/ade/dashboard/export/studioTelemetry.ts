/**
 * Privacy-safe Export studio usage telemetry — the client (MFX-46.5, #4383).
 *
 * Posts one whitelisted event to `/api/export/studio-metrics` (REST `POST /v1/export/{tenant}/studio-metrics`,
 * the same analytics path as the projection metrics of EFP-3.2): which target was chosen, each verify
 * verdict, the lossy acknowledgement asked for and given (the acknowledge-lossy rate), test-drive tools
 * opened or run, and visualizations shown. Every field is a controlled vocabulary — never an artifact
 * name, a source, a file or an option value; the REST layer refuses anything else.
 *
 * Telemetry is best-effort: a failed post is swallowed and never blocks or breaks the studio.
 */

import type { ExportVerifyVerdict } from './exportVerify';

/** Where the event happened. */
export type StudioSurface = 'studio' | 'dialog';

/** A verification's verdict as telemetry records it (`error`: the verification could not run). */
export type StudioVerdict = ExportVerifyVerdict | 'error';

/** The test-drive tools (mirrors Python `ExportTestToolKind`). */
export type StudioTestTool = 'swagger-ui' | 'redoc' | 'graphiql' | 'asyncapi-render' | 'mock-server' | 'toolchain';

/** The visualizations (the registry's view modes, plus the fidelity overlay and treemap). */
export type StudioViz = 'erd' | 'proto-imports' | 'service-map' | 'channel-topology' | 'fidelity-overlay' | 'fidelity-treemap';

/** One usage event. */
export type StudioEvent =
  | { kind: 'target_chosen'; target: string; mode?: 'single' | 'multi' }
  | { kind: 'verify_verdict'; verdict: StudioVerdict }
  | { kind: 'lossy_prompt_shown' | 'lossy_acknowledged'; verdict: 'lossy' | 'severe' }
  | { kind: 'test_drive_used'; tool: StudioTestTool; action?: 'open' | 'run' }
  | { kind: 'viz_used'; view: StudioViz };

const TEST_TOOLS: ReadonlySet<string> = new Set([
  'swagger-ui', 'redoc', 'graphiql', 'asyncapi-render', 'mock-server', 'toolchain',
]);
const VIEWS: ReadonlySet<string> = new Set([
  'erd', 'proto-imports', 'service-map', 'channel-topology', 'fidelity-overlay', 'fidelity-treemap',
]);

/** Whether a tool kind is one telemetry records (a newer server-side tool is skipped, not sent). */
export function isStudioTestTool(kind: string): kind is StudioTestTool {
  return TEST_TOOLS.has(kind);
}

/** Whether a view is one telemetry records (`text` and unknown modes are not). */
export function isStudioViz(view: string): view is StudioViz {
  return VIEWS.has(view);
}

/**
 * Record one usage event. Failures are swallowed — telemetry never blocks the studio.
 *
 * @param event The event.
 * @param surface Export studio (default) or the Export dialog.
 */
export async function trackStudioEvent(event: StudioEvent, surface: StudioSurface = 'studio'): Promise<void> {
  try {
    await fetch('/api/export/studio-metrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ ...event, surface }),
    });
  } catch {
    // Best-effort; ignore transport errors.
  }
}
