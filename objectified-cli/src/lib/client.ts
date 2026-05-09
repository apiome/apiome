import { createClient, type Client } from "../generated/client.js";
import type {
  BrowsePublicProjectsResponse,
  BrowsePublicTenantsResponse,
  BrowsePublicVersionsResponse,
  ClassSchema,
  CompatibilityCheckRequest,
  CompatibilityCheckResponse,
  ImportJobCreateRequest,
  ImportJobResponse,
  PrimitiveSchema,
  ProjectCreateRequest,
  ProjectSchema,
  TenantInfoResponse,
  TenantsMeResponse,
  VersionChangeReportOut,
  VersionCreateRequest,
  VersionPublishChangeReportPreviewOut,
  VersionPublishChangeReportPreviewRequest,
  VersionPublishRequest,
  VersionSchema,
  VersionTagCreateRequest,
  VersionTagSchema,
  VersionTagUpdateRequest,
  WorkflowAuditPageResponse,
} from "../generated/models.js";
import {
  cancelImportJobV1ImportsTenantSlugJobIdCancelPost,
  checkRevisionCompatibilityV1VersionsTenantSlugProjectIdCompatibilityPost,
  commitImportJobV1ImportsTenantSlugJobIdCommitPost,
  createImportJobV1ImportsTenantSlugPost,
  createVersionTagV1VersionTagsTenantSlugProjectIdPost,
  createVersionV1VersionsTenantSlugProjectIdPost,
  createProjectV1ProjectsTenantSlugPost,
  getImportJobV1ImportsTenantSlugJobIdGet,
  getProjectBySlugV1ProjectsTenantSlugBySlugProjectSlugGet,
  getProjectV1ProjectsTenantSlugProjectIdGet,
  getTenantInfoV1TenantsTenantSlugGet,
  getVersionByVersionIdV1VersionsTenantSlugProjectIdByVersionVersionIdGet,
  getVersionChangeReportV1VersionsTenantSlugProjectIdVersionRecordIdChangeReportGet,
  getVersionV1VersionsTenantSlugProjectIdVersionRecordIdGet,
  listClassesV1ClassesTenantSlugGet,
  listMyTenantsV1TenantsMeGet,
  listPrimitivesV1PrimitivesTenantSlugGet,
  listProjectsV1ProjectsTenantSlugGet,
  listPublicBrowseProjectsV1BrowseTenantsTenantSlugProjectsGet,
  listPublicBrowseTenantsV1BrowseTenantsGet,
  listPublicBrowseVersionsV1BrowseTenantsTenantSlugProjectsProjectSlugVersionsGet,
  listVersionTagsV1VersionTagsTenantSlugProjectIdGet,
  listVersionsV1VersionsTenantSlugProjectIdGet,
  listWorkflowAuditV1VersionsTenantSlugWorkflowAuditGet,
  patchVersionTagV1VersionTagsTenantSlugProjectIdTagIdPatch,
  previewChangeReportForPublishV1VersionsTenantSlugProjectIdVersionRecordIdChangeReportPublishPreviewPost,
  publishVersionV1VersionsTenantSlugProjectIdVersionRecordIdPublishPost,
  verifyTenantAccessV1TenantsTenantSlugHead,
} from "../generated/operations.js";

import { PROJECT_DOMAIN_FALLBACK_IDS } from "./projects/domain-categories.js";
import { normalizeProjectDomainsApiPayload } from "./projects/domains-payload.js";

import { EXIT_CODES } from "./exit-codes.js";
import { httpStatusToCliError, networkErrnoToCliError, ObjectifiedCliError } from "./errors.js";
import { redactApiKeyForLogs } from "./redact-api-key.js";

export type {
  BrowsePublicProjectsResponse,
  BrowsePublicTenantsResponse,
  BrowsePublicVersionsResponse,
  ClassSchema,
  CompatibilityCheckRequest,
  CompatibilityCheckResponse,
  ImportJobCreateRequest,
  ImportJobResponse,
  ImportSourceKind,
  ProjectCreateRequest,
  ProjectSchema,
  VersionChangeReportOut,
  VersionCreateRequest,
  VersionPublishChangeReportPreviewOut,
  VersionPublishChangeReportPreviewRequest,
  VersionPublishRequest,
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
  /**
   * Domain ids allowed for project metadata (`domainCategory`), from GET …/domains when deployed,
   * else cached fallback ids (#3204).
   */
  fetchProjectDomainsAllowlist(tenantSlug: string): Promise<string[]>;
  createProject(tenantSlug: string, body: ProjectCreateRequest): Promise<ProjectSchema>;
  getProject(tenantSlug: string, projectId: string): Promise<ProjectSchema>;
  getProjectBySlug(tenantSlug: string, projectSlug: string): Promise<ProjectSchema>;
  listVersions(tenantSlug: string, projectId: string): Promise<VersionSchema[]>;
  createVersion(
    tenantSlug: string,
    projectId: string,
    body: VersionCreateRequest,
  ): Promise<VersionSchema>;
  getVersion(
    tenantSlug: string,
    projectId: string,
    versionRecordId: string,
  ): Promise<VersionSchema>;
  getVersionByVersionId(
    tenantSlug: string,
    projectId: string,
    versionId: string,
  ): Promise<VersionSchema>;
  checkRevisionCompatibility(
    tenantSlug: string,
    projectId: string,
    body: CompatibilityCheckRequest,
  ): Promise<CompatibilityCheckResponse>;
  tryGetVersionChangeReport(
    tenantSlug: string,
    projectId: string,
    versionRecordId: string,
  ): Promise<VersionChangeReportOut | null>;
  previewPublishChangeReport(
    tenantSlug: string,
    projectId: string,
    versionRecordId: string,
    body?: VersionPublishChangeReportPreviewRequest,
  ): Promise<VersionPublishChangeReportPreviewOut>;
  publishVersion(
    tenantSlug: string,
    projectId: string,
    versionRecordId: string,
    body?: VersionPublishRequest,
  ): Promise<VersionSchema>;
  createVersionTag(
    tenantSlug: string,
    projectId: string,
    body: VersionTagCreateRequest,
  ): Promise<VersionTagSchema>;
  patchVersionTag(
    tenantSlug: string,
    projectId: string,
    tagId: string,
    body: VersionTagUpdateRequest,
  ): Promise<VersionTagSchema>;
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
  listPublicBrowseTenants(opts?: {
    search?: string;
    sort?: "latest" | "name" | "projects";
  }): Promise<BrowsePublicTenantsResponse>;
  listPublicBrowseProjects(opts: {
    tenantSlug: string;
    search?: string;
    domain?: string;
    hasPublished?: boolean;
  }): Promise<BrowsePublicProjectsResponse>;
  listPublicBrowseVersions(opts: {
    tenantSlug: string;
    projectSlug: string;
    since?: string;
  }): Promise<BrowsePublicVersionsResponse>;
  createImportJob(tenantSlug: string, body: ImportJobCreateRequest): Promise<ImportJobResponse>;
  getImportJob(tenantSlug: string, jobId: string): Promise<ImportJobResponse>;
  commitImportJob(tenantSlug: string, jobId: string): Promise<ImportJobResponse>;
  cancelImportJob(tenantSlug: string, jobId: string): Promise<ImportJobResponse>;
  /** Raw GET /v1/schema/… for streaming or hashing (published OpenAPI bundle or single class). */
  fetchOpenApiPublishedSchema(opts: {
    tenantSlug: string;
    projectSlug: string;
    versionSlug: string;
    className?: string;
    acceptHeader?: string;
  }): Promise<Response>;
};

const MAX_RETRY_AFTER_MS = 120_000;
export const MAX_TRANSIENT_ATTEMPTS = 4;

const PROJECT_DOMAINS_CACHE_TTL_MS = 5 * 60 * 1000;

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

export function formatApiError(error: unknown): string {
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

function parseVersionSinglePayload(data: unknown, ctx: string): VersionSchema {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: `Unexpected response shape for ${ctx}.`,
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; include request-id when reporting.",
    });
  }
  const v = data as Record<string, unknown>;
  if (typeof v.version_id !== "string" || typeof v.id !== "string") {
    throw new ObjectifiedCliError({
      message: "Invalid version fields in response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Required version fields were missing or mistyped.",
    });
  }
  return data as VersionSchema;
}

function parseCompatibilityPayload(data: unknown): CompatibilityCheckResponse {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for compatibility check.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape for POST …/compatibility.",
    });
  }
  const o = data as Record<string, unknown>;
  if (
    typeof o.overall !== "string" ||
    typeof o.baseRevisionId !== "string" ||
    typeof o.headRevisionId !== "string" ||
    typeof o.reportFingerprint !== "string"
  ) {
    throw new ObjectifiedCliError({
      message: "Invalid compatibility response fields.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected overall, baseRevisionId, headRevisionId, and reportFingerprint strings.",
    });
  }
  if (!Array.isArray(o.findings)) {
    throw new ObjectifiedCliError({
      message: "Invalid compatibility findings array.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected `findings` array from POST …/compatibility.",
    });
  }
  return data as CompatibilityCheckResponse;
}

function parseChangeReportPayload(data: unknown): VersionChangeReportOut {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for version change report.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape for GET …/change-report.",
    });
  }
  const o = data as Record<string, unknown>;
  if (
    typeof o.id !== "string" ||
    typeof o.publishedRevisionId !== "string" ||
    o.changeModelJson === undefined ||
    o.changeModelJson === null ||
    typeof o.changeModelJson !== "object"
  ) {
    throw new ObjectifiedCliError({
      message: "Invalid change report fields.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected id, publishedRevisionId, and changeModelJson from GET …/change-report.",
    });
  }
  return data as VersionChangeReportOut;
}

function parsePublishPreviewPayload(data: unknown): VersionPublishChangeReportPreviewOut {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for publish change-report preview.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape for POST …/change-report/publish-preview.",
    });
  }
  const o = data as Record<string, unknown>;
  if (
    typeof o.fromVersionLabel !== "string" ||
    typeof o.toVersionLabel !== "string" ||
    o.changeModelJson === undefined ||
    o.changeModelJson === null ||
    typeof o.changeModelJson !== "object"
  ) {
    throw new ObjectifiedCliError({
      message: "Invalid publish preview fields.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected fromVersionLabel, toVersionLabel, and changeModelJson from publish-preview.",
    });
  }
  return data as VersionPublishChangeReportPreviewOut;
}

function parseVersionTagSinglePayload(data: unknown, ctx: string): VersionTagSchema {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: `Unexpected response shape for ${ctx}.`,
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape for version tag mutation.",
    });
  }
  const v = data as Record<string, unknown>;
  if (
    typeof v.id !== "string" ||
    typeof v.name !== "string" ||
    typeof v.version_id !== "string"
  ) {
    throw new ObjectifiedCliError({
      message: "Invalid version tag fields in response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected id, name, and version_id on the version tag row.",
    });
  }
  return data as VersionTagSchema;
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

function parseBrowsePublicTenantsPayload(data: unknown): BrowsePublicTenantsResponse {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for public browse tenants.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const o = data as Record<string, unknown>;
  const ds = o.directory_stats;
  if (!ds || typeof ds !== "object") {
    throw new ObjectifiedCliError({
      message: "Missing directory_stats in browse tenants response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected directory_stats from GET /v1/browse/tenants.",
    });
  }
  const stats = ds as Record<string, unknown>;
  const tc = stats.tenant_count;
  const pc = stats.project_count;
  const vc = stats.version_count;
  if (
    typeof tc !== "number" ||
    typeof pc !== "number" ||
    typeof vc !== "number" ||
    !Number.isFinite(tc) ||
    !Number.isFinite(pc) ||
    !Number.isFinite(vc)
  ) {
    throw new ObjectifiedCliError({
      message: "Invalid directory_stats in browse tenants response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "directory_stats must include numeric tenant, project, and version counts.",
    });
  }
  if (!Array.isArray(o.tenants)) {
    throw new ObjectifiedCliError({
      message: "Missing tenants array in browse tenants response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected `tenants` from GET /v1/browse/tenants.",
    });
  }
  const tenantsOut: BrowsePublicTenantsResponse["tenants"] = [];
  for (const raw of o.tenants) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid tenant row in browse directory response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Each tenant row must be an object.",
      });
    }
    const t = raw as Record<string, unknown>;
    if (
      typeof t.slug !== "string" ||
      typeof t.name !== "string" ||
      typeof t.project_count !== "number" ||
      typeof t.published_versions !== "number"
    ) {
      throw new ObjectifiedCliError({
        message: "Invalid browse tenant fields.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Each row needs slug, name, project_count, and published_versions.",
      });
    }
    const lv = t.latest_version;
    const la = t.latest_activity_at;
    tenantsOut.push({
      slug: t.slug,
      name: t.name,
      project_count: t.project_count,
      published_versions: t.published_versions,
      latest_version: typeof lv === "string" || lv === null ? lv : undefined,
      latest_activity_at: typeof la === "string" ? la : la === null ? null : undefined,
    });
  }
  const fc = o.filtered_count;
  if (typeof fc !== "number" || !Number.isFinite(fc)) {
    throw new ObjectifiedCliError({
      message: "Invalid filtered_count in browse tenants response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected numeric filtered_count from GET /v1/browse/tenants.",
    });
  }
  return {
    directory_stats: { tenant_count: tc, project_count: pc, version_count: vc },
    tenants: tenantsOut,
    filtered_count: fc,
  };
}

function parseBrowsePublicProjectsPayload(data: unknown): BrowsePublicProjectsResponse {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for public browse projects.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const o = data as Record<string, unknown>;
  if (typeof o.tenant_slug !== "string" || typeof o.tenant_name !== "string") {
    throw new ObjectifiedCliError({
      message: "Invalid browse projects response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected tenant_slug and tenant_name from GET /v1/browse/tenants/{tenant}/projects.",
    });
  }
  if (!Array.isArray(o.projects)) {
    throw new ObjectifiedCliError({
      message: "Missing projects array in browse projects response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected `projects` from GET /v1/browse/tenants/{tenant}/projects.",
    });
  }
  const projectsOut: BrowsePublicProjectsResponse["projects"] = [];
  for (const raw of o.projects) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid project row in browse directory response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Each project row must be an object.",
      });
    }
    const p = raw as Record<string, unknown>;
    if (
      typeof p.slug !== "string" ||
      typeof p.name !== "string" ||
      typeof p.domain !== "string" ||
      typeof p.published_versions !== "number"
    ) {
      throw new ObjectifiedCliError({
        message: "Invalid browse project fields.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Each row needs slug, name, domain, and published_versions.",
      });
    }
    const lv = p.latest_version;
    const lp = p.latest_published_at;
    projectsOut.push({
      slug: p.slug,
      name: p.name,
      domain: p.domain,
      published_versions: p.published_versions,
      latest_version: typeof lv === "string" || lv === null ? lv : undefined,
      latest_published_at: typeof lp === "string" || lp === null ? lp : undefined,
    });
  }
  const fc = o.filtered_count;
  if (typeof fc !== "number" || !Number.isFinite(fc)) {
    throw new ObjectifiedCliError({
      message: "Invalid filtered_count in browse projects response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected numeric filtered_count from GET /v1/browse/tenants/{tenant}/projects.",
    });
  }
  return {
    tenant_slug: o.tenant_slug,
    tenant_name: o.tenant_name,
    projects: projectsOut,
    filtered_count: fc,
  };
}

function parseBrowsePublicVersionsPayload(data: unknown): BrowsePublicVersionsResponse {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: "Unexpected response shape for public browse versions.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; try again or upgrade the CLI.",
    });
  }
  const o = data as Record<string, unknown>;
  if (
    typeof o.tenant_slug !== "string" ||
    typeof o.tenant_name !== "string" ||
    typeof o.project_slug !== "string" ||
    typeof o.project_name !== "string"
  ) {
    throw new ObjectifiedCliError({
      message: "Invalid browse versions response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected tenant and project fields from GET /v1/browse/tenants/{tenant}/projects/{project}/versions.",
    });
  }
  if (!Array.isArray(o.versions)) {
    throw new ObjectifiedCliError({
      message: "Missing versions array in browse versions response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected `versions` from the browse versions endpoint.",
    });
  }
  const versionsOut: BrowsePublicVersionsResponse["versions"] = [];
  for (const raw of o.versions) {
    if (!raw || typeof raw !== "object") {
      throw new ObjectifiedCliError({
        message: "Invalid version row in browse versions response.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Each version row must be an object.",
      });
    }
    const v = raw as Record<string, unknown>;
    if (typeof v.id !== "string" || typeof v.version_id !== "string") {
      throw new ObjectifiedCliError({
        message: "Invalid browse version fields.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Each row needs id and version_id.",
      });
    }
    if (!Array.isArray(v.tags)) {
      throw new ObjectifiedCliError({
        message: "Invalid browse version tags.",
        exitCode: EXIT_CODES.VALIDATION,
        title: "Validation failed",
        hint: "Each row needs a string array `tags`.",
      });
    }
    const tags: string[] = [];
    for (const t of v.tags) {
      if (typeof t !== "string") {
        throw new ObjectifiedCliError({
          message: "Invalid browse version tag entry.",
          exitCode: EXIT_CODES.VALIDATION,
          title: "Validation failed",
          hint: "Tags must be strings.",
        });
      }
      tags.push(t);
    }
    const pub = v.published_at;
    const cs = v.changes_summary;
    const desc = v.description;
    const clog = v.change_log;
    versionsOut.push({
      id: v.id,
      version_id: v.version_id,
      published_at: typeof pub === "string" || pub === null ? pub : undefined,
      tags,
      changes_summary: typeof cs === "string" || cs === null ? cs : undefined,
      description: typeof desc === "string" || desc === null ? desc : undefined,
      change_log: typeof clog === "string" || clog === null ? clog : undefined,
    });
  }
  const fc = o.filtered_count;
  if (typeof fc !== "number" || !Number.isFinite(fc)) {
    throw new ObjectifiedCliError({
      message: "Invalid filtered_count in browse versions response.",
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected numeric filtered_count from GET /v1/browse/tenants/{tenant}/projects/{project}/versions.",
    });
  }
  return {
    tenant_slug: o.tenant_slug,
    tenant_name: o.tenant_name,
    project_slug: o.project_slug,
    project_name: o.project_name,
    versions: versionsOut,
    filtered_count: fc,
  };
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

function parseImportJobPayload(data: unknown, ctx: string, requestId: string | undefined): ImportJobResponse {
  if (!data || typeof data !== "object") {
    throw new ObjectifiedCliError({
      message: `Unexpected response shape for ${ctx}.`,
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "The API returned an unexpected JSON shape; include request-id when reporting.",
      requestId,
    });
  }
  const o = data as Record<string, unknown>;
  if (typeof o.jobId !== "string" || typeof o.state !== "string" || typeof o.tenantId !== "string") {
    throw new ObjectifiedCliError({
      message: `Invalid import job fields in ${ctx}.`,
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected jobId, state, and tenantId from the imports API.",
      requestId,
    });
  }
  if (typeof o.percent !== "number" || !Number.isFinite(o.percent)) {
    throw new ObjectifiedCliError({
      message: `Invalid import job percent in ${ctx}.`,
      exitCode: EXIT_CODES.VALIDATION,
      title: "Validation failed",
      hint: "Expected numeric percent from the imports API.",
      requestId,
    });
  }
  return data as ImportJobResponse;
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

  const baseUrlNorm = trimTrailingSlash(options.baseUrl);
  const domainsAllowlistCache = new Map<string, { ids: string[]; expiresAt: number }>();

  const hey: Client = createClient({
    baseUrl: baseUrlNorm,
    fetch: instrumented,
  });

  return {
    get lastRequestId() {
      return lastRequestId;
    },
    get lastRetriesAttempted() {
      return lastRetriesAttempted;
    },

    async fetchProjectDomainsAllowlist(tenantSlug: string): Promise<string[]> {
      const cacheKey = `${baseUrlNorm}|${tenantSlug}`;
      const now = Date.now();
      const hit = domainsAllowlistCache.get(cacheKey);
      if (hit !== undefined && hit.expiresAt > now) {
        return hit.ids;
      }

      const tryUrls = [
        `${baseUrlNorm}/v1/projects/${encodeURIComponent(tenantSlug)}/domains`,
        `${baseUrlNorm}/v1/projects/domains`,
      ];

      for (const url of tryUrls) {
        const res = await instrumented(
          new Request(url, { method: "GET", headers: { Accept: "application/json" } }),
        );
        if (res.status === 404) continue;

        const text = await res.text();
        const hdrId =
          res.headers.get("x-request-id") ?? res.headers.get("X-Request-Id") ?? undefined;

        if (!res.ok) {
          let apiMessage = text.slice(0, 800);
          try {
            apiMessage = formatApiError(JSON.parse(text) as unknown);
          } catch {
            /* keep truncated body */
          }
          throw httpStatusToCliError(res.status, apiMessage, {
            requestId: hdrId ?? lastRequestId,
            retriesAttempted: lastRetriesAttempted,
            credentialsWereSent: requestMeta.hadCredentials,
          });
        }

        let parsed: unknown = null;
        if (text.trim() !== "") {
          try {
            parsed = JSON.parse(text) as unknown;
          } catch {
            throw new ObjectifiedCliError({
              message: "Project domains response was not valid JSON.",
              exitCode: EXIT_CODES.VALIDATION,
              title: "Validation failed",
              hint: "Expected JSON from GET /v1/projects/{tenant}/domains (or /v1/projects/domains).",
              requestId: hdrId ?? lastRequestId,
              retriesAttempted: lastRetriesAttempted,
            });
          }
        }

        const ids = normalizeProjectDomainsApiPayload(parsed);
        if (ids.length > 0) {
          domainsAllowlistCache.set(cacheKey, {
            ids,
            expiresAt: now + PROJECT_DOMAINS_CACHE_TTL_MS,
          });
          return ids;
        }
      }

      const fallback = [...PROJECT_DOMAIN_FALLBACK_IDS];
      domainsAllowlistCache.set(cacheKey, {
        ids: fallback,
        expiresAt: now + PROJECT_DOMAINS_CACHE_TTL_MS,
      });
      return fallback;
    },

    async createProject(tenantSlug: string, body: ProjectCreateRequest): Promise<ProjectSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await createProjectV1ProjectsTenantSlugPost({
          client: hey,
          path: { tenant_slug: tenantSlug },
          body,
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

    async createVersion(
      tenantSlug: string,
      projectId: string,
      body: VersionCreateRequest,
    ): Promise<VersionSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await createVersionV1VersionsTenantSlugProjectIdPost({
          client: hey,
          path: { tenant_slug: tenantSlug, project_id: projectId },
          body,
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseVersionSinglePayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "version create",
      );
    },

    async getVersion(
      tenantSlug: string,
      projectId: string,
      versionRecordId: string,
    ): Promise<VersionSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await getVersionV1VersionsTenantSlugProjectIdVersionRecordIdGet({
          client: hey,
          path: {
            tenant_slug: tenantSlug,
            project_id: projectId,
            version_record_id: versionRecordId,
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
      return parseVersionSinglePayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "version get",
      );
    },

    async getVersionByVersionId(
      tenantSlug: string,
      projectId: string,
      versionId: string,
    ): Promise<VersionSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await getVersionByVersionIdV1VersionsTenantSlugProjectIdByVersionVersionIdGet({
          client: hey,
          path: {
            tenant_slug: tenantSlug,
            project_id: projectId,
            version_id: versionId,
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
      return parseVersionSinglePayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "version get by semver",
      );
    },

    async checkRevisionCompatibility(
      tenantSlug: string,
      projectId: string,
      body: CompatibilityCheckRequest,
    ): Promise<CompatibilityCheckResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await checkRevisionCompatibilityV1VersionsTenantSlugProjectIdCompatibilityPost(
          {
            client: hey,
            path: { tenant_slug: tenantSlug, project_id: projectId },
            body,
            throwOnError: false,
          },
        );
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseCompatibilityPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async tryGetVersionChangeReport(
      tenantSlug: string,
      projectId: string,
      versionRecordId: string,
    ): Promise<VersionChangeReportOut | null> {
      try {
        let rawUnknown: unknown;
        try {
          rawUnknown =
            await getVersionChangeReportV1VersionsTenantSlugProjectIdVersionRecordIdChangeReportGet(
              {
                client: hey,
                path: {
                  tenant_slug: tenantSlug,
                  project_id: projectId,
                  version_record_id: versionRecordId,
                },
                throwOnError: false,
              },
            );
        } catch (e) {
          if (e instanceof ObjectifiedCliError) throw e;
          if (e !== null && typeof e === "object" && "code" in e) {
            throw networkErrnoToCliError(e as NodeJS.ErrnoException);
          }
          throw e;
        }
        return parseChangeReportPayload(
          unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        );
      } catch (e) {
        if (e instanceof ObjectifiedCliError && e.exitCode === EXIT_CODES.NOT_FOUND) {
          return null;
        }
        throw e;
      }
    },

    async previewPublishChangeReport(
      tenantSlug: string,
      projectId: string,
      versionRecordId: string,
      body?: VersionPublishChangeReportPreviewRequest,
    ): Promise<VersionPublishChangeReportPreviewOut> {
      let rawUnknown: unknown;
      try {
        rawUnknown =
          await previewChangeReportForPublishV1VersionsTenantSlugProjectIdVersionRecordIdChangeReportPublishPreviewPost(
            {
              client: hey,
              path: {
                tenant_slug: tenantSlug,
                project_id: projectId,
                version_record_id: versionRecordId,
              },
              body: body ?? {},
              throwOnError: false,
            },
          );
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parsePublishPreviewPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async publishVersion(
      tenantSlug: string,
      projectId: string,
      versionRecordId: string,
      body?: VersionPublishRequest,
    ): Promise<VersionSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await publishVersionV1VersionsTenantSlugProjectIdVersionRecordIdPublishPost({
          client: hey,
          path: {
            tenant_slug: tenantSlug,
            project_id: projectId,
            version_record_id: versionRecordId,
          },
          body: body ?? {},
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseVersionSinglePayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "version publish",
      );
    },

    async createVersionTag(
      tenantSlug: string,
      projectId: string,
      body: VersionTagCreateRequest,
    ): Promise<VersionTagSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await createVersionTagV1VersionTagsTenantSlugProjectIdPost({
          client: hey,
          path: { tenant_slug: tenantSlug, project_id: projectId },
          body,
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseVersionTagSinglePayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "version tag create",
      );
    },

    async patchVersionTag(
      tenantSlug: string,
      projectId: string,
      tagId: string,
      body: VersionTagUpdateRequest,
    ): Promise<VersionTagSchema> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await patchVersionTagV1VersionTagsTenantSlugProjectIdTagIdPatch({
          client: hey,
          path: {
            tenant_slug: tenantSlug,
            project_id: projectId,
            tag_id: tagId,
          },
          body,
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseVersionTagSinglePayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "version tag patch",
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

    async listPublicBrowseTenants(opts?: {
      search?: string;
      sort?: "latest" | "name" | "projects";
    }): Promise<BrowsePublicTenantsResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listPublicBrowseTenantsV1BrowseTenantsGet({
          client: hey,
          query: {
            search: opts?.search ?? undefined,
            sort: opts?.sort ?? undefined,
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
      return parseBrowsePublicTenantsPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async listPublicBrowseProjects(opts: {
      tenantSlug: string;
      search?: string;
      domain?: string;
      hasPublished?: boolean;
    }): Promise<BrowsePublicProjectsResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listPublicBrowseProjectsV1BrowseTenantsTenantSlugProjectsGet({
          client: hey,
          path: { tenant_slug: opts.tenantSlug },
          query: {
            search: opts.search ?? undefined,
            domain: opts.domain ?? undefined,
            has_published: opts.hasPublished ?? undefined,
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
      return parseBrowsePublicProjectsPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async listPublicBrowseVersions(opts: {
      tenantSlug: string;
      projectSlug: string;
      since?: string;
    }): Promise<BrowsePublicVersionsResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await listPublicBrowseVersionsV1BrowseTenantsTenantSlugProjectsProjectSlugVersionsGet({
          client: hey,
          path: { tenant_slug: opts.tenantSlug, project_slug: opts.projectSlug },
          query: {
            since: opts.since ?? undefined,
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
      return parseBrowsePublicVersionsPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
      );
    },

    async createImportJob(tenantSlug: string, body: ImportJobCreateRequest): Promise<ImportJobResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await createImportJobV1ImportsTenantSlugPost({
          client: hey,
          path: { tenant_slug: tenantSlug },
          body,
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseImportJobPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "import job create",
        lastRequestId,
      );
    },

    async getImportJob(tenantSlug: string, jobId: string): Promise<ImportJobResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await getImportJobV1ImportsTenantSlugJobIdGet({
          client: hey,
          path: { tenant_slug: tenantSlug, job_id: jobId },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseImportJobPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "import job status",
        lastRequestId,
      );
    },

    async commitImportJob(tenantSlug: string, jobId: string): Promise<ImportJobResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await commitImportJobV1ImportsTenantSlugJobIdCommitPost({
          client: hey,
          path: { tenant_slug: tenantSlug, job_id: jobId },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseImportJobPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "import job commit",
        lastRequestId,
      );
    },

    async cancelImportJob(tenantSlug: string, jobId: string): Promise<ImportJobResponse> {
      let rawUnknown: unknown;
      try {
        rawUnknown = await cancelImportJobV1ImportsTenantSlugJobIdCancelPost({
          client: hey,
          path: { tenant_slug: tenantSlug, job_id: jobId },
          throwOnError: false,
        });
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
      return parseImportJobPayload(
        unwrapSdkGet(rawUnknown, lastRequestId, lastRetriesAttempted, requestMeta),
        "import job cancel",
        lastRequestId,
      );
    },

    async fetchOpenApiPublishedSchema(opts: {
      tenantSlug: string;
      projectSlug: string;
      versionSlug: string;
      className?: string;
      acceptHeader?: string;
    }): Promise<Response> {
      const t = encodeURIComponent(opts.tenantSlug);
      const p = encodeURIComponent(opts.projectSlug);
      const v = encodeURIComponent(opts.versionSlug);
      const path =
        opts.className !== undefined && opts.className !== ""
          ? `/v1/schema/${t}/${p}/${v}/${encodeURIComponent(opts.className)}`
          : `/v1/schema/${t}/${p}/${v}`;
      const url = `${baseUrlNorm}${path}`;
      const headers = new Headers();
      const accept = opts.acceptHeader?.trim();
      if (accept !== undefined && accept !== "") {
        headers.set("Accept", accept);
      }
      try {
        return await instrumented(new Request(url, { method: "GET", headers }));
      } catch (e) {
        if (e instanceof ObjectifiedCliError) throw e;
        if (e !== null && typeof e === "object" && "code" in e) {
          throw networkErrnoToCliError(e as NodeJS.ErrnoException);
        }
        throw e;
      }
    },
  };
}
