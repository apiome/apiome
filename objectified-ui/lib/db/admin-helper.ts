'use server';

const connectionPool = require('./db');
const bcrypt = require('bcrypt');

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
