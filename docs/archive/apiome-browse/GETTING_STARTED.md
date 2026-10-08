# Getting Started with Apiome Browse

This guide will help you set up and run the Apiome Browse application.

## Prerequisites

Before you begin, ensure you have the following installed:

- Node.js 20.x or later
- npm or yarn
- PostgreSQL database with Apiome schema
- apiome-rest service (for fetching specifications)

## Installation Steps

### 1. Install Dependencies

```bash
cd apiome-browse
npm install
```

### 2. Configure Environment Variables

Create a `.env.local` file in the root directory:

```bash
cp .env.example .env.local
```

Edit `.env.local` with your configuration:

```env
# Database configuration (for browsing tenants/projects/versions)
DATABASE_URL=postgresql://postgres:password@localhost:5432/apiome
POSTGRES_USER=postgres
POSTGRES_HOST=localhost
POSTGRES_DB=apiome
POSTGRES_PASSWORD=your_password_here
POSTGRES_PORT=5432

# REST API Base URL (for fetching specifications)
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1
```

### 3. Ensure apiome-rest is Running

The browse application relies on the REST API to fetch specifications. Make sure it's running:

```bash
cd ../apiome-rest
# Follow the REST API setup instructions
python -m uvicorn app.main:app --reload
```

The REST API should be accessible at `http://localhost:8000`.

### 4. Start the Development Server

```bash
npm run dev
```

The application will be available at `http://localhost:3000`.

## Verifying the Setup

### 1. Check Database Connection

The application should be able to connect to your PostgreSQL database. If you see database connection errors, verify:

- PostgreSQL is running
- Database credentials in `.env.local` are correct
- The `apiome` schema exists in your database

### 2. Check REST API Connection

The application fetches specifications from the REST API. Verify:

- apiome-rest is running on the configured port
- The `NEXT_PUBLIC_REST_API_BASE_URL` points to the correct URL
- You can access `http://localhost:8000` in your browser

### 3. Verify Data

For the browse application to display content, you need:

- At least one tenant in the database
- At least one project under that tenant
- At least one **published** version with `visibility='public'` for that project

## Testing with Sample Data

If you don't have any published public versions, you can create test data:

1. Log into the apiome-ui application
2. Create a tenant and project
3. Create a version with some classes
4. **Publish** the version
5. Set the version visibility to **public**

Now refresh the browse application - you should see your tenant, project, and version.

## Production Build

To create a production build:

```bash
npm run build
npm start
```

## Troubleshooting

### No organizations showing up

**Problem**: The home page shows "No published specifications available yet."

**Solutions**:
- Verify you have at least one version with `published=true` AND `visibility='public'`
- Check database connectivity
- Look for errors in the browser console or server logs

### Specifications not loading

**Problem**: Version details page shows "Failed to load specification"

**Solutions**:
- Verify apiome-rest is running
- Check the `NEXT_PUBLIC_REST_API_BASE_URL` environment variable
- Look at browser network tab for failed requests
- Verify the REST API can access the same database

### Database connection errors

**Problem**: "Connection refused" or "Authentication failed"

**Solutions**:
- Verify PostgreSQL is running: `psql -U postgres -l`
- Check DATABASE_URL format: `postgresql://user:password@host:port/database`
- Ensure the database user has SELECT permissions on `apiome` schema tables

### Page not found (404)

**Problem**: Clicking on a tenant/project shows 404

**Solutions**:
- Verify the slugs in the database are URL-safe
- Check that `deleted_at IS NULL` for all records
- Ensure the version is both published AND public

## Next Steps

Once the application is running:

1. Browse organizations and projects
2. View published specifications in multiple formats (OpenAPI, Arazzo, JSON Schema)
3. Compare different versions using the compare tool
4. Search for specific tenants or projects

## Support

For issues or questions:

1. Check the main README.md for detailed documentation
2. Review the apiome-rest documentation
3. Check the Apiome database schema documentation

## Development Tips

### Hot Reload

The development server supports hot reload - changes to pages and components will automatically refresh.

### Database Changes

If you modify database helper functions in `lib/db/helper.ts`, the server will automatically restart.

### Environment Variables

Changes to `.env.local` require a server restart:
- Stop the dev server (Ctrl+C)
- Start it again (`npm run dev`)

### Debugging

Enable detailed logging by setting:

```env
NODE_ENV=development
```

Check the terminal running `npm run dev` for server-side logs.
Check the browser console for client-side logs.

