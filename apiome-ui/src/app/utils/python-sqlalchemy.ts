/**
 * Python SQLAlchemy ORM Generator Utilities
 *
 * Generates SQLAlchemy 2.0+ ORM models from class definitions.
 * Supports:
 * - Declarative base models
 * - Mapped type hints
 * - Relationships (one-to-many, many-to-many)
 * - Constraints (primary key, foreign key, unique, check)
 * - Indexes
 * - Column types from OpenAPI formats
 */

interface SQLAlchemyOptions {
  includeRelationships?: boolean;
  generateMigrations?: boolean;
  databaseType?: 'postgresql' | 'mysql' | 'sqlite';
  customTableNames?: boolean;
}

/**
 * Maps JSON Schema types to SQLAlchemy column types
 */
function mapTypeToSQLAlchemy(propData: any, dbType: string = 'postgresql'): {
  type: string;
  needsImport: Set<string>;
} {
  const needsImport = new Set<string>();

  // Handle array types (usually JSON in SQL)
  if (propData.type === 'array') {
    if (dbType === 'postgresql') {
      needsImport.add('ARRAY');
      const itemResult = mapTypeToSQLAlchemy(propData.items || {}, dbType);
      itemResult.needsImport.forEach(imp => needsImport.add(imp));
      return { type: `ARRAY(${itemResult.type})`, needsImport };
    } else {
      needsImport.add('JSON');
      return { type: 'JSON', needsImport };
    }
  }

  // Handle object types (JSON in SQL)
  if (propData.type === 'object') {
    if (dbType === 'postgresql') {
      needsImport.add('JSONB');
      return { type: 'JSONB', needsImport };
    } else {
      needsImport.add('JSON');
      return { type: 'JSON', needsImport };
    }
  }

  // Handle string types with format
  if (propData.type === 'string') {
    if (propData.format === 'date') {
      needsImport.add('Date');
      return { type: 'Date', needsImport };
    }
    if (propData.format === 'date-time') {
      needsImport.add('DateTime');
      return { type: 'DateTime', needsImport };
    }
    if (propData.format === 'uuid') {
      if (dbType === 'postgresql') {
        needsImport.add('UUID');
        return { type: 'UUID(as_uuid=True)', needsImport };
      } else {
        needsImport.add('String');
        return { type: 'String(36)', needsImport };
      }
    }
    if (propData.format === 'email' || propData.format === 'uri' || propData.format === 'url') {
      needsImport.add('String');
      return { type: 'String(255)', needsImport };
    }

    // Regular string with length
    needsImport.add('String');
    const maxLen = propData.maxLength || 255;
    return { type: `String(${maxLen})`, needsImport };
  }

  // Handle enum types
  if (propData.enum && Array.isArray(propData.enum)) {
    needsImport.add('Enum');
    const enumName = 'str';  // Could be more sophisticated
    return { type: `Enum(${enumName})`, needsImport };
  }

  // Handle numeric types
  if (propData.type === 'integer') {
    if (propData.format === 'int32') {
      needsImport.add('Integer');
      return { type: 'Integer', needsImport };
    }
    if (propData.format === 'int64') {
      needsImport.add('BigInteger');
      return { type: 'BigInteger', needsImport };
    }
    needsImport.add('Integer');
    return { type: 'Integer', needsImport };
  }

  if (propData.type === 'number') {
    if (propData.format === 'float') {
      needsImport.add('Float');
      return { type: 'Float', needsImport };
    }
    needsImport.add('Numeric');
    return { type: 'Numeric', needsImport };
  }

  if (propData.type === 'boolean') {
    needsImport.add('Boolean');
    return { type: 'Boolean', needsImport };
  }

  // Default to String
  needsImport.add('String');
  return { type: 'String(255)', needsImport };
}

/**
 * Maps JSON Schema types to Python type hints for Mapped[]
 */
function mapTypeToPythonHint(propData: any): { type: string; needsImport: Set<string> } {
  const needsImport = new Set<string>();

  // Handle $ref (relationships)
  if (propData.$ref) {
    const refParts = propData.$ref.split('/');
    const refClassName = refParts[refParts.length - 1];
    return { type: `"${refClassName}"`, needsImport };
  }

  // Handle array types
  if (propData.type === 'array') {
    if (propData.items && propData.items.$ref) {
      const refParts = propData.items.$ref.split('/');
      const refClassName = refParts[refParts.length - 1];
      needsImport.add('list');
      return { type: `list["${refClassName}"]`, needsImport };
    }
    needsImport.add('list');
    return { type: 'list', needsImport };
  }

  // Handle object types
  if (propData.type === 'object') {
    needsImport.add('dict');
    return { type: 'dict', needsImport };
  }

  // Basic types
  switch (propData.type) {
    case 'string':
      return { type: 'str', needsImport };
    case 'integer':
      return { type: 'int', needsImport };
    case 'number':
      return { type: 'float', needsImport };
    case 'boolean':
      return { type: 'bool', needsImport };
    default:
      return { type: 'str', needsImport };
  }
}

/**
 * Generates check constraints for validation
 */
function generateCheckConstraints(propName: string, propData: any): string[] {
  const constraints: string[] = [];

  if (propData.minimum !== undefined && (propData.type === 'integer' || propData.type === 'number')) {
    constraints.push(`${propName} >= ${propData.minimum}`);
  }
  if (propData.maximum !== undefined && (propData.type === 'integer' || propData.type === 'number')) {
    constraints.push(`${propName} <= ${propData.maximum}`);
  }
  if (propData.minLength !== undefined && propData.type === 'string') {
    constraints.push(`LENGTH(${propName}) >= ${propData.minLength}`);
  }
  if (propData.maxLength !== undefined && propData.type === 'string') {
    constraints.push(`LENGTH(${propName}) <= ${propData.maxLength}`);
  }

  return constraints;
}

/**
 * Generates SQLAlchemy ORM models
 */
export function generateSQLAlchemyModels(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    includeRelationships?: boolean;
    databaseType?: 'postgresql' | 'mysql' | 'sqlite';
    customTableNames?: boolean;
    includeIndexes?: boolean;
  }
): string {
  const dbType = options?.databaseType || 'postgresql';
  const columnImports = new Set<string>(['Integer', 'String']);
  const ormImports = new Set<string>(['DeclarativeBase', 'Mapped', 'mapped_column']);

  if (options?.includeRelationships) {
    ormImports.add('relationship');
  }

  // Pre-scan for needed imports
  classes.forEach((cls) => {
    (cls.properties || []).forEach((prop: any) => {
      const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
      const typeResult = mapTypeToSQLAlchemy(propData, dbType);
      typeResult.needsImport.forEach(imp => columnImports.add(imp));
    });
  });

  // Build header
  let code = '"""\n';
  code += `${options?.projectName || 'Database Models'}\n`;
  if (options?.version) code += `Version: ${options.version}\n`;
  if (options?.description) code += `\n${options.description}\n`;
  code += '\nGenerated by Apiome Studio using SQLAlchemy 2.0+\n';
  code += '"""\n\n';

  // Imports
  code += `from sqlalchemy import ${Array.from(columnImports).sort().join(', ')}\n`;
  code += `from sqlalchemy.orm import ${Array.from(ormImports).sort().join(', ')}\n`;
  code += 'from typing import Optional\n\n';

  // Base class
  code += 'class Base(DeclarativeBase):\n';
  code += '    """Base class for all models"""\n';
  code += '    pass\n\n\n';

  // Generate each model
  classes.forEach((cls, index) => {
    if (index > 0) code += '\n\n';

    const schema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : (cls.schema || {});
    const tableName = options?.customTableNames
      ? cls.name.toLowerCase()
      : cls.name.toLowerCase() + 's';

    // Class header
    code += `class ${cls.name}(Base):\n`;
    code += `    """${cls.description || schema.description || cls.name + ' model'}"""\n`;
    code += `    __tablename__ = "${tableName}"\n\n`;

    // Generate columns
    if (!cls.properties || cls.properties.length === 0) {
      code += '    pass\n';
    } else {
      // Check if there's an 'id' field, if not add one
      const hasId = cls.properties.some((p: any) => p.name === 'id');
      if (!hasId) {
        code += '    id: Mapped[int] = mapped_column(primary_key=True)\n';
      }

      cls.properties.forEach((prop: any) => {
        const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;

        // Skip relationships for now (would need $ref analysis)
        if (propData.$ref) {
          // This would be a ForeignKey relationship
          return;
        }

        const typeResult = mapTypeToSQLAlchemy(propData, dbType);
        const hintResult = mapTypeToPythonHint(propData);
        const isOptional = !propData.required;
        const pythonHint = isOptional ? `Optional[${hintResult.type}]` : hintResult.type;

        // Build mapped_column parameters
        const columnParams: string[] = [typeResult.type];

        // Primary key
        if (prop.name === 'id') {
          columnParams.push('primary_key=True');
        }

        // Nullable
        if (propData.required) {
          columnParams.push('nullable=False');
        }

        // Unique constraint
        if (propData.uniqueItems || prop.name === 'email') {
          columnParams.push('unique=True');
        }

        // Default value
        if (propData.default !== undefined) {
          if (typeof propData.default === 'string') {
            columnParams.push(`default="${propData.default}"`);
          } else {
            columnParams.push(`default=${propData.default}`);
          }
        }

        // Generate the column
        code += `    ${prop.name}: Mapped[${pythonHint}] = mapped_column(${columnParams.join(', ')})`;

        // Add comment
        if (prop.description || propData.description) {
          code += `  # ${prop.description || propData.description}`;
        }
        code += '\n';
      });

      // Add __repr__ method
      code += '\n    def __repr__(self) -> str:\n';
      code += `        return f"<${cls.name}(id={self.id})>"\n`;
    }
  });

  // Add Alembic migration hint
  if (options?.includeRelationships) {
    code += '\n\n# To generate migrations, run:\n';
    code += '# alembic revision --autogenerate -m "Initial migration"\n';
    code += '# alembic upgrade head\n';
  }

  return code;
}

