-- Add metadata column to projects table for OpenAPI specification generation
-- This stores contact, license, and other API metadata
SET search_path TO apiome, public;

-- Add metadata JSONB column to projects table
ALTER TABLE projects ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- Create index for metadata queries
CREATE INDEX IF NOT EXISTS idx_projects_metadata ON projects USING gin(metadata) WHERE deleted_at IS NULL;

-- Add comment explaining the metadata column
COMMENT ON COLUMN projects.metadata IS 'JSON metadata for OpenAPI specification generation, including summary, terms of service, contact info, and license details';

-- Example metadata structure:
-- {
--   "summary": "Short summary of the API",
--   "termsOfService": "https://example.com/terms",
--   "contact": {
--     "name": "API Support Team",
--     "url": "https://example.com/support",
--     "email": "support@example.com"
--   },
--   "license": {
--     "name": "Apache 2.0",
--     "identifier": "Apache-2.0",
--     "url": "https://www.apache.org/licenses/LICENSE-2.0.html"
--   }
-- }

