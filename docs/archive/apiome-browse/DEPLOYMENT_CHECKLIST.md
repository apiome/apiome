# Apiome Browse - Deployment Checklist

## Pre-Deployment Checklist

### 1. Environment Configuration ✓
- [ ] Copy `.env.example` to `.env.local`
- [ ] Set `DATABASE_URL` or individual `POSTGRES_*` variables
- [ ] Set `NEXT_PUBLIC_REST_API_BASE_URL` to your REST API endpoint
- [ ] Verify environment variables are correct

### 2. Database Setup ✓
- [ ] PostgreSQL is running and accessible
- [ ] Database has `apiome` schema with required tables:
  - `apiome.tenants`
  - `apiome.projects`
  - `apiome.versions`
  - `apiome.users`
- [ ] Database user has SELECT permissions on all `apiome.*` tables
- [ ] At least one published public version exists for testing
- [ ] Test database connection:
  ```bash
  psql $DATABASE_URL -c "SELECT COUNT(*) FROM apiome.tenants;"
  ```

### 3. REST API Dependency ✓
- [ ] apiome-rest service is deployed and accessible
- [ ] REST API can connect to the same database
- [ ] Test REST API endpoint:
  ```bash
  curl http://localhost:8000/
  ```
- [ ] Verify specification endpoints work:
  ```bash
  curl http://localhost:8000/v1/schema/{tenant}/{project}/{version}
  ```

### 4. Application Build ✓
- [ ] Install dependencies:
  ```bash
  npm install
  ```
- [ ] Build application:
  ```bash
  npm run build
  ```
- [ ] Fix any build errors
- [ ] Test production build locally:
  ```bash
  npm start
  ```

### 5. Functional Testing ✓

#### Home Page
- [ ] Access http://localhost:3000
- [ ] Verify tenants list displays
- [ ] Search box is visible
- [ ] Click on a tenant navigates to projects page

#### Search
- [ ] Enter search query
- [ ] Verify results display
- [ ] Results grouped by organization
- [ ] Click-through to tenant/project works

#### Tenant Page
- [ ] Navigate to `/tenant/{slug}`
- [ ] Breadcrumb shows "← Back to all organizations"
- [ ] Projects list displays
- [ ] Click on project navigates to versions page

#### Project Page
- [ ] Navigate to `/tenant/{slug}/{project}`
- [ ] Breadcrumbs show proper path
- [ ] Versions list displays
- [ ] "Compare versions" link shows (if 2+ versions)
- [ ] Click on version navigates to details page

#### Version Details Page
- [ ] Navigate to `/tenant/{slug}/{project}/{version}`
- [ ] Full breadcrumb navigation works
- [ ] Changelog displays (if present)
- [ ] Format tabs work (OpenAPI, Arazzo, JSON Schema)
- [ ] Specification loads and displays
- [ ] Copy button works
- [ ] Download button works

#### Version Comparison
- [ ] Navigate to `/tenant/{slug}/{project}/compare`
- [ ] Both version selectors work
- [ ] Format selector works
- [ ] Side-by-side view displays both specs
- [ ] Unified diff view shows differences
- [ ] Switching versions updates URL

### 6. UI/UX Testing ✓

#### Responsive Design
- [ ] Test on mobile (< 640px)
- [ ] Test on tablet (640px - 1024px)
- [ ] Test on desktop (> 1024px)
- [ ] Grid layouts adjust properly
- [ ] Navigation is usable on all sizes

#### Dark Mode
- [ ] Toggle system dark mode
- [ ] Verify all pages work in dark mode
- [ ] Colors are readable
- [ ] No white flashes on page navigation

#### Error States
- [ ] Navigate to non-existent tenant → 404
- [ ] Navigate to non-existent project → 404
- [ ] Navigate to non-existent version → 404
- [ ] Stop REST API → error message displays
- [ ] Database connection error → error message displays

#### Empty States
- [ ] Remove all published versions → "No specifications" message
- [ ] Search for non-existent term → "No results" message
- [ ] Project with 0 versions → "No versions" message

### 7. Performance Testing ✓
- [ ] Home page loads in < 2 seconds
- [ ] Navigation between pages is fast
- [ ] Specification loading shows loading state
- [ ] Large specifications (> 1MB) load successfully
- [ ] No console errors in browser
- [ ] No memory leaks on repeated navigation

### 8. Security Review ✓
- [ ] Only published public versions are visible
- [ ] Private versions are not accessible
- [ ] SQL injection protection (parameterized queries)
- [ ] XSS protection (React escaping)
- [ ] No sensitive data exposed in client-side code
- [ ] Database credentials not in client-side bundle

### 9. Documentation ✓
- [ ] README.md is up to date
- [ ] GETTING_STARTED.md has correct setup instructions
- [ ] FEATURES.md describes all features
- [ ] QUICK_REFERENCE.md is accurate
- [ ] .env.example has all required variables

### 10. Production Configuration ✓

#### Environment Variables
- [ ] Set production `DATABASE_URL`
- [ ] Set production `NEXT_PUBLIC_REST_API_BASE_URL`
- [ ] Remove any development-only variables
- [ ] Verify no secrets in .env.example

#### Build Optimization
- [ ] Enable production optimizations in Next.js
- [ ] Minification enabled
- [ ] Tree shaking works
- [ ] No console.log statements in production build

#### Deployment
- [ ] Choose deployment platform (Vercel, AWS, etc.)
- [ ] Configure environment variables on platform
- [ ] Set up CI/CD pipeline (optional)
- [ ] Configure custom domain (optional)
- [ ] Set up SSL certificate
- [ ] Test deployment before going live

### 11. Monitoring & Logging ✓
- [ ] Set up error tracking (e.g., Sentry)
- [ ] Configure analytics (optional)
- [ ] Monitor database connection pool
- [ ] Monitor REST API availability
- [ ] Set up uptime monitoring

### 12. Post-Deployment ✓
- [ ] Verify production URL works
- [ ] Test all major flows in production
- [ ] Check performance in production
- [ ] Monitor error logs for first 24 hours
- [ ] Gather user feedback

## Quick Test Script

Run this script to quickly verify basic functionality:

```bash
#!/bin/bash
BASE_URL="http://localhost:3000"

echo "Testing home page..."
curl -s -o /dev/null -w "%{http_code}" $BASE_URL
echo ""

echo "Testing search..."
curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/search?q=test"
echo ""

echo "All basic tests passed! ✓"
```

## Rollback Plan

If deployment fails:

1. Revert to previous version
2. Check logs for errors
3. Verify database connectivity
4. Verify REST API connectivity
5. Test in development environment
6. Fix issues and redeploy

## Support Contacts

- Database Admin: [contact info]
- REST API Team: [contact info]
- DevOps: [contact info]

## Notes

- The application requires both database and REST API to be functional
- Database queries are read-only - no data modification risk
- Only published public versions are exposed
- Performance scales with database query performance

---

**Deployment Date**: _________________

**Deployed By**: _________________

**Sign-off**: _________________

