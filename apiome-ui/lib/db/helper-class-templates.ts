// Helper functions for class template management
'use server';

const connectionPool = require('./db');

// =============================================================================
// Class Template Types
// =============================================================================

export interface ClassTemplate {
  id: string;
  name: string;
  description: string | null;
  category: string;
  schema: any;
  tags: string[];
  tenant_id: string | null;
  created_by: string | null;
  is_system: boolean;
  is_public: boolean;
  usage_count: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ClassTemplateCategory {
  category: string;
  count: number;
}

// =============================================================================
// Class Template Functions
// =============================================================================

/**
 * Get all class templates visible to a tenant
 * Returns system templates + tenant's own templates + public templates from other tenants
 */
export async function getClassTemplates(tenantId?: string | null, category?: string | null) {
  try {
    let query = `
      SELECT id, name, description, category, schema, tags, tenant_id, created_by,
             is_system, is_public, usage_count, enabled, created_at, updated_at
      FROM apiome.class_templates
      WHERE deleted_at IS NULL AND enabled = true
        AND (
          is_system = true 
          OR is_public = true
          ${tenantId ? 'OR tenant_id = $1' : ''}
        )
    `;

    const params: any[] = [];
    if (tenantId) {
      params.push(tenantId);
    }

    if (category) {
      params.push(category);
      query += ` AND category = $${params.length}`;
    }

    query += ' ORDER BY is_system DESC, category, usage_count DESC, name';

    const result = await connectionPool.query(query, params);
    return JSON.stringify({ success: true, templates: result.rows });
  } catch (error: any) {
    console.error('Error fetching class templates:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Get class template categories with counts
 */
export async function getClassTemplateCategories(tenantId?: string | null) {
  try {
    let query = `
      SELECT category, COUNT(*) as count
      FROM apiome.class_templates
      WHERE deleted_at IS NULL AND enabled = true
        AND (
          is_system = true 
          OR is_public = true
          ${tenantId ? 'OR tenant_id = $1' : ''}
        )
      GROUP BY category
      ORDER BY category
    `;

    const params: any[] = tenantId ? [tenantId] : [];
    const result = await connectionPool.query(query, params);
    return JSON.stringify({ success: true, categories: result.rows });
  } catch (error: any) {
    console.error('Error fetching class template categories:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Search class templates by name, description, or tags
 */
export async function searchClassTemplates(
  searchQuery: string,
  tenantId?: string | null,
  category?: string | null
) {
  try {
    const params: any[] = [`%${searchQuery}%`];
    let paramIndex = 1;

    let query = `
      SELECT id, name, description, category, schema, tags, tenant_id, created_by,
             is_system, is_public, usage_count, enabled, created_at, updated_at
      FROM apiome.class_templates
      WHERE deleted_at IS NULL AND enabled = true
        AND (
          is_system = true 
          OR is_public = true
          ${tenantId ? `OR tenant_id = $${++paramIndex}` : ''}
        )
        AND (
          name ILIKE $1
          OR description ILIKE $1
          OR $1 ILIKE ANY(tags)
        )
    `;

    if (tenantId) {
      params.push(tenantId);
    }

    if (category) {
      params.push(category);
      query += ` AND category = $${++paramIndex}`;
    }

    query += ' ORDER BY usage_count DESC, name';

    const result = await connectionPool.query(query, params);
    return JSON.stringify({ success: true, templates: result.rows });
  } catch (error: any) {
    console.error('Error searching class templates:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Get a single class template by ID with its dependencies
 */
export async function getClassTemplateById(templateId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT id, name, description, category, schema, tags, tenant_id, created_by,
              is_system, is_public, usage_count, enabled, created_at, updated_at
       FROM apiome.class_templates
       WHERE id = $1 AND deleted_at IS NULL`,
      [templateId]
    );

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Template not found' });
    }

    // Fetch dependencies
    const depsResult = await connectionPool.query(
      `SELECT d.id, d.template_id, d.depends_on_template_id, d.ref_path, 
              d.property_name, d.is_required, d.created_at,
              t.name as depends_on_template_name
       FROM apiome.class_template_dependencies d
       JOIN apiome.class_templates t ON t.id = d.depends_on_template_id
       WHERE d.template_id = $1 AND t.deleted_at IS NULL`,
      [templateId]
    );

    const template = result.rows[0];
    template.dependencies = depsResult.rows;

    return JSON.stringify({ success: true, template });
  } catch (error: any) {
    console.error('Error fetching class template:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Get dependencies for a template
 */
export async function getTemplateDependencies(templateId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT d.id, d.template_id, d.depends_on_template_id, d.ref_path, 
              d.property_name, d.is_required, d.created_at,
              t.name as depends_on_template_name, t.category, t.description
       FROM apiome.class_template_dependencies d
       JOIN apiome.class_templates t ON t.id = d.depends_on_template_id
       WHERE d.template_id = $1 AND t.deleted_at IS NULL AND t.enabled = true
       ORDER BY d.is_required DESC, t.name`,
      [templateId]
    );

    return JSON.stringify({ success: true, dependencies: result.rows });
  } catch (error: any) {
    console.error('Error fetching template dependencies:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Add a dependency to a template
 */
export async function addTemplateDependency(
  templateId: string,
  dependsOnTemplateId: string,
  refPath?: string,
  propertyName?: string,
  isRequired: boolean = true
) {
  try {
    const result = await connectionPool.query(
      `INSERT INTO apiome.class_template_dependencies 
       (template_id, depends_on_template_id, ref_path, property_name, is_required)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, template_id, depends_on_template_id, ref_path, property_name, is_required, created_at`,
      [templateId, dependsOnTemplateId, refPath || null, propertyName || null, isRequired]
    );

    return JSON.stringify({ success: true, dependency: result.rows[0] });
  } catch (error: any) {
    console.error('Error adding template dependency:', error);
    if (error.code === '23505') {
      return JSON.stringify({ success: false, error: 'This dependency already exists' });
    }
    if (error.code === '23514') {
      return JSON.stringify({ success: false, error: 'A template cannot depend on itself' });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Remove a dependency from a template
 */
export async function removeTemplateDependency(dependencyId: string) {
  try {
    await connectionPool.query(
      `DELETE FROM apiome.class_template_dependencies WHERE id = $1`,
      [dependencyId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error removing template dependency:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Create a new class template
 */
export async function createClassTemplate(
  name: string,
  description: string | null,
  category: string,
  schema: any,
  tags: string[],
  tenantId: string | null,
  createdBy: string | null,
  isPublic: boolean = true
) {
  try {
    const result = await connectionPool.query(
      `INSERT INTO apiome.class_templates 
       (name, description, category, schema, tags, tenant_id, created_by, is_public)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       RETURNING id, name, description, category, schema, tags, tenant_id, created_by,
                 is_system, is_public, usage_count, enabled, created_at, updated_at`,
      [name, description, category, JSON.stringify(schema), tags, tenantId, createdBy, isPublic]
    );

    return JSON.stringify({ success: true, template: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating class template:', error);
    if (error.code === '23505') {
      return JSON.stringify({ success: false, error: 'A template with this name already exists in this category' });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Update a class template
 */
export async function updateClassTemplate(
  templateId: string,
  tenantId: string,
  updates: {
    name?: string;
    description?: string | null;
    category?: string;
    schema?: any;
    tags?: string[];
    isPublic?: boolean;
    enabled?: boolean;
  }
) {
  try {
    // First check if template exists and user has permission
    const checkResult = await connectionPool.query(
      `SELECT id, is_system, tenant_id FROM apiome.class_templates 
       WHERE id = $1 AND deleted_at IS NULL`,
      [templateId]
    );

    if (checkResult.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Template not found' });
    }

    const template = checkResult.rows[0];

    if (template.is_system) {
      return JSON.stringify({ success: false, error: 'System templates cannot be modified' });
    }

    if (template.tenant_id && template.tenant_id !== tenantId) {
      return JSON.stringify({ success: false, error: 'You do not have permission to modify this template' });
    }

    // Build update query
    const setClauses: string[] = ['updated_at = CURRENT_TIMESTAMP'];
    const params: any[] = [templateId];
    let paramIndex = 1;

    if (updates.name !== undefined) {
      setClauses.push(`name = $${++paramIndex}`);
      params.push(updates.name);
    }
    if (updates.description !== undefined) {
      setClauses.push(`description = $${++paramIndex}`);
      params.push(updates.description);
    }
    if (updates.category !== undefined) {
      setClauses.push(`category = $${++paramIndex}`);
      params.push(updates.category);
    }
    if (updates.schema !== undefined) {
      setClauses.push(`schema = $${++paramIndex}`);
      params.push(JSON.stringify(updates.schema));
    }
    if (updates.tags !== undefined) {
      setClauses.push(`tags = $${++paramIndex}`);
      params.push(updates.tags);
    }
    if (updates.isPublic !== undefined) {
      setClauses.push(`is_public = $${++paramIndex}`);
      params.push(updates.isPublic);
    }
    if (updates.enabled !== undefined) {
      setClauses.push(`enabled = $${++paramIndex}`);
      params.push(updates.enabled);
    }

    const result = await connectionPool.query(
      `UPDATE apiome.class_templates 
       SET ${setClauses.join(', ')}
       WHERE id = $1
       RETURNING id, name, description, category, schema, tags, tenant_id, created_by,
                 is_system, is_public, usage_count, enabled, created_at, updated_at`,
      params
    );

    return JSON.stringify({ success: true, template: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating class template:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Delete a class template (soft delete)
 */
export async function deleteClassTemplate(templateId: string, tenantId: string) {
  try {
    // Check if template exists and user has permission
    const checkResult = await connectionPool.query(
      `SELECT id, is_system, tenant_id FROM apiome.class_templates 
       WHERE id = $1 AND deleted_at IS NULL`,
      [templateId]
    );

    if (checkResult.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Template not found' });
    }

    const template = checkResult.rows[0];

    if (template.is_system) {
      return JSON.stringify({ success: false, error: 'System templates cannot be deleted' });
    }

    if (template.tenant_id && template.tenant_id !== tenantId) {
      return JSON.stringify({ success: false, error: 'You do not have permission to delete this template' });
    }

    await connectionPool.query(
      `UPDATE apiome.class_templates SET deleted_at = CURRENT_TIMESTAMP WHERE id = $1`,
      [templateId]
    );

    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting class template:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Use a class template to create a new class with its properties and dependencies
 * Creates the class, all associated properties, and any dependent classes from templates
 * @param templateId - The template to use
 * @param versionId - The version to create the class in
 * @param projectId - The project for properties
 * @param customName - Optional custom name for the main class
 * @param includeDependencies - Whether to also create dependent classes (default: true)
 * @param createdTemplateIds - Set of template IDs already created (prevents infinite loops)
 */
export async function useClassTemplate(
  templateId: string,
  versionId: string,
  projectId: string,
  customName?: string | null,
  includeDependencies: boolean = true,
  createdTemplateIds?: Set<string>
) {
  const client = await connectionPool.connect();
  const alreadyCreated = createdTemplateIds || new Set<string>();

  try {
    await client.query('BEGIN');

    // Prevent infinite loops - if we've already processed this template, skip
    if (alreadyCreated.has(templateId)) {
      await client.query('COMMIT');
      return JSON.stringify({
        success: true,
        skipped: true,
        message: 'Template already created in this batch'
      });
    }

    // Get the template
    const templateResult = await client.query(
      `SELECT id, name, description, schema FROM apiome.class_templates 
       WHERE id = $1 AND deleted_at IS NULL AND enabled = true`,
      [templateId]
    );

    if (templateResult.rowCount === 0) {
      await client.query('ROLLBACK');
      return JSON.stringify({ success: false, error: 'Template not found' });
    }

    const template = templateResult.rows[0];
    const className = customName?.trim() || template.name;
    const schema = typeof template.schema === 'string' ? JSON.parse(template.schema) : template.schema;

    // Check if class with this name already exists in the version
    const existingClassCheck = await client.query(
      `SELECT id FROM apiome.classes WHERE version_id = $1 AND name = $2 AND deleted_at IS NULL`,
      [versionId, className]
    );

    if (existingClassCheck.rowCount > 0) {
      // Class already exists - mark as created and continue (not an error for dependencies)
      alreadyCreated.add(templateId);
      await client.query('COMMIT');
      return JSON.stringify({
        success: true,
        skipped: true,
        existingClassId: existingClassCheck.rows[0].id,
        message: `Class "${className}" already exists in this version`
      });
    }

    // Mark this template as being created
    alreadyCreated.add(templateId);

    // First, create dependent classes if requested
    const createdDependencies: any[] = [];
    if (includeDependencies) {
      const depsResult = await client.query(
        `SELECT d.depends_on_template_id, t.name as template_name
         FROM apiome.class_template_dependencies d
         JOIN apiome.class_templates t ON t.id = d.depends_on_template_id
         WHERE d.template_id = $1 AND t.deleted_at IS NULL AND t.enabled = true`,
        [templateId]
      );

      // Release connection temporarily to allow recursive calls to get their own connections
      await client.query('COMMIT');
      client.release();

      for (const dep of depsResult.rows) {
        if (!alreadyCreated.has(dep.depends_on_template_id)) {
          try {
            const depResult = await useClassTemplate(
              dep.depends_on_template_id,
              versionId,
              projectId,
              null, // Use template's default name for dependencies
              true, // Also include nested dependencies
              alreadyCreated
            );
            const parsedResult = JSON.parse(depResult);
            if (parsedResult.success) {
              createdDependencies.push({
                templateId: dep.depends_on_template_id,
                templateName: dep.template_name,
                ...parsedResult
              });
            }
          } catch (depError) {
            console.error(`Error creating dependency ${dep.template_name}:`, depError);
            // Continue with other dependencies
          }
        }
      }

      // Reconnect for the main class creation
      const newClient = await connectionPool.connect();
      try {
        await newClient.query('BEGIN');

        // Now create the main class
        const mainResult = await createClassFromTemplate(
          newClient,
          template,
          className,
          schema,
          versionId,
          projectId,
          templateId
        );

        await newClient.query('COMMIT');

        return JSON.stringify({
          ...mainResult,
          dependenciesCreated: createdDependencies
        });
      } catch (error) {
        await newClient.query('ROLLBACK');
        throw error;
      } finally {
        newClient.release();
      }
    } else {
      // No dependencies - create the class directly
      const mainResult = await createClassFromTemplate(
        client,
        template,
        className,
        schema,
        versionId,
        projectId,
        templateId
      );

      await client.query('COMMIT');
      return JSON.stringify(mainResult);
    }
  } catch (error: any) {
    try {
      await client.query('ROLLBACK');
    } catch (rollbackError) {
      // Connection might already be released
    }
    console.error('Error using class template:', error);

    if (error.code === '23505' || error.constraint === 'classes_version_name_unique' || (error.message && String(error.message).includes('duplicate key value'))) {
      const nameHint = error.detail ? (error.detail.match(/\(version_id, name\)=\([^,]+, ([^)]+)\)/)?.[1] ?? '') : '';
      const friendly = nameHint
        ? `A class named "${nameHint}" already exists in this version. Please choose a different name in the Class Name field.`
        : 'A class with this name already exists in this version. Please choose a different name in the Class Name field.';
      return JSON.stringify({ success: false, error: friendly });
    }

    return JSON.stringify({ success: false, error: error.message || 'Failed to create class from template' });
  } finally {
    try {
      client.release();
    } catch (releaseError) {
      // Connection might already be released
    }
  }
}

/**
 * Helper function to create a class from template data
 */
async function createClassFromTemplate(
  client: any,
  template: any,
  className: string,
  schema: any,
  versionId: string,
  projectId: string,
  templateId: string
) {
  // Re-check for duplicate name (e.g. when reconnecting after creating dependencies)
  const dupCheck = await client.query(
    `SELECT id FROM apiome.classes WHERE version_id = $1 AND name = $2 AND deleted_at IS NULL`,
    [versionId, className]
  );
  if (dupCheck.rowCount > 0) {
    const err: any = new Error(`A class named "${className}" already exists in this version. Please choose a different name in the Class Name field.`);
    err.code = '23505';
    err.duplicateClassName = true;
    throw err;
  }

  // Create the class with the full schema
  const classResult = await client.query(
    `INSERT INTO apiome.classes (version_id, name, description, schema)
     VALUES ($1, $2, $3, $4)
     RETURNING id, version_id, name, description, schema, enabled, created_at, updated_at`,
    [versionId, className, schema.description || template.description, JSON.stringify(schema)]
  );

  const newClass = classResult.rows[0];
  const createdProperties: any[] = [];

  // Create properties from the schema
  if (schema.properties && typeof schema.properties === 'object') {
    const requiredProps = Array.isArray(schema.required) ? schema.required : [];

    for (const [propName, propSchema] of Object.entries(schema.properties)) {
      // Check if this property already exists in the project
      let propertyResult = await client.query(
        `SELECT id FROM apiome.properties WHERE project_id = $1 AND name = $2 AND deleted_at IS NULL`,
        [projectId, propName]
      );

      let propertyId: string;
      const propData = {
        ...(propSchema as object),
        required: requiredProps.includes(propName)
      };

      if (propertyResult.rowCount > 0) {
        // Property exists, use it
        propertyId = propertyResult.rows[0].id;
      } else {
        // Create new property
        const newPropResult = await client.query(
          `INSERT INTO apiome.properties (project_id, name, description, data)
           VALUES ($1, $2, $3, $4)
           RETURNING id, name, description, data`,
          [
            projectId,
            propName,
            (propSchema as any).description || null,
            JSON.stringify(propData)
          ]
        );

        propertyId = newPropResult.rows[0].id;
        createdProperties.push(newPropResult.rows[0]);
      }

      // Link property to class (check if link exists first)
      const existingLink = await client.query(
        `SELECT id FROM apiome.class_properties WHERE class_id = $1 AND name = $2 AND parent_id IS NULL`,
        [newClass.id, propName]
      );

      if (existingLink.rowCount === 0) {
        await client.query(
          `INSERT INTO apiome.class_properties (class_id, property_id, name, description, data, parent_id)
           VALUES ($1, $2, $3, $4, $5, $6)`,
          [
            newClass.id,
            propertyId,
            propName,
            (propSchema as any).description || null,
            JSON.stringify(propData),
            null
          ]
        );
      }
    }
  }

  // Increment template usage count
  await client.query(
    `UPDATE apiome.class_templates SET usage_count = usage_count + 1 WHERE id = $1`,
    [templateId]
  );

  return {
    success: true,
    class: newClass,
    propertiesCreated: createdProperties.length,
    propertiesLinked: schema.properties ? Object.keys(schema.properties).length : 0
  };
}

