-- Database Schema for Multi-tenant System
-- Tables: users, groups, tenants
-- All IDs use uuid_generate_v4() for automatic UUIDv4 generation

DROP SCHEMA IF EXISTS apiome CASCADE;
CREATE SCHEMA apiome;

-- Set the search path to use apiome schema by default
SET search_path TO apiome, public;

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Users table: Stores application users with authentication credentials
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT false,
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indices for users table
CREATE INDEX idx_users_email ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_enabled ON users(enabled) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_verified ON users(verified) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_deleted_at ON users(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_users_created_at ON users(created_at);

-- Tenants table: Represents separate organizational entities in the multi-tenant system
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    slug VARCHAR(255) NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indices for tenants table
CREATE INDEX idx_tenants_slug ON tenants(slug) WHERE deleted_at IS NULL;
CREATE INDEX idx_tenants_enabled ON tenants(enabled) WHERE deleted_at IS NULL;
CREATE INDEX idx_tenants_deleted_at ON tenants(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX idx_tenants_created_at ON tenants(created_at);
CREATE INDEX idx_tenants_name ON tenants(name) WHERE deleted_at IS NULL;

-- Tenant Users: Junction table assigning users to tenants
CREATE TABLE tenant_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, user_id)
);

-- Indices for tenant_users table
CREATE INDEX idx_tenant_users_tenant_id ON tenant_users(tenant_id);
CREATE INDEX idx_tenant_users_user_id ON tenant_users(user_id);
CREATE INDEX idx_tenant_users_created_at ON tenant_users(created_at);

-- Tenant Administrators: Junction table assigning users as administrators of tenants
CREATE TABLE tenant_administrators (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, user_id)
);

-- Add table and column comments for tenant_administrators
COMMENT ON TABLE tenant_administrators IS 'Associates users with tenants they administer';
COMMENT ON TABLE tenant_users IS 'Associates users with tenants they belong to';
COMMENT ON TABLE tenants IS 'Organizational tenants in the multi-tenant system';
COMMENT ON TABLE users IS 'Application users with authentication credentials and verification status';

-- Indices for tenant_administrators table
CREATE INDEX idx_tenant_administrators_tenant_id ON tenant_administrators(tenant_id);
CREATE INDEX idx_tenant_administrators_user_id ON tenant_administrators(user_id);
CREATE INDEX idx_tenant_administrators_created_at ON tenant_administrators(created_at);

INSERT INTO apiome.users (name, email, password, verified, enabled) VALUES
    ('Apiome Administrator', 'admin@apiome.app',
     '$2a$12$.1v68JPMx8lR1KFO.nbZcegTSnb1Tqp0J86sK5junucFOSkyI.jHe',
     true, true);

INSERT INTO apiome.users (name, email, password, verified, enabled) VALUES
    ('Test User 1', 'test1@user.com',
     '$2a$12$.1v68JPMx8lR1KFO.nbZcegTSnb1Tqp0J86sK5junucFOSkyI.jHe',
     true, true);

INSERT INTO apiome.users (name, email, password, verified, enabled) VALUES
    ('Test User 2', 'test2@user.com',
     '$2a$12$.1v68JPMx8lR1KFO.nbZcegTSnb1Tqp0J86sK5junucFOSkyI.jHe',
     true, true);

INSERT INTO apiome.users (name, email, password, verified, enabled) VALUES
    ('Test User 3', 'test3@user.com',
     '$2a$12$.1v68JPMx8lR1KFO.nbZcegTSnb1Tqp0J86sK5junucFOSkyI.jHe',
     true, true);

INSERT INTO apiome.users (name, email, password, verified, enabled) VALUES
    ('Test User 4', 'test4@user.com',
     '$2a$12$.1v68JPMx8lR1KFO.nbZcegTSnb1Tqp0J86sK5junucFOSkyI.jHe',
     true, true);

INSERT INTO apiome.users (name, email, password, verified, enabled) VALUES
    ('Test User 5', 'test5@user.com',
     '$2a$12$.1v68JPMx8lR1KFO.nbZcegTSnb1Tqp0J86sK5junucFOSkyI.jHe',
     true, true);

INSERT INTO apiome.tenants (name, description, slug, enabled) VALUES
    ('Apiome', 'The Apiome Project', 'apiome', true);

INSERT INTO apiome.tenant_users (user_id, tenant_id) VALUES
    ((SELECT id FROM apiome.users WHERE email='admin@apiome.app'),
     (SELECT id FROM apiome.tenants WHERE slug='apiome'));

INSERT INTO apiome.tenant_administrators (tenant_id, user_id) VALUES
    ((SELECT id FROM apiome.tenants WHERE slug='apiome'),
     (SELECT id FROM apiome.users WHERE email='admin@apiome.app'));
