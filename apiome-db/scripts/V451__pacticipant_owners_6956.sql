-- Teams and ownership for pacticipants — PFX-6.4 (#6956).
--
-- A pacticipant (an application in the workspace's Pact Broker, V432) can now have an owner team,
-- the same way a project, a consumer or a connector does (CDG-2.2, V285): at most one confirmed
-- owner and any number of suggestions in `entity_owners`, with `entity_kind = 'pacticipant'` and
-- `entity_id` the pacticipant's id. Pact findings — a stale pact, a re-publish request, a failed
-- verification — are routed to that team by owner routing (CDG-2.3), and a pacticipant with no
-- confirmed owner lands in the Unowned findings report (`unowned_findings`) like any other entity.
--
-- This migration only widens the two owner kind checks by `pacticipant`; no table, column or
-- index changes. apiome-rest removes a pacticipant's owner rows and unowned findings when the
-- retention sweep purges it for good (a soft-deleted pacticipant keeps its owner, so a restore
-- brings it back with it).
--
-- Online: two constraint swaps on small tables.
--
-- Rollback notes (reverse carefully in shared environments):
--   DELETE FROM apiome.entity_owners WHERE entity_kind = 'pacticipant';
--   DELETE FROM apiome.unowned_findings WHERE entity_kind = 'pacticipant';
--   -- re-add entity_owners_kind_check and unowned_findings_kind_check with the V299 kinds.

SET search_path TO apiome, public;

ALTER TABLE entity_owners DROP CONSTRAINT IF EXISTS entity_owners_kind_check;
ALTER TABLE entity_owners
    ADD CONSTRAINT entity_owners_kind_check
        CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model',
                               'gateway_config', 'component', 'pacticipant'));

ALTER TABLE unowned_findings DROP CONSTRAINT IF EXISTS unowned_findings_kind_check;
ALTER TABLE unowned_findings
    ADD CONSTRAINT unowned_findings_kind_check
        CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model',
                               'gateway_config', 'component', 'pacticipant'));

COMMENT ON COLUMN entity_owners.entity_kind IS
    'project | catalog_item | mcp_endpoint | consumer | connector | agent | model | gateway_config | component | pacticipant';
