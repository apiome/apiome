-- Security Schemes for OpenAPI (Ticket #410)
-- Adds version_security_scheme table for API Key (header, query, cookie) and future scheme types

SET search_path TO apiome, public;

-- version_security_scheme: Stores security scheme definitions per version (OpenAPI components.securitySchemes)
CREATE TABLE IF NOT EXISTS apiome.version_security_scheme (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    version_id UUID NOT NULL REFERENCES apiome.versions(id) ON DELETE CASCADE,
    -- OpenAPI scheme name (e.g., apiKey, bearerAuth)
    scheme_name VARCHAR(255) NOT NULL,
    -- Scheme type: apiKey, http, oauth2, openIdConnect, mutualTLS (OpenAPI 3.1)
    scheme_type VARCHAR(50) NOT NULL DEFAULT 'apiKey',
    -- For apiKey: header, query, cookie
    in_location VARCHAR(50),
    -- Parameter/header name (e.g., X-API-Key, api_key)
    param_name VARCHAR(255),
    -- For http: basic, bearer, digest, etc.
    http_scheme VARCHAR(50),
    -- Optional description
    description TEXT,
    -- Additional scheme-specific data (JSONB for flows, bearerFormat, etc.)
    data JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(version_id, scheme_name)
);

COMMENT ON TABLE apiome.version_security_scheme IS 'OpenAPI security scheme definitions per version (API Key, HTTP, OAuth2, etc.)';
COMMENT ON COLUMN apiome.version_security_scheme.scheme_name IS 'OpenAPI scheme identifier (e.g., apiKey, bearerAuth)';
COMMENT ON COLUMN apiome.version_security_scheme.scheme_type IS 'OpenAPI scheme type: apiKey, http, oauth2, openIdConnect, mutualTLS';
COMMENT ON COLUMN apiome.version_security_scheme.in_location IS 'For apiKey: header, query, or cookie';
COMMENT ON COLUMN apiome.version_security_scheme.param_name IS 'Header/query/cookie parameter name (e.g., X-API-Key)';

CREATE INDEX idx_version_security_scheme_version_id ON apiome.version_security_scheme(version_id);
