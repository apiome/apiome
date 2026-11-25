-- Provider-state registry — PFX-3.3 (#6933).
--
-- A pact interaction says "given an invoice 1042 exists". Before the hosted verifier (PFX-3.2)
-- replays it, the provider has to be put into that state. This migration stores, per provider,
-- the states it knows how to set up and how:
--
--   pact_provider_state          — one state of one provider: its name (as consumers write it),
--                                  the parameters it takes, and its setup — a call to a
--                                  state-change URL (the Pact state-change protocol) or a
--                                  recorded fixture (requests sent to the verification target).
--   pact_provider_state_override — a different setup for one state on one verification target
--                                  (staging seeds by fixture, a dev stack has a state-change URL).
--
-- Rules kept by the database:
--
--   1. **A state name is unique per provider** — the verifier looks states up by name.
--   2. **Setup is a closed list of kinds** (`state_change`, `fixture`); its shape is checked by
--      apiome-rest (`app.pact_provider_state`), which also runs the SSRF guard on a URL.
--   3. **Nothing crosses a tenant.** A state names its provider by `(id, tenant_id)`; an override
--      names its state and its verification target the same way.
--   4. **A state goes with its provider; an override with its state or its target.**
--
-- No secret is stored: a state-change call on the target carries the target's own credential
-- reference (ECA-1.2), resolved at run time; a call elsewhere carries none.
--
-- Online: two new tables; nothing existing is rewritten.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.pact_provider_state_override;
--   DROP TABLE IF EXISTS apiome.pact_provider_state;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. pact_provider_state
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_provider_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL,

    -- The state exactly as consumers write it in `providerStates[].name` / `providerState`.
    name TEXT NOT NULL
        CONSTRAINT pact_provider_state_name_check
            CHECK (length(btrim(name)) >= 1 AND length(name) <= 500),
    description TEXT
        CONSTRAINT pact_provider_state_description_check
            CHECK (description IS NULL OR length(description) <= 1000),

    -- [{name, required, default, description}] — the parameters the state takes.
    parameters JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT pact_provider_state_parameters_check CHECK (jsonb_typeof(parameters) = 'array'),

    -- {kind: 'state_change', url, teardown} or {kind: 'fixture', setup: [...], teardown: [...]}.
    setup JSONB NOT NULL
        CONSTRAINT pact_provider_state_setup_check
            CHECK (jsonb_typeof(setup) = 'object' AND setup->>'kind' IN ('state_change', 'fixture')),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_provider_state_name_key UNIQUE (tenant_id, provider_id, name),
    -- The target of pact_provider_state_override's composite reference.
    CONSTRAINT pact_provider_state_id_tenant_key UNIQUE (id, tenant_id),
    CONSTRAINT pact_provider_state_provider_fk
        FOREIGN KEY (provider_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

-- The provider reference's check (the name key leads with tenant_id).
CREATE INDEX IF NOT EXISTS idx_pact_provider_state_provider
    ON pact_provider_state (provider_id, tenant_id);

COMMENT ON TABLE pact_provider_state IS
    'A provider state the hosted Pact verifier can set up, and how (PFX-3.3, #6933)';
COMMENT ON COLUMN pact_provider_state.name IS 'The state as consumers write it; unique per provider';
COMMENT ON COLUMN pact_provider_state.parameters IS 'Declared parameters: [{name, required, default, description}]';
COMMENT ON COLUMN pact_provider_state.setup IS
    'state_change {url, teardown} or fixture {setup: [request], teardown: [request]}; checked by apiome-rest';

-- ---------------------------------------------------------------------------------------------------
-- 2. pact_provider_state_override
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_provider_state_override (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    state_id UUID NOT NULL,
    target_id UUID NOT NULL,

    setup JSONB NOT NULL
        CONSTRAINT pact_provider_state_override_setup_check
            CHECK (jsonb_typeof(setup) = 'object' AND setup->>'kind' IN ('state_change', 'fixture')),

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_provider_state_override_key UNIQUE (state_id, target_id),
    CONSTRAINT pact_provider_state_override_state_fk
        FOREIGN KEY (state_id, tenant_id)
        REFERENCES pact_provider_state (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT pact_provider_state_override_target_fk
        FOREIGN KEY (target_id, tenant_id)
        REFERENCES verification_target (id, tenant_id) ON DELETE CASCADE
);

-- The target reference's check (the override key leads with state_id).
CREATE INDEX IF NOT EXISTS idx_pact_provider_state_override_target
    ON pact_provider_state_override (target_id, tenant_id);

COMMENT ON TABLE pact_provider_state_override IS
    'A provider state''s setup on one verification target, in place of its default (PFX-3.3)';
COMMENT ON COLUMN pact_provider_state_override.setup IS 'Same shape as pact_provider_state.setup';
