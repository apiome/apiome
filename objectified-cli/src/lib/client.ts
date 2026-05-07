import { createClient, type Client } from "../generated/client.js";
import type {
  ClassSchema,
  PrimitiveSchema,
  ProjectSchema,
  VersionSchema,
} from "../generated/models.js";
import {
  listClassesV1ClassesTenantSlugGet,
  listPrimitivesV1PrimitivesTenantSlugGet,
  listProjectsV1ProjectsTenantSlugGet,
  listVersionsV1VersionsTenantSlugProjectIdGet,
} from "../generated/operations.js";

import { EXIT_CODES } from "./exit-codes.js";
import {
  httpStatusToCliError,
  networkErrnoToCliError,
  ObjectifiedCliError,
} from "./errors.js";

/** Mutable auth fields read on every request (supports 401 refresh hook). */
export type ApiAuthSnapshot = {
  apiKey?: string;
  bearer?: string;
};

export type CreateApiClientOptions = {
  baseUrl: string;
  auth: ApiAuthSnapshot;
  /** Log `x-request-id` from responses when true. */
  verbose?: boolean;
  stderrWrite?: (line: string) => void;
  /** Invoked once after a 401 before retrying the same request. */
  onUnauthorized?: () => Promise<void>;
};

export type ObjectifiedApi = {
  readonly lastRequestId: string | undefined;
  /** Transient HTTP retries consumed on the last instrumented request (429 / 5xx policy). */
  readonly lastRetriesAttempted: number;
  listProjects(tenantSlug: string): Promise<ProjectSchema[]>;
  listVersions(tenantSlug: string, projectId: string): Promise<VersionSchema[]>;
  listClasses(tenantSlug: string, versionId?: string): Promise<ClassSchema[]>;
  listPrimitives(tenantSlug: string): Promise<PrimitiveSchema[]>;
};

const MAX_RETRY_AFTER_MS = 120_000;
export const MAX_TRANSIENT_ATTEMPTS = 4;

const IDEMPOTENT_METHODS = new Set(["GET", "HEAD", "PUT", "DELETE"]);
const BACKOFF_MS = [250, 500, 1000, 2000];

function trimTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

function mergeAuthHeaders(request: Request, auth: ApiAuthSnapshot): Request {
  const headers = new Headers(request.headers);
  if (auth.apiKey) headers.set("X-API-Key", auth.apiKey);
  else headers.delete("X-API-Key");
  if (auth.bearer) headers.set("Authorization", `Bearer ${auth.bearer}`);
  else headers.delete("Authorization");
  return new Request(request, { headers });
}

/** Parse `Retry-After` as delta-seconds or HTTP-date. */
export function parseRetryAfterMs(headerValue: string | null): number | undefined {
  if (headerValue === null || headerValue === "") return undefined;
  const trimmed = headerValue.trim();
  const asSeconds = Number(trimmed);
  if (!Number.isNaN(asSeconds) && asSeconds >= 0) {
    return Math.min(asSeconds * 1000, MAX_RETRY_AFTER_MS);
  }
  const when = Date.parse(trimmed);
  if (!Number.isNaN(when)) {
    const delta = when - Date.now();
    if (delta <= 0) return 0;
    return Math.min(delta, MAX_RETRY_AFTER_MS);
  }
  return undefined;
}

/** Delay before retry `attemptIndex` (0-based), capped at 2s (#3191). */
export function exponentialBackoffMs(attemptIndex: number): number {
  const idx = Math.min(Math.max(attemptIndex, 0), BACKOFF_MS.length - 1);
  return BACKOFF_MS[idx] ?? 2000;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatApiError(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const o = error as Record<string, unknown>;
    if (typeof o.message === "string") return o.message;
    if (Array.isArray(o.detail)) {
      const parts = o.detail.map((d) =>
        typeof d === "object" && d && "msg" in d
          ? String((d as { msg: unknown }).msg)
          : JSON.stringify(d),
      );
      return parts.join("; ");
    }
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function methodIsIdempotent(method: string): boolean {
  return IDEMPOTENT_METHODS.has(method.toUpperCase());
}

function shouldRetryStatus(status: number, idempotent: boolean): boolean {
  if (status === 429) return true;
  if (idempotent && status >= 500 && status <= 599) return true;
  return false;
}

/** Validates the list endpoint payload enough for CLI rendering (required OpenAPI fields). */
function parseProjectsPayload(data: unknown): ProjectSchema[] {
  if (!Array.isArray(data)) {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for projects list.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const projects: ProjectSchema[] = [];
  for (const raw of data) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid project entry in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "The API returned invalid project rows; include request-id when reporting.",
      });
    }
    const p = raw as Record<string, unknown>;
    if (
      typeof p.id !== "string" ||
      typeof p.tenant_id !== "string" ||
      typeof p.name !== "string" ||
      typeof p.slug !== "string"
    ) {
      throw new ObjectifiedCliError({
        message: "Invalid project fields in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Required project fields were missing or mistyped.",
      });
    }
    if (
      p.enabled !== undefined &&
      p.enabled !== null &&
      typeof p.enabled !== "boolean"
    ) {
      throw new ObjectifiedCliError({
        message: "Invalid project fields in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "`enabled` must be boolean when present.",
      });
    }
    projects.push({
      ...(raw as ProjectSchema),
      enabled: typeof p.enabled === "boolean" ? p.enabled : true,
    });
  }
  return projects;
}

function unwrapSdkGet(
  rawUnknown: unknown,
  lastRequestId: string | undefined,
  lastRetriesAttempted: number,
): unknown {
  const rawBundle =
    rawUnknown && typeof rawUnknown === "object"
      ? (rawUnknown as {
          data?: unknown;
          error?: unknown;
          response?: Response;
        })
      : undefined;

  if (rawBundle === undefined) {
    throw new ObjectifiedCliError({
      message: "Empty SDK response from the API client.",
      exitCode: EXIT_CODES.GENERIC,
      title: "API error",
      hint: "Retry the command; set OBJECTIFIED_DEBUG=1 if you need a stack trace.",
    });
  }

  if (rawBundle.error !== undefined && rawBundle.error !== null && rawBundle.error !== "") {
    const status = rawBundle.response?.status ?? 0;
    const hdrId =
      rawBundle.response?.headers.get("x-request-id") ??
      rawBundle.response?.headers.get("X-Request-Id") ??
      undefined;
    throw httpStatusToCliError(status, formatApiError(rawBundle.error), {
      requestId: hdrId ?? lastRequestId,
      retriesAttempted: lastRetriesAttempted,
    });
  }

  return rawBundle.data;
}

function parseVersionsPayload(data: unknown): VersionSchema[] {
  if (!Array.isArray(data)) {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for versions list.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const versions: VersionSchema[] = [];
  for (const raw of data) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid version entry in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "The API returned invalid version rows.",
      });
    }
    const v = raw as Record<string, unknown>;
    if (typeof v.version_id !== "string" || typeof v.id !== "string") {
      throw new ObjectifiedCliError({
        message: "Invalid version fields in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Required version fields were missing or mistyped.",
      });
    }
    versions.push(raw as VersionSchema);
  }
  return versions;
}

function parseClassesPayload(data: unknown): ClassSchema[] {
  if (!Array.isArray(data)) {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for classes list.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const classes: ClassSchema[] = [];
  for (const raw of data) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid class entry in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "The API returned invalid class rows.",
      });
    }
    const c = raw as Record<string, unknown>;
    if (typeof c.name !== "string") {
      throw new ObjectifiedCliError({
        message: "Invalid class fields in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Required class fields were missing or mistyped.",
      });
    }
    classes.push(raw as ClassSchema);
  }
  return classes;
}

function parsePrimitivesPayload(data: unknown): PrimitiveSchema[] {
  if (!Array.isArray(data)) {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for primitives list.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const primitives: PrimitiveSchema[] = [];
  for (const raw of data) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid primitive entry in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "The API returned invalid primitive rows.",
      });
    }
    const p = raw as Record<string, unknown>;
    if (typeof p.name !== "string") {
      throw new ObjectifiedCliError({
        message: "Invalid primitive fields in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Required primitive fields were missing or mistyped.",
      });
    }
    primitives.push(raw as PrimitiveSchema);
  }
  return primitives;
}

function createInstrumentedFetch(opts: {
  inner: typeof fetch;
  auth: ApiAuthSnapshot;
  verbose?: boolean;
  stderrWrite?: (line: string) => void;
  onUnauthorized?: () => Promise<void>;
  onRetryStats?: (count: number) => void;
}): typeof fetch {
  const log = opts.stderrWrite ?? ((line: string) => process.stderr.write(`${line}\n`));

  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const baseReq = input instanceof Request ? input : new Request(input, init);
    let req = mergeAuthHeaders(baseReq, opts.auth);
    let transientRetries = 0;
    let didReauth = false;

    opts.onRetryStats?.(0);

    const bumpRetry = (): void => {
      transientRetries++;
      opts.onRetryStats?.(transientRetries);
    };

    for (;;) {
      const response = await opts.inner(req);
      const rid = response.headers.get("x-request-id") ?? response.headers.get("X-Request-Id");
      if (opts.verbose && rid !== null && rid !== "") log(`objectified: request-id=${rid}`);

      if (response.status === 401 && opts.onUnauthorized !== undefined && !didReauth) {
        didReauth = true;
        await opts.onUnauthorized();
        req = mergeAuthHeaders(baseReq, opts.auth);
        continue;
      }

      const idem = methodIsIdempotent(req.method);
      const attemptNumber = transientRetries + 1;

      if (
        attemptNumber < MAX_TRANSIENT_ATTEMPTS &&
        shouldRetryStatus(response.status, idem)
      ) {
        if (!idem && response.status !== 429) {
          return response;
        }

        let waitMs: number;
        if (response.status === 429) {
          const ra = parseRetryAfterMs(response.headers.get("retry-after"));
          waitMs = ra ?? exponentialBackoffMs(transientRetries);
        } else {
          waitMs = exponentialBackoffMs(transientRetries);
        }

        bumpRetry();
        await sleep(waitMs);
        req = mergeAuthHeaders(baseReq, opts.auth);
        continue;
      }

      return response;
    }
  };
}

export function createApiClient(options: CreateApiClientOptions): ObjectifiedApi {
  const innerFetch = globalThis.fetch.bind(globalThis);
  let lastRequestId: string | undefined;
  let lastRetriesAttempted = 0;

  const instrumented = createInstrumentedFetch({
    inner: async (input, init) => {
      try {
        const res = await innerFetch(input, init);
        const rid = res.headers.get("x-request-id") ?? res.headers.get("X-Request-Id") ?? undefined;
        if (rid !== undefined) lastRequestId = rid;
        return res;
      } catch (e) {
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
    },
    auth: options.auth,
    verbose: options.verbose,
    stderrWrite: options.stderrWrite,
    onUnauthorized: options.onUnauthorized,
    onRetryStats: (n) => {
      lastRetriesAttempted = n;
    },
  });

  const hey: Client = createClient({
    baseUrl: trimTrailingSlash(options.baseUrl),
    fetch: instrumented,
  });

  return {
    get lastRequestId() {
      return lastRequestId;
    },
    get lastRetriesAttempted() {
      return lastRetriesAttempted;
    },

    async listProjects(tenantSlug: string): Promise<ProjectSchema[]> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listProjectsV1ProjectsTenantSlugGet({
          client: hey,
          path: { tenant_slug: tenantSlug },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }

      return parseProjectsPayload(unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted));
    },

    async listVersions(tenantSlug: string, projectId: string): Promise<VersionSchema[]> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listVersionsV1VersionsTenantSlugProjectIdGet({
          client: hey,
          path: { tenant_slug: tenantSlug, project_id: projectId },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseVersionsPayload(unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted));
    },

    async listClasses(tenantSlug: string, versionId?: string): Promise<ClassSchema[]> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listClassesV1ClassesTenantSlugGet({
          client: hey,
          path: { tenant_slug: tenantSlug },
          query: versionId !== undefined ? { version_id: versionId } : {},
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseClassesPayload(unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted));
    },

    async listPrimitives(tenantSlug: string): Promise<PrimitiveSchema[]> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listPrimitivesV1PrimitivesTenantSlugGet({
          client: hey,
          path: { tenant_slug: tenantSlug },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parsePrimitivesPayload(unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted));
    },
  };
}
