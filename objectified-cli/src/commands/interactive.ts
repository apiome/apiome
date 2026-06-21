import { homedir } from "node:os";
import { join } from "node:path";

import { ExitError } from "@oclif/core/errors";
import { flush } from "@oclif/core/flush";
import { run as oclifRun } from "@oclif/core/run";

import { BaseCommand } from "../base-command.js";
import { computeCompletionCandidates } from "../lib/completion/candidates-logic.js";
import { parseCompletionLine } from "../lib/interactive/tokenize.js";
import { runInteractiveRepl } from "../lib/interactive/repl.js";
import { normalizeCliArgv } from "../lib/normalize-argv.js";

/** Set while a REPL is active so a typed `interactive`/`repl` cannot recurse. */
const INTERACTIVE_ENV = "OBJECTIFIED_INTERACTIVE";

export default class Interactive extends BaseCommand {
  static description =
    "Start an interactive session (REPL) that runs many commands in one process, with Tab completion. Running the CLI with no arguments enters this mode.";

  static aliases = ["repl"];

  static examples = [
    "<%= config.bin %>",
    "<%= config.bin %> <%= command.id %>",
    'printf "%s\\n" "projects list" "tenants list" | <%= config.bin %> <%= command.id %>',
  ];

  static seeAlso = ["completion", "hello", "config path"];

  async run(): Promise<void> {
    if (process.env[INTERACTIVE_ENV] === "1") {
      this.output.warn("Already in an interactive session.");
      return;
    }

    const bin = this.config.bin;
    // `process.stdin.isTTY` is `boolean` in types (runtime: undefined when piped → falsy).
    const isTTY = process.stdin.isTTY;
    const historyFile = join(homedir(), ".cache", "objectified", "interactive", "history");

    const execute = async (argv: string[]): Promise<void> => {
      try {
        // Reuse the already-loaded oclif Config so each line resolves like a real
        // invocation (global-flag promotion, topic separators, help/version plugins).
        await oclifRun(normalizeCliArgv(argv), this.config);
      } catch (error) {
        // BaseCommand.catch already formatted/printed command failures before
        // throwing ExitError — swallow it so the session stays alive. Surface only
        // genuinely unexpected errors.
        if (!(error instanceof ExitError)) {
          const message = error instanceof Error ? error.message : String(error);
          process.stderr.write(`${bin}: ${message}\n`);
        }
      } finally {
        await flush();
      }
    };

    const complete = async (line: string): Promise<string[]> => {
      const { words, cword } = parseCompletionLine(line, bin);
      try {
        return await computeCompletionCandidates({
          config: this.config,
          api: this.api,
          baseUrl: this.context.baseUrl,
          configDoc: this.configDoc,
          env: process.env,
          words,
          cword,
        });
      } catch {
        return [];
      }
    };

    const previous = process.env[INTERACTIVE_ENV];
    process.env[INTERACTIVE_ENV] = "1";
    try {
      await runInteractiveRepl({
        binName: bin,
        versionLabel: this.config.version,
        input: process.stdin,
        output: process.stdout,
        errorOutput: process.stderr,
        isTTY,
        color: this.context.color,
        quiet: Boolean(this.flags.quiet),
        execute,
        complete,
        historyFile,
      });
    } finally {
      if (previous === undefined) Reflect.deleteProperty(process.env, INTERACTIVE_ENV);
      else process.env[INTERACTIVE_ENV] = previous;
    }
  }
}
