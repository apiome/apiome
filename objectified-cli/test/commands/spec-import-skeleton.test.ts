import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

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

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(Buffer.isBuffer(c) ? c : Buffer.from(c)));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

describe("spec import skeleton (#3308)", () => {
  it("new project: POST project + POST import + poll (snapshot stdout, #3309)", async () => {
    const projId = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee";
    const jobId = "55555555-5555-5555-5555-555555555555";
    const projectRouteMethods: string[] = [];

    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");

        if (
          req.method === "GET" &&
          (url.pathname === "/v1/projects/acme/domains" || url.pathname === "/v1/projects/domains")
        ) {
          res.statusCode = 404;
          res.end();
          return;
        }
        if (req.method === "POST" && url.pathname === "/v1/projects/acme") {
          projectRouteMethods.push(req.method);
          const raw = await readBody(req);
          const body = JSON.parse(raw) as {
            name?: string;
            slug?: string;
            metadata?: Record<string, unknown>;
          };
          expect(body.name).toBe("Swagger Petstore");
          expect(body.slug).toBe("swagger-petstore");
          expect(body.metadata?.visibility).toBe("private");

          res.statusCode = 201;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              id: projId,
              tenant_id: "t1",
              name: body.name,
              slug: body.slug,
              description: null,
              enabled: true,
              metadata: body.metadata ?? null,
            }),
          );
          return;
        }

        if (req.method === "POST" && url.pathname === "/v1/imports/acme") {
          projectRouteMethods.push(req.method);
          const raw = await readBody(req);
          const body = JSON.parse(raw) as {
            sourceKind?: string;
            existingProjectId?: string;
            document?: { openapi?: string };
          };
          expect(body.sourceKind).toBe("openapi");
          expect(body.existingProjectId).toBe(projId);
          expect(body.document?.openapi).toBe("3.0.3");

          res.statusCode = 201;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              jobId,
              tenantId: "t1",
              projectId: projId,
              state: "completed",
              percent: 100,
              progress: null,
              events: [],
              summary: {
                classesCreated: 14,
                warnings: 3,
                failed: 0,
              },
              result: { versionId: "1.0.0", projectId: projId },
              error: null,
              createdAt: "2026-05-09T12:00:00.000Z",
              updatedAt: "2026-05-09T12:00:02.000Z",
              finishedAt: "2026-05-09T12:00:02.000Z",
            }),
          );
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
      const fixture = path.join(pkgRoot, "fixtures", "petstore.yaml");
      const result = await runCliCapture([
        "--base-url",
        base,
        "--api-key",
        "k",
        "--tenant",
        "acme",
        "--no-json",
        "spec",
        "import",
        fixture,
        "--yes",
      ]);
      expect(result.code).toBe(0);
      expect(result.stderr.trim()).toBe("");
      expect(projectRouteMethods).toEqual(["POST", "POST"]);
      expect(result.stdout).toMatchSnapshot();
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("new project: exits 6 on create conflict and suggests --slug (#3309)", async () => {
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");

        if (
          req.method === "GET" &&
          (url.pathname === "/v1/projects/acme/domains" || url.pathname === "/v1/projects/domains")
        ) {
          res.statusCode = 404;
          res.end();
          return;
        }

        if (req.method === "POST" && url.pathname === "/v1/projects/acme") {
          res.statusCode = 409;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              detail: "A project with slug 'swagger-petstore' already exists in this tenant",
            }),
          );
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
      const fixture = path.join(pkgRoot, "fixtures", "petstore.yaml");
      const result = await runCliCapture([
        "--base-url",
        base,
        "--api-key",
        "k",
        "--tenant",
        "acme",
        "--quiet",
        "--no-json",
        "spec",
        "import",
        fixture,
        "--yes",
      ]);
      expect(result.code).toBe(6);
      expect(result.stdout.trim()).toBe("");
      expect(result.stderr).toContain("Project slug 'swagger-petstore' is already in use");
      expect(result.stderr).toContain("Pass a different --slug or delete the existing project first.");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("happy path: POST import + poll GET until completed (snapshot stdout)", async () => {
    const projId = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
    const jobId = "11111111-1111-1111-1111-111111111111";
    let getCalls = 0;

    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");

        if (
          req.method === "GET" &&
          (url.pathname === "/v1/projects/acme/domains" || url.pathname === "/v1/projects/domains")
        ) {
          res.statusCode = 404;
          res.end();
          return;
        }

        if (req.method === "GET" && url.pathname === "/v1/projects/acme/by-slug/petstore") {
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              id: projId,
              tenant_id: "t1",
              name: "Petstore",
              slug: "petstore",
              enabled: true,
            }),
          );
          return;
        }

        if (req.method === "POST" && url.pathname === "/v1/imports/acme") {
          const raw = await readBody(req);
          const body = JSON.parse(raw) as {
            sourceKind?: string;
            existingProjectId?: string;
            document?: { openapi?: string };
          };
          expect(body.sourceKind).toBe("openapi");
          expect(body.existingProjectId).toBe(projId);
          expect(body.document?.openapi).toBe("3.0.3");

          res.statusCode = 201;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              jobId,
              tenantId: "t1",
              projectId: projId,
              state: "queued",
              percent: 0,
              progress: null,
              events: [],
              summary: null,
              result: null,
              error: null,
              createdAt: "2026-05-09T12:00:00.000Z",
              updatedAt: "2026-05-09T12:00:00.000Z",
              finishedAt: null,
            }),
          );
          return;
        }

        if (req.method === "GET" && url.pathname === `/v1/imports/acme/${jobId}`) {
          getCalls++;
          const running = getCalls === 1;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify(
              running
                ? {
                    jobId,
                    tenantId: "t1",
                    projectId: projId,
                    state: "running",
                    percent: 40,
                    progress: {
                      phase: "creating-classes",
                      total: 14,
                      completed: 7,
                      currentItem: "Charge",
                    },
                    events: [],
                    summary: null,
                    result: null,
                    error: null,
                    createdAt: "2026-05-09T12:00:00.000Z",
                    updatedAt: "2026-05-09T12:00:01.000Z",
                    finishedAt: null,
                  }
                : {
                    jobId,
                    tenantId: "t1",
                    projectId: projId,
                    state: "completed",
                    percent: 100,
                    progress: {
                      phase: "done",
                      total: 14,
                      completed: 14,
                      currentItem: null,
                    },
                    events: [],
                    summary: {
                      classesCreated: 14,
                      warnings: 3,
                      failed: 0,
                    },
                    result: { versionId: "1.0.0", projectId: projId },
                    error: null,
                    createdAt: "2026-05-09T12:00:00.000Z",
                    updatedAt: "2026-05-09T12:00:02.000Z",
                    finishedAt: "2026-05-09T12:00:02.000Z",
                  },
            ),
          );
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
      const fixture = path.join(pkgRoot, "fixtures", "petstore.yaml");
      const result = await runCliCapture([
        "--base-url",
        base,
        "--api-key",
        "k",
        "--tenant",
        "acme",
        "--no-json",
        "spec",
        "import",
        fixture,
        "--project",
        "petstore",
        "--yes",
      ]);
      expect(result.code).toBe(0);
      expect(result.stderr.trim()).toBe("");
      expect(result.stdout).toMatchSnapshot();
      expect(getCalls).toBe(2);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("auto-detect uses openapi key for OpenAPI 3.1 YAML", async () => {
    const projId = "cccccccc-cccc-cccc-cccc-cccccccccccc";
    const jobId = "33333333-3333-3333-3333-333333333333";

    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");

        if (
          req.method === "GET" &&
          (url.pathname === "/v1/projects/acme/domains" || url.pathname === "/v1/projects/domains")
        ) {
          res.statusCode = 404;
          res.end();
          return;
        }

        if (req.method === "GET" && url.pathname === "/v1/projects/acme/by-slug/demo") {
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              id: projId,
              tenant_id: "t1",
              name: "Demo",
              slug: "demo",
              enabled: true,
            }),
          );
          return;
        }

        if (req.method === "POST" && url.pathname === "/v1/imports/acme") {
          const raw = await readBody(req);
          const body = JSON.parse(raw) as { sourceKind?: string; document?: { openapi?: string } };
          expect(body.sourceKind).toBe("openapi");
          expect(body.document?.openapi).toBe("3.1.0");

          res.statusCode = 201;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              jobId,
              tenantId: "t1",
              projectId: projId,
              state: "completed",
              percent: 100,
              progress: null,
              events: [],
              summary: null,
              result: { versionId: "0.0.1", projectId: projId },
              error: null,
              createdAt: "2026-05-09T12:00:00.000Z",
              updatedAt: "2026-05-09T12:00:00.000Z",
              finishedAt: "2026-05-09T12:00:00.000Z",
            }),
          );
          return;
        }

        res.statusCode = 500;
        res.end();
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end();
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const result = await runCliCapture([
        "--base-url",
        `http://127.0.0.1:${String(addr.port)}`,
        "--api-key",
        "k",
        "--tenant",
        "acme",
        "spec",
        "import",
        path.join(pkgRoot, "fixtures", "openapi31.yaml"),
        "--project",
        "demo",
      ]);
      expect(result.code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("auto-detect uses arazzo key for Arazzo JSON", async () => {
    const projId = "dddddddd-dddd-dddd-dddd-dddddddddddd";
    const jobId = "44444444-4444-4444-4444-444444444444";

    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");

        if (
          req.method === "GET" &&
          (url.pathname === "/v1/projects/acme/domains" || url.pathname === "/v1/projects/domains")
        ) {
          res.statusCode = 404;
          res.end();
          return;
        }

        if (req.method === "GET" && url.pathname === "/v1/projects/acme/by-slug/flows") {
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              id: projId,
              tenant_id: "t1",
              name: "Flows",
              slug: "flows",
              enabled: true,
            }),
          );
          return;
        }

        if (req.method === "POST" && url.pathname === "/v1/imports/acme") {
          const raw = await readBody(req);
          const body = JSON.parse(raw) as { sourceKind?: string; document?: { arazzo?: string } };
          expect(body.sourceKind).toBe("arazzo");
          expect(body.document?.arazzo).toBe("1.0.0");

          res.statusCode = 201;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              jobId,
              tenantId: "t1",
              projectId: projId,
              state: "completed",
              percent: 100,
              progress: null,
              events: [],
              summary: null,
              result: { versionId: "1.0.0", projectId: projId },
              error: null,
              createdAt: "2026-05-09T12:00:00.000Z",
              updatedAt: "2026-05-09T12:00:00.000Z",
              finishedAt: "2026-05-09T12:00:00.000Z",
            }),
          );
          return;
        }

        res.statusCode = 500;
        res.end();
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end();
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const result = await runCliCapture([
        "--base-url",
        `http://127.0.0.1:${String(addr.port)}`,
        "--api-key",
        "k",
        "--tenant",
        "acme",
        "spec",
        "import",
        path.join(pkgRoot, "fixtures", "arazzo100.json"),
        "--project",
        "flows",
      ]);
      expect(result.code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("auto-detect uses swagger key for Swagger 2.0 JSON", async () => {
    const projId = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const jobId = "22222222-2222-2222-2222-222222222222";

    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");

        if (
          req.method === "GET" &&
          (url.pathname === "/v1/projects/t/domains" || url.pathname === "/v1/projects/domains")
        ) {
          res.statusCode = 404;
          res.end();
          return;
        }

        if (req.method === "GET" && url.pathname === "/v1/projects/t/by-slug/api") {
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              id: projId,
              tenant_id: "t1",
              name: "Api",
              slug: "api",
              enabled: true,
            }),
          );
          return;
        }

        if (req.method === "POST" && url.pathname === "/v1/imports/t") {
          const raw = await readBody(req);
          const body = JSON.parse(raw) as { sourceKind?: string };
          expect(body.sourceKind).toBe("swagger");

          res.statusCode = 201;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              jobId,
              tenantId: "t1",
              projectId: projId,
              state: "completed",
              percent: 100,
              progress: null,
              events: [],
              summary: null,
              result: { versionId: "2.0", projectId: projId },
              error: null,
              createdAt: "2026-05-09T12:00:00.000Z",
              updatedAt: "2026-05-09T12:00:00.000Z",
              finishedAt: "2026-05-09T12:00:00.000Z",
            }),
          );
          return;
        }

        res.statusCode = 500;
        res.end();
      })().catch(() => {
        if (!res.headersSent) res.statusCode = 500;
        res.end();
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const addr = server.address();
    if (addr === null || typeof addr === "string") throw new Error("expected AddressInfo");

    try {
      const swaggerPath = path.join(pkgRoot, "fixtures", "swagger20.json");
      const result = await runCliCapture([
        "--base-url",
        `http://127.0.0.1:${String(addr.port)}`,
        "--api-key",
        "k",
        "--tenant",
        "t",
        "spec",
        "import",
        swaggerPath,
        "--project",
        "api",
      ]);
      expect(result.code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });
});
