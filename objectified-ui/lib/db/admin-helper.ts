'use server';

const connectionPool = require('./db');
const bcrypt = require('bcrypt');
import { entitlementLimitsFromLicenseSeats } from './entitlement-limits-from-license-seats';

// Helper to standardize error responses
const errorResponse = (error: string) => JSON.stringify({ success: false, error });
const successResponse = (data: any = {}) => JSON.stringify({ success: true, ...data });

// ==================== User Management ====================

/**
 * Get all users from the database
 */
export async function getAllUsers() {
  try {
    const result = await connectionPool.query(
      `SELECT id, name, email, verified, enabled, created_at, updated_at, deleted_at
       FROM odb.users 
       WHERE deleted_at IS NULL
       ORDER BY created_at DESC`
    );
    return successResponse({ users: result.rows });
  } catch (error: any) {
    console.error('Error fetching users:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get a single user by ID
 */
export async function getUserById(userId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT id, name, email, verified, enabled, created_at, updated_at
       FROM odb.users 
       WHERE id = $1 AND deleted_at IS NULL`,
      [userId]
    );

    if (result.rows.length === 0) {
      return errorResponse('User not found');
    }

    return successResponse({ user: result.rows[0] });
  } catch (error: any) {
    console.error('Error fetching user:', error);
    return errorResponse(error.message);
  }
}

/**
 * Create a new user
 */
export async function createUser(
  name: string,
  email: string,
  password: string,
  verified: boolean = true,
  enabled: boolean = true
) {
  try {
    // Check if user already exists
    const existingUser = await connectionPool.query(
      'SELECT id FROM odb.users WHERE email = $1',
      [email]
    );

    if (existingUser.rowCount > 0) {
      return errorResponse('User with this email already exists');
    }

    // Password should already be hashed if coming from signup
    // If not hashed (manual creation), hash it
    let hashedPassword = password;
    if (!password.startsWith('$2a$') && !password.startsWith('$2b$')) {
      const saltRounds = 10;
      hashedPassword = await bcrypt.hash(password, saltRounds);
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.users (name, email, password, verified, enabled)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, name, email, verified, enabled, created_at`,
      [name, email, hashedPassword, verified, enabled]
    );

    return successResponse({ user: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating user:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update user details
 */
export async function updateUser(
  userId: string,
  updates: {
    name?: string;
    verified?: boolean;
    enabled?: boolean;
  }
) {
  try {
    const updateFields: string[] = [];
    const values: any[] = [];
    let paramIndex = 1;

    if (updates.name !== undefined) {
      updateFields.push(`name = $${paramIndex++}`);
      values.push(updates.name);
    }
    if (updates.verified !== undefined) {
      updateFields.push(`verified = $${paramIndex++}`);
      values.push(updates.verified);
    }
    if (updates.enabled !== undefined) {
      updateFields.push(`enabled = $${paramIndex++}`);
      values.push(updates.enabled);
    }

    if (updateFields.length === 0) {
      return errorResponse('No updates provided');
    }

    updateFields.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(userId);

    const result = await connectionPool.query(
      `UPDATE odb.users 
       SET ${updateFields.join(', ')}
       WHERE id = $${paramIndex} AND deleted_at IS NULL
       RETURNING id, name, email, verified, enabled, updated_at`,
      values
    );

    if (result.rowCount === 0) {
      return errorResponse('User not found or already deleted');
    }

    return successResponse({ user: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating user:', error);
    return errorResponse(error.message);
  }
}

/**
 * Soft delete a user
 */
export async function deleteUser(userId: string) {
  try {
    const result = await connectionPool.query(
      `UPDATE odb.users 
       SET deleted_at = CURRENT_TIMESTAMP, enabled = false, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND deleted_at IS NULL
       RETURNING id`,
      [userId]
    );

    if (result.rowCount === 0) {
      return errorResponse('User not found or already deleted');
    }

    return successResponse({ message: 'User deleted successfully' });
  } catch (error: any) {
    console.error('Error deleting user:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get user statistics
 */
export async function getUserStats() {
  try {
    const result = await connectionPool.query(
      `SELECT 
        COUNT(*) FILTER (WHERE deleted_at IS NULL) as total_users,
        COUNT(*) FILTER (WHERE enabled = true AND deleted_at IS NULL) as enabled_users,
        COUNT(*) FILTER (WHERE verified = true AND deleted_at IS NULL) as verified_users,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days' AND deleted_at IS NULL) as new_users_30_days,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days' AND deleted_at IS NULL) as new_users_7_days
       FROM odb.users`
    );

    return successResponse({ stats: result.rows[0] });
  } catch (error: any) {
    console.error('Error fetching user stats:', error);
    return errorResponse(error.message);
  }
}

// ==================== Signup Management ====================

/**
 * Get all pending signups
 */
export async function getAllSignups() {
  try {
    const result = await connectionPool.query(
      `SELECT name, email_address, signup_source, signup_date, password
       FROM odb.signup
       ORDER BY signup_date DESC`
    );
    return successResponse({ signups: result.rows });
  } catch (error: any) {
    console.error('Error fetching signups:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get signup statistics
 */
export async function getSignupStats() {
  try {
    const result = await connectionPool.query(
      `SELECT 
        COUNT(*) as total_signups,
        COUNT(*) FILTER (WHERE signup_date > NOW() - INTERVAL '30 days') as signups_30_days,
        COUNT(*) FILTER (WHERE signup_date > NOW() - INTERVAL '7 days') as signups_7_days,
        COUNT(*) FILTER (WHERE signup_date > NOW() - INTERVAL '1 day') as signups_today
       FROM odb.signup`
    );

    return successResponse({ stats: result.rows[0] });
  } catch (error: any) {
    console.error('Error fetching signup stats:', error);
    return errorResponse(error.message);
  }
}

/**
 * Create user from signup and remove signup entry
 */
export async function createUserFromSignup(
  email: string,
  verified: boolean = true,
  enabled: boolean = true
) {
  try {
    // Get signup data
    const signupResult = await connectionPool.query(
      'SELECT name, email_address, password, signup_source FROM odb.signup WHERE email_address = $1',
      [email]
    );

    if (signupResult.rowCount === 0) {
      return errorResponse('Signup not found');
    }

    const signup = signupResult.rows[0];

    // Check if user already exists
    const existingUser = await connectionPool.query(
      'SELECT id FROM odb.users WHERE email = $1',
      [signup.email_address]
    );

    if (existingUser.rowCount > 0) {
      return errorResponse('User with this email already exists');
    }

    // Create user with the hashed password from signup
    const userResult = await connectionPool.query(
      `INSERT INTO odb.users (name, email, password, verified, enabled)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, name, email, verified, enabled, created_at`,
      [signup.name, signup.email_address, signup.password, verified, enabled]
    );

    // Delete the signup entry
    await connectionPool.query(
      'DELETE FROM odb.signup WHERE email_address = $1',
      [email]
    );

    return successResponse({
      user: userResult.rows[0],
      message: 'User created successfully from signup'
    });
  } catch (error: any) {
    console.error('Error creating user from signup:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete a signup entry
 */
export async function deleteSignup(email: string) {
  try {
    const result = await connectionPool.query(
      'DELETE FROM odb.signup WHERE email_address = $1 RETURNING email_address',
      [email]
    );

    if (result.rowCount === 0) {
      return errorResponse('Signup not found');
    }

    return successResponse({ message: 'Signup deleted successfully' });
  } catch (error: any) {
    console.error('Error deleting signup:', error);
    return errorResponse(error.message);
  }
}

// ==================== Tenant Management ====================

/**
 * Get all tenants
 */
export async function getAllTenants() {
  try {
    const result = await connectionPool.query(
      `SELECT id, name, description, slug, enabled, created_at, updated_at
       FROM odb.tenants 
       WHERE deleted_at IS NULL
       ORDER BY created_at DESC`
    );
    return successResponse({ tenants: result.rows });
  } catch (error: any) {
    console.error('Error fetching tenants:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get tenant with user counts
 */
export async function getTenantStats() {
  try {
    const result = await connectionPool.query(
      `SELECT 
        t.id,
        t.name,
        t.slug,
        t.enabled,
        COUNT(DISTINCT tu.user_id) as user_count,
        COUNT(DISTINCT ta.user_id) as admin_count,
        COUNT(DISTINCT p.id) as project_count
       FROM odb.tenants t
       LEFT JOIN odb.tenant_users tu ON t.id = tu.tenant_id
       LEFT JOIN odb.tenant_administrators ta ON t.id = ta.tenant_id
       LEFT JOIN odb.projects p ON t.id = p.tenant_id AND p.deleted_at IS NULL
       WHERE t.deleted_at IS NULL
       GROUP BY t.id, t.name, t.slug, t.enabled
       ORDER BY t.created_at DESC`
    );
    return successResponse({ tenants: result.rows });
  } catch (error: any) {
    console.error('Error fetching tenant stats:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get users for a specific tenant
 */
export async function getTenantUsers(tenantId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT 
        u.id,
        u.name,
        u.email,
        u.verified,
        u.enabled,
        tu.created_at as added_at,
        EXISTS(SELECT 1 FROM odb.tenant_administrators ta WHERE ta.tenant_id = $1 AND ta.user_id = u.id) as is_admin
       FROM odb.users u
       JOIN odb.tenant_users tu ON u.id = tu.user_id
       WHERE tu.tenant_id = $1 AND u.deleted_at IS NULL
       ORDER BY tu.created_at DESC`,
      [tenantId]
    );
    return successResponse({ users: result.rows });
  } catch (error: any) {
    console.error('Error fetching tenant users:', error);
    return errorResponse(error.message);
  }
}

/**
 * Create a new tenant
 */
export async function createTenant(
  name: string,
  description: string,
  slug: string,
  enabled: boolean = true
) {
  try {
    // Check if slug already exists
    const existingTenant = await connectionPool.query(
      'SELECT id FROM odb.tenants WHERE slug = $1 AND deleted_at IS NULL',
      [slug]
    );

    if (existingTenant.rowCount > 0) {
      return errorResponse('A tenant with this slug already exists');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.tenants (name, description, slug, enabled)
       VALUES ($1, $2, $3, $4)
       RETURNING id, name, description, slug, enabled, created_at`,
      [name, description, slug, enabled]
    );

    return successResponse({ tenant: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating tenant:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update tenant details
 */
export async function updateTenant(
  tenantId: string,
  updates: {
    name?: string;
    description?: string;
    slug?: string;
    enabled?: boolean;
  }
) {
  try {
    const updateFields: string[] = [];
    const values: any[] = [];
    let paramIndex = 1;

    if (updates.name !== undefined) {
      updateFields.push(`name = $${paramIndex++}`);
      values.push(updates.name);
    }
    if (updates.description !== undefined) {
      updateFields.push(`description = $${paramIndex++}`);
      values.push(updates.description);
    }
    if (updates.slug !== undefined) {
      // Check if slug is already taken by another tenant
      const existingTenant = await connectionPool.query(
        'SELECT id FROM odb.tenants WHERE slug = $1 AND id != $2 AND deleted_at IS NULL',
        [updates.slug, tenantId]
      );

      if (existingTenant.rowCount > 0) {
        return errorResponse('This slug is already taken by another tenant');
      }

      updateFields.push(`slug = $${paramIndex++}`);
      values.push(updates.slug);
    }
    if (updates.enabled !== undefined) {
      updateFields.push(`enabled = $${paramIndex++}`);
      values.push(updates.enabled);
    }

    if (updateFields.length === 0) {
      return errorResponse('No updates provided');
    }

    updateFields.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(tenantId);

    const result = await connectionPool.query(
      `UPDATE odb.tenants 
       SET ${updateFields.join(', ')}
       WHERE id = $${paramIndex} AND deleted_at IS NULL
       RETURNING id, name, description, slug, enabled, updated_at`,
      values
    );

    if (result.rowCount === 0) {
      return errorResponse('Tenant not found or already deleted');
    }

    return successResponse({ tenant: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating tenant:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete a tenant (soft delete)
 */
export async function deleteTenant(tenantId: string) {
  try {
    const result = await connectionPool.query(
      `UPDATE odb.tenants 
       SET deleted_at = CURRENT_TIMESTAMP, enabled = false, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND deleted_at IS NULL
       RETURNING id`,
      [tenantId]
    );

    if (result.rowCount === 0) {
      return errorResponse('Tenant not found or already deleted');
    }

    return successResponse({ message: 'Tenant deleted successfully' });
  } catch (error: any) {
    console.error('Error deleting tenant:', error);
    return errorResponse(error.message);
  }
}

/**
 * Add a user to a tenant
 */
export async function addUserToTenant(tenantId: string, userId: string) {
  try {
    // Check if tenant exists
    const tenantCheck = await connectionPool.query(
      'SELECT id FROM odb.tenants WHERE id = $1 AND deleted_at IS NULL',
      [tenantId]
    );

    if (tenantCheck.rowCount === 0) {
      return errorResponse('Tenant not found');
    }

    // Check if user exists
    const userCheck = await connectionPool.query(
      'SELECT id FROM odb.users WHERE id = $1 AND deleted_at IS NULL',
      [userId]
    );

    if (userCheck.rowCount === 0) {
      return errorResponse('User not found');
    }

    // Check if user is already assigned
    const existingAssignment = await connectionPool.query(
      'SELECT id FROM odb.tenant_users WHERE tenant_id = $1 AND user_id = $2',
      [tenantId, userId]
    );

    if (existingAssignment.rowCount > 0) {
      return errorResponse('User is already assigned to this tenant');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.tenant_users (tenant_id, user_id)
       VALUES ($1, $2)
       RETURNING id, tenant_id, user_id, created_at`,
      [tenantId, userId]
    );

    return successResponse({ assignment: result.rows[0] });
  } catch (error: any) {
    console.error('Error adding user to tenant:', error);
    return errorResponse(error.message);
  }
}

/**
 * Remove a user from a tenant
 */
export async function removeUserFromTenant(tenantId: string, userId: string) {
  try {
    // Also remove from administrators if they are one
    await connectionPool.query(
      'DELETE FROM odb.tenant_administrators WHERE tenant_id = $1 AND user_id = $2',
      [tenantId, userId]
    );

    const result = await connectionPool.query(
      'DELETE FROM odb.tenant_users WHERE tenant_id = $1 AND user_id = $2 RETURNING user_id',
      [tenantId, userId]
    );

    if (result.rowCount === 0) {
      return errorResponse('User not found in this tenant');
    }

    return successResponse({ message: 'User removed from tenant successfully' });
  } catch (error: any) {
    console.error('Error removing user from tenant:', error);
    return errorResponse(error.message);
  }
}

/**
 * Add a user as tenant administrator
 */
export async function addTenantAdministrator(tenantId: string, userId: string) {
  try {
    // Check if user is a member of the tenant
    const memberCheck = await connectionPool.query(
      'SELECT id FROM odb.tenant_users WHERE tenant_id = $1 AND user_id = $2',
      [tenantId, userId]
    );

    if (memberCheck.rowCount === 0) {
      return errorResponse('User must be a member of the tenant first');
    }

    // Check if already an admin
    const existingAdmin = await connectionPool.query(
      'SELECT id FROM odb.tenant_administrators WHERE tenant_id = $1 AND user_id = $2',
      [tenantId, userId]
    );

    if (existingAdmin.rowCount > 0) {
      return errorResponse('User is already an administrator of this tenant');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.tenant_administrators (tenant_id, user_id)
       VALUES ($1, $2)
       RETURNING id, tenant_id, user_id, created_at`,
      [tenantId, userId]
    );

    return successResponse({ admin: result.rows[0] });
  } catch (error: any) {
    console.error('Error adding tenant administrator:', error);
    return errorResponse(error.message);
  }
}

/**
 * Provision the curated sample project for a tenant via the shared, idempotent
 * `odb.provision_sample_project()` routine (objectified-db migration V122), owned by `creatorId`.
 * Best-effort: callers should NOT fail tenant creation if this errors — a fresh tenant simply
 * starts empty. Returns the standard JSON envelope ({ success, project_id } | { success:false }).
 */
export async function provisionSampleProject(tenantId: string, creatorId: string) {
  try {
    const result = await connectionPool.query(
      'SELECT odb.provision_sample_project($1, $2) AS project_id',
      [tenantId, creatorId]
    );
    // project_id is NULL when the sample already existed (idempotent no-op).
    return successResponse({ project_id: result.rows[0]?.project_id ?? null });
  } catch (error) {
    console.error('Error provisioning sample project:', error);
    return errorResponse(error instanceof Error ? error.message : String(error));
  }
}

/**
 * Remove a user as tenant administrator
 */
export async function removeTenantAdministrator(tenantId: string, userId: string) {
  try {
    const result = await connectionPool.query(
      'DELETE FROM odb.tenant_administrators WHERE tenant_id = $1 AND user_id = $2 RETURNING user_id',
      [tenantId, userId]
    );

    if (result.rowCount === 0) {
      return errorResponse('User is not an administrator of this tenant');
    }

    return successResponse({ message: 'Administrator removed successfully' });
  } catch (error: any) {
    console.error('Error removing tenant administrator:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get all users not in a specific tenant (for assignment)
 */
export async function getUsersNotInTenant(tenantId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT id, name, email, verified, enabled
       FROM odb.users
       WHERE deleted_at IS NULL
         AND id NOT IN (
           SELECT user_id FROM odb.tenant_users WHERE tenant_id = $1
         )
       ORDER BY name`,
      [tenantId]
    );
    return successResponse({ users: result.rows });
  } catch (error: any) {
    console.error('Error fetching users not in tenant:', error);
    return errorResponse(error.message);
  }
}

// ==================== Property Template Management ====================

/**
 * Get all property templates (including system and tenant templates)
 */
export async function getAllPropertyTemplates() {
  try {
    const result = await connectionPool.query(
      `SELECT pt.id, pt.name, pt.description, pt.category, pt.schema, pt.tags,
              pt.tenant_id, pt.created_by, pt.is_system, pt.is_public,
              pt.usage_count, pt.enabled, pt.created_at, pt.updated_at,
              t.name as tenant_name,
              u.name as creator_name, u.email as creator_email
       FROM odb.property_templates pt
       LEFT JOIN odb.tenants t ON pt.tenant_id = t.id
       LEFT JOIN odb.users u ON pt.created_by = u.id
       WHERE pt.deleted_at IS NULL
       ORDER BY pt.is_system DESC, pt.category, pt.name`
    );
    return successResponse({ templates: result.rows });
  } catch (error: any) {
    console.error('Error fetching property templates:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get property template categories with counts (admin view - all templates)
 */
export async function getPropertyTemplateCategoriesAdmin() {
  try {
    const result = await connectionPool.query(
      `SELECT category, COUNT(*) as count,
              SUM(CASE WHEN is_system = true THEN 1 ELSE 0 END) as system_count,
              SUM(CASE WHEN is_system = false THEN 1 ELSE 0 END) as tenant_count
       FROM odb.property_templates
       WHERE deleted_at IS NULL
       GROUP BY category
       ORDER BY category`
    );
    return successResponse({ categories: result.rows });
  } catch (error: any) {
    console.error('Error fetching property template categories:', error);
    return errorResponse(error.message);
  }
}

/**
 * Create a new property template (admin can create system templates)
 */
export async function createPropertyTemplateAdmin(
  name: string,
  description: string | null,
  category: string,
  schema: any,
  tags: string[] = [],
  isSystem: boolean = false,
  isPublic: boolean = true
) {
  try {
    if (!name || name.trim().length === 0) {
      return errorResponse('Template name is required');
    }

    if (!category || category.trim().length === 0) {
      return errorResponse('Category is required');
    }

    if (!schema) {
      return errorResponse('Schema is required');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.property_templates 
       (name, description, category, schema, tags, is_system, is_public, tenant_id, created_by)
       VALUES ($1, $2, $3, $4, $5, $6, $7, NULL, NULL)
       RETURNING id, name, description, category, schema, tags, tenant_id, created_by,
                 is_system, is_public, usage_count, enabled, created_at, updated_at`,
      [name.trim(), description, category.trim(), JSON.stringify(schema), tags, isSystem, isPublic]
    );

    return successResponse({ template: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating property template:', error);

    if (error.code === '23505') {
      return errorResponse('A template with this name already exists in this category');
    }

    return errorResponse(error.message);
  }
}

/**
 * Update a property template (admin can update any template including system)
 */
export async function updatePropertyTemplateAdmin(
  templateId: string,
  name: string,
  description: string | null,
  category: string,
  schema: any,
  tags: string[] = [],
  isSystem: boolean = false,
  isPublic: boolean = true,
  enabled: boolean = true
) {
  try {
    if (!name || name.trim().length === 0) {
      return errorResponse('Template name is required');
    }

    if (!category || category.trim().length === 0) {
      return errorResponse('Category is required');
    }

    if (!schema) {
      return errorResponse('Schema is required');
    }

    const result = await connectionPool.query(
      `UPDATE odb.property_templates 
       SET name = $1, description = $2, category = $3, schema = $4, tags = $5, 
           is_system = $6, is_public = $7, enabled = $8, updated_at = CURRENT_TIMESTAMP
       WHERE id = $9 AND deleted_at IS NULL
       RETURNING id, name, description, category, schema, tags, tenant_id, created_by,
                 is_system, is_public, usage_count, enabled, created_at, updated_at`,
      [name.trim(), description, category.trim(), JSON.stringify(schema), tags, isSystem, isPublic, enabled, templateId]
    );

    if (result.rowCount === 0) {
      return errorResponse('Template not found');
    }

    return successResponse({ template: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating property template:', error);

    if (error.code === '23505') {
      return errorResponse('A template with this name already exists in this category');
    }

    return errorResponse(error.message);
  }
}

/**
 * Delete a property template (admin can delete any template)
 */
export async function deletePropertyTemplateAdmin(templateId: string) {
  try {
    const result = await connectionPool.query(
      `UPDATE odb.property_templates 
       SET deleted_at = CURRENT_TIMESTAMP 
       WHERE id = $1 AND deleted_at IS NULL
       RETURNING id, name`,
      [templateId]
    );

    if (result.rowCount === 0) {
      return errorResponse('Template not found');
    }

    return successResponse({ deleted: result.rows[0] });
  } catch (error: any) {
    console.error('Error deleting property template:', error);
    return errorResponse(error.message);
  }
}

// ==================== License Management ====================

/**
 * Get all license definitions with their assigned feature flags
 */
export async function getAllLicenses() {
  try {
    const result = await connectionPool.query(
      `SELECT
         l.id, l.name, l.description, l.license_type, l.seats, l.enabled,
         l.created_at, l.updated_at,
         COALESCE(
           json_agg(
             json_build_object(
               'id',         ff.id,
               'name',       ff.name,
               'label',      ff.label,
               'is_preview', ff.is_preview
             ) ORDER BY ff.label
           ) FILTER (WHERE ff.id IS NOT NULL),
           '[]'
         ) AS feature_flags
       FROM odb.licenses l
       LEFT JOIN odb.license_feature_flags lff ON lff.license_id = l.id
       LEFT JOIN odb.feature_flags ff           ON ff.id = lff.feature_flag_id
       GROUP BY l.id
       ORDER BY l.license_type, l.name`
    );
    return successResponse({ licenses: result.rows });
  } catch (error: any) {
    console.error('Error fetching licenses:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get a single license by ID with its feature flags
 */
export async function getLicenseById(licenseId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT
         l.id, l.name, l.description, l.license_type, l.seats, l.enabled,
         l.created_at, l.updated_at,
         COALESCE(
           json_agg(
             json_build_object(
               'id',         ff.id,
               'name',       ff.name,
               'label',      ff.label,
               'is_preview', ff.is_preview
             ) ORDER BY ff.label
           ) FILTER (WHERE ff.id IS NOT NULL),
           '[]'
         ) AS feature_flags
       FROM odb.licenses l
       LEFT JOIN odb.license_feature_flags lff ON lff.license_id = l.id
       LEFT JOIN odb.feature_flags ff           ON ff.id = lff.feature_flag_id
       WHERE l.id = $1
       GROUP BY l.id`,
      [licenseId]
    );
    if (result.rowCount === 0) return errorResponse('License not found');
    return successResponse({ license: result.rows[0] });
  } catch (error: any) {
    console.error('Error fetching license:', error);
    return errorResponse(error.message);
  }
}

/**
 * Create a new license plan
 */
export async function createLicense(
  name: string,
  description: string | null,
  licenseType: 'free' | 'paid' | 'sponsor',
  seats: Record<string, number>,
  featureFlagIds: string[] = []
) {
  try {
    const result = await connectionPool.query(
      `INSERT INTO odb.licenses (name, description, license_type, seats)
       VALUES ($1, $2, $3, $4)
       RETURNING id, name, description, license_type, seats, enabled, created_at`,
      [name, description, licenseType, JSON.stringify(seats)]
    );
    const license = result.rows[0];

    if (featureFlagIds.length > 0) {
      const placeholders = featureFlagIds.map((_, i) => `($1, $${i + 2})`).join(', ');
      await connectionPool.query(
        `INSERT INTO odb.license_feature_flags (license_id, feature_flag_id) VALUES ${placeholders}
         ON CONFLICT DO NOTHING`,
        [license.id, ...featureFlagIds]
      );
    }

    return successResponse({ license });
  } catch (error: any) {
    console.error('Error creating license:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update an existing license plan
 */
export async function updateLicense(
  licenseId: string,
  updates: {
    name?: string;
    description?: string | null;
    licenseType?: 'free' | 'paid' | 'sponsor';
    seats?: Record<string, number>;
    enabled?: boolean;
    featureFlagIds?: string[];
  }
) {
  try {
    const fields: string[] = [];
    const values: any[] = [];
    let idx = 1;

    if (updates.name      !== undefined) { fields.push(`name = $${idx++}`);         values.push(updates.name); }
    if (updates.description !== undefined) { fields.push(`description = $${idx++}`); values.push(updates.description); }
    if (updates.licenseType !== undefined) { fields.push(`license_type = $${idx++}`); values.push(updates.licenseType); }
    if (updates.seats     !== undefined) { fields.push(`seats = $${idx++}`);         values.push(JSON.stringify(updates.seats)); }
    if (updates.enabled   !== undefined) { fields.push(`enabled = $${idx++}`);       values.push(updates.enabled); }

    if (fields.length > 0) {
      fields.push(`updated_at = CURRENT_TIMESTAMP`);
      values.push(licenseId);
      const result = await connectionPool.query(
        `UPDATE odb.licenses SET ${fields.join(', ')} WHERE id = $${idx} RETURNING id`,
        values
      );
      if (result.rowCount === 0) return errorResponse('License not found');
    }

    if (updates.seats !== undefined) {
      const lim = entitlementLimitsFromLicenseSeats(updates.seats);
      await connectionPool.query(
        `UPDATE odb.user_entitlements
         SET max_tenants = $1, max_projects = $2, max_versions = $3
         WHERE license_id = $4`,
        [lim.max_tenants, lim.max_projects, lim.max_versions, licenseId]
      );
    }

    if (updates.featureFlagIds !== undefined) {
      await connectionPool.query(
        `DELETE FROM odb.license_feature_flags WHERE license_id = $1`, [licenseId]
      );
      if (updates.featureFlagIds.length > 0) {
        const placeholders = updates.featureFlagIds.map((_, i) => `($1, $${i + 2})`).join(', ');
        await connectionPool.query(
          `INSERT INTO odb.license_feature_flags (license_id, feature_flag_id) VALUES ${placeholders}
           ON CONFLICT DO NOTHING`,
          [licenseId, ...updates.featureFlagIds]
        );
      }
    }

    return getLicenseById(licenseId);
  } catch (error: any) {
    console.error('Error updating license:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete a license (hard delete; blocks if users are assigned)
 */
export async function deleteLicense(licenseId: string) {
  try {
    const assigned = await connectionPool.query(
      `SELECT COUNT(*)::int AS c FROM odb.user_entitlements WHERE license_id = $1`,
      [licenseId]
    );
    if ((assigned.rows[0]?.c ?? 0) > 0) {
      return errorResponse('Cannot delete: this license is currently assigned to one or more users. Reassign them first.');
    }
    const result = await connectionPool.query(
      `DELETE FROM odb.licenses WHERE id = $1 RETURNING id, name`, [licenseId]
    );
    if (result.rowCount === 0) return errorResponse('License not found');
    return successResponse({ deleted: result.rows[0] });
  } catch (error: any) {
    console.error('Error deleting license:', error);
    return errorResponse(error.message);
  }
}

// ==================== Feature Flag Management ====================

function normalizeFeatureFlagUrlPatterns(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === 'string');
}

/**
 * Get all feature flags
 */
export async function getAllFeatureFlags() {
  try {
    const result = await connectionPool.query(
      `SELECT id, name, label, description, url_patterns, is_preview, enabled, created_at, updated_at
       FROM odb.feature_flags
       ORDER BY label`
    );
    const featureFlags = result.rows.map((row: Record<string, unknown>) => ({
      ...row,
      url_patterns: normalizeFeatureFlagUrlPatterns(row.url_patterns),
    }));
    return successResponse({ featureFlags });
  } catch (error: any) {
    console.error('Error fetching feature flags:', error);
    return errorResponse(error.message);
  }
}

/**
 * Create a feature flag
 */
export async function createFeatureFlag(
  name: string,
  label: string,
  description: string | null,
  urlPatterns: string[],
  isPreview: boolean = false
) {
  try {
    const result = await connectionPool.query(
      `INSERT INTO odb.feature_flags (name, label, description, url_patterns, is_preview)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, name, label, description, url_patterns, is_preview, enabled, created_at`,
      [name, label, description, JSON.stringify(urlPatterns), isPreview]
    );
    const row = result.rows[0] as Record<string, unknown>;
    return successResponse({
      featureFlag: { ...row, url_patterns: normalizeFeatureFlagUrlPatterns(row.url_patterns) },
    });
  } catch (error: any) {
    if (error.code === '23505') return errorResponse(`A feature flag named "${name}" already exists`);
    console.error('Error creating feature flag:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update a feature flag
 */
export async function updateFeatureFlag(
  flagId: string,
  updates: {
    label?: string;
    description?: string | null;
    urlPatterns?: string[];
    isPreview?: boolean;
    enabled?: boolean;
  }
) {
  try {
    const fields: string[] = [];
    const values: any[] = [];
    let idx = 1;

    if (updates.label       !== undefined) { fields.push(`label = $${idx++}`);        values.push(updates.label); }
    if (updates.description !== undefined) { fields.push(`description = $${idx++}`);  values.push(updates.description); }
    if (updates.urlPatterns !== undefined) { fields.push(`url_patterns = $${idx++}`); values.push(JSON.stringify(updates.urlPatterns)); }
    if (updates.isPreview   !== undefined) { fields.push(`is_preview = $${idx++}`);   values.push(updates.isPreview); }
    if (updates.enabled     !== undefined) { fields.push(`enabled = $${idx++}`);      values.push(updates.enabled); }

    if (fields.length === 0) return errorResponse('No updates provided');

    fields.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(flagId);

    const result = await connectionPool.query(
      `UPDATE odb.feature_flags SET ${fields.join(', ')} WHERE id = $${idx}
       RETURNING id, name, label, description, url_patterns, is_preview, enabled, updated_at`,
      values
    );
    if (result.rowCount === 0) return errorResponse('Feature flag not found');
    const row = result.rows[0] as Record<string, unknown>;
    return successResponse({
      featureFlag: { ...row, url_patterns: normalizeFeatureFlagUrlPatterns(row.url_patterns) },
    });
  } catch (error: any) {
    console.error('Error updating feature flag:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete a feature flag (hard delete)
 */
export async function deleteFeatureFlag(flagId: string) {
  try {
    const result = await connectionPool.query(
      `DELETE FROM odb.feature_flags WHERE id = $1 RETURNING id, name`, [flagId]
    );
    if (result.rowCount === 0) return errorResponse('Feature flag not found');
    return successResponse({ deleted: result.rows[0] });
  } catch (error: any) {
    console.error('Error deleting feature flag:', error);
    return errorResponse(error.message);
  }
}

// ==================== Feature Flag Groups (packages) ====================

/**
 * List all feature flag groups with their member flags
 */
export async function getAllFeatureFlagGroups() {
  try {
    const result = await connectionPool.query(
      `SELECT
         g.id,
         g.name,
         g.label,
         g.description,
         g.created_at,
         g.updated_at,
         COALESCE(
           json_agg(
             jsonb_build_object(
               'id',         ff.id,
               'name',       ff.name,
               'label',      ff.label,
               'is_preview', ff.is_preview
             )
             ORDER BY ff.label
           ) FILTER (WHERE ff.id IS NOT NULL),
           '[]'
         ) AS feature_flags
       FROM odb.feature_flag_groups g
       LEFT JOIN odb.feature_flag_group_members m ON m.group_id = g.id
       LEFT JOIN odb.feature_flags ff ON ff.id = m.feature_flag_id
       GROUP BY g.id
       ORDER BY g.label`
    );
    return successResponse({ groups: result.rows });
  } catch (error: any) {
    console.error('Error fetching feature flag groups:', error);
    return errorResponse(error.message);
  }
}

/**
 * Create a feature flag group and optional initial members
 */
export async function createFeatureFlagGroup(
  name: string,
  label: string,
  description: string | null,
  featureFlagIds: string[]
) {
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    const insert = await client.query(
      `INSERT INTO odb.feature_flag_groups (name, label, description)
       VALUES ($1, $2, $3)
       RETURNING id, name, label, description, created_at, updated_at`,
      [name, label, description]
    );
    const group = insert.rows[0];
    const uniqueFlagIds = [...new Set(featureFlagIds)];
    if (uniqueFlagIds.length > 0) {
      const values = uniqueFlagIds.map((_, i) => `($1, $${i + 2})`).join(', ');
      await client.query(
        `INSERT INTO odb.feature_flag_group_members (group_id, feature_flag_id) VALUES ${values}`,
        [group.id, ...uniqueFlagIds]
      );
    }
    await client.query('COMMIT');
    return successResponse({ group });
  } catch (error: any) {
    await client.query('ROLLBACK');
    if (error.code === '23505') return errorResponse(`A feature flag package named "${name}" already exists`);
    console.error('Error creating feature flag group:', error);
    return errorResponse(error.message);
  } finally {
    client.release();
  }
}

/**
 * Update a feature flag group's metadata and/or replace its members
 */
export async function updateFeatureFlagGroup(
  groupId: string,
  updates: {
    label?: string;
    description?: string | null;
    featureFlagIds?: string[];
  }
) {
  if (
    updates.label === undefined &&
    updates.description === undefined &&
    updates.featureFlagIds === undefined
  ) {
    return errorResponse('No updates provided');
  }

  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');

    const fields: string[] = [];
    const values: unknown[] = [];
    let idx = 1;
    if (updates.label !== undefined) {
      fields.push(`label = $${idx++}`);
      values.push(updates.label);
    }
    if (updates.description !== undefined) {
      fields.push(`description = $${idx++}`);
      values.push(updates.description);
    }
    if (fields.length > 0) {
      fields.push(`updated_at = CURRENT_TIMESTAMP`);
      values.push(groupId);
      const res = await client.query(
        `UPDATE odb.feature_flag_groups SET ${fields.join(', ')} WHERE id = $${idx} RETURNING id`,
        values
      );
      if (res.rowCount === 0) {
        await client.query('ROLLBACK');
        return errorResponse('Feature flag package not found');
      }
    } else {
      const check = await client.query(`SELECT id FROM odb.feature_flag_groups WHERE id = $1`, [groupId]);
      if (check.rowCount === 0) {
        await client.query('ROLLBACK');
        return errorResponse('Feature flag package not found');
      }
    }

    if (updates.featureFlagIds !== undefined) {
      await client.query(`DELETE FROM odb.feature_flag_group_members WHERE group_id = $1`, [groupId]);
      const uniqueIds = [...new Set(updates.featureFlagIds)];
      if (uniqueIds.length > 0) {
        const placeholders = uniqueIds.map((_, i) => `($1, $${i + 2})`).join(', ');
        await client.query(
          `INSERT INTO odb.feature_flag_group_members (group_id, feature_flag_id) VALUES ${placeholders}`,
          [groupId, ...uniqueIds]
        );
      }
    }

    await client.query('COMMIT');
    return successResponse({ message: 'Feature flag package updated' });
  } catch (error: any) {
    await client.query('ROLLBACK');
    console.error('Error updating feature flag group:', error);
    return errorResponse(error.message);
  } finally {
    client.release();
  }
}

/**
 * Delete a feature flag group (members removed by CASCADE)
 */
export async function deleteFeatureFlagGroup(groupId: string) {
  try {
    const result = await connectionPool.query(
      `DELETE FROM odb.feature_flag_groups WHERE id = $1 RETURNING id, label`,
      [groupId]
    );
    if (result.rowCount === 0) return errorResponse('Feature flag package not found');
    return successResponse({ deleted: result.rows[0] });
  } catch (error: any) {
    console.error('Error deleting feature flag group:', error);
    return errorResponse(error.message);
  }
}

// ==================== User License Assignments ====================

/**
 * Get all users with their assigned license
 */
export async function getAllUsersWithLicenses() {
  try {
    const result = await connectionPool.query(
      `SELECT
         u.id, u.name, u.email, u.enabled, u.verified,
         ue.license_id,
         l.name        AS license_name,
         l.license_type,
         l.seats,
         ue.plan_code
       FROM odb.users u
       LEFT JOIN odb.user_entitlements ue ON ue.user_id = u.id
       LEFT JOIN odb.licenses          l  ON l.id = ue.license_id
       WHERE u.deleted_at IS NULL
       ORDER BY u.name`
    );
    return successResponse({ users: result.rows });
  } catch (error: any) {
    console.error('Error fetching users with licenses:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get the license assigned to a specific user, including effective feature flags
 */
export async function getUserLicense(userId: string) {
  try {
    // Anchor on users + LEFT JOIN entitlements so we still return a row (and user_overrides)
    // when user_feature_flags exist but there is no user_entitlements row yet.
    const result = await connectionPool.query(
      `SELECT
         l.id          AS license_id,
         l.name        AS license_name,
         l.license_type,
         l.seats,
         ue.plan_code,
         COALESCE(
           (
             SELECT json_agg(
               jsonb_build_object(
                 'id',         ff.id,
                 'name',       ff.name,
                 'label',      ff.label,
                 'is_preview', ff.is_preview
               ) ORDER BY ff.label
             )
             FROM odb.license_feature_flags lff
             JOIN odb.feature_flags ff ON ff.id = lff.feature_flag_id
             WHERE l.id IS NOT NULL AND lff.license_id = l.id
           ),
           '[]'::json
         ) AS license_feature_flags,
         COALESCE(
           (
             SELECT json_agg(
               jsonb_build_object(
                 'id',         uff_ff.id,
                 'name',       uff_ff.name,
                 'label',      uff_ff.label,
                 'enabled',    uff.enabled,
                 'is_preview', uff_ff.is_preview
               ) ORDER BY uff_ff.label
             )
             FROM odb.user_feature_flags uff
             JOIN odb.feature_flags uff_ff ON uff_ff.id = uff.feature_flag_id
             WHERE uff.user_id = u.id
           ),
           '[]'::json
         ) AS user_overrides
       FROM odb.users u
       LEFT JOIN odb.user_entitlements ue ON ue.user_id = u.id
       LEFT JOIN odb.licenses l ON l.id = ue.license_id
       WHERE u.id = $1 AND u.deleted_at IS NULL`,
      [userId]
    );
    return successResponse({ license: result.rows[0] ?? null });
  } catch (error: any) {
    console.error('Error fetching user license:', error);
    return errorResponse(error.message);
  }
}

/**
 * Assign a license to a user (upserts user_entitlements)
 */
export async function assignLicenseToUser(userId: string, licenseId: string) {
  try {
    const licenseResult = await connectionPool.query(
      `SELECT license_type, seats FROM odb.licenses WHERE id = $1`,
      [licenseId]
    );
    if (licenseResult.rowCount === 0) return errorResponse('License not found');

    const lim = entitlementLimitsFromLicenseSeats(licenseResult.rows[0].seats);

    await connectionPool.query(
      `INSERT INTO odb.user_entitlements (user_id, plan_code, max_tenants, max_projects, max_versions, license_id)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (user_id) DO UPDATE
         SET license_id   = EXCLUDED.license_id,
             plan_code    = EXCLUDED.plan_code,
             max_tenants  = EXCLUDED.max_tenants,
             max_projects = EXCLUDED.max_projects,
             max_versions = EXCLUDED.max_versions`,
      [
        userId,
        licenseResult.rows[0].license_type,
        lim.max_tenants,
        lim.max_projects,
        lim.max_versions,
        licenseId,
      ]
    );
    return successResponse({ message: 'License assigned successfully' });
  } catch (error: any) {
    console.error('Error assigning license:', error);
    return errorResponse(error.message);
  }
}

/**
 * Remove the license assignment from a user
 */
export async function removeUserLicense(userId: string) {
  try {
    await connectionPool.query(
      `UPDATE odb.user_entitlements SET license_id = NULL WHERE user_id = $1`, [userId]
    );
    return successResponse({ message: 'License removed' });
  } catch (error: any) {
    console.error('Error removing user license:', error);
    return errorResponse(error.message);
  }
}

// ==================== User Feature Flag Overrides ====================

/**
 * Set (upsert) a per-user feature flag override
 */
export async function setUserFeatureFlag(
  userId: string,
  featureFlagId: string,
  enabled: boolean,
  grantedBy?: string
) {
  try {
    await connectionPool.query(
      `INSERT INTO odb.user_feature_flags (user_id, feature_flag_id, enabled, granted_by)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (user_id, feature_flag_id) DO UPDATE
         SET enabled    = EXCLUDED.enabled,
             granted_by = EXCLUDED.granted_by,
             granted_at = CURRENT_TIMESTAMP`,
      [userId, featureFlagId, enabled, grantedBy ?? null]
    );
    return successResponse({ message: 'Feature flag override saved' });
  } catch (error: any) {
    console.error('Error setting user feature flag:', error);
    return errorResponse(error.message);
  }
}

/**
 * Remove a per-user feature flag override (reverts to license default)
 */
export async function removeUserFeatureFlag(userId: string, featureFlagId: string) {
  try {
    await connectionPool.query(
      `DELETE FROM odb.user_feature_flags WHERE user_id = $1 AND feature_flag_id = $2`,
      [userId, featureFlagId]
    );
    return successResponse({ message: 'Feature flag override removed' });
  } catch (error: any) {
    console.error('Error removing user feature flag:', error);
    return errorResponse(error.message);
  }
}

// ==================== Tenant Feature Flag Overrides ====================

/**
 * Set (upsert) a per-tenant feature flag override
 */
export async function setTenantFeatureFlag(
  tenantId: string,
  featureFlagId: string,
  enabled: boolean,
  grantedBy?: string
) {
  try {
    await connectionPool.query(
      `INSERT INTO odb.tenant_feature_flags (tenant_id, feature_flag_id, enabled, granted_by)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (tenant_id, feature_flag_id) DO UPDATE
         SET enabled    = EXCLUDED.enabled,
             granted_by = EXCLUDED.granted_by,
             granted_at = CURRENT_TIMESTAMP`,
      [tenantId, featureFlagId, enabled, grantedBy ?? null]
    );
    return successResponse({ message: 'Tenant feature flag override saved' });
  } catch (error: any) {
    console.error('Error setting tenant feature flag:', error);
    return errorResponse(error.message);
  }
}

/**
 * Remove a per-tenant feature flag override
 */
export async function removeTenantFeatureFlag(tenantId: string, featureFlagId: string) {
  try {
    await connectionPool.query(
      `DELETE FROM odb.tenant_feature_flags WHERE tenant_id = $1 AND feature_flag_id = $2`,
      [tenantId, featureFlagId]
    );
    return successResponse({ message: 'Tenant feature flag override removed' });
  } catch (error: any) {
    console.error('Error removing tenant feature flag:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get all feature flag overrides for a tenant
 */
export async function getTenantFeatureFlags(tenantId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT
         ff.id, ff.name, ff.label, ff.description, ff.is_preview,
         tff.enabled, tff.granted_at
       FROM odb.tenant_feature_flags tff
       JOIN odb.feature_flags ff ON ff.id = tff.feature_flag_id
       WHERE tff.tenant_id = $1
       ORDER BY ff.label`,
      [tenantId]
    );
    return successResponse({ featureFlags: result.rows });
  } catch (error: any) {
    console.error('Error fetching tenant feature flags:', error);
    return errorResponse(error.message);
  }
}

/**
 * Toggle property template enabled status
 */
export async function togglePropertyTemplateStatus(templateId: string, enabled: boolean) {
  try {
    const result = await connectionPool.query(
      `UPDATE odb.property_templates 
       SET enabled = $1, updated_at = CURRENT_TIMESTAMP 
       WHERE id = $2 AND deleted_at IS NULL
       RETURNING id, name, enabled`,
      [enabled, templateId]
    );

    if (result.rowCount === 0) {
      return errorResponse('Template not found');
    }

    return successResponse({ template: result.rows[0] });
  } catch (error: any) {
    console.error('Error toggling property template status:', error);
    return errorResponse(error.message);
  }
}

/**
 * Get property template statistics
 */
export async function getPropertyTemplateStats() {
  try {
    const result = await connectionPool.query(
      `SELECT 
         COUNT(*) as total_templates,
         SUM(CASE WHEN is_system = true THEN 1 ELSE 0 END) as system_templates,
         SUM(CASE WHEN is_system = false THEN 1 ELSE 0 END) as tenant_templates,
         SUM(CASE WHEN enabled = true THEN 1 ELSE 0 END) as enabled_templates,
         SUM(CASE WHEN enabled = false THEN 1 ELSE 0 END) as disabled_templates,
         SUM(usage_count) as total_usage,
         COUNT(DISTINCT category) as category_count
       FROM odb.property_templates
       WHERE deleted_at IS NULL`
    );
    return successResponse({ stats: result.rows[0] });
  } catch (error: any) {
    console.error('Error fetching property template stats:', error);
    return errorResponse(error.message);
  }
}
