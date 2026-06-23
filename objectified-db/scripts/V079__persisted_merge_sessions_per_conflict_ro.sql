-- Persisted merge sessions + per-conflict rows + status transition audit (#2573, P1-01)
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS merge_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_branch_id UUID REFERENCES version_branches(id) ON DELETE SET NULL,
    source_branch_name VARCHAR(255) NOT NULL,
    target_branch_name VARCHAR(255) NOT NULL,
    merge_base_version_id UUID NOT NULL REFERENCES versions(id) ON DELETE RESTRICT,
    source_tip_version_id UUID NOT NULL REFERENCES versions(id) ON DELETE RESTRICT,
    target_tip_version_id UUID NOT NULL REFERENCES versions(id) ON DELETE RESTRICT,
    status VARCHAR(32) NOT NULL DEFAULT 'preview'
        CHECK (status IN ('preview', 'resolving', 'applied', 'aborted')),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_merge_sessions_project_id ON merge_sessions(project_id);

COMMENT ON TABLE merge_sessions IS 'Merge conflict resolution session; optional snapshot from merge-preview (#2573)';
COMMENT ON COLUMN merge_sessions.status IS 'Lifecycle: preview → resolving → applied | aborted';

CREATE TABLE IF NOT EXISTS merge_session_conflicts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    merge_session_id UUID NOT NULL REFERENCES merge_sessions(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    kinds JSONB NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_merge_session_conflicts_merge_session_id
    ON merge_session_conflicts(merge_session_id);

COMMENT ON TABLE merge_session_conflicts IS 'Per-path conflict kinds for a merge session (#2573)';

CREATE TABLE IF NOT EXISTS merge_session_status_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    merge_session_id UUID NOT NULL REFERENCES merge_sessions(id) ON DELETE CASCADE,
    from_status VARCHAR(32),
    to_status VARCHAR(32) NOT NULL,
    changed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_merge_session_status_events_merge_session_id
    ON merge_session_status_events(merge_session_id);

COMMENT ON TABLE merge_session_status_events IS 'Audit trail for merge_sessions.status transitions (#2573)';
