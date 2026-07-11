/**
 * Shared client helpers for the Governance → Style Guides surfaces (GOV-2.1 / GOV-2.2).
 *
 * The list screen (`StyleGuidesClient`) and the guide editor (`GuideEditorClient`) both talk
 * to the `/api/style-guides` proxy, which forwards to the REST layer's tenant-scoped
 * `/v1/style-guides/{slug}/...` endpoints. Types mirror the REST models' camelCase
 * serialization aliases.
 */

export interface ProjectAssignment {
  projectId: string;
  projectName: string;
}

/** One tenant style guide with its list-view rollups (GOV-2.1). */
export interface StyleGuide {
  id: string;
  name: string;
  description: string | null;
  source: 'builtin' | 'custom';
  isDefault: boolean;
  ruleCount: number;
  enabledRuleCount: number;
  tenantAssigned: boolean;
  projectAssignments: ProjectAssignment[];
  createdAt: string | null;
  updatedAt: string | null;
}

export interface StyleGuideList {
  guides: StyleGuide[];
  count: number;
}

/** Severity a guide can assign a rule — matches the linter's Severity type. */
export type RuleSeverity = 'error' | 'warning' | 'info';

/** One built-in rule as the guide editor sees it: registry facts + guide state (GOV-2.2). */
export interface GuideRule {
  ruleId: string;
  pack: string;
  category: string;
  defaultSeverity: RuleSeverity;
  rationale: string;
  docsAnchor: string;
  enabled: boolean;
  severity: RuleSeverity;
}

/** The guide's full rule catalog view — `GET/PUT /api/style-guides/{id}/rules` (GOV-2.2). */
export interface GuideRulesView {
  guideId: string;
  guideName: string;
  source: 'builtin' | 'custom';
  rules: GuideRule[];
  count: number;
  enabledCount: number;
  docsPage: string;
}

/** The caller's permissions from `/api/access/permissions/me` (admin-gates mutations). */
export interface MyPermissions {
  is_admin: boolean;
  permissions: string[];
}

/**
 * Call the style-guides proxy (`/api/style-guides/...`).
 *
 * The proxy wraps REST responses as `{success, data, error}`; FastAPI error details can be
 * a string or a `{code, message}` object (read-only / name-conflict), so both are
 * normalized into the thrown Error's message.
 */
export async function styleGuidesApi<T>(path: string, init?: RequestInit): Promise<T | null> {
  const res = await fetch(`/api/style-guides${path ? `/${path}` : ''}`, init);
  if (res.status === 204) return null;
  const json = await res.json();
  if (!json.success) {
    const err = json.error;
    const message =
      typeof err === 'object' && err !== null
        ? (err as { message?: string }).message || 'Request failed'
        : err || 'Request failed';
    throw new Error(message);
  }
  return json.data as T;
}

/** Fetch the caller's permissions, degrading to `null` (read-only UI) on any failure. */
export async function fetchMyPermissions(): Promise<MyPermissions | null> {
  return fetch('/api/access/permissions/me')
    .then((r) => r.json())
    .then((j) => (j.success ? (j.data as MyPermissions) : null))
    .catch(() => null);
}
