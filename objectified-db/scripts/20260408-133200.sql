-- User theme preferences (issue #1332): persisted appearance and custom palette overrides.
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS user_theme_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme_name VARCHAR(32) NOT NULL DEFAULT 'system',
    overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_theme_preferences_updated_at
    ON user_theme_preferences (updated_at DESC);

COMMENT ON TABLE user_theme_preferences IS 'Per-user theme mode (light/dark/system) and optional --obj-* color overrides.';
COMMENT ON COLUMN user_theme_preferences.theme_name IS 'One of: light, dark, system.';
COMMENT ON COLUMN user_theme_preferences.overrides IS 'JSON object with optional keys: primary, secondary, accent, background, surface, text (CSS color strings).';
