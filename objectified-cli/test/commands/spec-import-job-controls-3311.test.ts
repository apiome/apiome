import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

const pkgRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

async function runCliCapture(
  args: string[],
  extraEnv: Record<string, string> = {},
  timeoutMs = 25_000,
): Promise<{ code: number; stdout: string; stderr: string }> {
  const env = {
    ...process.env,
    FORCE_COLOR: "0",
    LANG: "C",
    OBJECTIFIED_CLI_CREDENTIAL_BACKEND: "memory",
    ...extraEnv,
  };
  delete env.NODE_OPTIONS;

  return await new Promise((resolve, reject) => {
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
      reject(new Error(`CLI timed out after ${String(timeoutMs)}ms: ${args.join(" ")}`));
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
      resolve({
        code: code ?? 1,
        stdout: Buffer.concat(outChunks).toString("utf8"),
        stderr: Buffer.concat(errChunks).toString("utf8"),
      });
    });
  });
}

function samplePendingJob(jobId: string): Record<string, unknown> {
  const projId = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
  return {
    jobId,
    tenantId: "t1",
    projectId: projId,
    state: "pending-approval",
    percent: 90,
    progress: {
      phase: "verifying",
      total: 12,
      completed: 12,
      currentItem: null,
    },
    events: Array.from({ length: 38 }, (_, i) => ({
      code: "STEP",
      level: "info",
      message: `event-${String(i)}`,
    })),
    summary: { projectSlug: "payments-api" },
    result: null,
    error: null,
    createdAt: "2026-05-09T12:00:00.000Z",
    updatedAt: "2026-05-09T12:00:04.000Z",
    finishedAt: null,
  };
}

describe("spec import status / commit / cancel (#3311)", () => {
  let testHome: string;

  beforeEach(() => {
    testHome = fs.mkdtempSync(path.join(os.tmpdir(), "obj-cli-home-"));
  });

  afterEach(() => {
    fs.rmSync(testHome, { recursive: true, force: true });
  });

  it("status: human view", async () => {
    const jobId = "7c3d2a1b-1111-2222-3333-e22aaaaaaaaaa";
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (req.method === "GET" && url.pathname === `/v1/imports/acme/${jobId}`) {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(samplePendingJob(jobId)));
          return;
        }
        res.statusCode = 500;
        res.end(`unexpected ${req.method ?? "?"} ${url.pathname}`);
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end("handler error");
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      const result = await runCliCapture(
        [
          "--base-url",
          base,
          "--api-key",
          "k",
          "--tenant",
          "acme",
          "--no-json",
          "spec",
          "import",
          "status",
          jobId,
        ],
        { HOME: testHome },
      );
      expect(result.code).toBe(0);
      expect(result.stderr).toBe("");
      expect(result.stdout).toContain("Job 7c3d…aaaa (tenant=acme, project=payments-api)");
      expect(result.stdout).toContain("State: pending-approval");
      expect(result.stdout).toContain("Phase: verifying  (12/12)");
      expect(result.stdout).toContain("Events: 38");
      expect(result.stdout).toMatch(/^Started .+\.$/m);
      expect(result.stdout).toContain("objectified spec import commit");
      expect(result.stdout).toContain("objectified spec import cancel");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("status: --json full job (snapshot)", async () => {
    const jobId = "7c3d2a1b-1111-2222-3333-e22aaaaaaaaaa";
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (req.method === "GET" && url.pathname === `/v1/imports/acme/${jobId}`) {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(samplePendingJob(jobId)));
          return;
        }
        res.statusCode = 500;
        res.end(`unexpected ${req.method ?? "?"} ${url.pathname}`);
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end("handler error");
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      const result = await runCliCapture(
        [
          "--base-url",
          base,
          "--api-key",
          "k",
          "--tenant",
          "acme",
          "--json",
          "spec",
          "import",
          "status",
          jobId,
        ],
        { HOME: testHome },
      );
      expect(result.code).toBe(0);
      expect(result.stderr).toBe("");
      expect(JSON.parse(result.stdout)).toMatchSnapshot();
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("status: --last reads cache file", async () => {
    const jobId = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const cacheDir = path.join(testHome, ".cache", "objectified");
    fs.mkdirSync(cacheDir, { recursive: true });
    fs.writeFileSync(path.join(cacheDir, "last-import-job-acme.txt"), `${jobId}\n`, "utf8");

    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (req.method === "GET" && url.pathname === `/v1/imports/acme/${jobId}`) {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(samplePendingJob(jobId)));
          return;
        }
        res.statusCode = 500;
        res.end(`unexpected ${req.method ?? "?"} ${url.pathname}`);
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end("handler error");
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      const result = await runCliCapture(
        [
          "--base-url",
          base,
          "--api-key",
          "k",
          "--tenant",
          "acme",
          "--no-json",
          "spec",
          "import",
          "status",
          "--last",
        ],
        { HOME: testHome },
      );
      expect(result.code).toBe(0);
      expect(result.stdout).toContain("pending-approval");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("status: misuse when job id combined with --last", async () => {
    const result = await runCliCapture(
      [
        "--base-url",
        "http://127.0.0.1:9",
        "--api-key",
        "k",
        "--tenant",
        "acme",
        "spec",
        "import",
        "status",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "--last",
      ],
      { HOME: testHome },
    );
    expect(result.code).toBe(2);
    expect(result.stderr).toMatch(/not both|either/i);
  });

  it("commit: happy path (snapshot)", async () => {
    const jobId = "7c3d2a1b-1111-2222-3333-e22aaaaaaaaaa";
    const committed = {
      ...samplePendingJob(jobId),
      state: "completed",
      percent: 100,
      result: { versionId: "v2.4.0", projectId: samplePendingJob(jobId).projectId },
    };

    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "POST" &&
          url.pathname === `/v1/imports/acme/${jobId}/commit`
        ) {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(committed));
          return;
        }
        res.statusCode = 500;
        res.end(`unexpected ${req.method ?? "?"} ${url.pathname}`);
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end("handler error");
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      const result = await runCliCapture(
        [
          "--base-url",
          base,
          "--api-key",
          "k",
          "--tenant",
          "acme",
          "--no-json",
          "spec",
          "import",
          "commit",
          jobId,
          "--yes",
        ],
        { HOME: testHome },
      );
      expect(result.code).toBe(0);
      expect(result.stderr).toBe("");
      expect(result.stdout).toMatchSnapshot();
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("commit: refuses non-TTY without --yes (exit 6)", async () => {
    const jobId = "7c3d2a1b-1111-2222-3333-e22aaaaaaaaaa";
    const result = await runCliCapture(
      [
        "--base-url",
        "http://127.0.0.1:9",
        "--api-key",
        "k",
        "--tenant",
        "acme",
        "spec",
        "import",
        "commit",
        jobId,
      ],
      { HOME: testHome },
    );
    expect(result.code).toBe(6);
    expect(result.stderr).toMatch(/--yes/i);
  });

  it("commit: 409 surfaces REST detail and import hint (snapshot stderr)", async () => {
    const jobId = "7c3d2a1b-1111-2222-3333-e22aaaaaaaaaa";
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "POST" &&
          url.pathname === `/v1/imports/acme/${jobId}/commit`
        ) {
          res.statusCode = 409;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ detail: "Import job is not pending approval (state=failed)." }));
          return;
        }
        res.statusCode = 500;
        res.end(`unexpected ${req.method ?? "?"} ${url.pathname}`);
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end("handler error");
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      const result = await runCliCapture(
        [
          "--base-url",
          base,
          "--api-key",
          "k",
          "--tenant",
          "acme",
          "spec",
          "import",
          "commit",
          jobId,
          "--yes",
        ],
        { HOME: testHome },
      );
      expect(result.code).toBe(6);
      expect(result.stderr).toMatch(/pending approval|pending-approval/i);
      expect(result.stderr).toMatchSnapshot();
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("cancel: happy path (snapshot)", async () => {
    const jobId = "7c3d2a1b-1111-2222-3333-e22aaaaaaaaaa";
    const canceled = {
      ...samplePendingJob(jobId),
      state: "canceled",
      percent: 0,
      finishedAt: "2026-05-09T12:05:00.000Z",
    };

    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "POST" &&
          url.pathname === `/v1/imports/acme/${jobId}/cancel`
        ) {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(canceled));
          return;
        }
        res.statusCode = 500;
        res.end(`unexpected ${req.method ?? "?"} ${url.pathname}`);
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end("handler error");
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      const result = await runCliCapture(
        [
          "--base-url",
          base,
          "--api-key",
          "k",
          "--tenant",
          "acme",
          "--no-json",
          "spec",
          "import",
          "cancel",
          jobId,
          "--yes",
        ],
        { HOME: testHome },
      );
      expect(result.code).toBe(0);
      expect(result.stderr).toBe("");
      expect(result.stdout).toMatchSnapshot();
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("cancel: refuses non-TTY without --yes (exit 6)", async () => {
    const jobId = "7c3d2a1b-1111-2222-3333-e22aaaaaaaaaa";
    const result = await runCliCapture(
      [
        "--base-url",
        "http://127.0.0.1:9",
        "--api-key",
        "k",
        "--tenant",
        "acme",
        "spec",
        "import",
        "cancel",
        jobId,
      ],
      { HOME: testHome },
    );
    expect(result.code).toBe(6);
    expect(result.stderr).toMatch(/--yes/i);
  });

  it("status: GET 404 error path (snapshot stderr)", async () => {
    const jobId = "00000000-0000-0000-0000-000000000000";
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (req.method === "GET" && url.pathname === `/v1/imports/acme/${jobId}`) {
          res.statusCode = 404;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ detail: "Import job not found." }));
          return;
        }
        res.statusCode = 500;
        res.end(`unexpected ${req.method ?? "?"} ${url.pathname}`);
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end("handler error");
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      const result = await runCliCapture(
        [
          "--base-url",
          base,
          "--api-key",
          "k",
          "--tenant",
          "acme",
          "spec",
          "import",
          "status",
          jobId,
        ],
        { HOME: testHome },
      );
      expect(result.code).toBe(5);
      expect(result.stderr).toMatchSnapshot();
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });
});
