'use server';

const connectionPool = require('./db');
const bcrypt = require('bcrypt');

export async function getUserByEmail(emailAddress: string) {
  return await connectionPool.query('SELECT * FROM odb.users WHERE email = $1', [emailAddress]);
}

export async function getTenantsForUser(userId: string) {
  const result = await connectionPool.query('SELECT a.* FROM odb.tenants a, odb.tenant_users b WHERE b.user_id = $1 AND a.id = b.tenant_id', [userId]);

  return JSON.stringify(result.rows);
}

export async function getTenantsAdministratedByUser(userId: string) {
  // Get all administrators for tenants where the current user is an admin
  const result = await connectionPool.query(
    `SELECT a.id, a.tenant_id, a.user_id, b.name, b.email 
     FROM odb.tenant_administrators a, odb.users b 
     WHERE b.id = a.user_id 
     AND a.tenant_id IN (
       SELECT tenant_id FROM odb.tenant_administrators WHERE user_id = $1
     )`,
    [userId]
  );

  return JSON.stringify(result.rows);
}

export async function getTenantUsers(tenantId: string) {
  // Get all users for a specific tenant (including administrators)
  const result = await connectionPool.query(
    `SELECT a.id, a.tenant_id, a.user_id, b.name, b.email 
     FROM odb.tenant_users a, odb.users b 
     WHERE b.id = a.user_id 
     AND a.tenant_id = $1`,
    [tenantId]
  );

  return JSON.stringify(result.rows);
}

export async function addTenantAdministrator(tenantId: string, userEmail: string) {
  try {
    // First, get the user by email
    const userResult = await connectionPool.query(
      'SELECT id FROM odb.users WHERE email = $1',
      [userEmail]
    );

    if (userResult.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'User not found' });
    }

    const userId = userResult.rows[0].id;

    // Check if already an admin
    const existingAdmin = await connectionPool.query(
      'SELECT id FROM odb.tenant_administrators WHERE tenant_id = $1 AND user_id = $2',
      [tenantId, userId]
    );

    if (existingAdmin.rowCount > 0) {
      return JSON.stringify({ success: false, error: 'User is already an administrator' });
    }

    // Add to tenant_administrators
    await connectionPool.query(
      'INSERT INTO odb.tenant_administrators (tenant_id, user_id) VALUES ($1, $2)',
      [tenantId, userId]
    );

    // Ensure user is also in tenant_users
    const existingUser = await connectionPool.query(
      'SELECT id FROM odb.tenant_users WHERE tenant_id = $1 AND user_id = $2',
      [tenantId, userId]
    );

    if (existingUser.rowCount === 0) {
      await connectionPool.query(
        'INSERT INTO odb.tenant_users (tenant_id, user_id) VALUES ($1, $2)',
        [tenantId, userId]
      );
    }

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function addTenantUser(tenantId: string, userEmail: string) {
  try {
    // First, get the user by email
    const userResult = await connectionPool.query(
      'SELECT id FROM odb.users WHERE email = $1',
      [userEmail]
    );

    if (userResult.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'User not found' });
    }

    const userId = userResult.rows[0].id;

    // Check if already a member
    const existingUser = await connectionPool.query(
      'SELECT id FROM odb.tenant_users WHERE tenant_id = $1 AND user_id = $2',
      [tenantId, userId]
    );

    if (existingUser.rowCount > 0) {
      return JSON.stringify({ success: false, error: 'User is already a member of this tenant' });
    }

    // Add to tenant_users
    await connectionPool.query(
      'INSERT INTO odb.tenant_users (tenant_id, user_id) VALUES ($1, $2)',
      [tenantId, userId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function removeTenantAdministrator(adminRecordId: string) {
  try {
    await connectionPool.query(
      'DELETE FROM odb.tenant_administrators WHERE id = $1',
      [adminRecordId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function removeTenantUser(userRecordId: string) {
  try {
    await connectionPool.query(
      'DELETE FROM odb.tenant_users WHERE id = $1',
      [userRecordId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function updateUserName(userId: string, name: string) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Name cannot be empty' });
    }

    await connectionPool.query(
      'UPDATE odb.users SET name = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2',
      [name.trim(), userId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function updateUserPassword(userId: string, currentPassword: string, newPassword: string) {
  try {
    // Validate new password format
    if (!newPassword || newPassword.length < 8) {
      return JSON.stringify({ success: false, error: 'Password must be at least 8 characters long' });
    }

    // Check for uppercase letter
    if (!/[A-Z]/.test(newPassword)) {
      return JSON.stringify({ success: false, error: 'Password must contain at least one uppercase letter' });
    }

    // Check for lowercase letter
    if (!/[a-z]/.test(newPassword)) {
      return JSON.stringify({ success: false, error: 'Password must contain at least one lowercase letter' });
    }

    // Check for number or special character
    if (!/[0-9!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(newPassword)) {
      return JSON.stringify({ success: false, error: 'Password must contain at least one number or special character' });
    }

    // Get current password hash from database
    const userResult = await connectionPool.query(
      'SELECT password FROM odb.users WHERE id = $1',
      [userId]
    );

    if (userResult.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'User not found' });
    }

    const currentPasswordHash = userResult.rows[0].password;

    // Verify current password
    const isPasswordValid = await bcrypt.compare(currentPassword, currentPasswordHash);
    if (!isPasswordValid) {
      return JSON.stringify({ success: false, error: 'Current password is incorrect' });
    }

    // Hash new password
    const saltRounds = 10;
    const newPasswordHash = await bcrypt.hash(newPassword, saltRounds);

    // Update password in database
    await connectionPool.query(
      'UPDATE odb.users SET password = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2',
      [newPasswordHash, userId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

// Project Management Functions

export async function getProjectsForTenant(tenantId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT p.*, u.name as creator_name, u.email as creator_email
       FROM odb.projects p
       LEFT JOIN odb.users u ON p.creator_id = u.id
       WHERE p.tenant_id = $1 AND p.deleted_at IS NULL
       ORDER BY p.created_at DESC`,
      [tenantId]
    );

    return JSON.stringify(result.rows);
  } catch (error: any) {
    return JSON.stringify([]);
  }
}

export async function createProject(tenantId: string, creatorId: string, name: string, description: string, slug: string) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Project name is required' });
    }

    if (!slug || slug.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Project slug is required' });
    }

    // Validate slug format (lowercase, alphanumeric, dashes only)
    const slugRegex = /^[a-z0-9-]+$/;
    if (!slugRegex.test(slug.trim())) {
      return JSON.stringify({ success: false, error: 'Slug must contain only lowercase letters, numbers, and dashes' });
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.projects (tenant_id, creator_id, name, description, slug)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING *`,
      [tenantId, creatorId, name.trim(), description?.trim() || null, slug.trim().toLowerCase()]
    );

    return JSON.stringify({ success: true, project: result.rows[0] });
  } catch (error: any) {
    if (error.code === '23505') { // Unique constraint violation
      return JSON.stringify({ success: false, error: 'A project with this slug already exists in this tenant' });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function updateProject(projectId: string, name: string, description: string, slug: string, enabled: boolean) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Project name is required' });
    }

    if (!slug || slug.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Project slug is required' });
    }

    // Validate slug format (lowercase, alphanumeric, dashes only)
    const slugRegex = /^[a-z0-9-]+$/;
    if (!slugRegex.test(slug.trim())) {
      return JSON.stringify({ success: false, error: 'Slug must contain only lowercase letters, numbers, and dashes' });
    }

    await connectionPool.query(
      `UPDATE odb.projects 
       SET name = $1, description = $2, slug = $3, enabled = $4, updated_at = CURRENT_TIMESTAMP
       WHERE id = $5 AND deleted_at IS NULL`,
      [name.trim(), description?.trim() || null, slug.trim().toLowerCase(), enabled, projectId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    if (error.code === '23505') { // Unique constraint violation
      return JSON.stringify({ success: false, error: 'A project with this slug already exists in this tenant' });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function deleteProject(projectId: string) {
  try {
    // Soft delete - set enabled to false and deleted_at timestamp
    await connectionPool.query(
      `UPDATE odb.projects 
       SET enabled = false, deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND deleted_at IS NULL`,
      [projectId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

// Version Management Functions

export async function getVersionsForProject(projectId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT v.*, u.name as creator_name, u.email as creator_email
       FROM odb.versions v
       LEFT JOIN odb.users u ON v.creator_id = u.id
       WHERE v.project_id = $1 AND v.deleted_at IS NULL
       ORDER BY v.created_at DESC`,
      [projectId]
    );

    return JSON.stringify(result.rows);
  } catch (error: any) {
    return JSON.stringify([]);
  }
}

export async function getLatestVersionForProject(projectId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT version_id
       FROM odb.versions
       WHERE project_id = $1 AND deleted_at IS NULL
       ORDER BY created_at DESC
       LIMIT 1`,
      [projectId]
    );

    return result.rowCount > 0 ? result.rows[0].version_id : null;
  } catch (error: any) {
    return null;
  }
}

function parseSemanticVersion(version: string): { major: number, minor: number, patch: number } | null {
  const match = version.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) return null;

  return {
    major: parseInt(match[1], 10),
    minor: parseInt(match[2], 10),
    patch: parseInt(match[3], 10)
  };
}

function bumpMinorVersion(version: string): string {
  const parsed = parseSemanticVersion(version);
  if (!parsed) return '0.1.0';

  return `${parsed.major}.${parsed.minor + 1}.0`;
}

export async function copyClassesFromVersion(sourceVersionId: string, targetVersionId: string) {
  try {
    // Copy all classes from source version to target version
    const result = await connectionPool.query(
      `INSERT INTO odb.classes (version_id, name, description, schema, enabled)
       SELECT $1, name, description, schema, enabled
       FROM odb.classes
       WHERE version_id = $2 AND deleted_at IS NULL
       RETURNING id, name`,
      [targetVersionId, sourceVersionId]
    );

    const copiedClasses = result.rows;

    // For each copied class, copy its properties
    for (const copiedClass of copiedClasses) {
      // Find the original class by name in the source version
      const originalClassResult = await connectionPool.query(
        `SELECT id FROM odb.classes
         WHERE version_id = $1 AND name = $2 AND deleted_at IS NULL`,
        [sourceVersionId, copiedClass.name]
      );

      if (originalClassResult.rowCount > 0) {
        const originalClassId = originalClassResult.rows[0].id;
        const newClassId = copiedClass.id;

        // Copy all class properties
        await connectionPool.query(
          `INSERT INTO odb.class_properties (class_id, property_id, name, description, data)
           SELECT $1, property_id, name, description, data
           FROM odb.class_properties
           WHERE class_id = $2`,
          [newClassId, originalClassId]
        );
      }
    }

    return JSON.stringify({ success: true, copiedCount: copiedClasses.length });
  } catch (error: any) {
    console.error('Error copying classes from version:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function createVersion(projectId: string, creatorId: string, versionId: string | null, description: string, changeLog: string, sourceVersionId?: string | null) {
  try {
    let finalVersionId = versionId;

    // If no version ID provided, auto-generate by bumping the latest version
    if (!finalVersionId || finalVersionId.trim().length === 0) {
      const latestVersion = await getLatestVersionForProject(projectId);
      finalVersionId = latestVersion ? bumpMinorVersion(latestVersion) : '0.1.0';
    }

    // Validate semantic versioning format
    if (!parseSemanticVersion(finalVersionId)) {
      return JSON.stringify({ success: false, error: 'Version ID must follow semantic versioning format (e.g., 1.0.0)' });
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.versions (project_id, creator_id, version_id, description, change_log)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING *`,
      [projectId, creatorId, finalVersionId.trim(), description?.trim() || null, changeLog?.trim() || null]
    );

    const newVersion = result.rows[0];

    // If a source version was provided, copy its classes and properties
    if (sourceVersionId && sourceVersionId.trim().length > 0) {
      const copyResult = await copyClassesFromVersion(sourceVersionId, newVersion.id);
      const copyResponse = JSON.parse(copyResult);

      if (!copyResponse.success) {
        // If copy fails, still return success but include warning
        return JSON.stringify({
          success: true,
          version: newVersion,
          copyWarning: copyResponse.error
        });
      }

      return JSON.stringify({
        success: true,
        version: newVersion,
        copiedClasses: copyResponse.copiedCount
      });
    }

    return JSON.stringify({ success: true, version: newVersion });
  } catch (error: any) {
    if (error.code === '23505') { // Unique constraint violation
      return JSON.stringify({ success: false, error: 'A version with this ID already exists for this project' });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function updateVersion(versionRecordId: string, description: string, changeLog: string, enabled: boolean) {
  try {
    // Check if version is published (frozen)
    const versionCheck = await connectionPool.query(
      'SELECT published FROM odb.versions WHERE id = $1 AND deleted_at IS NULL',
      [versionRecordId]
    );

    if (versionCheck.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Version not found' });
    }

    if (versionCheck.rows[0].published) {
      return JSON.stringify({ success: false, error: 'Cannot edit a published version. Published versions are frozen.' });
    }

    await connectionPool.query(
      `UPDATE odb.versions 
       SET description = $1, change_log = $2, enabled = $3, updated_at = CURRENT_TIMESTAMP
       WHERE id = $4 AND deleted_at IS NULL`,
      [description?.trim() || null, changeLog?.trim() || null, enabled, versionRecordId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function publishVersion(versionRecordId: string) {
  try {
    await connectionPool.query(
      `UPDATE odb.versions 
       SET published = true, published_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND deleted_at IS NULL`,
      [versionRecordId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function unpublishVersion(versionRecordId: string) {
  try {
    await connectionPool.query(
      `UPDATE odb.versions 
       SET published = false, published_at = NULL, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND deleted_at IS NULL`,
      [versionRecordId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function deleteVersion(versionRecordId: string) {
  try {
    // Soft delete - set deleted_at timestamp
    await connectionPool.query(
      `UPDATE odb.versions 
       SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND deleted_at IS NULL`,
      [versionRecordId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

// Property Management Functions

export async function getPropertiesForProject(projectId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT id, project_id, name, description, data, enabled, created_at, updated_at
       FROM odb.properties
       WHERE project_id = $1 AND deleted_at IS NULL
       ORDER BY name ASC`,
      [projectId]
    );

    return JSON.stringify(result.rows);
  } catch (error: any) {
    console.error('Error fetching properties:', error);
    return JSON.stringify([]);
  }
}

export async function createProperty(projectId: string, name: string, description: string | null, data: any) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Property name is required' });
    }

    if (!data) {
      return JSON.stringify({ success: false, error: 'Property data is required' });
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.properties (project_id, name, description, data)
       VALUES ($1, $2, $3, $4)
       RETURNING id, project_id, name, description, data, enabled, created_at, updated_at`,
      [projectId, name.trim(), description, JSON.stringify(data)]
    );

    return JSON.stringify({ success: true, property: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating property:', error);

    // Handle unique constraint violation (duplicate name in same project)
    if (error.code === '23505') {
      return JSON.stringify({ success: false, error: 'A property with this name already exists in this project' });
    }

    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function updateProperty(propertyId: string, name: string, description: string | null, data: any) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Property name is required' });
    }

    if (!data) {
      return JSON.stringify({ success: false, error: 'Property data is required' });
    }

    const result = await connectionPool.query(
      `UPDATE odb.properties
       SET name = $1, description = $2, data = $3, updated_at = CURRENT_TIMESTAMP
       WHERE id = $4 AND deleted_at IS NULL
       RETURNING id, project_id, name, description, data, enabled, created_at, updated_at`,
      [name.trim(), description, JSON.stringify(data), propertyId]
    );

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Property not found' });
    }

    return JSON.stringify({ success: true, property: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating property:', error);

    // Handle unique constraint violation
    if (error.code === '23505') {
      return JSON.stringify({ success: false, error: 'A property with this name already exists in this project' });
    }

    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function deleteProperty(propertyId: string) {
  try {
    // Soft delete - set deleted_at timestamp
    const result = await connectionPool.query(
      `UPDATE odb.properties
       SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND deleted_at IS NULL
       RETURNING id`,
      [propertyId]
    );

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Property not found' });
    }

    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting property:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

// Class Management Functions

export async function getClassesForVersion(versionId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT id, version_id, name, description, schema, enabled, created_at, updated_at
       FROM odb.classes
       WHERE version_id = $1 AND deleted_at IS NULL
       ORDER BY name ASC`,
      [versionId]
    );

    return JSON.stringify(result.rows);
  } catch (error: any) {
    console.error('Error fetching classes:', error);
    return JSON.stringify([]);
  }
}

export async function createClass(versionId: string, name: string, description: string | null, schema: any) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Class name is required' });
    }

    if (!schema) {
      return JSON.stringify({ success: false, error: 'Class schema is required' });
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.classes (version_id, name, description, schema)
       VALUES ($1, $2, $3, $4)
       RETURNING id, version_id, name, description, schema, enabled, created_at, updated_at`,
      [versionId, name.trim(), description, JSON.stringify(schema)]
    );

    return JSON.stringify({ success: true, class: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating class:', error);

    // Handle unique constraint violation (duplicate name in same version)
    if (error.code === '23505') {
      return JSON.stringify({ success: false, error: 'A class with this name already exists in this version' });
    }

    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function updateClass(classId: string, name: string, description: string | null, schema: any) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Class name is required' });
    }

    if (!schema) {
      return JSON.stringify({ success: false, error: 'Class schema is required' });
    }

    const result = await connectionPool.query(
      `UPDATE odb.classes
       SET name = $1, description = $2, schema = $3, updated_at = CURRENT_TIMESTAMP
       WHERE id = $4 AND deleted_at IS NULL
       RETURNING id, version_id, name, description, schema, enabled, created_at, updated_at`,
      [name.trim(), description, JSON.stringify(schema), classId]
    );

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Class not found' });
    }

    return JSON.stringify({ success: true, class: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating class:', error);

    // Handle unique constraint violation
    if (error.code === '23505') {
      return JSON.stringify({ success: false, error: 'A class with this name already exists in this version' });
    }

    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function deleteClass(classId: string) {
  try {
    // Soft delete - set deleted_at timestamp
    const result = await connectionPool.query(
      `UPDATE odb.classes
       SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND deleted_at IS NULL
       RETURNING id`,
      [classId]
    );

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Class not found' });
    }

    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting class:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

// Class-Property Relationship Management Functions

export async function getPropertiesForClass(classId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data,
              p.id as property_source_id, p.name as property_source_name
       FROM odb.class_properties cp
       LEFT JOIN odb.properties p ON cp.property_id = p.id
       WHERE cp.class_id = $1
       ORDER BY cp.name ASC`,
      [classId]
    );

    return JSON.stringify(result.rows);
  } catch (error: any) {
    console.error('Error fetching class properties:', error);
    return JSON.stringify([]);
  }
}

export async function addPropertyToClass(classId: string, propertyId: string, name: string, description: string | null, data: any) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Property name is required' });
    }

    if (!data) {
      return JSON.stringify({ success: false, error: 'Property data is required' });
    }

    // Check if property already exists in this class
    const existingCheck = await connectionPool.query(
      'SELECT id FROM odb.class_properties WHERE class_id = $1 AND name = $2',
      [classId, name]
    );

    if (existingCheck.rowCount > 0) {
      return JSON.stringify({ success: false, error: 'A property with this name already exists in this class' });
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.class_properties (class_id, property_id, name, description, data)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, class_id, property_id, name, description, data`,
      [classId, propertyId, name.trim(), description, JSON.stringify(data)]
    );

    return JSON.stringify({ success: true, classProperty: result.rows[0] });
  } catch (error: any) {
    console.error('Error adding property to class:', error);

    // Handle unique constraint violation
    if (error.code === '23505') {
      return JSON.stringify({ success: false, error: 'A property with this name already exists in this class' });
    }

    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function updateClassProperty(classPropertyId: string, name: string, description: string | null, data: any) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'Property name is required' });
    }

    if (!data) {
      return JSON.stringify({ success: false, error: 'Property data is required' });
    }

    const result = await connectionPool.query(
      `UPDATE odb.class_properties
       SET name = $1, description = $2, data = $3
       WHERE id = $4
       RETURNING id, class_id, property_id, name, description, data`,
      [name.trim(), description, JSON.stringify(data), classPropertyId]
    );

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Class property relationship not found' });
    }

    return JSON.stringify({ success: true, classProperty: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating class property:', error);

    // Handle unique constraint violation
    if (error.code === '23505') {
      return JSON.stringify({ success: false, error: 'A property with this name already exists in this class' });
    }

    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function removePropertyFromClass(classPropertyId: string) {
  try {
    const result = await connectionPool.query(
      `DELETE FROM odb.class_properties
       WHERE id = $1
       RETURNING id`,
      [classPropertyId]
    );

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Class property relationship not found' });
    }

    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error removing property from class:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

// OpenAPI Import Functions

export async function importProjectFromOpenAPI(
  tenantId: string,
  creatorId: string,
  projectName: string,
  projectSlug: string,
  projectDescription: string | null,
  versionId: string,
  versionDescription: string | null,
  classes: any[]
) {
  const client = await connectionPool.connect();

  try {
    await client.query('BEGIN');

    // 1. Create the project
    const projectResult = await client.query(
      `INSERT INTO odb.projects (tenant_id, creator_id, name, description, slug)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING *`,
      [tenantId, creatorId, projectName.trim(), projectDescription?.trim() || null, projectSlug.trim().toLowerCase()]
    );

    const project = projectResult.rows[0];

    // 2. Create the version
    const versionResult = await client.query(
      `INSERT INTO odb.versions (project_id, creator_id, version_id, description)
       VALUES ($1, $2, $3, $4)
       RETURNING *`,
      [project.id, creatorId, versionId.trim(), versionDescription?.trim() || null]
    );

    const version = versionResult.rows[0];

    // 3. Collect all unique properties across all classes
    const propertyMap = new Map<string, string>(); // key -> property_id

    for (const cls of classes) {
      for (const prop of cls.properties) {
        const key = JSON.stringify({ name: prop.name, data: prop.data });

        if (!propertyMap.has(key)) {
          // Create the property
          const propResult = await client.query(
            `INSERT INTO odb.properties (project_id, name, description, data)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (project_id, name) DO UPDATE SET data = EXCLUDED.data
             RETURNING id`,
            [project.id, prop.name.trim(), prop.description?.trim() || null, JSON.stringify(prop.data)]
          );

          propertyMap.set(key, propResult.rows[0].id);
        }
      }
    }

    // 4. Create classes and link properties
    for (const cls of classes) {
      // Create the class
      const classResult = await client.query(
        `INSERT INTO odb.classes (version_id, name, description, schema)
         VALUES ($1, $2, $3, $4)
         RETURNING id`,
        [version.id, cls.name.trim(), cls.description?.trim() || null, JSON.stringify({ type: 'object' })]
      );

      const classId = classResult.rows[0].id;

      // Link properties to the class
      for (const prop of cls.properties) {
        const key = JSON.stringify({ name: prop.name, data: prop.data });
        const propertyId = propertyMap.get(key);

        if (propertyId) {
          await client.query(
            `INSERT INTO odb.class_properties (class_id, property_id, name, description, data)
             VALUES ($1, $2, $3, $4, $5)`,
            [classId, propertyId, prop.name.trim(), prop.description?.trim() || null, JSON.stringify(prop.data)]
          );
        }
      }
    }

    await client.query('COMMIT');

    return JSON.stringify({
      success: true,
      project: project,
      version: version
    });
  } catch (error: any) {
    await client.query('ROLLBACK');
    console.error('Error importing project from OpenAPI:', error);

    if (error.code === '23505') {
      if (error.constraint?.includes('slug')) {
        return JSON.stringify({ success: false, error: 'A project with this slug already exists in this tenant' });
      }
      if (error.constraint?.includes('version_id')) {
        return JSON.stringify({ success: false, error: 'A version with this ID already exists for this project' });
      }
    }

    return JSON.stringify({ success: false, error: error.message });
  } finally {
    client.release();
  }
}

// API Key Management Functions

export async function getApiKeysForTenant(tenantId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT id, tenant_id, name, description, key_prefix, last_used_at, expires_at, enabled, created_at, updated_at
       FROM odb.api_keys
       WHERE tenant_id = $1 AND deleted_at IS NULL
       ORDER BY created_at DESC`,
      [tenantId]
    );

    return JSON.stringify(result.rows);
  } catch (error: any) {
    return JSON.stringify([]);
  }
}

export async function createApiKey(tenantId: string, name: string, description: string, expiresInDays: number | null) {
  try {
    if (!name || name.trim().length === 0) {
      return JSON.stringify({ success: false, error: 'API key name is required' });
    }

    // Generate a random API key
    const crypto = require('crypto');
    const apiKey = 'sk_' + crypto.randomBytes(32).toString('hex');
    const keyPrefix = apiKey.substring(0, 12) + '...';

    // Hash the API key for storage
    const saltRounds = 10;
    const keyHash = await bcrypt.hash(apiKey, saltRounds);

    // Calculate expiration date if provided
    let expiresAt = null;
    if (expiresInDays && expiresInDays > 0) {
      const expirationDate = new Date();
      expirationDate.setDate(expirationDate.getDate() + expiresInDays);
      expiresAt = expirationDate;
    }

    // Insert the API key
    const result = await connectionPool.query(
      `INSERT INTO odb.api_keys (tenant_id, name, description, key_hash, key_prefix, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6)
       RETURNING id, key_prefix, created_at`,
      [tenantId, name.trim(), description?.trim() || null, keyHash, keyPrefix, expiresAt]
    );

    // Return the plain API key (only time it will be visible)
    return JSON.stringify({
      success: true,
      apiKey: apiKey,
      id: result.rows[0].id,
      keyPrefix: result.rows[0].key_prefix,
      createdAt: result.rows[0].created_at
    });
  } catch (error: any) {
    if (error.code === '23505') { // Unique constraint violation
      return JSON.stringify({ success: false, error: 'An API key with this name already exists for this tenant' });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function deleteApiKey(apiKeyId: string) {
  try {
    // Soft delete the API key
    await connectionPool.query(
      'UPDATE odb.api_keys SET deleted_at = CURRENT_TIMESTAMP WHERE id = $1',
      [apiKeyId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function toggleApiKeyStatus(apiKeyId: string, enabled: boolean) {
  try {
    await connectionPool.query(
      'UPDATE odb.api_keys SET enabled = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2',
      [enabled, apiKeyId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function updateApiKeyLastUsed(apiKeyId: string) {
  try {
    await connectionPool.query(
      'UPDATE odb.api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE id = $1',
      [apiKeyId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}

export async function validateApiKey(apiKey: string) {
  try {
    // Extract prefix for faster lookup
    const keyPrefix = apiKey.substring(0, 12) + '...';

    // Get all API keys with matching prefix
    const result = await connectionPool.query(
      `SELECT ak.id, ak.tenant_id, ak.key_hash, ak.expires_at, ak.enabled, t.id as tenant_id, t.name as tenant_name
       FROM odb.api_keys ak
       JOIN odb.tenants t ON ak.tenant_id = t.id
       WHERE ak.key_prefix = $1 
       AND ak.deleted_at IS NULL 
       AND ak.enabled = true
       AND t.deleted_at IS NULL
       AND t.enabled = true`,
      [keyPrefix]
    );

    // Check each result to find matching hash
    for (const row of result.rows) {
      const isValid = await bcrypt.compare(apiKey, row.key_hash);

      if (isValid) {
        // Check expiration
        if (row.expires_at && new Date(row.expires_at) < new Date()) {
          return JSON.stringify({ success: false, error: 'API key has expired' });
        }

        // Update last used timestamp
        await updateApiKeyLastUsed(row.id);

        return JSON.stringify({
          success: true,
          tenantId: row.tenant_id,
          tenantName: row.tenant_name,
          apiKeyId: row.id
        });
      }
    }

    return JSON.stringify({ success: false, error: 'Invalid API key' });
  } catch (error: any) {
    return JSON.stringify({ success: false, error: error.message });
  }
}
