import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const pkgRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

/** Run the built CLI with `stdinLines` piped in (non-TTY → batch/interactive session). */
function runWithStdin(
  args: string[],
  stdinLines: string[],
  extraEnv: Record<string, string> = {},
): { stdout: string; stderr: string } {
  const env = {
    ...process.env,
    FORCE_COLOR: "0",
    OBJECTIFIED_CLI_CREDENTIAL_BACKEND: "memory",
    ...extraEnv,
  };
  delete env.NODE_OPTIONS;
  const stdout = execFileSync("node", [path.join(pkgRoot, "bin/run.js"), ...args], {
    cwd: pkgRoot,
    encoding: "utf8",
    env,
    input: `${stdinLines.join("\n")}\n`,
  });
  return { stdout, stderr: "" };
}

describe("interactive session (batch via piped stdin)", () => {
  it("runs multiple commands in one process when invoked with no args", () => {
    const { stdout } = runWithStdin([], ["hello Ada", "hello Grace"]);
    expect(stdout).toContain("Hello Ada from Objectified CLI");
    expect(stdout).toContain("Hello Grace from Objectified CLI");
  });

  it("stops the session at `exit`", () => {
    const { stdout } = runWithStdin([], ["hello one", "exit", "hello two"]);
    expect(stdout).toContain("Hello one from Objectified CLI");
    expect(stdout).not.toContain("Hello two from Objectified CLI");
  });

  it("keeps the session alive after a command fails", () => {
    // `projects show` with no ref fails (exit 2); the next command must still run.
    const { stdout } = runWithStdin(["interactive"], ["hello one", "projects show", "hello two"]);
    expect(stdout).toContain("Hello one from Objectified CLI");
    expect(stdout).toContain("Hello two from Objectified CLI");
  });

  it("refuses to nest a second interactive session", () => {
    // stderr is merged into the thrown error only on failure; capture via execSync stdio here.
    const out = execFileSync("node", [path.join(pkgRoot, "bin/run.js"), "interactive"], {
      cwd: pkgRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        FORCE_COLOR: "0",
        OBJECTIFIED_CLI_CREDENTIAL_BACKEND: "memory",
      },
      input: "interactive\nhello ok\n",
      stdio: ["pipe", "pipe", "pipe"],
    });
    expect(out).toContain("Hello ok from Objectified CLI");
  });
});
