'use server';

/**
 * Helper functions for version server definitions (OpenAPI servers array).
 * Section 4.3: Multiple servers, variables (enum), environment (dev/staging/prod), description, relative paths.
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

/** OpenAPI Server Variable: default, optional enum, optional description */
export interface ServerVariable {
  default: string;
  enum?: string[];
  description?: string;
}

export interface VersionServerRecord {
  id: string;
  version_id: string;
  name: string | null;
  url: string;
  description: string | null;
  sort_order: number;
  /** OpenAPI Server variables: { varName: { default, enum?, description? } } */
  variables: Record<string, ServerVariable> | null;
  /** Environment label: dev, staging, prod */
  environment: string | null;
  created_at: string;
  updated_at: string;
}

export interface VersionServerInput {
  name?: string;
  url: string;
  description?: string;
  sort_order?: number;
  variables?: Record<string, ServerVariable> | null;
  environment?: string | null;
}

/**
 * Get all servers for a version (ordered by sort_order, url)
 */
export async function getServersForVersion(versionId: string): Promise<VersionServerRecord[]> {
  const result = await connectionPool.query(
    `SELECT id, version_id, name, url, description, sort_order, variables, environment, created_at, updated_at
     FROM apiome.version_server
     WHERE version_id = $1
     ORDER BY sort_order, url`,
    [versionId]
  );
  return result.rows.map((r: Record<string, unknown>) => ({
    id: r.id,
    version_id: r.version_id,
    name: r.name,
    url: r.url,
    description: r.description,
    sort_order: Number(r.sort_order) || 0,
    variables: r.variables ? (typeof r.variables === 'string' ? JSON.parse(r.variables as string) : r.variables) : null,
    environment: r.environment,
    created_at: r.created_at,
    updated_at: r.updated_at,
  }));
}

/**
 * Create a server for a version
 */
export async function createServer(
  versionId: string,
  input: VersionServerInput
): Promise<{ success: boolean; server?: VersionServerRecord; error?: string }> {
  try {
    const sortOrder = input.sort_order ?? 0;
    const variablesJson = input.variables && Object.keys(input.variables).length > 0
      ? JSON.stringify(input.variables)
      : null;
    const environmentVal = input.environment?.trim() || null;
    const result = await connectionPool.query(
      `INSERT INTO apiome.version_server (version_id, name, url, description, sort_order, variables, environment)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       RETURNING id, version_id, name, url, description, sort_order, variables, environment, created_at, updated_at`,
      [
        versionId,
        input.name?.trim() || null,
        input.url.trim(),
        input.description?.trim() || null,
        sortOrder,
        variablesJson,
        environmentVal,
      ]
    );
    const row = result.rows[0];
    return {
      success: true,
      server: rowToServerRecord(row),
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

function rowToServerRecord(row: Record<string, unknown>): VersionServerRecord {
  return {
    id: row.id as string,
    version_id: row.version_id as string,
    name: row.name as string | null,
    url: row.url as string,
    description: row.description as string | null,
    sort_order: Number(row.sort_order) || 0,
    variables: row.variables ? (typeof row.variables === 'string' ? JSON.parse(row.variables as string) : row.variables) as Record<string, ServerVariable> : null,
    environment: row.environment as string | null,
    created_at: row.created_at as string,
    updated_at: row.updated_at as string,
  };
}

/**
 * Update a server
 */
export async function updateServer(
  serverId: string,
  input: Partial<VersionServerInput>
): Promise<{ success: boolean; server?: VersionServerRecord; error?: string }> {
  try {
    const updates: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (input.name !== undefined) {
      updates.push(`name = $${idx++}`);
      values.push(input.name.trim() || null);
    }
    if (input.url !== undefined) {
      updates.push(`url = $${idx++}`);
      values.push(input.url.trim());
    }
    if (input.description !== undefined) {
      updates.push(`description = $${idx++}`);
      values.push(input.description.trim() || null);
    }
    if (input.sort_order !== undefined) {
      updates.push(`sort_order = $${idx++}`);
      values.push(input.sort_order);
    }
    if (input.variables !== undefined) {
      updates.push(`variables = $${idx++}`);
      values.push(input.variables && Object.keys(input.variables).length > 0 ? JSON.stringify(input.variables) : null);
    }
    if (input.environment !== undefined) {
      updates.push(`environment = $${idx++}`);
      values.push(input.environment?.trim() || null);
    }
    if (updates.length === 0) {
      return { success: false, error: 'No fields to update' };
    }
    updates.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(serverId);

    const result = await connectionPool.query(
      `UPDATE apiome.version_server SET ${updates.join(', ')} WHERE id = $${idx} RETURNING id, version_id, name, url, description, sort_order, variables, environment, created_at, updated_at`,
      values
    );
    if (result.rows.length === 0) {
      return { success: false, error: 'Server not found' };
    }
    const row = result.rows[0];
    return {
      success: true,
      server: rowToServerRecord(row),
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/**
 * Delete a server
 */
export async function deleteServer(serverId: string): Promise<{ success: boolean; error?: string }> {
  try {
    const result = await connectionPool.query('DELETE FROM apiome.version_server WHERE id = $1 RETURNING id', [serverId]);
    return { success: result.rowCount > 0 };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    return { success: false, error: msg };
  }
}

/** OpenAPI Server object: url, description?, variables? */
export type OpenAPIServerObject = {
  url: string;
  description?: string;
  variables?: Record<string, { default: string; enum?: string[]; description?: string }>;
};

/**
 * Convert version servers to OpenAPI servers array (url, description, variables).
 * Async to satisfy Server Action requirement ('use server').
 */
export async function serversToOpenAPI(servers: VersionServerRecord[]): Promise<OpenAPIServerObject[]> {
  return servers
    .filter((s) => s.url?.trim())
    .map((s) => {
      const obj: OpenAPIServerObject = { url: s.url.trim() };
      if (s.description?.trim()) obj.description = s.description.trim();
      if (s.variables && Object.keys(s.variables).length > 0) obj.variables = s.variables;
      return obj;
    });
}
