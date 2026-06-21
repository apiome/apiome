#!/usr/bin/env -S node --import tsx

import { flush } from "@oclif/core/flush";
import { ExitError } from "@oclif/core/errors";
import { run } from "@oclif/core/run";
import { settings } from "@oclif/core/settings";

import { normalizeCliArgv } from "../src/lib/normalize-argv.js";
import { formatAndReportCliFailure, resolveDebugStacks } from "../src/lib/handle-error.js";

process.env.NODE_ENV = "development";
settings.debug = true;

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
