import type pg from "pg";

import { CliError } from "../errors.js";
import { isUniqueViolation, resolveTenant, resolveUser } from "../db.js";
import { note, printRecord, printRows, type OutputMode } from "../output.js";
import { confirmDestructive, isValidSlug } from "../util.js";

export type CreateTenantInput = {
  name: string;
  slug: string;
  description?: string;
  enabled: boolean;
};

export async function createTenant(
  client: pg.Client,
  input: CreateTenantInput,
  mode: OutputMode,
): Promise<void> {
  if (!isValidSlug(input.slug)) {
    throw new CliError(`Invalid slug: ${input.slug}`, {
      hint: "Slugs are lowercase letters/digits separated by single hyphens (e.g. acme-corp).",
    });
  }
  try {
    const res = await client.query(
      `INSERT INTO apiome.tenants (name, slug, description, enabled)
       VALUES ($1, $2, $3, $4)
       RETURNING id, name, slug, enabled, created_at`,
      [input.name, input.slug, input.description ?? null, input.enabled],
    );
    printRecord(mode, res.rows[0] as Record<string, unknown>);
  } catch (err) {
    if (isUniqueViolation(err)) {
      throw new CliError(`A tenant with slug ${input.slug} already exists.`);
    }
    throw err;
  }
}

/**
 * Provision the curated sample project for a tenant, owned by `userRef`. Delegates to the shared,
 * idempotent `apiome.provision_sample_project()` routine (migration V122) — the same one used by the
 * dev seed and the UI tenant-creation paths. Reports the new project id, or that the sample was
 * already present.
 */
export async function provisionSample(
  client: pg.Client,
  tenantRef: string,
  userRef: string,
  mode: OutputMode,
): Promise<void> {
  const tenant = await resolveTenant(client, tenantRef);
  const user = await resolveUser(client, userRef);
  const res = await client.query<{ project_id: string | null }>(
    "SELECT apiome.provision_sample_project($1, $2) AS project_id",
    [tenant.id, user.id],
  );
  const projectId = res.rows[0]?.project_id ?? null;
  printRecord(mode, {
    tenant: tenant.slug,
    creator: user.email,
    project_id: projectId ?? "(already provisioned)",
  });
}

export async function listTenants(
  client: pg.Client,
  opts: { all: boolean },
  mode: OutputMode,
): Promise<void> {
  const where = opts.all ? "" : "WHERE deleted_at IS NULL";
  const res = await client.query(
    `SELECT id, slug, name, enabled, created_at, deleted_at
     FROM apiome.tenants ${where}
     ORDER BY created_at`,
  );
  printRows(mode, res.rows as Record<string, unknown>[], [
    { key: "id", label: "ID" },
    { key: "slug", label: "Slug" },
    { key: "name", label: "Name" },
    { key: "enabled", label: "Enabled" },
    { key: "created_at", label: "Created" },
  ]);
}

export async function deleteTenant(
  client: pg.Client,
  ref: string,
  opts: { hard: boolean; yes: boolean },
  mode: OutputMode,
): Promise<void> {
  const tenant = await resolveTenant(client, ref);
  const action = opts.hard ? "HARD-DELETE (permanent, cascades members & API keys)" : "soft-delete (disable)";
  const ok = await confirmDestructive(`${action} tenant ${tenant.slug} (${tenant.id})?`, opts.yes);
  if (!ok) {
    note("Aborted.");
    return;
  }
  if (opts.hard) {
    await client.query("DELETE FROM apiome.tenants WHERE id = $1", [tenant.id]);
  } else {
    await client.query(
      "UPDATE apiome.tenants SET deleted_at = CURRENT_TIMESTAMP, enabled = false, updated_at = CURRENT_TIMESTAMP WHERE id = $1",
      [tenant.id],
    );
  }
  printRecord(mode, { id: tenant.id, slug: tenant.slug, deleted: opts.hard ? "hard" : "soft" });
}

export async function addUserToTenant(
  client: pg.Client,
  tenantRef: string,
  userRef: string,
  opts: { admin: boolean },
  mode: OutputMode,
): Promise<void> {
  const tenant = await resolveTenant(client, tenantRef);
  const user = await resolveUser(client, userRef);

  const memberRes = await client.query(
    `INSERT INTO apiome.tenant_users (tenant_id, user_id)
     VALUES ($1, $2)
     ON CONFLICT (tenant_id, user_id) DO NOTHING
     RETURNING id`,
    [tenant.id, user.id],
  );
  const addedMember = (memberRes.rowCount ?? 0) > 0;

  let addedAdmin = false;
  if (opts.admin) {
    const adminRes = await client.query(
      `INSERT INTO apiome.tenant_administrators (tenant_id, user_id)
       VALUES ($1, $2)
       ON CONFLICT (tenant_id, user_id) DO NOTHING
       RETURNING id`,
      [tenant.id, user.id],
    );
    addedAdmin = (adminRes.rowCount ?? 0) > 0;
  }

  printRecord(mode, {
    tenant: tenant.slug,
    user: user.email,
    member: addedMember ? "added" : "already a member",
    admin: opts.admin ? (addedAdmin ? "added" : "already an admin") : "unchanged",
  });
}

export async function removeUserFromTenant(
  client: pg.Client,
  tenantRef: string,
  userRef: string,
  opts: { adminOnly: boolean; yes: boolean },
  mode: OutputMode,
): Promise<void> {
  const tenant = await resolveTenant(client, tenantRef);
  const user = await resolveUser(client, userRef);

  const what = opts.adminOnly
    ? `revoke admin role for ${user.email} on ${tenant.slug}`
    : `remove ${user.email} from ${tenant.slug} (membership + admin)`;
  const ok = await confirmDestructive(`${what}?`, opts.yes);
  if (!ok) {
    note("Aborted.");
    return;
  }

  const adminRes = await client.query(
    "DELETE FROM apiome.tenant_administrators WHERE tenant_id = $1 AND user_id = $2",
    [tenant.id, user.id],
  );
  let removedMember = false;
  if (!opts.adminOnly) {
    const memberRes = await client.query(
      "DELETE FROM apiome.tenant_users WHERE tenant_id = $1 AND user_id = $2",
      [tenant.id, user.id],
    );
    removedMember = (memberRes.rowCount ?? 0) > 0;
  }

  printRecord(mode, {
    tenant: tenant.slug,
    user: user.email,
    admin_removed: (adminRes.rowCount ?? 0) > 0,
    member_removed: opts.adminOnly ? "kept" : removedMember,
  });
}

export async function listTenantMembers(
  client: pg.Client,
  tenantRef: string,
  mode: OutputMode,
): Promise<void> {
  const tenant = await resolveTenant(client, tenantRef);
  const res = await client.query(
    `SELECT u.id, u.email, u.name, u.enabled,
            (ta.user_id IS NOT NULL) AS is_admin
     FROM apiome.tenant_users tu
     JOIN apiome.users u ON u.id = tu.user_id
     LEFT JOIN apiome.tenant_administrators ta
            ON ta.tenant_id = tu.tenant_id AND ta.user_id = tu.user_id
     WHERE tu.tenant_id = $1 AND u.deleted_at IS NULL
     ORDER BY u.email`,
    [tenant.id],
  );
  printRows(mode, res.rows as Record<string, unknown>[], [
    { key: "id", label: "ID" },
    { key: "email", label: "Email" },
    { key: "name", label: "Name" },
    { key: "enabled", label: "Enabled" },
    { key: "is_admin", label: "Admin" },
  ]);
}
