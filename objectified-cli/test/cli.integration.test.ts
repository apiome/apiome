import { execFileSync, spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import { performance } from "node:perf_hooks";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const pkgRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

function run(args: string[], extraEnv: Record<string, string> = {}): string {
  const env = {
    ...process.env,
    FORCE_COLOR: "0",
    OBJECTIFIED_CLI_CREDENTIAL_BACKEND: "memory",
    ...extraEnv,
  };
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

function runExitAsync(
  args: string[],
  extraEnv: Record<string, string> = {},
  timeoutMs = 20_000,
): Promise<number> {
  const env = {
    ...process.env,
    FORCE_COLOR: "0",
    OBJECTIFIED_CLI_CREDENTIAL_BACKEND: "memory",
    ...extraEnv,
  };
  delete env.NODE_OPTIONS;

  return new Promise((resolve, reject) => {
    const child = spawn("node", [path.join(pkgRoot, "bin/run.js"), ...args], {
      cwd: pkgRoot,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    child.stdout?.on("data", () => {});
    child.stderr?.on("data", () => {});

    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      reject(new Error(`CLI subprocess timed out after ${String(timeoutMs)}ms: ${args.join(" ")}`));
    }, timeoutMs);

    child.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(err);
    });

    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(code ?? 1);
    });
  });
}

/** Same as {@link runExitAsync} but captures stdout (for JSON) without blocking the event loop. */
function spawnCliCaptureAsync(
  args: string[],
  extraEnv: Record<string, string> = {},
  timeoutMs = 20_000,
): Promise<{ code: number; stdout: string; stderr: string }> {
  const env = {
    ...process.env,
    FORCE_COLOR: "0",
    OBJECTIFIED_CLI_CREDENTIAL_BACKEND: "memory",
    ...extraEnv,
  };
  delete env.NODE_OPTIONS;

  return new Promise((resolve, reject) => {
    const child = spawn("node", [path.join(pkgRoot, "bin/run.js"), ...args], {
      cwd: pkgRoot,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const outChunks: Buffer[] = [];
    const errChunks: Buffer[] = [];
    child.stdout?.on("data", (c: Buffer | string) => {
      outChunks.push(Buffer.isBuffer(c) ? c : Buffer.from(c));
    });
    child.stderr?.on("data", (c: Buffer | string) => {
      errChunks.push(Buffer.isBuffer(c) ? c : Buffer.from(c));
    });

    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      reject(new Error(`CLI subprocess timed out after ${String(timeoutMs)}ms: ${args.join(" ")}`));
    }, timeoutMs);

    child.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(err);
    });

    child.on("exit", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        code: code ?? 1,
        stdout: Buffer.concat(outChunks).toString("utf8"),
        stderr: Buffer.concat(errChunks).toString("utf8"),
      });
    });
  });
}

function runExit(args: string[], extraEnv: Record<string, string> = {}): number {
  const env = {
    ...process.env,
    FORCE_COLOR: "0",
    OBJECTIFIED_CLI_CREDENTIAL_BACKEND: "memory",
    ...extraEnv,
  };
  delete env.NODE_OPTIONS;
  const r = spawnSync("node", [path.join(pkgRoot, "bin/run.js"), ...args], {
    cwd: pkgRoot,
    encoding: "utf8",
    env,
  });
  if (r.error) throw r.error;
  return r.status ?? 1;
}

function runStdin(args: string[], stdin: string, extraEnv: Record<string, string> = {}): string {
  const env = {
    ...process.env,
    FORCE_COLOR: "0",
    OBJECTIFIED_CLI_CREDENTIAL_BACKEND: "memory",
    ...extraEnv,
  };
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
    expect(err).toMatch(/tenants use/i);
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

  it("auth login help lists PKCE login and --no-browser", () => {
    const out = run(["auth", "login", "--help"]);
    expect(out).toMatch(/PKCE/i);
    expect(out).toMatch(/--no-browser/);
    expect(out).toMatch(/--api-key/);
  });

  it("auth status exits 3 without credentials", () => {
    expect(runExit(["--no-json", "auth", "status"])).toBe(3);
  });

  it("auth status calls GET /v1/auth/cli/whoami and exits 0 with OBJECTIFIED_API_KEY", async () => {
    const body = {
      tenant: { slug: "acme-corp", name: "Acme Corporation" },
      user: { id: "u_1", email: "kenji@example.com" },
      plan: "enterprise",
      auth: {
        type: "api_key",
        expires_at: null as string | null,
        refresh_valid: null as boolean | null,
      },
    };
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (!req.url?.startsWith("/v1/auth/cli/whoami")) {
        res.statusCode = 404;
        res.end();
        return;
      }
      if (req.method !== "GET") {
        res.statusCode = 405;
        res.end();
        return;
      }
      if (req.headers["x-api-key"] !== "sk_live_test") {
        res.statusCode = 401;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "Authentication required" }));
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(body));
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const code = await runExitAsync(
        ["--base-url", `http://127.0.0.1:${addr.port}`, "--no-json", "auth", "status"],
        { OBJECTIFIED_API_KEY: "sk_live_test" },
      );
      expect(code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("whoami alias hits whoami and prints JSON", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (!req.url?.startsWith("/v1/auth/cli/whoami")) {
        res.statusCode = 404;
        res.end();
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(
        JSON.stringify({
          tenant: { slug: "t1", name: null },
          user: { id: null, email: "e@e.com" },
          plan: "pro",
          auth: { type: "api_key" },
        }),
      );
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const { code, stdout } = await spawnCliCaptureAsync(
        ["--json", "--base-url", `http://127.0.0.1:${addr.port}`, "whoami"],
        { OBJECTIFIED_API_KEY: "k" },
      );
      expect(code).toBe(0);
      const j = JSON.parse(stdout.trim()) as Record<string, unknown>;
      expect(j.profile).toBe("default");
      expect(j.user).toEqual({ email: "e@e.com", id: null });
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("projects list exits 3 when tenant is set but credentials are missing", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-auth-"));
    const cfg = path.join(dir, "config.toml");
    fs.writeFileSync(
      cfg,
      `
[default]
tenant_slug = "acme"
`,
      "utf8",
    );
    expect(runExit(["--no-json", "--config", cfg, "projects", "list"])).toBe(3);
  });

  it("projects list sends X-API-Key to a mock API (#3195)", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (!req.url?.startsWith("/v1/projects/acme")) {
        res.statusCode = 404;
        res.end();
        return;
      }
      if (req.headers["x-api-key"] !== "good-key") {
        res.statusCode = 401;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "Authentication required" }));
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(
        JSON.stringify([
          { id: "p1", tenant_id: "t1", name: "Payments", slug: "payments", enabled: true },
        ]),
      );
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const code = await runExitAsync(
        [
          "--base-url",
          `http://127.0.0.1:${addr.port}`,
          "--api-key",
          "good-key",
          "--no-json",
          "projects",
          "list",
        ],
        { OBJECTIFIED_TENANT: "acme" },
      );
      expect(code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("projects list exits 4 when the API rejects the API key", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      res.statusCode = 401;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ detail: "Invalid API key" }));
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const code = await runExitAsync(
        [
          "--base-url",
          `http://127.0.0.1:${addr.port}`,
          "--api-key",
          "bad-key",
          "--no-json",
          "projects",
          "list",
        ],
        { OBJECTIFIED_TENANT: "acme" },
      );
      expect(code).toBe(4);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("tenants use validates HEAD then writes tenant_slug (#3199)", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-tuse-"));
    const cfg = path.join(dir, "config.toml");

    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (
        req.method === "HEAD" &&
        req.url?.startsWith("/v1/tenants/acme-staging") &&
        req.headers["x-api-key"] === "good-key"
      ) {
        res.statusCode = 200;
        res.end();
        return;
      }
      res.statusCode = 404;
      res.end();
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      fs.writeFileSync(
        cfg,
        `default_profile = "default"\n\n[profile.default]\nbase_url = "${base}"\n`,
        "utf8",
      );

      const code = await runExitAsync(
        ["--no-json", "--config", cfg, "--api-key", "good-key", "tenants", "use", "acme-staging"],
        {},
      );
      expect(code).toBe(0);
      expect(fs.readFileSync(cfg, "utf8")).toContain('tenant_slug = "acme-staging"');
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("tenants use --clear removes tenant_slug and is a no-op when repeated (#3199)", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-tuse-clear-"));
    const cfg = path.join(dir, "config.toml");
    fs.writeFileSync(
      cfg,
      `default_profile = "default"\n\n[profile.default]\nbase_url = "https://api.example.test"\ntenant_slug = "acme-staging"\n`,
      "utf8",
    );

    const firstCode = await runExitAsync(
      ["--no-json", "--config", cfg, "tenants", "use", "--clear"],
      {},
    );
    expect(firstCode).toBe(0);
    const afterFirstClear = fs.readFileSync(cfg, "utf8");
    expect(afterFirstClear).not.toContain("tenant_slug");

    const mtimeAfterFirst = fs.statSync(cfg).mtimeMs;
    await new Promise((resolve) => setTimeout(resolve, 25));

    const secondCode = await runExitAsync(
      ["--no-json", "--config", cfg, "tenants", "use", "--clear"],
      {},
    );
    expect(secondCode).toBe(0);
    expect(fs.readFileSync(cfg, "utf8")).toBe(afterFirstClear);
    expect(fs.statSync(cfg).mtimeMs).toBe(mtimeAfterFirst);
  });

  it("tenants use exit 5 suggests similar slug after HEAD 404 (#3199)", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-tuse404-"));
    const cfg = path.join(dir, "config.toml");

    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (
        req.method === "HEAD" &&
        req.url?.startsWith("/v1/tenants/acme-stagin") &&
        req.headers["x-api-key"] === "good-key"
      ) {
        res.statusCode = 404;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "Tenant not found: acme-stagin" }));
        return;
      }
      if (req.method === "GET" && req.url?.startsWith("/v1/tenants/me")) {
        res.setHeader("Content-Type", "application/json");
        res.end(
          JSON.stringify({
            items: [
              { slug: "acme-staging", name: "Staging", role: "admin" },
              { slug: "acme-prod", name: "Prod", role: "member" },
            ],
            total: 2,
            limit: 50,
            offset: 0,
          }),
        );
        return;
      }
      res.statusCode = 404;
      res.end();
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      fs.writeFileSync(
        cfg,
        `default_profile = "default"\n\n[profile.default]\nbase_url = "${base}"\n`,
        "utf8",
      );

      const { code, stderr } = await spawnCliCaptureAsync(
        ["--no-json", "--config", cfg, "--api-key", "good-key", "tenants", "use", "acme-stagin"],
        {},
      );
      expect(code).toBe(5);
      expect(stderr).toMatch(/Did you mean/i);
      expect(stderr).toMatch(/acme-staging/);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("tenants use exit 4 when HEAD returns 403 (#3199)", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-tuse403-"));
    const cfg = path.join(dir, "config.toml");

    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (
        req.method === "HEAD" &&
        req.url?.startsWith("/v1/tenants/other") &&
        req.headers["x-api-key"] === "good-key"
      ) {
        res.statusCode = 403;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "No access to tenant: other" }));
        return;
      }
      res.statusCode = 404;
      res.end();
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      fs.writeFileSync(
        cfg,
        `default_profile = "default"\n\n[profile.default]\nbase_url = "${base}"\n`,
        "utf8",
      );

      const code = await runExitAsync(
        ["--no-json", "--config", cfg, "--api-key", "good-key", "tenants", "use", "other"],
        {},
      );
      expect(code).toBe(4);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("projects list honors --tenant over OBJECTIFIED_TENANT (#3199)", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (!req.url?.startsWith("/v1/projects/from-flag")) {
        res.statusCode = 404;
        res.end();
        return;
      }
      if (req.headers["x-api-key"] !== "good-key") {
        res.statusCode = 401;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "Authentication required" }));
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify([]));
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const code = await runExitAsync(
        [
          "--base-url",
          `http://127.0.0.1:${String(addr.port)}`,
          "--api-key",
          "good-key",
          "--tenant",
          "from-flag",
          "--no-json",
          "projects",
          "list",
        ],
        { OBJECTIFIED_TENANT: "wrong-tenant" },
      );
      expect(code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("projects list reads API key from --api-key-file", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-keyfile-"));
    const keyPath = path.join(dir, "apikey.txt");
    fs.writeFileSync(keyPath, "good-key\n", "utf8");

    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (!req.url?.startsWith("/v1/projects/acme")) {
        res.statusCode = 404;
        res.end();
        return;
      }
      if (req.headers["x-api-key"] !== "good-key") {
        res.statusCode = 401;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "no" }));
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify([]));
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const code = await runExitAsync(
        [
          "--base-url",
          `http://127.0.0.1:${addr.port}`,
          "--api-key-file",
          keyPath,
          "--no-json",
          "projects",
          "list",
        ],
        { OBJECTIFIED_TENANT: "acme" },
      );
      expect(code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("projects list --json emits a top-level array (#3202)", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (!req.url?.startsWith("/v1/projects/acme")) {
        res.statusCode = 404;
        res.end();
        return;
      }
      if (req.headers["x-api-key"] !== "good-key") {
        res.statusCode = 401;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "Authentication required" }));
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(
        JSON.stringify([
          { id: "p1", tenant_id: "t1", name: "Payments", slug: "payments", enabled: true },
        ]),
      );
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const { code, stdout } = await spawnCliCaptureAsync(
        [
          "--base-url",
          `http://127.0.0.1:${String(addr.port)}`,
          "--api-key",
          "good-key",
          "--json",
          "projects",
          "list",
        ],
        { OBJECTIFIED_TENANT: "acme" },
      );
      expect(code).toBe(0);
      const parsed: unknown = JSON.parse(stdout.trim());
      expect(Array.isArray(parsed)).toBe(true);
      expect(parsed).toHaveLength(1);
      expect((parsed as { slug?: string }[])[0]?.slug).toBe("payments");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("projects list prints create hint when tenant has no projects (#3202)", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (!req.url?.startsWith("/v1/projects/acme")) {
        res.statusCode = 404;
        res.end();
        return;
      }
      if (req.headers["x-api-key"] !== "good-key") {
        res.statusCode = 401;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "Authentication required" }));
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify([]));
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const { code, stdout } = await spawnCliCaptureAsync(
        [
          "--base-url",
          `http://127.0.0.1:${String(addr.port)}`,
          "--api-key",
          "good-key",
          "--no-json",
          "projects",
          "list",
        ],
        { OBJECTIFIED_TENANT: "acme" },
      );
      expect(code).toBe(0);
      expect(stdout).toMatch(/projects create/);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("projects show resolves by slug and returns composite json (#3203)", async () => {
    const PROJ = "33333333-4444-5555-6666-777777777777";
    const projectBody = {
      id: PROJ,
      tenant_id: "t1",
      name: "Showcase",
      slug: "showcase",
      enabled: true,
      description: "Demo",
      creator_email: "u@example.com",
      created_at: "2024-08-19T10:00:00Z",
      updated_at: "2026-04-02T15:00:00Z",
      metadata: { domain: "finance" },
    };

    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (req.headers["x-api-key"] !== "good-key") {
        res.statusCode = 401;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "Authentication required" }));
        return;
      }

      const urlRaw = req.url ?? "";
      const url = new URL(urlRaw, "http://127.0.0.1");

      if (req.method === "GET" && url.pathname === "/v1/projects/acme/by-slug/showcase") {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(projectBody));
        return;
      }

      if (req.method === "GET" && url.pathname === `/v1/versions/acme/${PROJ}`) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify([]));
        return;
      }

      if (req.method === "GET" && url.pathname === `/v1/version-tags/acme/${PROJ}`) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify([]));
        return;
      }

      if (req.method === "GET" && url.pathname === "/v1/versions/acme/workflow-audit") {
        if (url.searchParams.get("projectId") !== PROJ || url.searchParams.get("limit") !== "10") {
          res.statusCode = 400;
          res.end();
          return;
        }
        res.setHeader("Content-Type", "application/json");
        res.end(
          JSON.stringify({
            schemaVersion: 1,
            items: [],
            pagination: { limit: 10, total: 0, hasMore: false, offset: 0 },
          }),
        );
        return;
      }

      res.statusCode = 404;
      res.end();
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const { code, stdout } = await spawnCliCaptureAsync(
        [
          "--base-url",
          `http://127.0.0.1:${String(addr.port)}`,
          "--api-key",
          "good-key",
          "--json",
          "projects",
          "show",
          "showcase",
        ],
        { OBJECTIFIED_TENANT: "acme" },
      );
      expect(code).toBe(0);
      const parsed = JSON.parse(stdout.trim()) as { slug?: string; activity?: unknown[] };
      expect(parsed.slug).toBe("showcase");
      expect(Array.isArray(parsed.activity)).toBe(true);
      expect(parsed.activity).toHaveLength(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("projects list rejects --all with --limit before calling the API (#3202)", async () => {
    const { code, stderr } = await spawnCliCaptureAsync(
      [
        "--no-json",
        "--base-url",
        "http://127.0.0.1:9",
        "projects",
        "list",
        "--all",
        "--limit",
        "10",
      ],
      { OBJECTIFIED_TENANT: "acme" },
    );
    expect(code).toBe(2);
    expect(stderr).toMatch(/Cannot use --all/);
  });

  it("projects list passes include_deleted to the API (#3202)", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (!req.url?.startsWith("/v1/projects/acme")) {
        res.statusCode = 404;
        res.end();
        return;
      }
      const u = new URL(req.url ?? "/", "http://127.0.0.1");
      if (u.searchParams.get("include_deleted") !== "true") {
        res.statusCode = 400;
        res.end();
        return;
      }
      if (req.headers["x-api-key"] !== "good-key") {
        res.statusCode = 401;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "no" }));
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify([]));
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const code = await runExitAsync(
        [
          "--base-url",
          `http://127.0.0.1:${String(addr.port)}`,
          "--api-key",
          "good-key",
          "--no-json",
          "projects",
          "list",
          "--include-deleted",
        ],
        { OBJECTIFIED_TENANT: "acme" },
      );
      expect(code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
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

  it("completion show zsh passes zero-based cword", () => {
    const out = run(["completion", "show", "zsh", "--no-json"]);
    expect(out).toContain('--cword "$((CURRENT-1))"');
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

  it("tenants list calls GET /v1/tenants/me with --json", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      if (req.url?.startsWith("/v1/tenants/me")) {
        res.statusCode = 200;
        res.setHeader("Content-Type", "application/json");
        res.end(
          JSON.stringify({
            items: [{ slug: "acme", name: "Acme", role: "member" }],
            total: 1,
            limit: 100,
            offset: 0,
          }),
        );
        return;
      }
      res.statusCode = 404;
      res.end();
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");
    try {
      const { code, stdout } = await spawnCliCaptureAsync(
        [
          "--json",
          "--base-url",
          `http://127.0.0.1:${addr.port}`,
          "--api-key",
          "k",
          "tenants",
          "list",
        ],
        {},
      );
      expect(code).toBe(0);
      const j = JSON.parse(stdout.trim()) as { tenants: Array<{ slug: string }> };
      expect(j.tenants).toHaveLength(1);
      expect(j.tenants[0]?.slug).toBe("acme");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("tenants info exits 4 when API returns 403", async () => {
    const server = http.createServer((req, res) => {
      res.setHeader("Connection", "close");
      res.statusCode = 403;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ detail: "No access to tenant: other" }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");
    try {
      const code = await runExitAsync(
        [
          "--base-url",
          `http://127.0.0.1:${addr.port}`,
          "--api-key",
          "k",
          "--no-json",
          "tenants",
          "info",
          "other",
        ],
        {},
      );
      expect(code).toBe(4);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
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
