'use server';

/**
 * Helper functions for version security schemes (OpenAPI components.securitySchemes)
 * Supports API Key (header, query, cookie) and future scheme types.
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

export interface SecuritySchemeRecord {
  id: string;
  version_id: string;
  scheme_name: string;
  scheme_type: string;
  in_location: string | null;
  param_name: string | null;
  http_scheme: string | null;
  description: string | null;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** OpenAPI API Key scheme: in header, query, or cookie */
export interface ApiKeySchemeInput {
  scheme_name: string;
  in_location: 'header' | 'query' | 'cookie';
  param_name: string;
  description?: string;
}

/** OpenAPI HTTP scheme: basic, bearer, or custom (e.g. Digest) */
export interface HttpSchemeInput {
  scheme_name: string;
  http_scheme: 'basic' | 'bearer' | string; // 'basic' | 'bearer' | custom (e.g. 'Digest', 'HOBA')
  bearer_format?: string; // e.g. 'JWT' for bearer
  description?: string;
}

/** OAuth2 flow types (OpenAPI 3.1) */
export type OAuth2FlowType = 'authorizationCode' | 'implicit' | 'clientCredentials' | 'password';

/** Single OAuth2 flow config: URLs and scopes (scope name -> description) */
export interface OAuth2FlowConfig {
  authorizationUrl?: string;
  tokenUrl?: string;
  refreshUrl?: string;
  scopes: Record<string, string>;
}

/** OpenAPI OAuth2 scheme: flows object stored in data */
export interface OAuth2SchemeInput {
  scheme_name: string;
  description?: string;
  flows: {
    authorizationCode?: OAuth2FlowConfig;
    implicit?: OAuth2FlowConfig;
    clientCredentials?: OAuth2FlowConfig;
    password?: OAuth2FlowConfig;
  };
}

/** OpenAPI OpenID Connect scheme: discovery URL and optional scopes (scopes used in security requirements) */
export interface OpenIdConnectSchemeInput {
  scheme_name: string;
  open_id_connect_url: string;
  description?: string;
  scopes?: string[];
}

/** OpenAPI Mutual TLS scheme: certificate-based authentication (type + optional description only in spec) */
export interface MutualTlsSchemeInput {
  scheme_name: string;
  description?: string;
}

/** Custom security scheme: type string (e.g. apiKey or x-custom-auth) + description + additional properties for export */
export interface CustomSchemeInput {
  scheme_name: string;
  type: string;
  description?: string;
  additional_properties?: Record<string, string>;
}

/** OpenAPI security scheme definition for export */
export interface OpenAPISecurityScheme {
  type: 'apiKey' | 'http' | 'oauth2' | 'openIdConnect' | 'mutualTLS';
  name?: string;
  in?: 'header' | 'query' | 'cookie';
  scheme?: string;
  bearerFormat?: string;
  openIdConnectUrl?: string;
  description?: string;
  [key: string]: unknown;
}

/**
 * Get all security schemes for a version
 */
export async function getSecuritySchemesForVersion(versionId: string): Promise<SecuritySchemeRecord[]> {
  const result = await connectionPool.query(
    `SELECT id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at
     FROM apiome.version_security_scheme
     WHERE version_id = $1
     ORDER BY scheme_name`,
    [versionId]
  );
  return result.rows.map((r: Record<string, unknown>) => ({
    id: r.id,
    version_id: r.version_id,
    scheme_name: r.scheme_name,
    scheme_type: r.scheme_type,
    in_location: r.in_location,
    param_name: r.param_name,
    http_scheme: r.http_scheme,
    description: r.description,
    data: r.data ? (typeof r.data === 'string' ? JSON.parse(r.data as string) : r.data) : {},
    created_at: r.created_at,
    updated_at: r.updated_at,
  }));
}

/**
 * Create an API Key security scheme (header, query, or cookie)
 */
export async function createApiKeySecurityScheme(
  versionId: string,
  input: ApiKeySchemeInput
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const result = await connectionPool.query(
      `INSERT INTO apiome.version_security_scheme (version_id, scheme_name, scheme_type, in_location, param_name, description)
       VALUES ($1, $2, 'apiKey', $3, $4, $5)
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      [
        versionId,
        input.scheme_name.trim(),
        input.in_location,
        input.param_name.trim(),
        input.description?.trim() || null,
      ]
    );
    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data || {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Update an API Key security scheme
 */
export async function updateApiKeySecurityScheme(
  schemeId: string,
  input: Partial<ApiKeySchemeInput>
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const updates: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (input.scheme_name !== undefined) {
      updates.push(`scheme_name = $${idx++}`);
      values.push(input.scheme_name.trim());
    }
    if (input.in_location !== undefined) {
      updates.push(`in_location = $${idx++}`);
      values.push(input.in_location);
    }
    if (input.param_name !== undefined) {
      updates.push(`param_name = $${idx++}`);
      values.push(input.param_name.trim());
    }
    if (input.description !== undefined) {
      updates.push(`description = $${idx++}`);
      values.push(input.description.trim() || null);
    }

    if (updates.length === 0) {
      return { success: false, error: 'No updates provided' };
    }

    updates.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(schemeId);

    const result = await connectionPool.query(
      `UPDATE apiome.version_security_scheme SET ${updates.join(', ')}
       WHERE id = $${idx} AND scheme_type = 'apiKey'
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      values
    );

    if (result.rows.length === 0) {
      return { success: false, error: 'Scheme not found or not an API Key scheme' };
    }

    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data || {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Create an HTTP security scheme (basic, bearer, or custom)
 */
export async function createHttpSecurityScheme(
  versionId: string,
  input: HttpSchemeInput
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const raw = input.http_scheme.trim();
    const schemeValue = raw.toLowerCase() === 'basic' || raw.toLowerCase() === 'bearer' ? raw.toLowerCase() : raw;
    const data =
      schemeValue === 'bearer' && input.bearer_format
        ? JSON.stringify({ bearerFormat: input.bearer_format.trim() })
        : '{}';
    const result = await connectionPool.query(
      `INSERT INTO apiome.version_security_scheme (version_id, scheme_name, scheme_type, http_scheme, description, data)
       VALUES ($1, $2, 'http', $3, $4, $5::jsonb)
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      [
        versionId,
        input.scheme_name.trim(),
        schemeValue,
        input.description?.trim() || null,
        data,
      ]
    );
    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Update an HTTP security scheme
 */
export async function updateHttpSecurityScheme(
  schemeId: string,
  input: Partial<HttpSchemeInput>
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const updates: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (input.scheme_name !== undefined) {
      updates.push(`scheme_name = $${idx++}`);
      values.push(input.scheme_name.trim());
    }
    if (input.http_scheme !== undefined) {
      const raw = input.http_scheme.trim();
      const schemeValue = raw.toLowerCase() === 'basic' || raw.toLowerCase() === 'bearer' ? raw.toLowerCase() : raw;
      updates.push(`http_scheme = $${idx++}`);
      values.push(schemeValue);
    }
    if (input.description !== undefined) {
      updates.push(`description = $${idx++}`);
      values.push(input.description.trim() || null);
    }
    if (input.bearer_format !== undefined) {
      const schemeVal = (input.http_scheme ?? '').toString().trim().toLowerCase();
      const data = schemeVal === 'bearer' ? JSON.stringify({ bearerFormat: input.bearer_format.trim() }) : '{}';
      updates.push(`data = $${idx++}::jsonb`);
      values.push(data);
    }

    if (updates.length === 0) {
      return { success: false, error: 'No updates provided' };
    }

    updates.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(schemeId);

    const result = await connectionPool.query(
      `UPDATE apiome.version_security_scheme SET ${updates.join(', ')}
       WHERE id = $${idx} AND scheme_type = 'http'
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      values
    );

    if (result.rows.length === 0) {
      return { success: false, error: 'Scheme not found or not an HTTP scheme' };
    }

    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Build OAuth2 flows object for OpenAPI (only include non-empty flows with required fields)
 */
function buildOAuth2FlowsForStorage(flows: OAuth2SchemeInput['flows']): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (flows.authorizationCode?.authorizationUrl && flows.authorizationCode?.tokenUrl) {
    out.authorizationCode = {
      authorizationUrl: flows.authorizationCode.authorizationUrl.trim(),
      tokenUrl: flows.authorizationCode.tokenUrl.trim(),
      ...(flows.authorizationCode.refreshUrl?.trim() && { refreshUrl: flows.authorizationCode.refreshUrl.trim() }),
      scopes: flows.authorizationCode.scopes && typeof flows.authorizationCode.scopes === 'object' ? flows.authorizationCode.scopes : {},
    };
  }
  if (flows.implicit?.authorizationUrl) {
    out.implicit = {
      authorizationUrl: flows.implicit.authorizationUrl.trim(),
      ...(flows.implicit.refreshUrl?.trim() && { refreshUrl: flows.implicit.refreshUrl.trim() }),
      scopes: flows.implicit.scopes && typeof flows.implicit.scopes === 'object' ? flows.implicit.scopes : {},
    };
  }
  if (flows.clientCredentials?.tokenUrl) {
    out.clientCredentials = {
      tokenUrl: flows.clientCredentials.tokenUrl.trim(),
      ...(flows.clientCredentials.refreshUrl?.trim() && { refreshUrl: flows.clientCredentials.refreshUrl.trim() }),
      scopes: flows.clientCredentials.scopes && typeof flows.clientCredentials.scopes === 'object' ? flows.clientCredentials.scopes : {},
    };
  }
  if (flows.password?.tokenUrl) {
    out.password = {
      tokenUrl: flows.password.tokenUrl.trim(),
      ...(flows.password.refreshUrl?.trim() && { refreshUrl: flows.password.refreshUrl.trim() }),
      scopes: flows.password.scopes && typeof flows.password.scopes === 'object' ? flows.password.scopes : {},
    };
  }
  return out;
}

/**
 * Create an OAuth2 security scheme (Authorization Code, Implicit, Client Credentials, Password flows)
 */
export async function createOAuth2SecurityScheme(
  versionId: string,
  input: OAuth2SchemeInput
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const flowsData = buildOAuth2FlowsForStorage(input.flows);
    if (Object.keys(flowsData).length === 0) {
      return { success: false, error: 'At least one OAuth2 flow with required URLs must be defined.' };
    }
    const dataJson = JSON.stringify({ flows: flowsData });
    const result = await connectionPool.query(
      `INSERT INTO apiome.version_security_scheme (version_id, scheme_name, scheme_type, description, data)
       VALUES ($1, $2, 'oauth2', $3, $4::jsonb)
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      [versionId, input.scheme_name.trim(), input.description?.trim() || null, dataJson]
    );
    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Update an OAuth2 security scheme
 */
export async function updateOAuth2SecurityScheme(
  schemeId: string,
  input: Partial<OAuth2SchemeInput>
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const updates: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (input.scheme_name !== undefined) {
      updates.push(`scheme_name = $${idx++}`);
      values.push(input.scheme_name.trim());
    }
    if (input.description !== undefined) {
      updates.push(`description = $${idx++}`);
      values.push(input.description.trim() || null);
    }
    if (input.flows !== undefined) {
      const flowsData = buildOAuth2FlowsForStorage(input.flows);
      if (Object.keys(flowsData).length === 0) {
        return { success: false, error: 'At least one OAuth2 flow with required URLs must be defined.' };
      }
      updates.push(`data = $${idx++}::jsonb`);
      values.push(JSON.stringify({ flows: flowsData }));
    }

    if (updates.length === 0) {
      return { success: false, error: 'No updates provided' };
    }

    updates.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(schemeId);

    const result = await connectionPool.query(
      `UPDATE apiome.version_security_scheme SET ${updates.join(', ')}
       WHERE id = $${idx} AND scheme_type = 'oauth2'
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      values
    );

    if (result.rows.length === 0) {
      return { success: false, error: 'Scheme not found or not an OAuth2 scheme' };
    }

    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Create an OpenID Connect security scheme (discovery URL with optional scopes)
 */
export async function createOpenIdConnectSecurityScheme(
  versionId: string,
  input: OpenIdConnectSchemeInput
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const url = input.open_id_connect_url.trim();
    if (!url) {
      return { success: false, error: 'OpenID Connect discovery URL is required.' };
    }
    const data: Record<string, unknown> = { openIdConnectUrl: url };
    if (input.scopes && Array.isArray(input.scopes) && input.scopes.length > 0) {
      data.scopes = input.scopes.filter((s) => typeof s === 'string' && s.trim()).map((s) => s.trim());
    }
    const dataJson = JSON.stringify(data);
    const result = await connectionPool.query(
      `INSERT INTO apiome.version_security_scheme (version_id, scheme_name, scheme_type, description, data)
       VALUES ($1, $2, 'openIdConnect', $3, $4::jsonb)
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      [versionId, input.scheme_name.trim(), input.description?.trim() || null, dataJson]
    );
    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Update an OpenID Connect security scheme
 */
export async function updateOpenIdConnectSecurityScheme(
  schemeId: string,
  input: Partial<OpenIdConnectSchemeInput>
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const updates: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (input.scheme_name !== undefined) {
      updates.push(`scheme_name = $${idx++}`);
      values.push(input.scheme_name.trim());
    }
    if (input.description !== undefined) {
      updates.push(`description = $${idx++}`);
      values.push(input.description.trim() || null);
    }
    if (input.open_id_connect_url !== undefined) {
      const url = input.open_id_connect_url.trim();
      if (!url) {
        return { success: false, error: 'OpenID Connect discovery URL is required.' };
      }
      updates.push(`data = COALESCE(data, '{}'::jsonb) || jsonb_build_object('openIdConnectUrl', $${idx++}::text)`);
      values.push(url);
    }
    if (input.scopes !== undefined) {
      const scopes = Array.isArray(input.scopes)
        ? input.scopes.filter((s) => typeof s === 'string' && s.trim()).map((s) => (s as string).trim())
        : [];
      updates.push(`data = COALESCE(data, '{}'::jsonb) || jsonb_build_object('scopes', $${idx++}::jsonb)`);
      values.push(JSON.stringify(scopes));
    }

    if (updates.length === 0) {
      return { success: false, error: 'No updates provided' };
    }

    updates.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(schemeId);

    const result = await connectionPool.query(
      `UPDATE apiome.version_security_scheme SET ${updates.join(', ')}
       WHERE id = $${idx} AND scheme_type = 'openIdConnect'
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      values
    );

    if (result.rows.length === 0) {
      return { success: false, error: 'Scheme not found or not an OpenID Connect scheme' };
    }

    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Create a Mutual TLS security scheme (certificate-based authentication)
 */
export async function createMutualTlsSecurityScheme(
  versionId: string,
  input: MutualTlsSchemeInput
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const name = input.scheme_name.trim();
    if (!name) {
      return { success: false, error: 'Scheme name is required.' };
    }
    const result = await connectionPool.query(
      `INSERT INTO apiome.version_security_scheme (version_id, scheme_name, scheme_type, description, data)
       VALUES ($1, $2, 'mutualTLS', $3, '{}'::jsonb)
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      [versionId, name, input.description?.trim() || null]
    );
    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Update a Mutual TLS security scheme
 */
export async function updateMutualTlsSecurityScheme(
  schemeId: string,
  input: Partial<MutualTlsSchemeInput>
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const updates: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (input.scheme_name !== undefined) {
      const name = input.scheme_name.trim();
      if (!name) {
        return { success: false, error: 'Scheme name is required.' };
      }
      updates.push(`scheme_name = $${idx++}`);
      values.push(name);
    }
    if (input.description !== undefined) {
      updates.push(`description = $${idx++}`);
      values.push(input.description.trim() || null);
    }

    if (updates.length === 0) {
      return { success: false, error: 'No updates provided' };
    }

    updates.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(schemeId);

    const result = await connectionPool.query(
      `UPDATE apiome.version_security_scheme SET ${updates.join(', ')}
       WHERE id = $${idx} AND scheme_type = 'mutualTLS'
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      values
    );

    if (result.rows.length === 0) {
      return { success: false, error: 'Scheme not found or not a Mutual TLS scheme' };
    }

    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Create a custom security scheme (type + description + additional properties for export)
 */
export async function createCustomSecurityScheme(
  versionId: string,
  input: CustomSchemeInput
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const name = input.scheme_name.trim();
    if (!name) {
      return { success: false, error: 'Scheme name is required.' };
    }
    const typeVal = input.type?.trim() || 'apiKey';
    const data: Record<string, unknown> = { type: typeVal };
    if (input.description?.trim()) data.description = input.description.trim();
    if (input.additional_properties && typeof input.additional_properties === 'object') {
      for (const [k, v] of Object.entries(input.additional_properties)) {
        const key = k.trim();
        if (key && v !== undefined && v !== null) data[key] = String(v).trim();
      }
    }
    const dataJson = JSON.stringify(data);
    const result = await connectionPool.query(
      `INSERT INTO apiome.version_security_scheme (version_id, scheme_name, scheme_type, description, data)
       VALUES ($1, $2, 'custom', $3, $4::jsonb)
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      [versionId, name, input.description?.trim() || null, dataJson]
    );
    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Update a custom security scheme
 */
export async function updateCustomSecurityScheme(
  schemeId: string,
  input: Partial<CustomSchemeInput>
): Promise<{ success: boolean; scheme?: SecuritySchemeRecord; error?: string }> {
  try {
    const updates: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (input.scheme_name !== undefined) {
      const name = input.scheme_name.trim();
      if (!name) {
        return { success: false, error: 'Scheme name is required.' };
      }
      updates.push(`scheme_name = $${idx++}`);
      values.push(name);
    }
    if (input.description !== undefined) {
      updates.push(`description = $${idx++}`);
      values.push(input.description.trim() || null);
    }
    if (input.type !== undefined || input.additional_properties !== undefined) {
      const data: Record<string, unknown> = {};
      if (input.type !== undefined) data.type = input.type.trim() || 'apiKey';
      if (input.description !== undefined) data.description = input.description.trim();
      if (input.additional_properties && typeof input.additional_properties === 'object') {
        for (const [k, v] of Object.entries(input.additional_properties)) {
          const key = k.trim();
          if (key && v !== undefined && v !== null) data[key] = String(v).trim();
        }
      }
      updates.push(`data = $${idx++}::jsonb`);
      values.push(JSON.stringify(data));
    }

    if (updates.length === 0) {
      return { success: false, error: 'No updates provided' };
    }

    updates.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(schemeId);

    const result = await connectionPool.query(
      `UPDATE apiome.version_security_scheme SET ${updates.join(', ')}
       WHERE id = $${idx} AND scheme_type = 'custom'
       RETURNING id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data, created_at, updated_at`,
      values
    );

    if (result.rows.length === 0) {
      return { success: false, error: 'Scheme not found or not a custom scheme' };
    }

    const row = result.rows[0];
    return {
      success: true,
      scheme: {
        id: row.id,
        version_id: row.version_id,
        scheme_name: row.scheme_name,
        scheme_type: row.scheme_type,
        in_location: row.in_location,
        param_name: row.param_name,
        http_scheme: row.http_scheme,
        description: row.description,
        data: row.data ? (typeof row.data === 'string' ? JSON.parse(row.data) : row.data) : {},
        created_at: row.created_at,
        updated_at: row.updated_at,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Delete a security scheme
 */
export async function deleteSecurityScheme(schemeId: string): Promise<{ success: boolean; error?: string }> {
  try {
    const result = await connectionPool.query(
      `DELETE FROM apiome.version_security_scheme WHERE id = $1 RETURNING id`,
      [schemeId]
    );
    return { success: result.rows.length > 0 };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Convert security scheme records to OpenAPI components.securitySchemes format
 */
export async function securitySchemesToOpenAPI(schemes: SecuritySchemeRecord[]): Promise<Record<string, OpenAPISecurityScheme>> {
  const result: Record<string, OpenAPISecurityScheme> = {};
  for (const s of schemes) {
    if (s.scheme_type === 'apiKey') {
      result[s.scheme_name] = {
        type: 'apiKey',
        name: s.param_name || s.scheme_name,
        in: (s.in_location as 'header' | 'query' | 'cookie') || 'header',
        description: s.description || undefined,
      };
    } else if (s.scheme_type === 'http' && s.http_scheme) {
      const httpScheme: OpenAPISecurityScheme = {
        type: 'http',
        scheme: s.http_scheme,
        description: s.description || undefined,
      };
      const bearerFormat = (s.data as { bearerFormat?: string })?.bearerFormat;
      if (bearerFormat) httpScheme.bearerFormat = bearerFormat;
      result[s.scheme_name] = httpScheme;
    } else if (s.scheme_type === 'oauth2') {
      const flows = (s.data as { flows?: Record<string, unknown> })?.flows;
      if (flows && typeof flows === 'object' && Object.keys(flows).length > 0) {
        result[s.scheme_name] = {
          type: 'oauth2',
          flows,
          description: s.description || undefined,
        };
      }
    } else if (s.scheme_type === 'openIdConnect') {
      const url = (s.data as { openIdConnectUrl?: string })?.openIdConnectUrl;
      if (url && typeof url === 'string' && url.trim()) {
        result[s.scheme_name] = {
          type: 'openIdConnect',
          openIdConnectUrl: url.trim(),
          description: s.description || undefined,
        };
      }
    } else if (s.scheme_type === 'mutualTLS') {
      result[s.scheme_name] = {
        type: 'mutualTLS',
        description: s.description || undefined,
      };
    } else if (s.scheme_type === 'custom') {
      const data = s.data as Record<string, unknown>;
      const typeVal = (data?.type as string)?.trim() || 'apiKey';
      const out: Record<string, unknown> = {
        type: typeVal,
        description: s.description || (data?.description as string) || undefined,
      };
      if (data && typeof data === 'object') {
        for (const [k, v] of Object.entries(data)) {
          if (k === 'type' || k === 'description') continue;
          if (v !== undefined && v !== null) out[k] = typeof v === 'string' ? v : v;
        }
      }
      result[s.scheme_name] = out as OpenAPISecurityScheme;
    }
  }
  return result;
}
