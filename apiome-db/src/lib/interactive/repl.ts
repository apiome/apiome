/**
 * Interactive REPL loop for apiome-db.
 *
 * A TTY session creates a fresh `readline` interface per prompt and closes it
 * before executing a command, so sub-commands that read stdin (e.g.
 * `--password-stdin`) get exclusive control of the input stream — exactly as in
 * a one-shot invocation. Non-TTY input is treated as a batch script: every line
 * is executed in order (useful for piping a command list).
 */

import { createInterface } from "node:readline";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { tokenizeLine } from "./tokenize.js";

const HISTORY_LIMIT = 500;

export type ReplDeps = {
  /** CLI binary name (e.g. "apiome-db"); used for the prompt. */
  binName: string;
  /** Version label shown in the banner. */
  versionLabel?: string;
  input: NodeJS.ReadStream;
  output: NodeJS.WritableStream;
  errorOutput: NodeJS.WritableStream;
  /** Whether the session is attached to a terminal (prompt + history). */
  isTTY: boolean;
  /** Allow ANSI styling in the banner/prompt. */
  color: boolean;
  /** Run one command line's argv (errors already reported by the command). */
  execute: (argv: string[]) => Promise<void>;
  /** Best-effort persistent history file (TTY only). */
  historyFile?: string;
};

type LineKind =
  | { kind: "empty" }
  | { kind: "exit" }
  | { kind: "clear" }
  | { kind: "nested" }
  | { kind: "run"; argv: string[] };

const EXIT_WORDS = new Set(["exit", "quit", ":q"]);
const NESTED_WORDS = new Set(["interactive", "repl"]);

export function classifyLine(line: string): LineKind {
  const argv = tokenizeLine(line);
  if (argv.length === 0) return { kind: "empty" };
  const head = (argv[0] ?? "").toLowerCase();
  if (argv.length === 1 && EXIT_WORDS.has(head)) return { kind: "exit" };
  if (argv.length === 1 && head === "clear") return { kind: "clear" };
  if (NESTED_WORDS.has(head)) return { kind: "nested" };
  return { kind: "run", argv };
}

function dim(text: string, color: boolean): string {
  return color ? `\x1b[2m${text}\x1b[0m` : text;
}

function loadHistory(file: string | undefined): string[] {
  if (!file) return [];
  try {
    const raw = readFileSync(file, "utf8");
    // Stored oldest-first; readline wants most-recent-first.
    return raw
      .split("\n")
      .filter((l) => l.trim() !== "")
      .reverse();
  } catch {
    return [];
  }
}

function persistHistory(file: string | undefined, history: string[]): void {
  if (!file) return;
  try {
    mkdirSync(dirname(file), { recursive: true });
    // history is most-recent-first; persist oldest-first, capped.
    const oldestFirst = [...history].slice(0, HISTORY_LIMIT).reverse();
    writeFileSync(file, `${oldestFirst.join("\n")}\n`, "utf8");
  } catch {
    /* best-effort */
  }
}

function rememberHistory(history: string[], line: string): void {
  const trimmed = line.trim();
  if (trimmed === "") return;
  if (history[0] === trimmed) return; // skip consecutive duplicates
  history.unshift(trimmed);
  if (history.length > HISTORY_LIMIT) history.length = HISTORY_LIMIT;
}

type LineResult = { type: "line"; value: string } | { type: "eof" } | { type: "sigint" };

/** Read exactly one line from a freshly created (then closed) readline interface. */
function readOneLine(deps: ReplDeps, prompt: string, history: string[]): Promise<LineResult> {
  return new Promise((resolve) => {
    const rl = createInterface({
      input: deps.input,
      output: deps.output,
      terminal: true,
      history: [...history],
      historySize: HISTORY_LIMIT,
      prompt,
    });

    let settled = false;
    const finish = (result: LineResult): void => {
      if (settled) return;
      settled = true;
      rl.close();
      resolve(result);
    };

    rl.on("line", (value) => {
      finish({ type: "line", value });
    });
    rl.on("close", () => {
      finish({ type: "eof" });
    });
    rl.on("SIGINT", () => {
      deps.output.write("\n");
      finish({ type: "sigint" });
    });

    rl.prompt();
  });
}

async function runTtySession(deps: ReplDeps): Promise<void> {
  const prompt = deps.color
    ? `\x1b[36m${deps.binName}\x1b[0m\x1b[2m>\x1b[0m `
    : `${deps.binName}> `;

  const v = deps.versionLabel ? ` v${deps.versionLabel}` : "";
  deps.output.write(`apiome-db${v} — interactive admin session\n`);
  deps.output.write(
    dim(
      `Type a command (e.g. \`tenants list\`), "help" for commands, "exit" to quit.\n` +
        `Connection comes from APIOME_DB_URL / POSTGRES_* env (or pass --database-url per command).\n`,
      deps.color,
    ),
  );

  const history = loadHistory(deps.historyFile);

  for (;;) {
    const result = await readOneLine(deps, prompt, history);
    if (result.type === "eof") {
      deps.output.write("\n");
      break;
    }
    if (result.type === "sigint") {
      continue; // cancel the current line, keep the session alive
    }

    const line = result.value;
    rememberHistory(history, line);
    const classified = classifyLine(line);

    if (classified.kind === "empty") continue;
    if (classified.kind === "exit") break;
    if (classified.kind === "clear") {
      deps.output.write("\x1b[2J\x1b[H");
      continue;
    }
    if (classified.kind === "nested") {
      deps.errorOutput.write("Already in an interactive session.\n");
      continue;
    }

    await deps.execute(classified.argv);
  }

  persistHistory(deps.historyFile, history);
  deps.output.write(dim("Bye.\n", deps.color));
}

function readAllStdin(input: NodeJS.ReadStream): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    input.on("data", (d: string | Buffer) => {
      chunks.push(typeof d === "string" ? Buffer.from(d) : d);
    });
    input.on("end", () => {
      resolve(Buffer.concat(chunks).toString("utf8"));
    });
    input.on("error", reject);
  });
}

/** Batch mode: execute every non-empty line read from non-TTY stdin, in order. */
async function runBatchSession(deps: ReplDeps): Promise<void> {
  const raw = await readAllStdin(deps.input);
  const lines = raw.split("\n");
  for (const line of lines) {
    const classified = classifyLine(line);
    if (classified.kind === "empty") continue;
    if (classified.kind === "exit") break;
    if (classified.kind === "clear") continue;
    if (classified.kind === "nested") {
      deps.errorOutput.write("Already in an interactive session.\n");
      continue;
    }
    await deps.execute(classified.argv);
  }
}

export async function runInteractiveRepl(deps: ReplDeps): Promise<void> {
  if (deps.isTTY) {
    await runTtySession(deps);
  } else {
    await runBatchSession(deps);
  }
}
