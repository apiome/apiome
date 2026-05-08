import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";
import { tmpdir } from "node:os";
import { readFile, unlink } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { parse as parseYaml } from "yaml";
import { describe, expect, it } from "vitest";

const pkgRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

async function runCliCaptureAsync(
  args: string[],
  extraEnv: Record<string, string> = {},
  timeoutMs = 25_000,
): Promise<{ code: number; stdout: string }> {
  const env = {
    ...process.env,
    FORCE_COLOR: "0",
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
    child.stdout?.on("data", (c: Buffer | string) => {
      outChunks.push(Buffer.isBuffer(c) ? c : Buffer.from(c));
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
      });
    });
  });
}

describe("schema fetch CLI (#3247)", () => {
  const publishedSpec = {
    openapi: "3.1.0",
    info: { title: "Payments", version: "2.1.0" },
    paths: {},
  };
  const publishedWire = JSON.stringify(publishedSpec);

  it("rejects refs that are not exactly tenant/project/version", async () => {
    const out = await runCliCaptureAsync(["schema", "fetch", "acme/payments-api/2.1.0/extra"]);
    expect(out.code).toBe(2);
  });

  it("downloads OpenAPI JSON for tenant/project/version", async () => {
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "GET" &&
          url.pathname === "/v1/schema/acme/payments-api/2.1.0"
        ) {
          res.setHeader("Content-Type", "application/json");
          res.end(publishedWire);
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
      const out = await runCliCaptureAsync([
        "--base-url",
        base,
        "schema",
        "fetch",
        "acme/payments-api/2.1.0",
      ]);
      expect(out.code).toBe(0);
      const body = JSON.parse(out.stdout) as { openapi?: string; info?: { title?: string } };
      expect(body.openapi).toBe("3.1.0");
      expect(body.info?.title).toBe("Payments");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("uses class path and YAML negotiation for --class --format yaml", async () => {
    let capturedAccept = "";
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "GET" &&
          url.pathname === "/v1/schema/acme/payments-api/2.1.0/Charge"
        ) {
          capturedAccept = req.headers.accept ?? "";
          res.setHeader("Content-Type", "application/x-yaml");
          res.end("openapi: 3.1.0\ninfo:\n  title: Charge\n  version: 1.0.0\npaths: {}\n");
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
      const out = await runCliCaptureAsync([
        "--base-url",
        base,
        "schema",
        "fetch",
        "acme/payments-api/2.1.0",
        "--class",
        "Charge",
        "--format",
        "yaml",
      ]);
      expect(out.code).toBe(0);
      expect(capturedAccept).toContain("application/yaml");
      const doc = parseYaml(out.stdout) as { openapi?: string; info?: { title?: string } };
      expect(doc.openapi).toBe("3.1.0");
      expect(doc.info?.title).toBe("Charge");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("converts full bundle to YAML with --format yaml", async () => {
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "GET" &&
          url.pathname === "/v1/schema/acme/payments-api/2.1.0"
        ) {
          res.setHeader("Content-Type", "application/json");
          res.end(publishedWire);
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
      const out = await runCliCaptureAsync([
        "--base-url",
        base,
        "schema",
        "fetch",
        "acme/payments-api/2.1.0",
        "--format",
        "yaml",
      ]);
      expect(out.code).toBe(0);
      const doc = parseYaml(out.stdout) as { openapi?: string };
      expect(doc.openapi).toBe("3.1.0");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("exits 7 when --expect-sha256 does not match emitted bytes", async () => {
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "GET" &&
          url.pathname === "/v1/schema/acme/payments-api/2.1.0"
        ) {
          res.setHeader("Content-Type", "application/json");
          res.end(publishedWire);
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
      const bad = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
      const out = await runCliCaptureAsync([
        "--base-url",
        base,
        "schema",
        "fetch",
        "acme/payments-api/2.1.0",
        "--expect-sha256",
        bad,
      ]);
      expect(out.code).toBe(7);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("passes when --expect-sha256 matches JSON bundle bytes", async () => {
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "GET" &&
          url.pathname === "/v1/schema/acme/payments-api/2.1.0"
        ) {
          res.setHeader("Content-Type", "application/json");
          res.end(publishedWire);
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
      const digest = createHash("sha256").update(Buffer.from(publishedWire, "utf8")).digest("hex");
      const out = await runCliCaptureAsync([
        "--base-url",
        base,
        "schema",
        "fetch",
        "acme/payments-api/2.1.0",
        "--expect-sha256",
        digest,
      ]);
      expect(out.code).toBe(0);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("sends /latest when --latest is set", async () => {
    let sawLatest = false;
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (req.method === "GET" && url.pathname === "/v1/schema/acme/payments-api/latest") {
          sawLatest = true;
          res.setHeader("Content-Type", "application/json");
          res.end(publishedWire);
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
      const out = await runCliCaptureAsync([
        "--base-url",
        base,
        "schema",
        "fetch",
        "acme/payments-api/2.1.0",
        "--latest",
      ]);
      expect(out.code).toBe(0);
      expect(sawLatest).toBe(true);
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("forwards --accept to the HTTP Accept header", async () => {
    let acceptHeader = "";
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "GET" &&
          url.pathname === "/v1/schema/acme/payments-api/2.1.0"
        ) {
          acceptHeader = req.headers.accept ?? "";
          res.setHeader("Content-Type", "application/json");
          res.end(publishedWire);
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
      const out = await runCliCaptureAsync([
        "--base-url",
        base,
        "schema",
        "fetch",
        "acme/payments-api/2.1.0",
        "--accept",
        "tag:stable",
      ]);
      expect(out.code).toBe(0);
      expect(acceptHeader).toContain("tag:stable");
    } finally {
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });

  it("writes --output and matches file bytes", async () => {
    const server = http.createServer((req, res) => {
      void (async () => {
        res.setHeader("Connection", "close");
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (
          req.method === "GET" &&
          url.pathname === "/v1/schema/acme/payments-api/2.1.0"
        ) {
          res.setHeader("Content-Type", "application/json");
          res.end(publishedWire);
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

    const tmp = path.join(
      tmpdir(),
      `objectified-schema-fetch-${String(process.pid)}-${String(Math.random()).slice(2)}.json`,
    );

    try {
      const base = `http://127.0.0.1:${String(addr.port)}`;
      const out = await runCliCaptureAsync([
        "--base-url",
        base,
        "schema",
        "fetch",
        "acme/payments-api/2.1.0",
        "--output",
        tmp,
      ]);
      expect(out.code).toBe(0);
      expect(out.stdout).toBe("");
      const disk = await readFile(tmp, "utf8");
      expect(disk).toBe(publishedWire);
    } finally {
      await unlink(tmp).catch(() => {});
      server.closeAllConnections?.();
      await new Promise<void>((resolve, reject) =>
        server.close((err) => (err !== undefined ? reject(err) : resolve())),
      );
    }
  });
});
