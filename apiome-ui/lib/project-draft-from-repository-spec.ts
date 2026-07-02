import YAML from 'yaml';
import type { RepositorySpecFormat } from './repository-file-spec-metadata';

export type RepositorySpecProjectDraft = {
  projectName: string;
  projectSlug: string;
  projectDescription: string;
  metadataSummary: string;
  metadataTermsOfService: string;
  metadataContactName: string;
  metadataContactUrl: string;
  metadataContactEmail: string;
  metadataLicenseName: string;
  metadataLicenseIdentifier: string;
  metadataLicenseUrl: string;
};

function str(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'string') return v.trim();
  if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  return '';
}

function parseRoot(content: string, path: string): { root: Record<string, unknown> } | { error: string } {
  const t = content.trim();
  if (!t) return { error: 'Empty file' };
  const lowerPath = path.toLowerCase();
  const preferJson = lowerPath.endsWith('.json') || lowerPath.endsWith('.avsc');
  if (preferJson && (t.startsWith('{') || t.startsWith('['))) {
    try {
      const root = JSON.parse(t) as unknown;
      if (root && typeof root === 'object' && !Array.isArray(root)) {
        return { root: root as Record<string, unknown> };
      }
      return { error: 'Expected a JSON object at the root' };
    } catch (e) {
      return { error: e instanceof Error ? e.message : 'Invalid JSON' };
    }
  }
  if (t.startsWith('{') || t.startsWith('[')) {
    try {
      const root = JSON.parse(t) as unknown;
      if (root && typeof root === 'object' && !Array.isArray(root)) {
        return { root: root as Record<string, unknown> };
      }
    } catch {
      /* YAML */
    }
  }
  try {
    const root = YAML.parse(t);
    if (root && typeof root === 'object' && !Array.isArray(root)) {
      return { root: root as Record<string, unknown> };
    }
    return { error: 'Expected a YAML mapping at the root' };
  } catch (e) {
    return { error: e instanceof Error ? e.message : 'Invalid YAML' };
  }
}

function detectFormat(root: Record<string, unknown>): RepositorySpecFormat {
  if (root.openapi != null) return 'openapi';
  const sv = root.swagger;
  if (typeof sv === 'string' && sv.trim().startsWith('2.')) return 'swagger2';
  if (typeof sv === 'number' && Number.isFinite(sv) && sv >= 2 && sv < 3) return 'swagger2';
  if (root.asyncapi != null) return 'asyncapi';
  if (root.arazzo != null) return 'arazzo';
  return 'unknown';
}

function looksLikeJsonSchemaRoot(root: Record<string, unknown>): boolean {
  if (root.$schema != null || root.$id != null || root.$defs != null || root.definitions != null) {
    return true;
  }
  const t = root.type;
  return typeof t === 'string' || (Array.isArray(t) && t.every((x) => typeof x === 'string'));
}

function looksLikeGraphqlSdl(content: string): boolean {
  const t = content.trim();
  if (!t || t.startsWith('{') || t.startsWith('[')) return false;
  return /\b(type|schema|enum|interface|input|scalar|union|directive)\b/.test(t);
}

function detectFormatForMetadata(root: Record<string, unknown>, content: string): RepositorySpecFormat {
  const fmt = detectFormat(root);
  if (fmt !== 'unknown') return fmt;
  if (looksLikeJsonSchemaRoot(root)) return 'json_schema';
  if (looksLikeGraphqlSdl(content)) return 'graphql';
  return 'unknown';
}

function specContextFromRoot(root: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of ['openapi', 'swagger', 'asyncapi', 'arazzo', '$schema', '$id'] as const) {
    if (root[key] !== undefined) out[key] = root[key];
  }
  return out;
}

export type RepositorySpecOriginalMetadata = {
  parseError: string | null;
  format: RepositorySpecFormat;
  /** Where metadata lives in the document, e.g. `info` or root fields. */
  sectionLabel: string;
  /** Untouched metadata object from the parsed file. */
  payload: Record<string, unknown> | null;
  /** Spec dialect/version keys copied from the document root for context. */
  specContext: Record<string, unknown>;
  /** Root-level external docs when present (OpenAPI-style). */
  externalDocs: Record<string, unknown> | null;
};

/** Raw metadata block from a repository spec file for read-only reference in the import UI. */
export function extractRepositorySpecOriginalMetadata(
  content: string,
  path: string
): RepositorySpecOriginalMetadata {
  const parsed = parseRoot(content, path);
  if ('error' in parsed) {
    return {
      parseError: parsed.error,
      format: 'unknown',
      sectionLabel: '—',
      payload: null,
      specContext: {},
      externalDocs: null,
    };
  }

  const root = parsed.root;
  const fmt = detectFormatForMetadata(root, content);
  const specContext = specContextFromRoot(root);
  const externalDocs =
    root.externalDocs && typeof root.externalDocs === 'object' && !Array.isArray(root.externalDocs)
      ? (root.externalDocs as Record<string, unknown>)
      : null;

  if (fmt === 'openapi' || fmt === 'swagger2' || fmt === 'asyncapi' || fmt === 'arazzo') {
    const info =
      root.info && typeof root.info === 'object' && !Array.isArray(root.info)
        ? (root.info as Record<string, unknown>)
        : null;
    return {
      parseError: null,
      format: fmt,
      sectionLabel: 'info',
      payload: info,
      specContext,
      externalDocs,
    };
  }

  if (fmt === 'json_schema') {
    const payload: Record<string, unknown> = {};
    for (const key of [
      'title',
      'description',
      'version',
      'summary',
      'termsOfService',
      'contact',
      'license',
      'externalDocs',
      'type',
    ]) {
      if (root[key] !== undefined) payload[key] = root[key];
    }
    return {
      parseError: null,
      format: fmt,
      sectionLabel: 'root',
      payload: Object.keys(payload).length ? payload : null,
      specContext,
      externalDocs: externalDocs ?? null,
    };
  }

  return {
    parseError: null,
    format: fmt,
    sectionLabel: fmt === 'graphql' ? 'SDL' : '—',
    payload: null,
    specContext,
    externalDocs: null,
  };
}

function licenseFromOpenApi3(lic: unknown): { name: string; identifier: string; url: string } {
  if (!lic || typeof lic !== 'object' || Array.isArray(lic)) {
    return { name: '', identifier: '', url: '' };
  }
  const o = lic as Record<string, unknown>;
  return {
    name: str(o.name),
    identifier: str(o.identifier),
    url: str(o.url),
  };
}

function contactFromInfo(contact: unknown): { name: string; url: string; email: string } {
  if (!contact || typeof contact !== 'object' || Array.isArray(contact)) {
    return { name: '', url: '', email: '' };
  }
  const o = contact as Record<string, unknown>;
  return {
    name: str(o.name),
    url: str(o.url),
    email: str(o.email),
  };
}

/**
 * Pull OpenAPI-style `info` fields into the same shape as the Create Project manual form.
 * Returns null if the document does not have a usable info block for this flow.
 */
export function projectDraftFromRepositorySpec(
  content: string,
  path: string
): { ok: true; draft: RepositorySpecProjectDraft; format: RepositorySpecFormat } | { ok: false; reason: string } {
  const parsed = parseRoot(content, path);
  if ('error' in parsed) return { ok: false, reason: parsed.error };

  const fmt = detectFormat(parsed.root);
  if (
    fmt !== 'openapi' &&
    fmt !== 'swagger2' &&
    fmt !== 'asyncapi' &&
    fmt !== 'arazzo'
  ) {
    return {
      ok: false,
      reason:
        'This file does not expose an OpenAPI-, Swagger-, AsyncAPI-, or Arazzo-style info block to copy from. Fill the form manually or pick another spec.',
    };
  }

  const info = parsed.root.info && typeof parsed.root.info === 'object' && !Array.isArray(parsed.root.info)
    ? (parsed.root.info as Record<string, unknown>)
    : {};

  const title = str(info.title) || str(info.summary);
  const description = str(info.description);

  let terms = str(info.termsOfService);
  const contact = contactFromInfo(info.contact);

  let licName = '';
  let licId = '';
  let licUrl = '';
  const licRaw = info.license;
  if (fmt === 'swagger2') {
    if (typeof licRaw === 'string') {
      licName = licRaw;
    } else if (licRaw && typeof licRaw === 'object' && !Array.isArray(licRaw)) {
      const o = licRaw as Record<string, unknown>;
      licName = str(o.name);
      licUrl = str(o.url);
    }
  } else {
    const L = licenseFromOpenApi3(licRaw);
    licName = L.name;
    licId = L.identifier;
    licUrl = L.url;
  }

  const externalDocs = parsed.root.externalDocs;
  if (!terms && externalDocs && typeof externalDocs === 'object' && !Array.isArray(externalDocs)) {
    const desc = str((externalDocs as Record<string, unknown>).description).toLowerCase();
    if (desc.includes('terms')) {
      terms = str((externalDocs as Record<string, unknown>).url);
    }
  }

  if (!title && !description && !contact.name && !licName && !licId) {
    return {
      ok: false,
      reason: 'No title, description, contact, or license was found in the spec info to copy.',
    };
  }

  const slugBase = title || path.split('/').pop()?.replace(/\.(ya?ml|json)$/i, '') || 'project';
  const slug = slugBase
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 50);

  const draft: RepositorySpecProjectDraft = {
    projectName: title || 'Imported API',
    projectSlug: slug || 'project',
    projectDescription: description,
    metadataSummary: description ? description.slice(0, 500) : title,
    metadataTermsOfService: terms,
    metadataContactName: contact.name,
    metadataContactUrl: contact.url,
    metadataContactEmail: contact.email,
    metadataLicenseName: licName,
    metadataLicenseIdentifier: licId,
    metadataLicenseUrl: licUrl,
  };

  return { ok: true, draft, format: fmt };
}
