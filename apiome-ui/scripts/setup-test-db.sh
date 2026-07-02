#!/bin/bash

# Import Validation Test Database Setup
# Creates the test database and schema for running import validation tests

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Import Validation Test Database Setup${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Load environment variables
if [ -f .env.test ]; then
    source .env.test
else
    echo -e "${YELLOW}Warning: .env.test not found, using defaults${NC}"
    TEST_POSTGRES_DB=${TEST_POSTGRES_DB:-apiome_test}
    POSTGRES_HOST=${POSTGRES_HOST:-localhost}
    POSTGRES_PORT=${POSTGRES_PORT:-5432}
    POSTGRES_USER=${POSTGRES_USER:-postgres}
    POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-postgres}
fi

echo "Configuration:"
echo "  Database: ${TEST_POSTGRES_DB}"
echo "  Host: ${POSTGRES_HOST}"
echo "  Port: ${POSTGRES_PORT}"
echo "  User: ${POSTGRES_USER}"
echo ""

# Check if PostgreSQL is running
echo -e "${YELLOW}Checking PostgreSQL connection...${NC}"
if ! PGPASSWORD=${POSTGRES_PASSWORD} psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${RED}Error: Cannot connect to PostgreSQL${NC}"
    echo "Please ensure PostgreSQL is running:"
    echo "  macOS: brew services start postgresql@16"
    echo "  Linux: sudo systemctl start postgresql"
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL is running${NC}"

# Check if test database exists
echo -e "${YELLOW}Checking if test database exists...${NC}"
if PGPASSWORD=${POSTGRES_PASSWORD} psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -lqt | cut -d \| -f 1 | grep -qw ${TEST_POSTGRES_DB}; then
    echo -e "${YELLOW}Test database already exists${NC}"
    read -p "Do you want to drop and recreate it? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Dropping existing database...${NC}"
        PGPASSWORD=${POSTGRES_PASSWORD} psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -c "DROP DATABASE IF EXISTS ${TEST_POSTGRES_DB};"
        echo -e "${GREEN}✓ Database dropped${NC}"
    else
        echo -e "${YELLOW}Keeping existing database${NC}"
        exit 0
    fi
fi

# Create test database
echo -e "${YELLOW}Creating test database...${NC}"
PGPASSWORD=${POSTGRES_PASSWORD} psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -c "CREATE DATABASE ${TEST_POSTGRES_DB};"
echo -e "${GREEN}✓ Test database created${NC}"

# Create test schema and tables
echo -e "${YELLOW}Creating test schema and tables...${NC}"
PGPASSWORD=${POSTGRES_PASSWORD} psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${TEST_POSTGRES_DB} << 'EOF'
-- Create test schema
CREATE SCHEMA IF NOT EXISTS test_schema;
SET search_path TO test_schema;

-- Create tables
CREATE TABLE tenants (
  id TEXT PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  slug TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(tenant_id, slug)
);

CREATE TABLE versions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL,
  description TEXT,
  is_published BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(project_id, version_id)
);

CREATE TABLE classes (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  schema JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(version_id, name)
);

CREATE TABLE properties (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  name TEXT NOT NULL,
  description TEXT,
  data JSONB NOT NULL,
  signature TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(tenant_id, signature)
);

CREATE TABLE class_properties (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  property_id TEXT REFERENCES properties(id),
  name TEXT NOT NULL,
  description TEXT,
  data JSONB NOT NULL,
  sort_order INTEGER DEFAULT 0,
  parent_id TEXT REFERENCES class_properties(id),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes
CREATE INDEX idx_classes_version ON classes(version_id);
CREATE INDEX idx_class_properties_class ON class_properties(class_id);
CREATE INDEX idx_class_properties_property ON class_properties(property_id);

-- Insert test tenant and user
INSERT INTO tenants (id, slug, name)
VALUES ('test-tenant', 'test-tenant', 'Test Tenant');

INSERT INTO users (id, email, name)
VALUES ('test-user', 'test@example.com', 'Test User');

EOF

echo -e "${GREEN}✓ Schema and tables created${NC}"

# Verify setup
echo -e "${YELLOW}Verifying setup...${NC}"
TABLE_COUNT=$(PGPASSWORD=${POSTGRES_PASSWORD} psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${TEST_POSTGRES_DB} -t -c "SET search_path TO test_schema; SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'test_schema';")
echo "  Tables created: ${TABLE_COUNT}"

if [ "$TABLE_COUNT" -ge 7 ]; then
    echo -e "${GREEN}✓ Setup verified${NC}"
else
    echo -e "${RED}Error: Expected at least 7 tables, found ${TABLE_COUNT}${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "You can now run the import validation tests:"
echo "  yarn test:import"
echo ""

