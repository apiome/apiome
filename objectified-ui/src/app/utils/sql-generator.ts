/**
 * SQL DDL Generator Utilities
 *
 * Generates SQL CREATE TABLE statements from class definitions.
 * Supports multiple SQL dialects:
 * - PostgreSQL
 * - MySQL
 * - SQL Server (T-SQL)
 * - Oracle
 * - SQLite
 *
 * Features:
 * - Tables with columns and types
 * - Primary keys
 * - Foreign keys
 * - Unique constraints
 * - Check constraints
 * - Indexes
 * - Comments/documentation
 */

export type SQLDialect = 'postgresql' | 'mysql' | 'sqlserver' | 'oracle' | 'sqlite';

interface SQLGenerationOptions {
  dialect: SQLDialect;
  includeDropStatements?: boolean;
  includeComments?: boolean;
  schemaName?: string;
  namingConvention?: 'snake_case' | 'camelCase' | 'PascalCase';
}

/**
 * Maps JSON Schema types to SQL types based on dialect
 */
function mapTypeToSQL(propData: any, dialect: SQLDialect): string {
  const jsonType = propData.type;
  const format = propData.format;

  // Handle enum as VARCHAR with CHECK constraint
  if (propData.enum && Array.isArray(propData.enum)) {
    switch (dialect) {
      case 'postgresql':
        return 'VARCHAR(255)';
      case 'mysql':
        return `ENUM(${propData.enum.map((v: any) => `'${v}'`).join(', ')})`;
      case 'sqlserver':
        return 'NVARCHAR(255)';
      case 'oracle':
        return 'VARCHAR2(255)';
      case 'sqlite':
        return 'TEXT';
    }
  }

  // Handle $ref (foreign key relationships)
  if (propData.$ref) {
    switch (dialect) {
      case 'postgresql':
        return 'UUID';
      case 'mysql':
        return 'CHAR(36)';
      case 'sqlserver':
        return 'UNIQUEIDENTIFIER';
      case 'oracle':
        return 'VARCHAR2(36)';
      case 'sqlite':
        return 'TEXT';
    }
  }

  // Handle array types (serialize as JSON)
  if (jsonType === 'array') {
    switch (dialect) {
      case 'postgresql':
        return 'JSONB';
      case 'mysql':
        return 'JSON';
      case 'sqlserver':
        return 'NVARCHAR(MAX)';
      case 'oracle':
        return 'CLOB';
      case 'sqlite':
        return 'TEXT';
    }
  }

  // Handle object types (serialize as JSON)
  if (jsonType === 'object') {
    switch (dialect) {
      case 'postgresql':
        return 'JSONB';
      case 'mysql':
        return 'JSON';
      case 'sqlserver':
        return 'NVARCHAR(MAX)';
      case 'oracle':
        return 'CLOB';
      case 'sqlite':
        return 'TEXT';
    }
  }

  // String types with format
  if (jsonType === 'string') {
    if (format === 'date-time' || format === 'date') {
      switch (dialect) {
        case 'postgresql':
          return format === 'date' ? 'DATE' : 'TIMESTAMP';
        case 'mysql':
          return format === 'date' ? 'DATE' : 'DATETIME';
        case 'sqlserver':
          return format === 'date' ? 'DATE' : 'DATETIME2';
        case 'oracle':
          return format === 'date' ? 'DATE' : 'TIMESTAMP';
        case 'sqlite':
          return 'TEXT';
      }
    }
    if (format === 'uuid') {
      switch (dialect) {
        case 'postgresql':
          return 'UUID';
        case 'mysql':
          return 'CHAR(36)';
        case 'sqlserver':
          return 'UNIQUEIDENTIFIER';
        case 'oracle':
          return 'VARCHAR2(36)';
        case 'sqlite':
          return 'TEXT';
      }
    }
    if (format === 'email' || format === 'uri') {
      switch (dialect) {
        case 'postgresql':
          return 'VARCHAR(255)';
        case 'mysql':
          return 'VARCHAR(255)';
        case 'sqlserver':
          return 'NVARCHAR(255)';
        case 'oracle':
          return 'VARCHAR2(255)';
        case 'sqlite':
          return 'TEXT';
      }
    }
    // Default string with length consideration
    const maxLength = propData.maxLength;
    if (maxLength && maxLength <= 255) {
      switch (dialect) {
        case 'postgresql':
          return `VARCHAR(${maxLength})`;
        case 'mysql':
          return `VARCHAR(${maxLength})`;
        case 'sqlserver':
          return `NVARCHAR(${maxLength})`;
        case 'oracle':
          return `VARCHAR2(${maxLength})`;
        case 'sqlite':
          return 'TEXT';
      }
    }
    // Text for longer strings
    switch (dialect) {
      case 'postgresql':
        return 'TEXT';
      case 'mysql':
        return 'TEXT';
      case 'sqlserver':
        return 'NVARCHAR(MAX)';
      case 'oracle':
        return 'CLOB';
      case 'sqlite':
        return 'TEXT';
    }
  }

  // Integer types
  if (jsonType === 'integer') {
    switch (dialect) {
      case 'postgresql':
        return 'INTEGER';
      case 'mysql':
        return 'INT';
      case 'sqlserver':
        return 'INT';
      case 'oracle':
        return 'NUMBER(10)';
      case 'sqlite':
        return 'INTEGER';
    }
  }

  // Number types (float/double)
  if (jsonType === 'number') {
    switch (dialect) {
      case 'postgresql':
        return 'NUMERIC';
      case 'mysql':
        return 'DECIMAL(10,2)';
      case 'sqlserver':
        return 'DECIMAL(10,2)';
      case 'oracle':
        return 'NUMBER';
      case 'sqlite':
        return 'REAL';
    }
  }

  // Boolean types
  if (jsonType === 'boolean') {
    switch (dialect) {
      case 'postgresql':
        return 'BOOLEAN';
      case 'mysql':
        return 'TINYINT(1)';
      case 'sqlserver':
        return 'BIT';
      case 'oracle':
        return 'NUMBER(1)';
      case 'sqlite':
        return 'INTEGER';
    }
  }

  // Default fallback
  switch (dialect) {
    case 'postgresql':
      return 'TEXT';
    case 'mysql':
      return 'TEXT';
    case 'sqlserver':
      return 'NVARCHAR(MAX)';
    case 'oracle':
      return 'CLOB';
    case 'sqlite':
      return 'TEXT';
  }
}

/**
 * Convert name to snake_case
 */
function toSnakeCase(str: string): string {
  if (!str) return '';
  return str
    .replace(/([A-Z])/g, '_$1')
    .toLowerCase()
    .replace(/^_/, '');
}

/**
 * Convert name based on naming convention
 */
function convertName(name: string, convention: 'snake_case' | 'camelCase' | 'PascalCase'): string {
  if (!name) return '';
  if (convention === 'snake_case') {
    return toSnakeCase(name);
  }
  return name; // Keep original for other conventions
}

/**
 * Generate CREATE TABLE statement for a class
 */
function generateTableSQL(
  className: string,
  properties: any[],
  options: SQLGenerationOptions,
  allClasses: any[]
): string {
  const { dialect, includeComments, schemaName, namingConvention = 'snake_case' } = options;
  const tableName = convertName(className, namingConvention);
  const fullTableName = schemaName ? `${schemaName}.${tableName}` : tableName;

  let sql = '';

  // Add comments about the table
  if (includeComments) {
    sql += `-- Table: ${className}\n`;
    sql += `-- Generated from Objectified Schema\n\n`;
  }

  sql += `CREATE TABLE ${fullTableName} (\n`;

  const columns: string[] = [];
  const constraints: string[] = [];
  const foreignKeys: string[] = [];

  // Always add an ID column as primary key
  const idColumnName = convertName('id', namingConvention);
  let idColumn = '';

  switch (dialect) {
    case 'postgresql':
      idColumn = `  ${idColumnName} UUID PRIMARY KEY DEFAULT gen_random_uuid()`;
      break;
    case 'mysql':
      idColumn = `  ${idColumnName} CHAR(36) PRIMARY KEY DEFAULT (UUID())`;
      break;
    case 'sqlserver':
      idColumn = `  ${idColumnName} UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID()`;
      break;
    case 'oracle':
      idColumn = `  ${idColumnName} VARCHAR2(36) PRIMARY KEY`;
      break;
    case 'sqlite':
      idColumn = `  ${idColumnName} TEXT PRIMARY KEY`;
      break;
  }

  columns.push(idColumn);

  // Add properties as columns
  properties.forEach((prop) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {});
    const columnName = convertName(prop.name, namingConvention);
    const sqlType = mapTypeToSQL(propData, dialect);

    let columnDef = `  ${columnName} ${sqlType}`;

    // Add NOT NULL constraint if property is required
    if (propData.required || prop.required) {
      columnDef += ' NOT NULL';
    }

    // Add DEFAULT value if specified
    if (propData.default !== undefined && propData.default !== null) {
      const defaultValue = typeof propData.default === 'string'
        ? `'${propData.default}'`
        : propData.default;
      columnDef += ` DEFAULT ${defaultValue}`;
    }

    columns.push(columnDef);

    // Track foreign key relationships
    if (propData.$ref) {
      const refParts = propData.$ref.split('/');
      const refClassName = refParts[refParts.length - 1];
      const refTableName = convertName(refClassName, namingConvention);
      const refFullTableName = schemaName ? `${schemaName}.${refTableName}` : refTableName;
      const refIdColumn = convertName('id', namingConvention);

      foreignKeys.push(
        `  FOREIGN KEY (${columnName}) REFERENCES ${refFullTableName}(${refIdColumn})`
      );
    }

    // Add UNIQUE constraint if specified
    if (propData.unique || prop.unique) {
      constraints.push(`  UNIQUE (${columnName})`);
    }

    // Add CHECK constraints for enums (PostgreSQL, SQL Server, Oracle, SQLite)
    if (propData.enum && Array.isArray(propData.enum) && dialect !== 'mysql') {
      const enumValues = propData.enum.map((v: any) => `'${v}'`).join(', ');
      constraints.push(`  CHECK (${columnName} IN (${enumValues}))`);
    }

    // Add CHECK constraints for min/max
    if (propData.minimum !== undefined || propData.maximum !== undefined) {
      const checks: string[] = [];
      if (propData.minimum !== undefined) {
        checks.push(`${columnName} >= ${propData.minimum}`);
      }
      if (propData.maximum !== undefined) {
        checks.push(`${columnName} <= ${propData.maximum}`);
      }
      if (checks.length > 0) {
        constraints.push(`  CHECK (${checks.join(' AND ')})`);
      }
    }
  });

  // Combine all parts
  const allParts = [...columns, ...constraints, ...foreignKeys];
  sql += allParts.join(',\n');
  sql += '\n)';

  // Add table-specific options
  switch (dialect) {
    case 'mysql':
      sql += ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci';
      break;
    case 'postgresql':
      // PostgreSQL doesn't need table options here
      break;
  }

  sql += ';\n';

  // Add table comments (PostgreSQL style)
  if (includeComments && dialect === 'postgresql') {
    sql += `\nCOMMENT ON TABLE ${fullTableName} IS 'Generated from ${className} schema';\n`;
  }

  return sql;
}

/**
 * Generate CREATE INDEX statements for a table
 */
function generateIndexSQL(
  className: string,
  properties: any[],
  options: SQLGenerationOptions
): string {
  const { dialect, schemaName, namingConvention = 'snake_case' } = options;
  const tableName = convertName(className, namingConvention);
  const fullTableName = schemaName ? `${schemaName}.${tableName}` : tableName;

  let sql = '';

  properties.forEach((prop) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {});

    // Create indexes for foreign keys
    if (propData.$ref) {
      const columnName = convertName(prop.name, namingConvention);
      const indexName = `idx_${tableName}_${columnName}`;
      sql += `CREATE INDEX ${indexName} ON ${fullTableName}(${columnName});\n`;
    }

    // Create unique indexes
    if (propData.unique || prop.unique) {
      const columnName = convertName(prop.name, namingConvention);
      const indexName = `idx_unique_${tableName}_${columnName}`;
      sql += `CREATE UNIQUE INDEX ${indexName} ON ${fullTableName}(${columnName});\n`;
    }
  });

  return sql;
}

/**
 * Main function to generate SQL DDL from classes
 */
export function generateSQL(
  classes: any[],
  dialect: SQLDialect = 'postgresql',
  options: Partial<SQLGenerationOptions> = {}
): string {
  const fullOptions: SQLGenerationOptions = {
    dialect,
    includeDropStatements: false,
    includeComments: true,
    schemaName: '',
    namingConvention: 'snake_case',
    ...options,
  };

  try {
    if (!classes || classes.length === 0) {
      return `-- No classes defined\n-- Add classes to the canvas to generate SQL DDL`;
    }

    let sql = '';

    // Header comment
    sql += `-- SQL DDL Generated from Objectified Schema\n`;
    sql += `-- Dialect: ${fullOptions.dialect.toUpperCase()}\n`;
    sql += `-- Generated: ${new Date().toISOString()}\n\n`;

    // Add dialect-specific setup
    switch (fullOptions.dialect) {
      case 'postgresql':
        sql += `-- Enable UUID extension (if not already enabled)\n`;
        sql += `-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";\n`;
        sql += `-- CREATE EXTENSION IF NOT EXISTS "pgcrypto";\n\n`;
        break;
      case 'sqlite':
        sql += `-- Enable foreign keys\n`;
        sql += `PRAGMA foreign_keys = ON;\n\n`;
        break;
    }

    // Use classes that already have properties loaded
    const classesWithProperties = classes;

    // Generate DROP statements if requested
    if (fullOptions.includeDropStatements) {
      sql += `-- Drop existing tables (in reverse order to handle foreign keys)\n`;
      [...classesWithProperties].reverse().forEach((cls) => {
        const tableName = convertName(cls.name, fullOptions.namingConvention!);
        const fullTableName = fullOptions.schemaName
          ? `${fullOptions.schemaName}.${tableName}`
          : tableName;
        sql += `DROP TABLE IF EXISTS ${fullTableName};\n`;
      });
      sql += `\n`;
    }

    // Generate CREATE TABLE statements
    classesWithProperties.forEach((cls, index) => {
      if (index > 0) sql += `\n`;
      sql += generateTableSQL(cls.name, cls.properties, fullOptions, classesWithProperties);
    });

    // Generate indexes
    sql += `\n-- Indexes\n`;
    classesWithProperties.forEach((cls) => {
      const indexSQL = generateIndexSQL(cls.name, cls.properties, fullOptions);
      if (indexSQL) {
        sql += indexSQL;
      }
    });

    return sql;

  } catch (error) {
    console.error('Error generating SQL:', error);
    return `-- Error generating SQL: ${error instanceof Error ? error.message : 'Unknown error'}`;
  }
}

