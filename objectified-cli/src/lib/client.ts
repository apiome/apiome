import { createClient, type Client } from "../generated/client.js";
import type {
  ClassSchema,
  PrimitiveSchema,
  ProjectSchema,
  TenantInfoResponse,
  TenantsMeResponse,
  VersionSchema,
  VersionTagSchema,
  WorkflowAuditPageResponse,
} from "../generated/models.js";
import {
  getProjectBySlugV1ProjectsTenantSlugBySlugProjectSlugGet,
  getProjectV1ProjectsTenantSlugProjectIdGet,
  getTenantInfoV1TenantsTenantSlugGet,
  listClassesV1ClassesTenantSlugGet,
  listMyTenantsV1TenantsMeGet,
  listPrimitivesV1PrimitivesTenantSlugGet,
  listProjectsV1ProjectsTenantSlugGet,
  listVersionTagsV1VersionTagsTenantSlugProjectIdGet,
  listVersionsV1VersionsTenantSlugProjectIdGet,
  listWorkflowAuditV1VersionsTenantSlugWorkflowAuditGet,
  verifyTenantAccessV1TenantsTenantSlugHead,
} from "../generated/operations.js";

import { EXIT_CODES } from "./exit-codes.js";
import { httpStatusToCliError, networkErrnoToCliError, ObjectifiedCliError } from "./errors.js";
import { redactApiKeyForLogs } from "./redact-api-key.js";

export type {
  ProjectSchema,
  VersionSchema,
  VersionTagSchema,
  WorkflowAuditEntryOut,
  WorkflowAuditPageResponse,
} from "../generated/models.js";

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

type RequestAuthMeta = { hadCredentials: boolean };

export type ListProjectsOptions = {
  /** When true, request soft-deleted projects from the API (listed after active rows). */
  include_deleted?: boolean;
};

export type ObjectifiedApi = {
  readonly lastRequestId: string | undefined;
  /** Transient HTTP retries consumed on the last instrumented request (429 / 5xx policy). */
  readonly lastRetriesAttempted: number;
  listProjects(tenantSlug: string, options?: ListProjectsOptions): Promise<ProjectSchema[]>;
  getProject(tenantSlug: string, projectId: string): Promise<ProjectSchema>;
  getProjectBySlug(tenantSlug: string, projectSlug: string): Promise<ProjectSchema>;
  listVersions(tenantSlug: string, projectId: string): Promise<VersionSchema[]>;
  listVersionTags(tenantSlug: string, projectId: string): Promise<VersionTagSchema[]>;
  listWorkflowAudit(opts: {
    tenantSlug: string;
    projectId?: string;
    limit?: number;
    offset?: number;
  }): Promise<WorkflowAuditPageResponse>;
  listClasses(tenantSlug: string, versionId?: string): Promise<ClassSchema[]>;
  listPrimitives(tenantSlug: string): Promise<PrimitiveSchema[]>;
  listMyTenantsPage(limit: number, offset: number): Promise<TenantsMeResponse>;
  getTenantInfo(tenantSlug: string): Promise<TenantInfoResponse>;
  verifyTenantAccess(tenantSlug: string): Promise<void>;
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
  if (auth.apiKey) {
    headers.set("X-API-Key", auth.apiKey);
    headers.delete("Authorization");
  } else {
    headers.delete("X-API-Key");
    if (auth.bearer) headers.set("Authorization", `Bearer ${auth.bearer}`);
    else headers.delete("Authorization");
  }
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

function parseProjectRecord(raw: unknown, ctx: string): ProjectSchema {
  if (!raw || typeof raw !== "object") {
    throw new ObjectifiedCliError({
      message: `Invalid project entry in ${ctx}.`,
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; include request-id when reporting.",
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
  if (p.enabled !== undefined && p.enabled !== null && typeof p.enabled !== "boolean") {
    throw new ObjectifiedCliError({
      message: "Invalid project fields in response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "`enabled` must be boolean when present.",
    });
  }
  return {
    ...(raw as ProjectSchema),
    enabled: typeof p.enabled === "boolean" ? p.enabled : true,
  };
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
    projects.push(parseProjectRecord(raw, "projects list"));
  }
  return projects;
}

function parseProjectPayload(data: unknown): ProjectSchema {
  return parseProjectRecord(data, "project response");
}

function parseVersionTagsPayload(data: unknown): VersionTagSchema[] {
  if (!Array.isArray(data)) {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for version tags list.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const tags: VersionTagSchema[] = [];
  for (const raw of data) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid version tag entry in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "The API returned invalid tag rows.",
      });
    }
    const t = raw as Record<string, unknown>;
    if (
      typeof t.id !== "string" ||
      typeof t.project_id !== "string" ||
      typeof t.version_id !== "string" ||
      typeof t.name !== "string"
    ) {
      throw new ObjectifiedCliError({
        message: "Invalid version tag fields in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Required tag fields were missing or mistyped.",
      });
    }
    tags.push(raw as VersionTagSchema);
  }
  return tags;
}

function parseWorkflowAuditPayload(data: unknown): WorkflowAuditPageResponse {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for workflow audit.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const o = data as Record<string, unknown>;
  if (!Array.isArray(o.items) || !o.pagination || typeof o.pagination !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for workflow audit.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected items and pagination from GET .../workflow-audit.",
    });
  }
  const pag = o.pagination as Record<string, unknown>;
  if (
    typeof pag.limit !== "number" ||
    typeof pag.total !== "number" ||
    typeof pag.hasMore !== "boolean"
  ) {
    throw new ObjectifiedCliError({
      message: "Invalid pagination fields in workflow audit response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected numeric limit, total, and boolean hasMore.",
    });
  }
  return data as WorkflowAuditPageResponse;
}

function unwrapSdkGet(
  rawUnknown: unknown,
  lastRequestId: string | undefined,
  lastRetriesAttempted: number,
  requestMeta: RequestAuthMeta,
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
      credentialsWereSent: requestMeta.hadCredentials,
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

function parseTenantsMePayload(data: unknown): TenantsMeResponse {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for tenants list.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const o = data as Record<string, unknown>;
  if (!Array.isArray(o.items)) {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for tenants list.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected `items` array from GET /v1/tenants/me.",
    });
  }
  const items: TenantsMeResponse["items"] = [];
  for (const raw of o.items) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid tenant row in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "The API returned invalid tenant membership rows.",
      });
    }
    const t = raw as Record<string, unknown>;
    if (typeof t.slug !== "string" || typeof t.name !== "string" || typeof t.role !== "string") {
      throw new ObjectifiedCliError({
        message: "Invalid tenant membership fields in response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Each tenant row needs slug, name, and role strings.",
      });
    }
    items.push({ slug: t.slug, name: t.name, role: t.role });
  }
  const total = typeof o.total === "number" ? o.total : Number.NaN;
  const limit = typeof o.limit === "number" ? o.limit : Number.NaN;
  const offset = typeof o.offset === "number" ? o.offset : Number.NaN;
  if (!Number.isFinite(total) || !Number.isFinite(limit) || !Number.isFinite(offset)) {
    throw new ObjectifiedCliError({
      message: "Invalid pagination fields in tenants list response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected numeric total, limit, and offset from GET /v1/tenants/me.",
    });
  }
  return { items, total, limit, offset };
}

function parseTenantInfoPayload(data: unknown): TenantInfoResponse {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for tenant info.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const t = data as Record<string, unknown>;
  if (typeof t.slug !== "string" || typeof t.name !== "string") {
    throw new ObjectifiedCliError({
      message: "Invalid tenant info fields in response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected slug and name from GET /v1/tenants/{slug}.",
    });
  }
  const plan =
    t.plan === null || t.plan === undefined ? null : typeof t.plan === "string" ? t.plan : null;
  const created_at =
    t.created_at === null || t.created_at === undefined
      ? null
      : typeof t.created_at === "string"
        ? t.created_at
        : null;
  const num = (k: string): number => {
    const v = t[k];
    return typeof v === "number" && Number.isFinite(v) ? v : 0;
  };
  const optInt = (k: string): number | null | undefined => {
    const v = t[k];
    if (v === null || v === undefined) return v === null ? null : undefined;
    if (typeof v === "number" && Number.isFinite(v)) return v;
    return null;
  };
  return {
    slug: t.slug,
    name: t.name,
    plan,
    created_at,
    members_count: num("members_count"),
    projects_count: num("projects_count"),
    versions_count: num("versions_count"),
    published_versions_count: num("published_versions_count"),
    storage_used_bytes: optInt("storage_used_bytes") ?? null,
    storage_quota_bytes: optInt("storage_quota_bytes") ?? null,
  };
}

function createInstrumentedFetch(opts: {
  inner: typeof fetch;
  auth: ApiAuthSnapshot;
  verbose?: boolean;
  stderrWrite?: (line: string) => void;
  onUnauthorized?: () => Promise<void>;
  onRetryStats?: (count: number) => void;
  requestMeta: RequestAuthMeta;
}): typeof fetch {
  const log = opts.stderrWrite ?? ((line: string) => process.stderr.write(`${line}\n`));

  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const baseReq = input instanceof Request ? input : new Request(input, init);
    opts.requestMeta.hadCredentials = Boolean(opts.auth.apiKey || opts.auth.bearer);
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
      if (opts.verbose) {
        const mode = opts.auth.apiKey
          ? `api-key=${redactApiKeyForLogs(opts.auth.apiKey)}`
          : opts.auth.bearer
            ? "bearer=***"
            : "none";
        log(`objectified: auth=${mode}`);
      }

      if (response.status === 401 && opts.onUnauthorized !== undefined && !didReauth) {
        didReauth = true;
        await opts.onUnauthorized();
        req = mergeAuthHeaders(baseReq, opts.auth);
        continue;
      }

      const idem = methodIsIdempotent(req.method);
      const attemptNumber = transientRetries + 1;

      if (attemptNumber < MAX_TRANSIENT_ATTEMPTS && shouldRetryStatus(response.status, idem)) {
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
  const requestMeta: RequestAuthMeta = { hadCredentials: false };

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
    requestMeta,
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

    async listProjects(
      tenantSlug: string,
      options?: ListProjectsOptions,
    ): Promise<ProjectSchema[]> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listProjectsV1ProjectsTenantSlugGet({
          client: hey,
          path: { tenant_slug: tenantSlug },
          query: options?.include_deleted === true ? { include_deleted: true } : {},
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }

      return parseProjectsPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async getProject(tenantSlug: string, projectId: string): Promise<ProjectSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await getProjectV1ProjectsTenantSlugProjectIdGet({
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
      return parseProjectPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async getProjectBySlug(tenantSlug: string, projectSlug: string): Promise<ProjectSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await getProjectBySlugV1ProjectsTenantSlugBySlugProjectSlugGet({
          client: hey,
          path: { tenant_slug: tenantSlug, project_slug: projectSlug },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseProjectPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
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
      return parseVersionsPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async listVersionTags(tenantSlug: string, projectId: string): Promise<VersionTagSchema[]> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listVersionTagsV1VersionTagsTenantSlugProjectIdGet({
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
      return parseVersionTagsPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async listWorkflowAudit(opts: {
      tenantSlug: string;
      projectId?: string;
      limit?: number;
      offset?: number;
    }): Promise<WorkflowAuditPageResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listWorkflowAuditV1VersionsTenantSlugWorkflowAuditGet({
          client: hey,
          path: { tenant_slug: opts.tenantSlug },
          query: {
            projectId: opts.projectId ?? undefined,
            limit: opts.limit ?? undefined,
            offset: opts.offset ?? undefined,
          },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseWorkflowAuditPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
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
      return parseClassesPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
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
      return parsePrimitivesPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async listMyTenantsPage(limit: number, offset: number): Promise<TenantsMeResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listMyTenantsV1TenantsMeGet({
          client: hey,
          query: { limit, offset },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseTenantsMePayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async getTenantInfo(tenantSlug: string): Promise<TenantInfoResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await getTenantInfoV1TenantsTenantSlugGet({
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
      return parseTenantInfoPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async verifyTenantAccess(tenantSlug: string): Promise<void> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await verifyTenantAccessV1TenantsTenantSlugHead({
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
      unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta);
    },
  };
}
