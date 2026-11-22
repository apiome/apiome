/**
 * `apiome-db plan-check`: EXPLAIN the hot queries on the scale database and fail on a large
 * sequential scan or a blown time budget (DBP-1.1, #7184). See src/plan-check.ts.
 */

import fs from "node:fs/promises";

import type pg from "pg";

import { CliError } from "../errors.js";
import { note, printRecord, type OutputMode } from "../output.js";
import {
  defaultQueriesFile,
  loadPlanCheckSpec,
  reportMarkdown,
  runPlanCheck,
} from "../plan-check.js";

export type PlanCheckOptions = {
  /** Query list (default: the package's plan-check/hot-queries.json). */
  queries?: string;
  /** Override the list's row threshold. */
  rowThreshold?: number;
  /** Executions per query; the fastest counts. */
  runs?: number;
  /** Only run these query names. */
  only?: string[];
  /** Also write the Markdown report here (e.g. `$GITHUB_STEP_SUMMARY`). */
  markdown?: string;
};

/**
 * Run the plan check and print the report; exit 1 when a query fails.
 *
 * @param client An open connection to the scale database.
 * @param opts Command options.
 * @param mode Table or JSON output.
 * @throws CliError With exit code 1 when any query fails.
 */
export async function runPlanCheckCommand(
  client: pg.Client,
  opts: PlanCheckOptions,
  mode: OutputMode,
): Promise<void> {
  const spec = await loadPlanCheckSpec(opts.queries ?? defaultQueriesFile());
  if (opts.rowThreshold !== undefined) {
    if (!Number.isFinite(opts.rowThreshold) || opts.rowThreshold < 0) {
      throw new CliError("--row-threshold must be a number ≥ 0.", { exitCode: 2 });
    }
    spec.rowThreshold = opts.rowThreshold;
  }
  const report = await runPlanCheck(client, spec, { runs: opts.runs, only: opts.only });
  const markdown = reportMarkdown(report);
  if (opts.markdown) await fs.appendFile(opts.markdown, markdown, "utf8");
  if (mode.json) printRecord(mode, report);
  else process.stdout.write(markdown);
  if (report.failed > 0) {
    throw new CliError(`${report.failed} of ${report.results.length} hot queries failed the plan check.`, {
      exitCode: 1,
    });
  }
  if (!mode.json) note(`All ${report.results.length} hot queries passed (or are known and tracked).`);
}
