'use server';

const connectionPool = require('./db');

export type UserEntitlementRow = {
  plan_code: string;
  max_tenants: number;
  max_projects: number;
  max_versions: number;
};

async function getEntitlements(userId: string): Promise<UserEntitlementRow | null> {
  const result = await connectionPool.query(
    `SELECT plan_code, max_tenants, max_projects, max_versions
     FROM odb.user_entitlements WHERE user_id = $1`,
    [userId]
  );
  if (result.rowCount === 0) return null;
  return result.rows[0];
}

async function countProjectsForUser(userId: string): Promise<number> {
  const result = await connectionPool.query(
    `SELECT COUNT(DISTINCT p.id)::int AS c
     FROM odb.projects p
     INNER JOIN odb.tenant_users tu ON tu.tenant_id = p.tenant_id AND tu.user_id = $1
     WHERE p.deleted_at IS NULL`,
    [userId]
  );
  return result.rows[0]?.c ?? 0;
}

async function countVersionsForUser(userId: string): Promise<number> {
  const result = await connectionPool.query(
    `SELECT COUNT(DISTINCT v.id)::int AS c
     FROM odb.versions v
     INNER JOIN odb.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
     INNER JOIN odb.tenant_users tu ON tu.tenant_id = p.tenant_id AND tu.user_id = $1
     WHERE v.deleted_at IS NULL`,
    [userId]
  );
  return result.rows[0]?.c ?? 0;
}

/** Returns an error message if another project would exceed the plan, otherwise null. */
export async function getPlanBlockMessageForNewProject(userId: string): Promise<string | null> {
  const ent = await getEntitlements(userId);
  if (!ent) return null;
  const n = await countProjectsForUser(userId);
  if (n >= ent.max_projects) {
    return `Your ${ent.plan_code} plan allows up to ${ent.max_projects} project(s). Upgrade or remove a project to add another.`;
  }
  return null;
}

/** Returns an error message if another version would exceed the plan, otherwise null. */
export async function getPlanBlockMessageForNewVersion(userId: string): Promise<string | null> {
  const ent = await getEntitlements(userId);
  if (!ent) return null;
  const n = await countVersionsForUser(userId);
  if (n >= ent.max_versions) {
    return `Your ${ent.plan_code} plan allows up to ${ent.max_versions} version(s). Upgrade or remove a version to add another.`;
  }
  return null;
}
