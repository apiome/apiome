/**
 * SQL Generator Tests
 *
 * Tests for SQL DDL generation from class definitions
 */

import { generateSQL, SQLDialect } from '../src/app/utils/sql-generator';

describe('SQL Generator', () => {
  const mockClasses = [
    {
      id: 'class-1',
      name: 'User',
      description: 'User account',
      properties: [
        {
          id: 'prop-1',
          name: 'name',
          data: JSON.stringify({ type: 'string', maxLength: 100 })
        },
        {
          id: 'prop-2',
          name: 'email',
          data: JSON.stringify({ type: 'string', format: 'email', required: true })
        },
        {
          id: 'prop-3',
          name: 'age',
          data: JSON.stringify({ type: 'integer', minimum: 0, maximum: 150 })
        },
        {
          id: 'prop-4',
          name: 'isActive',
          data: JSON.stringify({ type: 'boolean' })
        }
      ]
    },
    {
      id: 'class-2',
      name: 'Post',
      description: 'Blog post',
      properties: [
        {
          id: 'prop-5',
          name: 'title',
          data: JSON.stringify({ type: 'string', maxLength: 200 })
        },
        {
          id: 'prop-6',
          name: 'content',
          data: JSON.stringify({ type: 'string' })
        },
        {
          id: 'prop-7',
          name: 'authorId',
          data: JSON.stringify({ $ref: '#/components/schemas/User' })
        },
        {
          id: 'prop-8',
          name: 'status',
          data: JSON.stringify({ type: 'string', enum: ['draft', 'published', 'archived'] })
        }
      ]
    }
  ];

  describe('PostgreSQL dialect', () => {
    it('should generate valid PostgreSQL DDL', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain('-- Dialect: POSTGRESQL');
      expect(sql).toContain('CREATE TABLE user');
      expect(sql).toContain('CREATE TABLE post');
    });

    it('should include UUID primary keys', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain('id UUID PRIMARY KEY DEFAULT gen_random_uuid()');
    });

    it('should map string types correctly', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain('VARCHAR(100)');
      expect(sql).toContain('VARCHAR(255)'); // email format
      expect(sql).toContain('TEXT'); // content without maxLength
    });

    it('should include NOT NULL for required fields', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain('email VARCHAR(255) NOT NULL');
    });

    it('should generate CHECK constraints for min/max', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain('CHECK (age >= 0 AND age <= 150)');
    });

    it('should generate CHECK constraints for enums', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain("CHECK (status IN ('draft', 'published', 'archived'))");
    });

    it('should generate foreign key references', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain('FOREIGN KEY (author_id) REFERENCES user(id)');
    });

    it('should generate indexes for foreign keys', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain('CREATE INDEX idx_post_author_id ON post(author_id)');
    });
  });

  describe('MySQL dialect', () => {
    it('should generate valid MySQL DDL', () => {
      const sql = generateSQL(mockClasses, 'mysql');

      expect(sql).toContain('-- Dialect: MYSQL');
      expect(sql).toContain('ENGINE=InnoDB');
      expect(sql).toContain('DEFAULT CHARSET=utf8mb4');
    });

    it('should use CHAR(36) for UUIDs', () => {
      const sql = generateSQL(mockClasses, 'mysql');

      expect(sql).toContain('id CHAR(36) PRIMARY KEY');
    });

    it('should use ENUM type for enums', () => {
      const sql = generateSQL(mockClasses, 'mysql');

      expect(sql).toContain("ENUM('draft', 'published', 'archived')");
    });

    it('should use TINYINT(1) for booleans', () => {
      const sql = generateSQL(mockClasses, 'mysql');

      expect(sql).toContain('TINYINT(1)');
    });
  });

  describe('SQL Server dialect', () => {
    it('should generate valid SQL Server DDL', () => {
      const sql = generateSQL(mockClasses, 'sqlserver');

      expect(sql).toContain('-- Dialect: SQLSERVER');
    });

    it('should use UNIQUEIDENTIFIER for UUIDs', () => {
      const sql = generateSQL(mockClasses, 'sqlserver');

      expect(sql).toContain('UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID()');
    });

    it('should use NVARCHAR types', () => {
      const sql = generateSQL(mockClasses, 'sqlserver');

      expect(sql).toContain('NVARCHAR(100)');
      expect(sql).toContain('NVARCHAR(255)');
    });

    it('should use BIT for booleans', () => {
      const sql = generateSQL(mockClasses, 'sqlserver');

      expect(sql).toContain('BIT');
    });
  });

  describe('Oracle dialect', () => {
    it('should generate valid Oracle DDL', () => {
      const sql = generateSQL(mockClasses, 'oracle');

      expect(sql).toContain('-- Dialect: ORACLE');
    });

    it('should use VARCHAR2 types', () => {
      const sql = generateSQL(mockClasses, 'oracle');

      expect(sql).toContain('VARCHAR2(100)');
      expect(sql).toContain('VARCHAR2(255)');
    });

    it('should use NUMBER for integers', () => {
      const sql = generateSQL(mockClasses, 'oracle');

      expect(sql).toContain('NUMBER(10)');
    });

    it('should use NUMBER(1) for booleans', () => {
      const sql = generateSQL(mockClasses, 'oracle');

      expect(sql).toContain('NUMBER(1)');
    });
  });

  describe('SQLite dialect', () => {
    it('should generate valid SQLite DDL', () => {
      const sql = generateSQL(mockClasses, 'sqlite');

      expect(sql).toContain('-- Dialect: SQLITE');
      expect(sql).toContain('PRAGMA foreign_keys = ON');
    });

    it('should use TEXT for most string types', () => {
      const sql = generateSQL(mockClasses, 'sqlite');

      expect(sql).toContain('TEXT');
    });

    it('should use INTEGER for primary keys', () => {
      const sql = generateSQL(mockClasses, 'sqlite');

      expect(sql).toContain('id TEXT PRIMARY KEY');
    });
  });

  describe('Options', () => {
    it('should include DROP statements when requested', () => {
      const sql = generateSQL(mockClasses, 'postgresql', {
        includeDropStatements: true
      });

      expect(sql).toContain('DROP TABLE IF EXISTS');
    });

    it('should include comments when requested', () => {
      const sql = generateSQL(mockClasses, 'postgresql', {
        includeComments: true
      });

      expect(sql).toContain('-- Table: User');
      expect(sql).toContain('-- Table: Post');
    });

    it('should use schema name when provided', () => {
      const sql = generateSQL(mockClasses, 'postgresql', {
        schemaName: 'public'
      });

      expect(sql).toContain('public.user');
      expect(sql).toContain('public.post');
    });

    it('should convert names to snake_case by default', () => {
      const sql = generateSQL(mockClasses, 'postgresql');

      expect(sql).toContain('author_id');
      expect(sql).toContain('is_active');
    });
  });

  describe('Edge cases', () => {
    it('should handle empty classes array', () => {
      const sql = generateSQL([], 'postgresql');

      expect(sql).toContain('No classes defined');
    });

    it('should handle classes without properties', () => {
      const sql = generateSQL([
        { id: 'empty', name: 'Empty', properties: [] }
      ], 'postgresql');

      expect(sql).toContain('CREATE TABLE empty');
      expect(sql).toContain('id UUID PRIMARY KEY');
    });

    it('should handle properties with object data as string', () => {
      const classes = [
        {
          id: 'test',
          name: 'Test',
          properties: [
            {
              id: 'p1',
              name: 'field',
              data: '{"type":"string"}'
            }
          ]
        }
      ];

      const sql = generateSQL(classes, 'postgresql');
      expect(sql).toContain('field TEXT');
    });

    it('should handle properties with object data as object', () => {
      const classes = [
        {
          id: 'test',
          name: 'Test',
          properties: [
            {
              id: 'p1',
              name: 'field',
              data: { type: 'string' }
            }
          ]
        }
      ];

      const sql = generateSQL(classes, 'postgresql');
      expect(sql).toContain('field TEXT');
    });
  });
});

