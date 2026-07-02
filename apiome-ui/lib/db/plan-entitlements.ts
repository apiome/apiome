'use server';

const connectionPool = require('./db');
import { entitlementLimitsFromLicenseSeats } from './entitlement-limits-from-license-seats';

export type UserEntitlementRow = {
  plan_code: string;
  max_tenants: number;
  max_projects: number;
  max_versions: number;
};

/** Minimal query interface satisfied by both the global pool and a transaction client. */
type Queryable = { query: (text: string, params?: any[]) => Promise<any> };

async function getEntitlements(userId: string, client?: Queryable): Promise<UserEntitlementRow | null> {
  const db = client ?? connectionPool;
  const result = await db.query(
    `SELECT
       ue.plan_code,
       ue.max_tenants,
       ue.max_projects,
       ue.max_versions,
       ue.license_id,
       l.seats AS license_seats
     FROM apiome.user_entitlements ue
     LEFT JOIN apiome.licenses l ON l.id = ue.license_id
     WHERE ue.user_id = $1`,
    [userId]
  );
  if (result.rowCount === 0) return null;
  const row = result.rows[0] as {
    plan_code: string;
    max_tenants: number;
    max_projects: number;
    max_versions: number;
    license_id: string | null;
    license_seats: unknown;
  };

  // When a catalog license is assigned, quotas live on `licenses.seats` (JSONB). The mirrored
  // columns on `user_entitlements` can lag; always prefer the joined license row for enforcement.
  if (row.license_id != null && row.license_seats != null) {
    const lim = entitlementLimitsFromLicenseSeats(row.license_seats);
    return {
      plan_code: row.plan_code,
      max_tenants: lim.max_tenants,
      max_projects: lim.max_projects,
      max_versions: lim.max_versions,
    };
  }

  return {
    plan_code: row.plan_code,
    max_tenants: row.max_tenants,
    max_projects: row.max_projects,
    max_versions: row.max_versions,
  };
}

async function countProjectsForUser(userId: string, client?: Queryable): Promise<number> {
  const db = client ?? connectionPool;
  const result = await db.query(
    `SELECT COUNT(DISTINCT p.id)::int AS c
     FROM apiome.projects p
     INNER JOIN apiome.tenant_users tu ON tu.tenant_id = p.tenant_id AND tu.user_id = $1
     WHERE p.deleted_at IS NULL`,
    [userId]
  );
  return result.rows[0]?.c ?? 0;
}

async function countVersionsForUser(userId: string, client?: Queryable): Promise<number> {
  const db = client ?? connectionPool;
  const result = await db.query(
    `SELECT COUNT(DISTINCT v.id)::int AS c
     FROM apiome.versions v
     INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
     INNER JOIN apiome.tenant_users tu ON tu.tenant_id = p.tenant_id AND tu.user_id = $1
     WHERE v.deleted_at IS NULL`,
    [userId]
  );
  return result.rows[0]?.c ?? 0;
}

/** Returns an error message if another project would exceed the plan, otherwise null. */
export async function getPlanBlockMessageForNewProject(userId: string, client?: Queryable): Promise<string | null> {
  const ent = await getEntitlements(userId, client);
  if (!ent) return null;
  if (ent.max_projects < 0) return null;
  const n = await countProjectsForUser(userId, client);
  if (n >= ent.max_projects) {
    return `Your ${ent.plan_code} plan allows up to ${ent.max_projects} project(s). Upgrade or remove a project to add another.`;
  }
  return null;
}

/** Returns an error message if another version would exceed the plan, otherwise null. */
export async function getPlanBlockMessageForNewVersion(userId: string, client?: Queryable): Promise<string | null> {
  const ent = await getEntitlements(userId, client);
  if (!ent) return null;
  if (ent.max_versions < 0) return null;
  const n = await countVersionsForUser(userId, client);
  if (n >= ent.max_versions) {
    return `Your ${ent.plan_code} plan allows up to ${ent.max_versions} version(s). Upgrade or remove a version to add another.`;
  }
  return null;
}
