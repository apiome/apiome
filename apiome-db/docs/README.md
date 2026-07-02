# Apiome Database

This directory contains database migration scripts and documentation for the Apiome project.

## Migration Scripts

Migration scripts are located in the `scripts/` directory and should be run in order by timestamp:

- `20251026-012616.sql` - Initial schema (users, tenants, tenant_users, tenant_administrators)
- `20251031-223953.sql` - Projects and versions
- `20251101-005912.sql` - Properties table
- `20251101-033329.sql` - Additional schema updates
- `20251101-154100.sql` - Classes and class_properties tables
- `20251108-220159.sql` - API keys and version visibility
- `20251112-182735.sql` - **Nested properties support** (adds parent_id to class_properties)
- `20251114-191956.sql` - NULL property_id support for references
- `20251120-010147.sql` - Signup table
- `20251121-external-auth-providers.sql` - **External authentication providers** (SSO account linking)

## Running Migrations

To run a migration script:

```bash
psql -U postgres -d apiome -f scripts/YYYYMMDD-HHMMSS.sql
```

Or run all migrations in order:

```bash
for file in scripts/*.sql; do
  echo "Running $file..."
  psql -U postgres -d apiome -f "$file"
done
```

## Recent Updates

### NULL property_id Support for References (2025-11-14)

Modified the `class_properties` table to allow NULL values for `property_id`, enabling reference properties to exist without linking to the property library. This supports the new drag-and-drop reference creation workflow.

**Key Changes:**
- Removed NOT NULL constraint from `property_id` column
- Added check constraint to validate NULL property_id entries contain `$ref`
- Updated documentation for property_id column
- Enables references as class-specific relationships

**Migration:**
```bash
psql -U kenji -d kenji -f scripts/20251114-191956.sql
```

**Documentation:**
- [Migration Documentation](MIGRATION_20251114_NULL_PROPERTY_ID.md)
- [Reference Drag-Drop Implementation](../../apiome-ui/docs/REFERENCE_DRAG_DROP_IMPLEMENTATION.md)

### Nested Properties (2025-11-12)

Added support for hierarchical property structures by introducing a `parent_id` column to the `class_properties` table. This allows properties of type "object" to contain inline child properties.

**Key Changes:**
- Added `parent_id UUID` column with self-referential foreign key
- Updated unique constraint to `(class_id, parent_id, name)` for scoped uniqueness
- Added cascade deletion for child properties
- Updated TypeScript and Python code to support nested structures

**Documentation:**
- [Feature Documentation](NESTED_PROPERTIES_FEATURE.md)
- [Implementation Summary](IMPLEMENTATION_SUMMARY_NESTED_PROPERTIES.md)
- [Usage Examples](NESTED_PROPERTIES_EXAMPLE.md)

### External Authentication Providers / Linked Accounts (2025-11-21)

Added support for linking external OAuth provider accounts (GitHub, GitLab, AWS, GCP, etc.) to Apiome user accounts. This enables SSO authentication while keeping the master account data in `apiome.users`.

**Key Features:**
- Link multiple OAuth providers to a single Apiome account
- Auto-link on first OAuth login (if email matches)
- Manual account linking from Dashboard → Linked Accounts
- Unlink accounts at any time
- All database operations are server-side only (no public REST endpoints)
- Secure with unique constraints and foreign key cascades
- User data always sourced from `apiome.users` (never overridden by OAuth data)

**Migration:**
```bash
psql -U your_user -d your_database -f scripts/20251121-external-auth-providers.sql
```

**Documentation:**
- [🚀 Quick Start Guide](LINKED_ACCOUNTS_QUICKSTART.md) - Get started quickly
- [📋 Implementation Summary](LINKED_ACCOUNTS_IMPLEMENTATION.md) - Complete implementation details
- [🏗️ System Architecture](LINKED_ACCOUNTS_ARCHITECTURE.md) - Architecture diagrams and data flow
- [📖 Full Feature Docs](EXTERNAL_AUTH_PROVIDERS.md) - Comprehensive documentation
- [📝 Quick Reference](EXTERNAL_AUTH_PROVIDERS_SUMMARY.md) - Quick reference guide

**UI Location:**
Dashboard → Account → Linked Accounts

## Database Connection

The database connection settings are configured in:
- **REST API**: `apiome-rest/src/app/config.py`
- **UI**: `apiome-ui/lib/db/db.ts`

## Schema

The database uses PostgreSQL with the `apiome` schema. Key tables:

- **tenants**: Multi-tenant organizations
- **users**: Application users
- **external_auth_providers**: OAuth provider accounts linked to users (SSO)
- **projects**: API/schema projects
- **versions**: Project versions
- **classes**: Data object definitions
- **properties**: Reusable property definitions
- **class_properties**: Junction table linking classes to properties (supports nesting via parent_id)
- **groups**: Visual groupings of classes on the canvas with positional metadata
- **group_classes**: Junction table linking groups to their member classes
- **canvas_layouts**: Canvas layout state (positions, viewport, edges) per version
- **api_keys**: External API access keys
- **signup**: User signup requests

## Backup and Restore

### Backup
```bash
pg_dump -U postgres -d apiome > backup_$(date +%Y%m%d_%H%M%S).sql
```

### Restore
```bash
psql -U postgres -d apiome < backup_file.sql
```

## Development

For local development:

1. Ensure PostgreSQL is installed and running
2. Create the database: `createdb -U postgres apiome`
3. Run migrations in order
4. Update connection strings in application configs

