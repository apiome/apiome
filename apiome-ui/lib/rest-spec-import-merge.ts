/**
 * Merge OpenAPI / Swagger `info` into catalog project fields for REST/CLI imports.
 * Parity with dashboard OpenAPIImportDialog (title/description from info).
 *
 * `projectMetadata` uses the same flat shape as the Projects "API Metadata" tab and
 * published OpenAPI `x-metadata` / `info` enrichment (summary, termsOfService, contact,
 * license, plus any other `info.*` keys such as vendor `x-*` extensions).
 * `info.description` maps to the project `description` column only when the request did not supply one.
 */

export type RestSpecImportMetadata = {
  project: { name: string; slug: string; description?: string | null };
  version: { versionId: string; description?: string | null };
};

export type MergedCatalogTargets = {
  project: { name: string; slug: string; description?: string | null };
  version: { versionId: string; description?: string | null };
  /** Stored in apiome.projects.metadata on create */
  projectMetadata: Record<string, unknown> | undefined;
};

function nonEmptyString(v: unknown): string | undefined {
  if (typeof v !== "string") return undefined;
  const t = v.trim();
  return t || undefined;
}

function pickContact(c: unknown): Record<string, string> | undefined {
  if (!c || typeof c !== "object") return undefined;
  const o = c as Record<string, unknown>;
  const out: Record<string, string> = {};
  const n = nonEmptyString(o.name);
  const u = nonEmptyString(o.url);
  const e = nonEmptyString(o.email);
  if (n) out.name = n;
  if (u) out.url = u;
  if (e) out.email = e;
  return Object.keys(out).length > 0 ? out : undefined;
}

function pickLicense(l: unknown): Record<string, string> | undefined {
  if (!l || typeof l !== "object") return undefined;
  const o = l as Record<string, unknown>;
  const out: Record<string, string> = {};
  for (const key of ["name", "url", "identifier"] as const) {
    const s = nonEmptyString(o[key]);
    if (s) out[key] = s;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function extractOpenApiInfoObject(document: unknown): Record<string, unknown> | undefined {
  if (!document || typeof document !== "object") return undefined;
  const d = document as Record<string, unknown>;
  // OpenAPI 3.x / Swagger 2.0 both use top-level `info`
  const info = d.info;
  if (!info || typeof info !== "object") return undefined;
  return info as Record<string, unknown>;
}

/**
 * When merging for OpenAPI/Swagger (`internalKind === 'openapi'`), reads `document.info`:
 * - Fills `project.description` from `info.description` if the request did not supply one.
 * - Builds flat `projectMetadata` for `apiome.projects.metadata` (summary, termsOfService, contact, license).
 */
export function mergeOpenApiDocumentIntoCatalogTargets(
  metadata: RestSpecImportMetadata,
  document: unknown,
  sourceKind: "openapi" | "arazzo",
): MergedCatalogTargets {
  const base: MergedCatalogTargets = {
    project: {
      name: metadata.project.name,
      slug: metadata.project.slug,
      description: metadata.project.description ?? undefined,
    },
    version: {
      versionId: metadata.version.versionId,
      description: metadata.version.description ?? null,
    },
    projectMetadata: undefined,
  };

  if (sourceKind !== "openapi") {
    return base;
  }

  const info = extractOpenApiInfoObject(document);
  if (!info) {
    return base;
  }

  const desc = nonEmptyString(info.description);
  const summary = nonEmptyString(info.summary);
  const tos = nonEmptyString(info.termsOfService);
  const contact = pickContact(info.contact);
  const license = pickLicense(info.license);

  const flatMeta: Record<string, unknown> = {};
  if (summary) flatMeta.summary = summary;
  if (tos) flatMeta.termsOfService = tos;
  if (contact) flatMeta.contact = contact;
  if (license) flatMeta.license = license;

  const skipExtraInfoKeys = new Set([
    "title",
    "version",
    "description",
    "summary",
    "termsOfService",
    "contact",
    "license",
  ]);
  for (const [key, value] of Object.entries(info)) {
    if (skipExtraInfoKeys.has(key)) continue;
    if (value !== undefined && value !== null) {
      flatMeta[key] = value;
    }
  }

  if (Object.keys(flatMeta).length > 0) {
    base.projectMetadata = flatMeta;
  }

  const reqDesc = nonEmptyString(metadata.project.description);
  if (!reqDesc && desc) {
    base.project.description = desc;
  }

  return base;
}
