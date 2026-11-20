-- External `$ref` state per project — COA-2.8 (#7051).
--
-- A project's OpenAPI document may depend on definitions that live at other URLs
-- (`https://schemas.acme.com/common.json#/Money`). The Versions screen's **References** tab lists
-- them, and **Refresh** fetches each one (under the tenant's external-ref policy, REPO-3.9, and the
-- SSRF guard) to see whether it changed. This table remembers, per project and URL:
--
--   * the last check: when, by whom, its status and — for a refusal or a failure — why;
--   * the last fetched snapshot: its sha-256 digest, the parsed document and when it was fetched;
--   * an optional **pin**: the snapshot the team accepted. While a reference is pinned, every
--     refresh compares against the pin, so a remote change stays reported until someone re-pins;
--   * the last change a refresh detected, as JSON Pointer rows (`added` / `removed` / `changed`).
--
-- Rules the schema enforces:
--
--   1. One row per project and URL (`UNIQUE (project_id, url)`); a refresh upserts it.
--   2. Known statuses only: `ok` (unchanged), `changed` (differs from the pin, or from the previous
--      snapshot), `unreachable` (the fetch failed) and `blocked` (policy, kill switch or SSRF guard).
--   3. A pin is all-or-nothing: digest and document are set together or both NULL.
--   4. The rows go with the project (`ON DELETE CASCADE`).
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.project_external_refs;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS project_external_refs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url TEXT NOT NULL CHECK (char_length(url) BETWEEN 1 AND 2048),
    status VARCHAR(16) NOT NULL CHECK (status IN ('ok', 'changed', 'unreachable', 'blocked')),
    reason VARCHAR(64),
    detail TEXT,
    content_digest VARCHAR(80),
    document JSONB,
    fetched_at TIMESTAMPTZ,
    diff JSONB,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checked_by UUID REFERENCES users(id) ON DELETE SET NULL,
    pinned_digest VARCHAR(80),
    pinned_document JSONB,
    pinned_at TIMESTAMPTZ,
    pinned_by UUID REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT project_external_refs_url_uq UNIQUE (project_id, url),
    CONSTRAINT project_external_refs_pin_ck CHECK ((pinned_digest IS NULL) = (pinned_document IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_project_external_refs_tenant_project
    ON project_external_refs (tenant_id, project_id);

COMMENT ON TABLE project_external_refs IS
    'COA-2.8 (#7051): per project and URL, the last external $ref check, the last fetched snapshot, '
    'an optional pinned snapshot and the last change a refresh detected.';
COMMENT ON COLUMN project_external_refs.status IS
    'ok | changed | unreachable | blocked — the outcome of the last refresh.';
COMMENT ON COLUMN project_external_refs.diff IS
    '{changes: [{pointer, kind, before?, after?}], total, truncated, against: pin|previous} or NULL.';
COMMENT ON COLUMN project_external_refs.pinned_digest IS
    'The accepted snapshot; while set, every refresh compares against it.';
