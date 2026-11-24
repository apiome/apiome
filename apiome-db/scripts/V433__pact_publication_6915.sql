-- Pact publication — PFX-1.2 (#6915).
--
-- V432 says *who* takes part in a pact (pacticipants, their versions, branches and tags). This
-- migration stores the pacts themselves, in two tables:
--
--   pact_version     — one distinct pact between a consumer and a provider, addressed by the SHA-256
--                      of its canonical content. The document is kept as published, in JSONB.
--   pact_publication — "consumer version V published this pact for provider P": the link from a
--                      pacticipant_version to the pact_version it carries.
--
-- Rules kept by the database:
--
--   1. **Content is stored once.** `pact_version` is UNIQUE on (consumer, provider, sha), so the
--      same pact published for ten consumer versions is one row with ten publications — and one
--      target for a provider to verify.
--   2. **One pact per consumer version and provider.** `pact_publication` is UNIQUE on
--      (consumer_version_id, consumer_id, provider_id). Publishing different content for a version
--      that already has a pact is refused by apiome-rest (409) unless the deployment allows it, in
--      which case the row is repointed and `revision` counts the change.
--   3. **Nothing crosses a tenant.** `pact_version` carries `tenant_id` and references both
--      pacticipants by `(id, tenant_id)`, so a consumer and a provider of different tenants cannot
--      share a pact. A publication references its pact version by `(id, consumer_id, provider_id)`
--      and its consumer version by `(id, pacticipant_id)`, so it can only join rows of the same
--      pair.
--   4. **A pact goes with its pacticipants.** Every reference is ON DELETE CASCADE: deleting a
--      pacticipant removes its versions (V432) and with them the pacts it published or was named
--      in.
--
-- Online: two new tables, and one unique index on `pacticipant (id, tenant_id)` built in place
-- (the table is small: one row per application).
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.pact_publication, apiome.pact_version;
--   ALTER TABLE apiome.pacticipant DROP CONSTRAINT IF EXISTS pacticipant_id_tenant_key;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 0. The composite key a pact's two pacticipants are referenced by (rule 3)
-- ---------------------------------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pacticipant_id_tenant_key' AND conrelid = 'apiome.pacticipant'::regclass
    ) THEN
        ALTER TABLE apiome.pacticipant ADD CONSTRAINT pacticipant_id_tenant_key UNIQUE (id, tenant_id);
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------------------------------
-- 1. pact_version — one distinct pact between a consumer and a provider
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_version (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Constrained through the two pacticipant references below, which is why it needs no reference
    -- to tenants of its own.
    tenant_id UUID NOT NULL,
    consumer_id UUID NOT NULL,
    provider_id UUID NOT NULL,

    -- Rule 1. Lowercase hex SHA-256 of the pact's canonical content (apiome-rest
    -- app.pact_publication.pact_content_sha): the part of the document a verification depends on.
    sha CHAR(64) NOT NULL
        CONSTRAINT pact_version_sha_shape_check CHECK (sha ~ '^[0-9a-f]{64}$'),
    -- The Pact document as the consumer published it.
    content JSONB NOT NULL
        CONSTRAINT pact_version_content_object_check CHECK (jsonb_typeof(content) = 'object'),
    -- The Pact specification version the document declares (`2.0.0`, `4.0`), when it declares one.
    specification_version VARCHAR(32),
    -- How many interactions (or messages) the document carries.
    interaction_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT pact_version_interaction_count_check CHECK (interaction_count >= 0),

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_version_content_key UNIQUE (consumer_id, provider_id, sha),
    -- Referenced by pact_publication (rule 3).
    CONSTRAINT pact_version_id_pair_key UNIQUE (id, consumer_id, provider_id),
    CONSTRAINT pact_version_consumer_fk
        FOREIGN KEY (consumer_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_version_provider_fk
        FOREIGN KEY (provider_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

-- The referential checks of the two pacticipants, and "the pacts this provider must honour".
CREATE INDEX IF NOT EXISTS idx_pact_version_consumer
    ON pact_version (consumer_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_version_provider
    ON pact_version (provider_id, tenant_id);

COMMENT ON TABLE pact_version IS
    'One distinct pact between a consumer and a provider, addressed by the SHA-256 of its canonical content (PFX-1.2, #6915)';
COMMENT ON COLUMN pact_version.tenant_id IS 'Owning tenant; equal to the tenant of both pacticipants by the composite references';
COMMENT ON COLUMN pact_version.consumer_id IS 'The consumer pacticipant';
COMMENT ON COLUMN pact_version.provider_id IS 'The provider pacticipant';
COMMENT ON COLUMN pact_version.sha IS 'Lowercase hex SHA-256 of the canonical content; unique per consumer and provider';
COMMENT ON COLUMN pact_version.content IS 'The Pact document as published (specification 1.x to 4.x)';
COMMENT ON COLUMN pact_version.specification_version IS 'The Pact specification version the document declares, if any';
COMMENT ON COLUMN pact_version.interaction_count IS 'How many interactions or messages the document carries';

-- ---------------------------------------------------------------------------------------------------
-- 2. pact_publication — a consumer version published a pact for a provider
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_publication (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    consumer_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    consumer_version_id UUID NOT NULL,
    pact_version_id UUID NOT NULL,

    -- 1 for the first publication; +1 each time the pact of this consumer version is replaced by
    -- different content (only possible where the deployment allows it).
    revision INTEGER NOT NULL DEFAULT 1
        CONSTRAINT pact_publication_revision_check CHECK (revision >= 1),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    -- Email or key name at the time of publishing, kept after the user is gone.
    actor_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- When the pact of this consumer version was last replaced.
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 2.
    CONSTRAINT pact_publication_version_provider_key
        UNIQUE (consumer_version_id, consumer_id, provider_id),
    -- Rule 3: the version is the consumer's, and the pact is this pair's.
    CONSTRAINT pact_publication_consumer_version_fk
        FOREIGN KEY (consumer_version_id, consumer_id)
        REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE,
    CONSTRAINT pact_publication_pact_version_fk
        FOREIGN KEY (pact_version_id, consumer_id, provider_id)
        REFERENCES pact_version (id, consumer_id, provider_id) ON DELETE CASCADE
);

-- The referential check of the pact version, and "which consumer versions carry this pact".
CREATE INDEX IF NOT EXISTS idx_pact_publication_pact_version
    ON pact_publication (pact_version_id, consumer_id, provider_id);
-- "The pacts between this consumer and this provider" — what the latest-pact read walks.
CREATE INDEX IF NOT EXISTS idx_pact_publication_pair
    ON pact_publication (provider_id, consumer_id);

COMMENT ON TABLE pact_publication IS
    'A consumer version published a pact for a provider: links a pacticipant_version to its pact_version (PFX-1.2, #6915)';
COMMENT ON COLUMN pact_publication.consumer_version_id IS 'The consumer''s application version that published the pact';
COMMENT ON COLUMN pact_publication.pact_version_id IS 'The content it published; shared by every consumer version that published the same pact';
COMMENT ON COLUMN pact_publication.revision IS '1 on first publication; incremented when the pact of this consumer version is replaced';
COMMENT ON COLUMN pact_publication.actor_label IS 'Who published it, as text, kept after the user row is gone';
COMMENT ON COLUMN pact_publication.updated_at IS 'When the pact of this consumer version was last replaced';
