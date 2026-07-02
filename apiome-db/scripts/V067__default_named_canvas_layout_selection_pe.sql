-- Default named canvas layout selection per user and per tenant (team).
-- Resolved order when opening the studio: user default → tenant default → built-in fallback in app.

SET search_path TO apiome, public;

CREATE TABLE user_canvas_layout_defaults (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    layout_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, version_id)
);

CREATE TABLE tenant_canvas_layout_defaults (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    layout_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, version_id)
);

CREATE INDEX idx_user_canvas_layout_defaults_version_id ON user_canvas_layout_defaults(version_id);
CREATE INDEX idx_tenant_canvas_layout_defaults_version_id ON tenant_canvas_layout_defaults(version_id);

COMMENT ON TABLE user_canvas_layout_defaults IS 'Preferred named canvas layout to load first for a user on a version';
COMMENT ON TABLE tenant_canvas_layout_defaults IS 'Team (tenant) default named canvas layout for a version when the user has no personal default';

CREATE OR REPLACE FUNCTION update_user_canvas_layout_defaults_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_canvas_layout_defaults_updated_at
    BEFORE UPDATE ON user_canvas_layout_defaults
    FOR EACH ROW
    EXECUTE FUNCTION update_user_canvas_layout_defaults_updated_at();

CREATE OR REPLACE FUNCTION update_tenant_canvas_layout_defaults_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_tenant_canvas_layout_defaults_updated_at
    BEFORE UPDATE ON tenant_canvas_layout_defaults
    FOR EACH ROW
    EXECUTE FUNCTION update_tenant_canvas_layout_defaults_updated_at();
