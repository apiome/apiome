-- Pact environments and deployment recording — PFX-1.5 (#6918).
--
-- can-i-deploy (PFX-1.6) answers "is it safe to deploy this version to *production*?", which needs to
-- know what is in production now. This migration stores where versions run:
--
--   pact_environment — a place versions are deployed or released to (`test`, `production`): name,
--                      display name, production flag, Apiome's contract-required flag, contacts.
--   deployed_version — one deployment of a pacticipant version to an environment, optionally to one
--                      application instance of it. `currently_deployed` until it is replaced or
--                      undeployed; the row stays as history either way.
--   released_version — a version released to an environment (a mobile app, a library: several
--                      versions are live at once). `currently_supported` until support ends.
--
-- Rules kept by the database:
--
--   1. **Environment names are unique per tenant** and are one word: no whitespace (the Pact
--      Broker's rule; `pact-broker record-deployment --environment` names one).
--   2. **One version is currently deployed per environment, pacticipant and application
--      instance.** A partial unique index over the currently deployed rows enforces it.
--      apiome-rest's `app.pact_environment_store.record_deployment` marks the previous one
--      undeployed in the same transaction before it inserts the new one.
--   3. **Deployment history is kept.** A deployed_version row never changes except to be marked
--      undeployed (`currently_deployed` true → false with `undeployed_at` set), once. A trigger
--      refuses everything else, apart from the database's own `created_by` SET NULL.
--   4. **A version is released to an environment once.** `released_version` is UNIQUE per
--      (version, environment); recording the release again starts supporting it again, as the
--      Pact Broker does. Only the support flag, its timestamp and `updated_at` may change.
--   5. **Nothing crosses a tenant.** Both record tables reference the version by
--      `(id, pacticipant_id)`, the pacticipant by `(id, tenant_id)` and the environment by
--      `(id, tenant_id)`, so a row can only join one tenant's rows.
--   6. **Records go with their environment, pacticipant and version.** Every reference cascades.
--
-- Apiome has no project-level environment model to link to (Slate's hosting lanes are per docs
-- site, and an API product member's `environment` is a free label), so environments live here; an
-- API product member's label is matched to a Pact environment by name.
--
-- Online: three new tables; nothing existing is rewritten.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.released_version, apiome.deployed_version, apiome.pact_environment;
--   DROP FUNCTION IF EXISTS apiome.deployed_version_history_guard();
--   DROP FUNCTION IF EXISTS apiome.released_version_history_guard();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. pact_environment
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_environment (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 1.
    name VARCHAR(255) NOT NULL
        CONSTRAINT pact_environment_name_shape_check
            CHECK (name <> '' AND name !~ '[[:space:][:cntrl:]]'),
    display_name VARCHAR(255) NOT NULL
        CONSTRAINT pact_environment_display_name_check
            CHECK (btrim(display_name) <> '' AND display_name !~ '[[:cntrl:]]'),
    -- What can-i-deploy reads: whether this is a production environment, and (Apiome) whether a
    -- pacticipant must have a contract before it can be deployed here.
    production BOOLEAN NOT NULL DEFAULT FALSE,
    contract_required BOOLEAN NOT NULL DEFAULT FALSE,
    -- Who to talk to about the environment: `[{"name": …, "details": {…}}]`, as the broker takes it.
    contacts JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT pact_environment_contacts_array_check CHECK (jsonb_typeof(contacts) = 'array'),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_environment_tenant_name_key UNIQUE (tenant_id, name),
    -- Rule 5: the key the record tables reference.
    CONSTRAINT pact_environment_id_tenant_key UNIQUE (id, tenant_id)
);

COMMENT ON TABLE pact_environment IS
    'A place pacticipant versions are deployed or released to (PFX-1.5, #6918)';
COMMENT ON COLUMN pact_environment.name IS 'The name tooling uses (`production`); unique per tenant, no whitespace';
COMMENT ON COLUMN pact_environment.display_name IS 'The name people read (`Production`)';
COMMENT ON COLUMN pact_environment.production IS 'Whether this is a production environment';
COMMENT ON COLUMN pact_environment.contract_required IS
    'Apiome: whether a pacticipant must have a contract before can-i-deploy allows it here';
COMMENT ON COLUMN pact_environment.contacts IS 'Who to contact about the environment, as the Pact Broker takes them';

-- ---------------------------------------------------------------------------------------------------
-- 2. deployed_version
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS deployed_version (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Constrained through the pacticipant reference below.
    tenant_id UUID NOT NULL,
    pacticipant_id UUID NOT NULL,
    version_id UUID NOT NULL,
    environment_id UUID NOT NULL,

    -- One deployment target inside the environment (a region, a customer's instance). NULL is the
    -- environment's only, unnamed instance.
    application_instance VARCHAR(255)
        CONSTRAINT deployed_version_application_instance_check
            CHECK (application_instance IS NULL
                   OR (application_instance <> '' AND application_instance = btrim(application_instance)
                       AND application_instance !~ '[[:cntrl:]]')),

    currently_deployed BOOLEAN NOT NULL DEFAULT TRUE,
    undeployed_at TIMESTAMP WITH TIME ZONE,
    -- Order of recording across the table.
    seq BIGINT GENERATED ALWAYS AS IDENTITY,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT deployed_version_undeployed_check CHECK (currently_deployed = (undeployed_at IS NULL)),
    CONSTRAINT deployed_version_version_fk
        FOREIGN KEY (version_id, pacticipant_id)
        REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE,
    CONSTRAINT deployed_version_pacticipant_fk
        FOREIGN KEY (pacticipant_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT deployed_version_environment_fk
        FOREIGN KEY (environment_id, tenant_id)
        REFERENCES pact_environment (id, tenant_id) ON DELETE CASCADE
);

-- Rule 2. Also the read "what is deployed to this environment now".
CREATE UNIQUE INDEX IF NOT EXISTS uq_deployed_version_current
    ON deployed_version (environment_id, pacticipant_id, COALESCE(application_instance, ''))
    WHERE currently_deployed;
-- The referential checks, and "where is this version deployed" (the selectors, PFX-1.3) and
-- "every deployment of this pacticipant" (history).
CREATE INDEX IF NOT EXISTS idx_deployed_version_environment
    ON deployed_version (environment_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_deployed_version_pacticipant
    ON deployed_version (pacticipant_id, tenant_id, seq DESC);
CREATE INDEX IF NOT EXISTS idx_deployed_version_version
    ON deployed_version (version_id, pacticipant_id);

COMMENT ON TABLE deployed_version IS
    'One deployment of a pacticipant version to an environment; kept as history once undeployed (PFX-1.5, #6918)';
COMMENT ON COLUMN deployed_version.application_instance IS
    'The instance of the environment deployed to; NULL for the environment''s only instance';
COMMENT ON COLUMN deployed_version.currently_deployed IS
    'True until the version is replaced or undeployed; never set back to true';
COMMENT ON COLUMN deployed_version.undeployed_at IS 'When it stopped being deployed; NULL while currently deployed';

-- Rule 3.
CREATE OR REPLACE FUNCTION apiome.deployed_version_history_guard()
RETURNS trigger AS $$
BEGIN
    IF (to_jsonb(NEW) - 'created_by' - 'currently_deployed' - 'undeployed_at')
           = (to_jsonb(OLD) - 'created_by' - 'currently_deployed' - 'undeployed_at')
       AND (NEW.created_by IS NULL OR NEW.created_by IS NOT DISTINCT FROM OLD.created_by)
       AND (NEW.currently_deployed = OLD.currently_deployed
            OR (OLD.currently_deployed AND NOT NEW.currently_deployed))
       AND (OLD.undeployed_at IS NULL OR NEW.undeployed_at IS NOT DISTINCT FROM OLD.undeployed_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'deployed_version % can only be marked undeployed, once', OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_deployed_version_history_guard ON deployed_version;
CREATE TRIGGER trg_deployed_version_history_guard
    BEFORE UPDATE ON deployed_version
    FOR EACH ROW
    EXECUTE FUNCTION apiome.deployed_version_history_guard();

-- ---------------------------------------------------------------------------------------------------
-- 3. released_version
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS released_version (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Constrained through the pacticipant reference below.
    tenant_id UUID NOT NULL,
    pacticipant_id UUID NOT NULL,
    version_id UUID NOT NULL,
    environment_id UUID NOT NULL,

    currently_supported BOOLEAN NOT NULL DEFAULT TRUE,
    support_ended_at TIMESTAMP WITH TIME ZONE,
    seq BIGINT GENERATED ALWAYS AS IDENTITY,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT released_version_support_check CHECK (currently_supported = (support_ended_at IS NULL)),
    -- Rule 4.
    CONSTRAINT released_version_version_environment_key UNIQUE (version_id, environment_id),
    CONSTRAINT released_version_version_fk
        FOREIGN KEY (version_id, pacticipant_id)
        REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE,
    CONSTRAINT released_version_pacticipant_fk
        FOREIGN KEY (pacticipant_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT released_version_environment_fk
        FOREIGN KEY (environment_id, tenant_id)
        REFERENCES pact_environment (id, tenant_id) ON DELETE CASCADE
);

-- "What is supported in this environment now", the referential checks, and history.
CREATE INDEX IF NOT EXISTS idx_released_version_environment
    ON released_version (environment_id, tenant_id, pacticipant_id);
CREATE INDEX IF NOT EXISTS idx_released_version_pacticipant
    ON released_version (pacticipant_id, tenant_id, seq DESC);
CREATE INDEX IF NOT EXISTS idx_released_version_version
    ON released_version (version_id, pacticipant_id);

COMMENT ON TABLE released_version IS
    'A pacticipant version released to an environment, supported until support ends (PFX-1.5, #6918)';
COMMENT ON COLUMN released_version.currently_supported IS
    'True while the release is supported; recording the release again sets it back to true';
COMMENT ON COLUMN released_version.support_ended_at IS 'When support ended; NULL while supported';

-- Rule 4: only the support flag moves.
CREATE OR REPLACE FUNCTION apiome.released_version_history_guard()
RETURNS trigger AS $$
BEGIN
    IF (to_jsonb(NEW) - 'created_by' - 'currently_supported' - 'support_ended_at' - 'updated_at')
           = (to_jsonb(OLD) - 'created_by' - 'currently_supported' - 'support_ended_at' - 'updated_at')
       AND (NEW.created_by IS NULL OR NEW.created_by IS NOT DISTINCT FROM OLD.created_by) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'released_version % can only change whether it is supported', OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_released_version_history_guard ON released_version;
CREATE TRIGGER trg_released_version_history_guard
    BEFORE UPDATE ON released_version
    FOR EACH ROW
    EXECUTE FUNCTION apiome.released_version_history_guard();
