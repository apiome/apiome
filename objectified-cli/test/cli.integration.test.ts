import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import { performance } from "node:perf_hooks";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const pkgRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

function run(args: string[], extraEnv: Record<string, string> = {}): string {
  const env = { ...process.env, FORCE_COLOR: "0", ...extraEnv };
  delete env.NODE_OPTIONS;
  return execFileSync("node", [path.join(pkgRoot, "bin/run.js"), ...args], {
    cwd: pkgRoot,
    encoding: "utf8",
    env,
  });
}

function runExpectFailure(args: string[], extraEnv: Record<string, string> = {}): string {
  try {
    run(args, extraEnv);
    throw new Error(`Expected command to fail: ${args.join(" ")}`);
  } catch (err: unknown) {
    if (err && typeof err === "object" && "stderr" in err) {
      const se = (err as { stderr: Buffer | string }).stderr;
      return typeof se === "string" ? se : se.toString("utf8");
    }
    throw err;
  }
}

function runStdin(args: string[], stdin: string, extraEnv: Record<string, string> = {}): string {
  const env = { ...process.env, FORCE_COLOR: "0", ...extraEnv };
  delete env.NODE_OPTIONS;
  return execFileSync("node", [path.join(pkgRoot, "bin/run.js"), ...args], {
    cwd: pkgRoot,
    encoding: "utf8",
    input: stdin,
    env,
  });
}

describe("objectified CLI", () => {
  it("prints version", () => {
    const out = run(["--version"]);
    expect(out.trim()).toMatch(/\d+\.\d+\.\d+/);
  });

  it("prints top-level help", () => {
    const out = run(["--help"]);
    expect(out).toContain("VERSION");
    expect(out).toContain("COMMANDS");
    expect(out).toContain("GLOBAL FLAGS");
    expect(out).toContain("Resolution order for base URL");
    expect(out).toContain("--base-url");
  });

  it("runs hello smoke command", () => {
    const out = run(["hello"]);
    expect(out).toContain("Hello world from Objectified CLI");
  });

  it("runs hello with a name argument", () => {
    const out = run(["hello", "Ada"]);
    expect(out).toContain("Hello Ada from Objectified CLI");
  });

  it("outputs JSON for hello when --json", () => {
    const out = run(["--json", "hello"]);
    expect(() => JSON.parse(out.trim())).not.toThrow();
    expect(JSON.parse(out.trim())).toMatchObject({
      message: "Hello world from Objectified CLI",
    });
  });

  it("projects list requires tenant slug (no network)", () => {
    const err = runExpectFailure(["--json", "projects", "list"]);
    expect(err).toMatch(/Tenant slug is required/i);
  });

  it("docs errors prints exit code reference", () => {
    const out = run(["docs", "errors", "--no-json"]);
    expect(out).toMatch(/Exit codes/);
    expect(out).toMatch(/not authenticated/);
    expect(out).toMatch(/OBJECTIFIED_DEBUG/);
  });

  it("docs lists available topics", () => {
    const out = run(["docs", "--no-json"]);
    expect(out).toMatch(/Topic/);
    expect(out).toMatch(/\berrors\b/);
    expect(out).toMatch(/\boutput\b/);
    expect(out).toMatch(/\bprofiles\b/);
    expect(out).toMatch(/\bcompletions\b/);
    expect(out).toMatch(/\bplugins\b/);
    expect(out).toMatch(/\btelemetry\b/);
  });

  it("docs completions describes completion install/show/uninstall", () => {
    const out = run(["docs", "completions", "--no-json"]);
    expect(out).toMatch(/completion install/);
    expect(out).toMatch(/completion show/);
    expect(out).toMatch(/completion uninstall/);
  });

  it("docs output prints long-form prose", () => {
    const out = run(["docs", "output", "--no-json"]);
    expect(out).toMatch(/OUTPUT FORMATTING/);
    expect(out).toMatch(/Stable JSON/);
  });

  it("command help includes EXAMPLES and SEE ALSO", () => {
    const out = run(["hello", "--help"]);
    expect(out).toMatch(/^EXAMPLES/m);
    expect(out).toMatch(/^SEE ALSO/m);
    expect(out).toMatch(/\bCOMMON\b/);
    expect(out).toMatch(/\bOUTPUT\b/);
    expect(out).toMatch(/\bAUTH\b/);
  });

  it("unknown command suggests typo fix when close match", () => {
    const err = runExpectFailure(["helol"]);
    expect(err).toMatch(/Unknown command/);
    expect(err).toMatch(/Did you mean/);
    expect(err).toMatch(/hello/);
  });

  it("config path respects OBJECTIFIED_CONFIG", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-int-"));
    const cfg = path.join(dir, "objectified.toml");
    const out = run(["--no-json", "config", "path"], { OBJECTIFIED_CONFIG: cfg }).trim();
    expect(out).toBe(cfg);
    expect(fs.existsSync(cfg)).toBe(true);
  });

  it("config get reads default_profile after auto-create", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-int-"));
    const cfg = path.join(dir, "c.toml");
    const out = run(["--no-json", "config", "get", "default_profile"], {
      OBJECTIFIED_CONFIG: cfg,
    }).trim();
    expect(out).toBe("default");
  });

  it("--profile staging uses [profile.staging] when present", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-prof-"));
    const cfg = path.join(dir, "config.toml");
    fs.writeFileSync(
      cfg,
      `
default_profile = "prod"

[profile.prod]
base_url = "https://api.prod.example"

[profile.staging]
base_url = "https://api.staging.example"
`,
      "utf8",
    );
    const out = run([
      "--json",
      "--profile",
      "staging",
      "--config",
      cfg,
      "config",
      "get",
      "profile.staging.base_url",
    ]).trim();
    expect(JSON.parse(out)).toEqual({
      key: "profile.staging.base_url",
      value: "https://api.staging.example",
    });
  });

  it("missing profile prints a friendly error", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-miss-"));
    const cfg = path.join(dir, "config.toml");
    fs.writeFileSync(
      cfg,
      `
[profile.prod]
base_url = "https://api.prod.example"
`,
      "utf8",
    );
    const err = runExpectFailure(["--profile", "staging", "--config", cfg, "projects", "list"]);
    expect(err).toMatch(/Profile 'staging' not found/);
    expect(err).toMatch(/Available:/);
  });

  it("suppresses hello stdout with --quiet", () => {
    expect(run(["hello", "--quiet", "--no-json"]).trim()).toBe("");
  });

  it("does not emit ANSI escapes when NO_COLOR is set", () => {
    const out = run(["hello"], { NO_COLOR: "1" });
    expect(out.includes("\u001B[")).toBe(false);
  });

  it("does not emit ANSI escapes for errors when --no-color is set", () => {
    const err = runExpectFailure(["--no-color", "helol"]);
    expect(err.includes("\u001B[")).toBe(false);
  });

  it("completion show bash prints bash complete function", () => {
    const out = run(["completion", "show", "bash", "--no-json"]);
    expect(out).toContain(">>> objectified completion >>>");
    expect(out).toMatch(/complete\s+-F/);
    expect(out).toContain("completion candidates");
  });

  it("completion candidates lists next static segment offline", () => {
    const stdin = ["objectified", "projects", ""].join("\n");
    const out = runStdin(
      ["--no-json", "completion", "candidates", "--shell", "bash", "--cword", "2"],
      `${stdin}\n`,
    );
    const lines = out
      .trim()
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    expect(lines).toContain("list");
    expect(lines).toContain("show");
  });

  it("cold-starts --version within 200 ms on developer machines", () => {
    const iterations = process.env.CI ? 2 : 5;
    let fastest = Number.POSITIVE_INFINITY;
    for (let i = 0; i < iterations; i++) {
      const start = performance.now();
      run(["--version"]);
      fastest = Math.min(fastest, performance.now() - start);
    }
    const budgetMs = process.env.CI ? 600 : 200;
    expect(fastest).toBeLessThan(budgetMs);
  });
});
