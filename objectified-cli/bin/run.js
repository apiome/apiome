#!/usr/bin/env node

import { flush } from "@oclif/core/flush";
import { ExitError } from "@oclif/core/errors";
import { run } from "@oclif/core/run";

import { normalizeCliArgv } from "../dist/lib/normalize-argv.js";
import { formatAndReportCliFailure, resolveDebugStacks } from "../dist/lib/handle-error.js";

const rawArgs = process.argv.slice(2);
// No arguments at all → drop into the interactive session (REPL).
const argv = rawArgs.length === 0 ? ["interactive"] : normalizeCliArgv(rawArgs);

try {
  await run(argv, import.meta.url);
  flush();
} catch (error) {
  flush();
  if (error instanceof ExitError) {
    process.exit(error.oclif?.exit ?? 1);
  }
  const debugStacks = resolveDebugStacks(argv, process.env);
  const color =
    process.env.NO_COLOR === undefined || process.env.NO_COLOR === ""
      ? Boolean(process.stderr.isTTY)
      : false;
  const code = formatAndReportCliFailure(error, { debugStacks, color });
  process.exit(code);
}
