# SQL Generation - Quick Reference

## How to Use

1. **Open Studio** - Navigate to any project version
2. **Click "Generate" tab** - Switch from Canvas to Generate view
3. **Select "SQL"** from language dropdown
4. **Choose dialect** - PostgreSQL, MySQL, SQL Server, Oracle, or SQLite
5. **View SQL** - Monaco editor shows generated SQL DDL
6. **Copy or Export** - Use buttons to copy or download SQL file

## Supported Dialects

| Dialect | File Extension | Key Features |
|---------|---------------|--------------|
| PostgreSQL | `.sql` | UUID, JSONB, advanced indexes, COMMENT statements |
| MySQL | `.sql` | AUTO_INCREMENT, ENUM types, InnoDB engine |
| SQL Server | `.sql` | IDENTITY, UNIQUEIDENTIFIER, extended properties |
| Oracle | `.sql` | NUMBER, VARCHAR2, CLOB, tablespace hints |
| SQLite | `.sql` | Simplified types, AUTOINCREMENT, embedded-friendly |

## Generated SQL Includes

✅ CREATE TABLE statements  
✅ Primary keys (auto-generated IDs)  
✅ Foreign keys (from `$ref` relationships)  
✅ Unique constraints  
✅ NOT NULL constraints  
✅ CHECK constraints (from enums, min/max)  
✅ DEFAULT values  
✅ Indexes on foreign keys  
✅ SQL comments and documentation  

## Type Mapping Examples

### String Types
- `string` → TEXT/VARCHAR/NVARCHAR
- `string` (format: date) → DATE
- `string` (format: date-time) → TIMESTAMP/DATETIME
- `string` (format: uuid) → UUID/UNIQUEIDENTIFIER/CHAR(36)
- `string` (format: email) → VARCHAR(255)

### Numeric Types
- `integer` → INTEGER/INT/NUMBER(10)
- `number` → NUMERIC/DECIMAL/REAL

### Boolean
- `boolean` → BOOLEAN/TINYINT(1)/BIT/NUMBER(1)

### Complex Types
- `array` → JSONB/JSON/TEXT (serialized)
- `object` → JSONB/JSON/TEXT (serialized)

## Example Output

```sql
-- SQL DDL Generated from Objectified Schema
-- Dialect: POSTGRESQL
-- Generated: 2024-12-08T...

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username VARCHAR(50) NOT NULL,
  email VARCHAR(255) NOT NULL,
  UNIQUE (username)
);

CREATE INDEX idx_users_email ON users(email);
```

## Keyboard Shortcuts (Monaco Editor)

- `Cmd/Ctrl + F` - Find
- `Cmd/Ctrl + A` - Select all
- `Cmd/Ctrl + C` - Copy
- `Cmd/Ctrl + /` - Toggle comment

## Tips

💡 **Foreign Keys**: Add `$ref` properties to classes to generate FK relationships  
💡 **Constraints**: Use `required`, `unique`, `enum` to add constraints  
💡 **Validation**: Set min/max to generate CHECK constraints  
💡 **Naming**: Class names are converted to snake_case for table names  
💡 **Export**: Each dialect gets its own filename (e.g., `schema_postgresql.sql`)  

## Coming Soon

- [ ] Include DROP TABLE statements option
- [ ] Custom schema/database name
- [ ] Migration script generation
- [ ] Seed data (INSERT statements)

---

**Need Help?** Check the full documentation: `docs/SQL_GENERATION_FEATURE.md`

