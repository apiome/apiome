-- Contracts guided set-up: what a workspace has marked and done from the set-up page — PFX-8.20 (#7317).
--
-- The **Set up contracts** page (`/ade/dashboard/pacts/setup`) walks a workspace through six
-- sections. Most of a section's state is read from what exists (pacticipants, environments, pacts,
-- provider-contract sources, verification results). What cannot be read from anything else is kept
-- here, one row per tenant, so the page resumes where it was left and never sets a thing up twice:
--
--   * `marked`         — sections a Contracts admin marked done by hand (a pipeline wired outside
--                        Apiome, a provider verified elsewhere, the gates section finished);
--   * `first_pact_path` — which way to the first pact was chosen (`tests` or `spec`);
--   * `ci_key_id` / `ci_key_prefix` — the API key the page created for CI, so a resume shows it
--                        instead of creating a second one. The key's secret is never stored;
--   * `github`         — per repository (`{"<repository id>": {...}}`): when the two Actions secrets
--                        were written and the pull request the page opened. No token and no secret
--                        value is ever stored here.
--
-- Rules kept by the database:
--
--   1. **Only known sections and paths.** `marked` holds section ids of the page; `first_pact_path`
--      is one of the two paths.
--   2. **A key is named whole.** `ci_key_id` and `ci_key_prefix` come together.
--   3. **Nothing crosses a tenant.** The row is keyed by `tenant_id` and goes with it.
--
-- Online: one new table and one partial index.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.pact_setup_progress;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS pact_setup_progress (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,

    marked TEXT[] NOT NULL DEFAULT '{}'
        CONSTRAINT pact_setup_progress_marked_check
            CHECK (marked <@ ARRAY['pacticipants', 'environments', 'pipelines', 'first-pact', 'provider', 'gates']),
    first_pact_path VARCHAR(8)
        CONSTRAINT pact_setup_progress_first_pact_path_check
            CHECK (first_pact_path IS NULL OR first_pact_path IN ('tests', 'spec')),

    -- No foreign key: a deleted key simply reads as "no key yet" (apiome-rest checks it is still live).
    ci_key_id UUID,
    ci_key_prefix TEXT,
    CONSTRAINT pact_setup_progress_ci_key_whole_check
        CHECK ((ci_key_id IS NULL) = (ci_key_prefix IS NULL)),

    github JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT pact_setup_progress_github_object_check CHECK (jsonb_typeof(github) = 'object'),

    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by_label TEXT,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pact_setup_progress_updated_by
    ON pact_setup_progress (updated_by) WHERE updated_by IS NOT NULL;

COMMENT ON TABLE pact_setup_progress IS
    'What a workspace marked and did on the Contracts set-up page (PFX-8.20, #7317); no row = nothing yet';
COMMENT ON COLUMN pact_setup_progress.marked IS 'Sections a Contracts admin marked done by hand';
COMMENT ON COLUMN pact_setup_progress.first_pact_path IS 'The chosen way to the first pact: tests or spec';
COMMENT ON COLUMN pact_setup_progress.ci_key_id IS 'The API key the page created for CI (its secret is never stored)';
COMMENT ON COLUMN pact_setup_progress.ci_key_prefix IS 'That key''s visible prefix';
COMMENT ON COLUMN pact_setup_progress.github IS
    'Per repository id: when the Actions secrets were written and the pull request opened (no token, no secret value)';
