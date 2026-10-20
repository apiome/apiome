-- Registry-as-source ingestion (#3978, MFI-18.5): the `registry` connector kind.
--
-- An import adapter can now declare a **registry crawl** (`ImportSource.registry_crawl`): list a
-- registry, page it, fetch each artifact and import it as its own catalog item. Every crawl runs on
-- the CDG-1.1 connector engine as one connector kind, `registry`, whose scope names the crawl
-- (`{"protocol": "a2a-registry" | "xregistry" | "fhir-metadata", ...}`). The engine already gives
-- each crawled artifact an inventory row (`catalog_connector_items`, keyed by its registry id), a
-- revision gate plus content digest for incremental re-crawl, per-revision provenance, cadence,
-- the tenant pull quota and the run ledger — so the only schema change is admitting the kind.
--
-- The V281 column check is unnamed, so Postgres named it `catalog_connectors_kind_check`; it is
-- dropped and re-created with the new kind. `apiome-rest/src/app/catalog_connectors.KINDS` mirrors
-- this list.
--
-- Rollback: delete any `registry` connectors, then restore the V281 list.

SET search_path TO apiome, public;

ALTER TABLE catalog_connectors DROP CONSTRAINT IF EXISTS catalog_connectors_kind_check;
ALTER TABLE catalog_connectors ADD CONSTRAINT catalog_connectors_kind_check
    CHECK (kind IN (
        'kong-konnect',
        'kong-admin',
        'aws-apigateway',
        'azure-apim',
        'apigee',
        'url',
        'schema-registry',
        'mcp-registry',
        'registry'
    ));

COMMENT ON COLUMN catalog_connectors.kind IS
    'Connector kind: a gateway (kong-konnect, kong-admin, aws-apigateway, azure-apim, apigee), url, schema-registry, mcp-registry, or registry (an adapter-declared registry crawl, MFI-18.5)';
