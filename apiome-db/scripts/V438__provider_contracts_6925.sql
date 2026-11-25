-- Provider contract publication — PFX-2.1 (#6925).
--
-- Bi-directional contract testing compares a consumer's pact with the provider's OpenAPI document
-- instead of replaying the pact against a running provider. This migration stores that OpenAPI
-- document — the *provider contract* — against a provider version of the broker's model (V432),
-- in two tables shaped like the pact tables of V433:
--
--   provider_contract             — one distinct OpenAPI document of a provider, addressed by the
--                                   SHA-256 of its canonical JSON. Kept as JSONB.
--   provider_contract_publication — "provider version V published this contract": the link from a
--                                   pacticipant_version to the provider_contract it carries, with
--                                   where the document came from and the self-verification results
--                                   sent with it.
--
-- Rules kept by the database:
--
--   1. **Content is stored once.** `provider_contract` is UNIQUE on (provider, sha), so one
--      document published for ten provider versions is one row with ten publications.
--   2. **Write-once per provider version.** `provider_contract_publication` is UNIQUE on
--      `provider_version_id`. apiome-rest answers a republish of the same contract as a no-op and
--      refuses a different one (409); no statement ever updates a publication.
--   3. **Nothing crosses a tenant.** `provider_contract` references its provider by
--      `(id, tenant_id)`; a publication references its contract by `(id, provider_id)` and its
--      version by `(id, pacticipant_id)`, so it can only join rows of one provider. A contract
--      published from an Apiome version references that version's project by `(id, tenant_id)`.
--   4. **A contract goes with its provider.** Every reference to the provider and its versions is
--      ON DELETE CASCADE. Deleting the Apiome project or version a contract was published from
--      only clears the link (`SET NULL`): the stored document, and the labels saying where it came
--      from, stay.
--
-- Online: two new tables, nothing existing is altered.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.provider_contract_publication, apiome.provider_contract;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. provider_contract — one distinct OpenAPI document of a provider
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provider_contract (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Constrained through the provider reference below.
    tenant_id UUID NOT NULL,
    provider_id UUID NOT NULL,

    -- Rule 1. Lowercase hex SHA-256 of the document's canonical JSON (apiome-rest
    -- app.provider_contract.provider_contract_sha): sorted keys, so JSON and YAML of one
    -- document have one address.
    sha CHAR(64) NOT NULL
        CONSTRAINT provider_contract_sha_shape_check CHECK (sha ~ '^[0-9a-f]{64}$'),
    -- The OpenAPI document, parsed from JSON or YAML.
    content JSONB NOT NULL
        CONSTRAINT provider_contract_content_object_check CHECK (jsonb_typeof(content) = 'object'),
    -- The `openapi` version the document declares (`3.0.3`, `3.1.0`).
    oas_version VARCHAR(32) NOT NULL,
    -- How many operations the document declares.
    operation_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT provider_contract_operation_count_check CHECK (operation_count >= 0),

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT provider_contract_content_key UNIQUE (provider_id, sha),
    -- Referenced by provider_contract_publication (rule 3).
    CONSTRAINT provider_contract_id_provider_key UNIQUE (id, provider_id),
    CONSTRAINT provider_contract_provider_fk
        FOREIGN KEY (provider_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

-- The referential check of the provider.
CREATE INDEX IF NOT EXISTS idx_provider_contract_provider
    ON provider_contract (provider_id, tenant_id);

COMMENT ON TABLE provider_contract IS
    'One distinct OpenAPI document of a provider, addressed by the SHA-256 of its canonical JSON (PFX-2.1, #6925)';
COMMENT ON COLUMN provider_contract.tenant_id IS 'Owning tenant; equal to the provider''s tenant by the composite reference';
COMMENT ON COLUMN provider_contract.provider_id IS 'The provider pacticipant';
COMMENT ON COLUMN provider_contract.sha IS 'Lowercase hex SHA-256 of the canonical JSON; unique per provider';
COMMENT ON COLUMN provider_contract.content IS 'The OpenAPI 3.x document, parsed from the JSON or YAML published';
COMMENT ON COLUMN provider_contract.oas_version IS 'The openapi version the document declares';
COMMENT ON COLUMN provider_contract.operation_count IS 'How many operations the document declares';

-- ---------------------------------------------------------------------------------------------------
-- 2. provider_contract_publication — a provider version published a contract
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provider_contract_publication (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    provider_version_id UUID NOT NULL,
    provider_contract_id UUID NOT NULL,

    -- The media type the document was sent as (`application/json`, `application/yaml`); for a
    -- contract published from an Apiome version, `application/json`.
    content_type VARCHAR(100) NOT NULL,
    -- `inline`: the request carried the document. `apiome`: it was rendered from an Apiome version.
    source VARCHAR(16) NOT NULL
        CONSTRAINT provider_contract_publication_source_check CHECK (source IN ('inline', 'apiome')),
    -- For `apiome`: the project and version it was rendered from. The ids are cleared when either
    -- is deleted (rule 4); the labels keep saying where the document came from.
    source_project_id UUID,
    source_version_id UUID,
    source_project_slug TEXT,
    source_version_label TEXT,
    CONSTRAINT provider_contract_publication_source_shape_check CHECK (
        (source = 'inline' AND source_project_id IS NULL AND source_version_id IS NULL
            AND source_project_slug IS NULL AND source_version_label IS NULL)
        OR (source = 'apiome' AND source_project_slug IS NOT NULL AND source_version_label IS NOT NULL)
    ),

    -- The self-verification results sent with the contract (PFX-2.4, #6928, decides what they
    -- prove): success flag, verifier, content type, base64 content and its SHA-256. NULL when none
    -- were sent.
    verification_results JSONB
        CONSTRAINT provider_contract_publication_results_object_check
            CHECK (verification_results IS NULL OR jsonb_typeof(verification_results) = 'object'),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    -- Email or key name at the time of publishing, kept after the user is gone.
    actor_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 2.
    CONSTRAINT provider_contract_publication_version_key UNIQUE (provider_version_id),
    -- Rule 3.
    CONSTRAINT provider_contract_publication_provider_fk
        FOREIGN KEY (provider_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT provider_contract_publication_version_fk
        FOREIGN KEY (provider_version_id, provider_id)
        REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE,
    CONSTRAINT provider_contract_publication_contract_fk
        FOREIGN KEY (provider_contract_id, provider_id)
        REFERENCES provider_contract (id, provider_id) ON DELETE CASCADE,
    -- Rule 4.
    CONSTRAINT provider_contract_publication_project_fk
        FOREIGN KEY (source_project_id, tenant_id)
        REFERENCES projects (id, tenant_id) ON DELETE SET NULL (source_project_id),
    CONSTRAINT provider_contract_publication_source_version_fk
        FOREIGN KEY (source_version_id)
        REFERENCES versions (id) ON DELETE SET NULL
);

-- The referential checks, and "which provider versions carry this contract".
CREATE INDEX IF NOT EXISTS idx_provider_contract_publication_provider
    ON provider_contract_publication (provider_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_provider_contract_publication_version
    ON provider_contract_publication (provider_version_id, provider_id);
CREATE INDEX IF NOT EXISTS idx_provider_contract_publication_contract
    ON provider_contract_publication (provider_contract_id, provider_id);
CREATE INDEX IF NOT EXISTS idx_provider_contract_publication_project
    ON provider_contract_publication (source_project_id, tenant_id)
    WHERE source_project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_provider_contract_publication_source_version
    ON provider_contract_publication (source_version_id)
    WHERE source_version_id IS NOT NULL;

COMMENT ON TABLE provider_contract_publication IS
    'A provider version published an OpenAPI provider contract; write-once per version (PFX-2.1, #6925)';
COMMENT ON COLUMN provider_contract_publication.provider_version_id IS 'The provider''s application version that published the contract';
COMMENT ON COLUMN provider_contract_publication.provider_contract_id IS 'The document it published; shared by every provider version that published the same one';
COMMENT ON COLUMN provider_contract_publication.content_type IS 'The media type the document was sent as';
COMMENT ON COLUMN provider_contract_publication.source IS 'inline (the request carried the document) or apiome (rendered from an Apiome version)';
COMMENT ON COLUMN provider_contract_publication.source_project_id IS 'For source apiome: the project rendered from; cleared when the project is deleted';
COMMENT ON COLUMN provider_contract_publication.source_version_id IS 'For source apiome: the version rendered from; cleared when the version is deleted';
COMMENT ON COLUMN provider_contract_publication.source_project_slug IS 'For source apiome: the project slug at publication time';
COMMENT ON COLUMN provider_contract_publication.source_version_label IS 'For source apiome: the version label at publication time';
COMMENT ON COLUMN provider_contract_publication.verification_results IS 'Self-verification results sent with the contract (PFX-2.4), or NULL';
COMMENT ON COLUMN provider_contract_publication.actor_label IS 'Who published it, as text, kept after the user row is gone';
