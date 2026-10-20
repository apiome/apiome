-- Backstage and Compass import — CDG-5.5 (#5983).
--
-- Teams leaving Backstage or Atlassian Compass bring a catalog of components, systems, domains and
-- groups. This migration gives that catalog a place to land, and keeps the rule that nothing an
-- importer reads becomes a confirmed owner or a resolved entity without a click:
--
--   catalog_import_runs        — one import report: a repository branch's `catalog-info.yaml`
--                                files (re-written by each scan) or one uploaded Compass export.
--                                It keeps the counts and every field the importer could not map.
--   catalog_import_suggestions — what a run found, staged: a component (Backstage `Component`,
--                                `System`, `Domain`; a Compass component) or a team (a Backstage
--                                `Group`, a Compass owner). Each waits as `suggested` until someone
--                                accepts or dismisses it.
--   catalog_components         — an accepted component: a catalog entity of the new kind
--                                `component`, with its links, an owner team (CDG-2.2) and declared
--                                edges (CDG-3.2).
--
-- `component` joins the graph's node kinds, the owner kinds and the kinds a declared dependency
-- can come from.
--
-- Rules kept by the database:
--
--   1. **One suggestion per thing per source.** A suggestion is keyed by (tenant, source, kind,
--      external ref), so a re-scan or a re-uploaded export refreshes it and keeps its decision.
--   2. **One live component per external ref**, and component slugs are handles unique among a
--      tenant's live components. Deletes are soft, so an edge or an audit entry still resolves.
--   3. **A decided suggestion says who decided it and when.**
--   4. **Deleting a repository deletes its import report** (ON DELETE CASCADE), and deleting a
--      report deletes its suggestions.
--
-- Rollback notes (reverse carefully in shared environments):
--   DELETE FROM apiome.catalog_edges WHERE from_kind = 'component' OR to_kind = 'component';
--   DELETE FROM apiome.catalog_unresolved_dependencies WHERE from_kind = 'component';
--   DELETE FROM apiome.entity_owners WHERE entity_kind = 'component';
--   DELETE FROM apiome.unowned_findings WHERE entity_kind = 'component';
--   -- re-add catalog_edges_node_kinds_check and both owner kind checks with the V298 kinds, and
--   -- catalog_unresolved_dependencies_from_kind_check with the V289 kinds;
--   DROP TABLE IF EXISTS apiome.catalog_components;
--   DROP TABLE IF EXISTS apiome.catalog_import_suggestions;
--   DROP TABLE IF EXISTS apiome.catalog_import_runs;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- catalog_import_runs — one import report.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_import_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source VARCHAR(16) NOT NULL
        CONSTRAINT catalog_import_runs_source_check CHECK (source IN ('backstage', 'compass')),
    -- `backstage:<repository id>@<branch>` (one report per branch, re-written by each scan) or
    -- `compass:<upload id>` (one report per upload).
    source_ref TEXT NOT NULL
        CONSTRAINT catalog_import_runs_source_ref_check CHECK (length(source_ref) BETWEEN 1 AND 600),
    -- What the person sees: "acme/payments · main", "compass-export.json".
    label VARCHAR(400) NOT NULL
        CONSTRAINT catalog_import_runs_label_not_blank_check CHECK (btrim(label) <> ''),
    repository_id UUID REFERENCES tenant_repositories(id) ON DELETE CASCADE,
    branch TEXT,
    -- {files, entities, apis_imported, components, teams, owner_suggestions, declared, unresolved}.
    counts JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT catalog_import_runs_counts_object_check CHECK (jsonb_typeof(counts) = 'object'),
    -- [{entity, field, reason}] — every field the importer did not map (capped; see unmapped_total).
    unmapped JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT catalog_import_runs_unmapped_array_check CHECK (jsonb_typeof(unmapped) = 'array'),
    unmapped_total INTEGER NOT NULL DEFAULT 0
        CONSTRAINT catalog_import_runs_unmapped_total_check CHECK (unmapped_total >= 0),
    -- [{entityKind, entityId, externalRef, ownerRef, digest}] — existing entities the run read: the
    -- catalog items its Backstage APIs were imported into (with the definition's digest, so an
    -- unchanged definition is not imported again) and the Projects its components matched. A team
    -- created from a suggestion later is suggested as their owner.
    entity_refs JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT catalog_import_runs_entity_refs_array_check CHECK (jsonb_typeof(entity_refs) = 'array'),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT catalog_import_runs_identity_key UNIQUE (tenant_id, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_catalog_import_runs_tenant_updated
    ON catalog_import_runs (tenant_id, updated_at DESC);

COMMENT ON TABLE catalog_import_runs IS
    'One Backstage or Compass import report: counts and every unmapped field (CDG-5.5, #5983)';

-- ---------------------------------------------------------------------------------------------------
-- catalog_import_suggestions — what a run found, waiting for a click.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_import_suggestions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES catalog_import_runs(id) ON DELETE CASCADE,
    source VARCHAR(16) NOT NULL
        CONSTRAINT catalog_import_suggestions_source_check CHECK (source IN ('backstage', 'compass')),
    suggestion_kind VARCHAR(16) NOT NULL
        CONSTRAINT catalog_import_suggestions_kind_check CHECK (suggestion_kind IN ('component', 'team')),
    -- The thing in its own catalog: `component:default/payments`, a Compass component or team ARI.
    external_ref TEXT NOT NULL
        CONSTRAINT catalog_import_suggestions_external_ref_check CHECK (length(external_ref) BETWEEN 1 AND 600),
    name VARCHAR(400) NOT NULL
        CONSTRAINT catalog_import_suggestions_name_not_blank_check CHECK (btrim(name) <> ''),
    slug VARCHAR(128) NOT NULL
        CONSTRAINT catalog_import_suggestions_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    -- What accepting would write: description, category, type, links, owner ref, references.
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT catalog_import_suggestions_payload_object_check CHECK (jsonb_typeof(payload) = 'object'),
    -- An existing Project or catalog item the component already is (its providesApis or its slug).
    match_kind VARCHAR(32)
        CONSTRAINT catalog_import_suggestions_match_kind_check
            CHECK (match_kind IS NULL OR match_kind IN ('project', 'catalog_item')),
    match_id UUID,
    status VARCHAR(16) NOT NULL DEFAULT 'suggested'
        CONSTRAINT catalog_import_suggestions_status_check CHECK (status IN ('suggested', 'accepted', 'dismissed')),
    -- What accepting made or applied to: a component, a team, or the matched Project/catalog item.
    entity_kind VARCHAR(32),
    entity_id UUID,
    decided_by UUID REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT catalog_import_suggestions_match_pair_check CHECK ((match_kind IS NULL) = (match_id IS NULL)),
    CONSTRAINT catalog_import_suggestions_decided_stamp_check
        CHECK ((status = 'suggested') = (decided_at IS NULL)),
    CONSTRAINT catalog_import_suggestions_accepted_entity_check
        CHECK (status <> 'accepted' OR (entity_kind IS NOT NULL AND entity_id IS NOT NULL)),
    CONSTRAINT catalog_import_suggestions_identity_key
        UNIQUE (tenant_id, source, suggestion_kind, external_ref)
);

CREATE INDEX IF NOT EXISTS idx_catalog_import_suggestions_run
    ON catalog_import_suggestions (run_id, suggestion_kind, status);

COMMENT ON TABLE catalog_import_suggestions IS
    'Backstage and Compass components and teams staged until accepted or dismissed (CDG-5.5, #5983)';

-- ---------------------------------------------------------------------------------------------------
-- catalog_components — the `component` entity kind.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_components (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug VARCHAR(128) NOT NULL
        CONSTRAINT catalog_components_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    name VARCHAR(400) NOT NULL
        CONSTRAINT catalog_components_name_not_blank_check CHECK (btrim(name) <> ''),
    description TEXT
        CONSTRAINT catalog_components_description_length_check CHECK (description IS NULL OR length(description) <= 4000),
    -- Backstage's entity kinds; a Compass component is a `component`.
    category VARCHAR(16) NOT NULL DEFAULT 'component'
        CONSTRAINT catalog_components_category_check CHECK (category IN ('component', 'system', 'domain')),
    -- Backstage `spec.type` (service, website, library) or the Compass type (SERVICE, LIBRARY, …).
    component_type VARCHAR(64),
    lifecycle VARCHAR(64),
    -- The system or domain it belongs to, as written (`system:default/payments`).
    parent_ref VARCHAR(600),
    -- [{type, url, title}] — type is chat, on_call, document, repository, dashboard or other.
    links JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT catalog_components_links_array_check CHECK (jsonb_typeof(links) = 'array'),
    source VARCHAR(16) NOT NULL
        CONSTRAINT catalog_components_source_check CHECK (source IN ('backstage', 'compass')),
    -- The declaring source of its edges: `backstage:<path>` or `compass:<upload id>`.
    source_ref TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_components_tenant_slug
    ON catalog_components (tenant_id, slug)
    WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_components_external
    ON catalog_components (tenant_id, source, external_ref)
    WHERE deleted_at IS NULL;

COMMENT ON TABLE catalog_components IS
    'Accepted Backstage or Compass components, systems and domains: the component entity kind (CDG-5.5, #5983)';

-- ---------------------------------------------------------------------------------------------------
-- Widened checks.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE catalog_edges DROP CONSTRAINT IF EXISTS catalog_edges_node_kinds_check;
ALTER TABLE catalog_edges
    ADD CONSTRAINT catalog_edges_node_kinds_check CHECK (
        from_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector',
                      'repository', 'mcp_source', 'identity_group', 'gateway_config', 'component')
        AND to_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector',
                        'repository', 'mcp_source', 'identity_group', 'gateway_config', 'component')
    );

ALTER TABLE catalog_unresolved_dependencies DROP CONSTRAINT IF EXISTS catalog_unresolved_dependencies_from_kind_check;
ALTER TABLE catalog_unresolved_dependencies
    ADD CONSTRAINT catalog_unresolved_dependencies_from_kind_check CHECK (from_kind IN (
        'project', 'catalog_item', 'consumer', 'connector', 'mcp_endpoint', 'mcp_source', 'repository',
        'identity_group', 'component'
    ));

ALTER TABLE entity_owners DROP CONSTRAINT IF EXISTS entity_owners_kind_check;
ALTER TABLE entity_owners
    ADD CONSTRAINT entity_owners_kind_check
        CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model',
                               'gateway_config', 'component'));

ALTER TABLE unowned_findings DROP CONSTRAINT IF EXISTS unowned_findings_kind_check;
ALTER TABLE unowned_findings
    ADD CONSTRAINT unowned_findings_kind_check
        CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model',
                               'gateway_config', 'component'));
