-- Feature flag packages: named groups of flags for bulk admin grants (#feature-flag-packages)
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS feature_flag_groups (
    id           UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         VARCHAR(64)  NOT NULL UNIQUE,
    label        VARCHAR(255) NOT NULL,
    description  TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feature_flag_groups_name ON odb.feature_flag_groups (name);

COMMENT ON TABLE odb.feature_flag_groups IS
  'Named bundles of feature flags; super-admins can grant or clear all members for a user at once';

CREATE TABLE IF NOT EXISTS feature_flag_group_members (
    group_id        UUID NOT NULL REFERENCES odb.feature_flag_groups(id) ON DELETE CASCADE,
    feature_flag_id UUID NOT NULL REFERENCES odb.feature_flags(id)       ON DELETE CASCADE,
    PRIMARY KEY (group_id, feature_flag_id)
);

CREATE INDEX IF NOT EXISTS idx_ffgm_group_id ON odb.feature_flag_group_members (group_id);
CREATE INDEX IF NOT EXISTS idx_ffgm_flag_id  ON odb.feature_flag_group_members (feature_flag_id);

COMMENT ON TABLE odb.feature_flag_group_members IS
  'Junction: which feature flags belong to each package';
