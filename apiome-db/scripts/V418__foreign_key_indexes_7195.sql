-- Foreign-key index coverage (DBP-1.12, #7195).
--
-- Deleting a row (or changing its key) runs PostgreSQL's referential check against every table
-- that references it: SELECT 1 FROM ONLY <child> WHERE <fk col> = $1 FOR KEY SHARE, as a cached
-- generic plan. With no index led by the foreign-key column that is a sequential scan of the child
-- table, once per deleted parent row. An index partial on deleted_at IS NULL does not help: the
-- check says nothing about deleted_at, so the planner cannot use it. A partial index on
-- <fk col> IS NOT NULL does (the planner proves it from <fk col> = $1).
--
-- On the migrated schema (V417), 388 of 1,024 foreign keys had no index the check can use: 303
-- with none, 85 covered only by a partial index of the wrong kind. (A count that treats every
-- partial index as unusable finds 473; 85 of those partials are on <fk col> IS NOT NULL and serve
-- the check.) Measured on the DBP-1.1 scale database (1.0M classes), the REST hard-delete sequence
-- (Database.permanently_delete_project) spent 27 ms of one version delete and 224 ms of a
-- ten-version project delete in classes_version_id_fkey alone, a sequential scan of classes.
--
-- This migration indexes the 166 that reference anything other than users: every foreign key a
-- version, project, tenant, MCP endpoint version or verification run delete reaches, and the
-- run, event and delivery logs under the configuration rows (delivery profiles, presets,
-- repositories, webhooks) that people delete in normal use.
--
--   * A NOT NULL foreign-key column gets a plain index.
--   * A nullable one gets a partial index WHERE <col> IS NOT NULL (47 of them): it serves the
--     check and costs nothing when a row leaves the column empty, which most of these
--     (replacement_id, baseline_run_id, delivery_profile_id …) do.
--   * Where a non-unique index on exactly the same columns was partial on deleted_at IS NULL, the
--     new index replaces it (31 drops). Every query that used the partial one filters on the same
--     column, so it uses the new one; its live-row filter becomes a heap filter.
--
-- The 222 foreign keys to users (created_by, updated_by, decided_by-style columns on nearly every
-- table) are left unindexed on purpose. Users are only hard-deleted by the admin CLI
-- (apiome-db users delete); the app soft-deletes them. Indexing them would add a write to almost
-- every insert in the schema to speed up a rare operator command, so that command accepts the
-- scan. They are listed one by one, with that reason, in
-- apiome-db/test/foreign-key-index-allowlist.json; test/foreign-key-index-coverage.test.ts
-- fails when a migration adds a foreign key that has no usable index and is not on that list.
--
-- Large databases: a migration runs in one transaction, so these are plain CREATE INDEX
-- statements and each blocks writes to its table while it builds. Only classes (1M rows on the
-- scale database: about 1 s) and the run / job tables are large. To avoid the block, build them
-- first by hand with CREATE INDEX CONCURRENTLY (same names and definitions); every statement is
-- IF [NOT] EXISTS, so the migration then only drops the replaced indexes.
--
-- Rollback notes: DROP INDEX the idx_*_fk indexes created here; recreate a replaced index from
-- the migration that introduced it (its name is in the comment above its DROP).

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.versions (15)
-- ---------------------------------------------------------------------------------------------

-- api_agent_descriptors_version_id_fkey (replaces idx_api_agent_descriptors_version_id)
CREATE INDEX IF NOT EXISTS idx_api_agent_descriptors_version_id_fk
    ON apiome.api_agent_descriptors (version_id);
DROP INDEX IF EXISTS apiome.idx_api_agent_descriptors_version_id;

-- api_agent_skills_version_id_fkey (replaces idx_api_agent_skills_version_id)
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_version_id_fk
    ON apiome.api_agent_skills (version_id);
DROP INDEX IF EXISTS apiome.idx_api_agent_skills_version_id;

-- api_artifacts_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_artifacts_version_id_fk
    ON apiome.api_artifacts (version_id);

-- api_channels_version_id_fkey (replaces idx_api_channels_version_id)
CREATE INDEX IF NOT EXISTS idx_api_channels_version_id_fk
    ON apiome.api_channels (version_id);
DROP INDEX IF EXISTS apiome.idx_api_channels_version_id;

-- api_fields_version_id_fkey (replaces idx_api_fields_version_id)
CREATE INDEX IF NOT EXISTS idx_api_fields_version_id_fk
    ON apiome.api_fields (version_id);
DROP INDEX IF EXISTS apiome.idx_api_fields_version_id;

-- api_messages_version_id_fkey (replaces idx_api_messages_version_id)
CREATE INDEX IF NOT EXISTS idx_api_messages_version_id_fk
    ON apiome.api_messages (version_id);
DROP INDEX IF EXISTS apiome.idx_api_messages_version_id;

-- api_operations_version_id_fkey (replaces idx_api_operations_version_id)
CREATE INDEX IF NOT EXISTS idx_api_operations_version_id_fk
    ON apiome.api_operations (version_id);
DROP INDEX IF EXISTS apiome.idx_api_operations_version_id;

-- api_services_version_id_fkey (replaces idx_api_services_version_id)
CREATE INDEX IF NOT EXISTS idx_api_services_version_id_fk
    ON apiome.api_services (version_id);
DROP INDEX IF EXISTS apiome.idx_api_services_version_id;

-- api_types_version_id_fkey (replaces idx_api_types_version_id)
CREATE INDEX IF NOT EXISTS idx_api_types_version_id_fk
    ON apiome.api_types (version_id);
DROP INDEX IF EXISTS apiome.idx_api_types_version_id;

-- api_workflow_steps_version_id_fkey (replaces idx_api_workflow_steps_version_id)
CREATE INDEX IF NOT EXISTS idx_api_workflow_steps_version_id_fk
    ON apiome.api_workflow_steps (version_id);
DROP INDEX IF EXISTS apiome.idx_api_workflow_steps_version_id;

-- api_workflows_version_id_fkey (replaces idx_api_workflows_version_id)
CREATE INDEX IF NOT EXISTS idx_api_workflows_version_id_fk
    ON apiome.api_workflows (version_id);
DROP INDEX IF EXISTS apiome.idx_api_workflows_version_id;

-- classes_version_id_fkey (replaces idx_classes_version_id)
CREATE INDEX IF NOT EXISTS idx_classes_version_id_fk
    ON apiome.classes (version_id);
DROP INDEX IF EXISTS apiome.idx_classes_version_id;

-- domains_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_domains_version_id_fk
    ON apiome.domains (version_id);

-- version_component_pins_version_id_fkey (replaces idx_version_component_pins_version)
CREATE INDEX IF NOT EXISTS idx_version_component_pins_version_id_fk
    ON apiome.version_component_pins (version_id);
DROP INDEX IF EXISTS apiome.idx_version_component_pins_version;

-- version_preservation_claims_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_version_preservation_claims_version_id_fk
    ON apiome.version_preservation_claims (version_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.projects (2)
-- ---------------------------------------------------------------------------------------------

-- api_workflows_project_id_fkey (replaces idx_api_workflows_project_id)
CREATE INDEX IF NOT EXISTS idx_api_workflows_project_id_fk
    ON apiome.api_workflows (project_id)
    WHERE project_id IS NOT NULL;
DROP INDEX IF EXISTS apiome.idx_api_workflows_project_id;

-- sunset_still_used_alert_project_id_fkey
CREATE INDEX IF NOT EXISTS idx_sunset_still_used_alert_project_id_fk
    ON apiome.sunset_still_used_alert (project_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.tenants (69)
-- ---------------------------------------------------------------------------------------------

-- agent_invocation_samples_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_agent_invocation_samples_tenant_id_fk
    ON apiome.agent_invocation_samples (tenant_id);

-- api_agent_descriptors_tenant_id_fkey (replaces idx_api_agent_descriptors_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_agent_descriptors_tenant_id_fk
    ON apiome.api_agent_descriptors (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_agent_descriptors_tenant_id;

-- api_agent_skills_tenant_id_fkey (replaces idx_api_agent_skills_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_tenant_id_fk
    ON apiome.api_agent_skills (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_agent_skills_tenant_id;

-- api_artifacts_tenant_id_fkey (replaces idx_api_artifacts_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_artifacts_tenant_id_fk
    ON apiome.api_artifacts (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_artifacts_tenant_id;

-- api_channels_tenant_id_fkey (replaces idx_api_channels_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_channels_tenant_id_fk
    ON apiome.api_channels (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_channels_tenant_id;

-- api_check_suite_policy_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_check_suite_policy_tenant_id_fk
    ON apiome.api_check_suite_policy (tenant_id);

-- api_fields_tenant_id_fkey (replaces idx_api_fields_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_fields_tenant_id_fk
    ON apiome.api_fields (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_fields_tenant_id;

-- api_messages_tenant_id_fkey (replaces idx_api_messages_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_messages_tenant_id_fk
    ON apiome.api_messages (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_messages_tenant_id;

-- api_operations_tenant_id_fkey (replaces idx_api_operations_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_operations_tenant_id_fk
    ON apiome.api_operations (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_operations_tenant_id;

-- api_products_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_products_tenant_id_fk
    ON apiome.api_products (tenant_id);

-- api_services_tenant_id_fkey (replaces idx_api_services_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_services_tenant_id_fk
    ON apiome.api_services (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_services_tenant_id;

-- api_types_tenant_id_fkey (replaces idx_api_types_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_types_tenant_id_fk
    ON apiome.api_types (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_types_tenant_id;

-- api_workflow_steps_tenant_id_fkey (replaces idx_api_workflow_steps_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_workflow_steps_tenant_id_fk
    ON apiome.api_workflow_steps (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_workflow_steps_tenant_id;

-- api_workflows_tenant_id_fkey (replaces idx_api_workflows_tenant_id)
CREATE INDEX IF NOT EXISTS idx_api_workflows_tenant_id_fk
    ON apiome.api_workflows (tenant_id);
DROP INDEX IF EXISTS apiome.idx_api_workflows_tenant_id;

-- auth_one_time_codes_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_auth_one_time_codes_tenant_id_fk
    ON apiome.auth_one_time_codes (tenant_id)
    WHERE tenant_id IS NOT NULL;

-- catalog_agent_consumers_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_agent_consumers_tenant_id_fk
    ON apiome.catalog_agent_consumers (tenant_id);

-- catalog_agent_keys_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_agent_keys_tenant_id_fk
    ON apiome.catalog_agent_keys (tenant_id);

-- catalog_components_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_components_tenant_id_fk
    ON apiome.catalog_components (tenant_id);

-- catalog_connector_notification_throttle_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_connector_notification_throttle_tenant_id_fk
    ON apiome.catalog_connector_notification_throttle (tenant_id);

-- catalog_connectors_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_connectors_tenant_id_fk
    ON apiome.catalog_connectors (tenant_id);

-- catalog_drift_events_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_drift_events_tenant_id_fk
    ON apiome.catalog_drift_events (tenant_id);

-- catalog_gateway_configs_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_gateway_configs_tenant_id_fk
    ON apiome.catalog_gateway_configs (tenant_id);

-- cli_login_requests_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_cli_login_requests_tenant_id_fk
    ON apiome.cli_login_requests (tenant_id)
    WHERE tenant_id IS NOT NULL;

-- component_revision_approvals_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_component_revision_approvals_tenant_id_fk
    ON apiome.component_revision_approvals (tenant_id);

-- component_revision_deprecations_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_component_revision_deprecations_tenant_id_fk
    ON apiome.component_revision_deprecations (tenant_id);

-- consumer_contract_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_consumer_contract_tenant_id_fk
    ON apiome.consumer_contract (tenant_id);

-- deploy_gate_policy_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_deploy_gate_policy_tenant_id_fk
    ON apiome.deploy_gate_policy (tenant_id);

-- draft_binding_sync_candidates_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_draft_binding_sync_candidates_tenant_id_fk
    ON apiome.draft_binding_sync_candidates (tenant_id);

-- draft_sync_conflicts_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_draft_sync_conflicts_tenant_id_fk
    ON apiome.draft_sync_conflicts (tenant_id);

-- draft_sync_plans_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_draft_sync_plans_tenant_id_fk
    ON apiome.draft_sync_plans (tenant_id);

-- element_locks_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_element_locks_tenant_id_fk
    ON apiome.element_locks (tenant_id);

-- entity_owners_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_entity_owners_tenant_id_fk
    ON apiome.entity_owners (tenant_id);

-- mcp_api_keys_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_tenant_id_fk
    ON apiome.mcp_api_keys (tenant_id);

-- mcp_discovery_jobs_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_discovery_jobs_tenant_id_fk
    ON apiome.mcp_discovery_jobs (tenant_id);

-- mcp_probe_targets_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_probe_targets_tenant_id_fk
    ON apiome.mcp_probe_targets (tenant_id);

-- mcp_trust_baselines_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_trust_baselines_tenant_id_fk
    ON apiome.mcp_trust_baselines (tenant_id);

-- merge_requests_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_merge_requests_tenant_id_fk
    ON apiome.merge_requests (tenant_id);

-- operational_components_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_operational_components_tenant_id_fk
    ON apiome.operational_components (tenant_id);

-- owner_notification_throttle_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_owner_notification_throttle_tenant_id_fk
    ON apiome.owner_notification_throttle (tenant_id);

-- portal_magic_links_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_portal_magic_links_tenant_id_fk
    ON apiome.portal_magic_links (tenant_id);

-- project_federation_merges_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_project_federation_merges_tenant_id_fk
    ON apiome.project_federation_merges (tenant_id);

-- project_presence_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_project_presence_tenant_id_fk
    ON apiome.project_presence (tenant_id);

-- project_repository_sources_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_project_repository_sources_tenant_id_fk
    ON apiome.project_repository_sources (tenant_id);

-- provider_check_runs_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_provider_check_runs_tenant_id_fk
    ON apiome.provider_check_runs (tenant_id);

-- push_webhook_subscriptions_tenant_id_fkey (replaces idx_push_webhook_subscriptions_tenant_id)
CREATE INDEX IF NOT EXISTS idx_push_webhook_subscriptions_tenant_id_fk
    ON apiome.push_webhook_subscriptions (tenant_id);
DROP INDEX IF EXISTS apiome.idx_push_webhook_subscriptions_tenant_id;

-- review_suggestions_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_review_suggestions_tenant_id_fk
    ON apiome.review_suggestions (tenant_id);

-- schema_subjects_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_schema_subjects_tenant_id_fk
    ON apiome.schema_subjects (tenant_id);

-- schema_test_suite_payloads_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_schema_test_suite_payloads_tenant_id_fk
    ON apiome.schema_test_suite_payloads (tenant_id);

-- sdk_generation_settings_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_sdk_generation_settings_tenant_id_fk
    ON apiome.sdk_generation_settings (tenant_id);

-- sdk_regen_jobs_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_tenant_id_fk
    ON apiome.sdk_regen_jobs (tenant_id);

-- sdk_registry_credentials_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_sdk_registry_credentials_tenant_id_fk
    ON apiome.sdk_registry_credentials (tenant_id);

-- slate_security_approvals_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_slate_security_approvals_tenant_id_fk
    ON apiome.slate_security_approvals (tenant_id);

-- slate_security_exceptions_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_slate_security_exceptions_tenant_id_fk
    ON apiome.slate_security_exceptions (tenant_id);

-- slate_security_rule_revisions_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_slate_security_rule_revisions_tenant_id_fk
    ON apiome.slate_security_rule_revisions (tenant_id);

-- teams_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_teams_tenant_id_fk
    ON apiome.teams (tenant_id);

-- tenant_repositories_tenant_id_fkey (replaces idx_tenant_repositories_tenant_id)
CREATE INDEX IF NOT EXISTS idx_tenant_repositories_tenant_id_fk
    ON apiome.tenant_repositories (tenant_id);
DROP INDEX IF EXISTS apiome.idx_tenant_repositories_tenant_id;

-- tenant_repository_file_scan_jobs_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_tenant_repository_file_scan_jobs_tenant_id_fk
    ON apiome.tenant_repository_file_scan_jobs (tenant_id);

-- tenant_repository_refresh_jobs_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_tenant_repository_refresh_jobs_tenant_id_fk
    ON apiome.tenant_repository_refresh_jobs (tenant_id);

-- usage_consumer_binding_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_usage_consumer_binding_tenant_id_fk
    ON apiome.usage_consumer_binding (tenant_id);

-- usage_sample_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_usage_sample_tenant_id_fk
    ON apiome.usage_sample (tenant_id);

-- verification_run_artifact_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_verification_run_artifact_tenant_id_fk
    ON apiome.verification_run_artifact (tenant_id);

-- verification_run_assertion_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_verification_run_assertion_tenant_id_fk
    ON apiome.verification_run_assertion (tenant_id);

-- verification_run_operation_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_verification_run_operation_tenant_id_fk
    ON apiome.verification_run_operation (tenant_id);

-- verification_schedule_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_verification_schedule_tenant_id_fk
    ON apiome.verification_schedule (tenant_id);

-- verification_target_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_verification_target_tenant_id_fk
    ON apiome.verification_target (tenant_id);

-- version_component_pins_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_version_component_pins_tenant_id_fk
    ON apiome.version_component_pins (tenant_id);

-- version_overlay_renders_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_version_overlay_renders_tenant_id_fk
    ON apiome.version_overlay_renders (tenant_id);

-- version_preservation_claims_tenant_id_fkey
CREATE INDEX IF NOT EXISTS idx_version_preservation_claims_tenant_id_fk
    ON apiome.version_preservation_claims (tenant_id);

-- workspace_custom_actions_tenant_id_fkey (replaces idx_workspace_custom_actions_tenant)
CREATE INDEX IF NOT EXISTS idx_workspace_custom_actions_tenant_id_fk
    ON apiome.workspace_custom_actions (tenant_id);
DROP INDEX IF EXISTS apiome.idx_workspace_custom_actions_tenant;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.mcp_endpoint_versions (5)
-- ---------------------------------------------------------------------------------------------

-- mcp_endpoint_views_last_seen_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_views_last_seen_version_id_fk
    ON apiome.mcp_endpoint_views (last_seen_version_id)
    WHERE last_seen_version_id IS NOT NULL;

-- mcp_endpoints_current_version_fk (replaces idx_mcp_endpoints_current_version)
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_current_version_id_fk
    ON apiome.mcp_endpoints (current_version_id)
    WHERE current_version_id IS NOT NULL;
DROP INDEX IF EXISTS apiome.idx_mcp_endpoints_current_version;

-- mcp_probe_runs_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_probe_runs_version_id_fk
    ON apiome.mcp_probe_runs (version_id)
    WHERE version_id IS NOT NULL;

-- mcp_test_invocations_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_test_invocations_version_id_fk
    ON apiome.mcp_test_invocations (version_id)
    WHERE version_id IS NOT NULL;

-- mcp_trust_baselines_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_trust_baselines_version_id_fk
    ON apiome.mcp_trust_baselines (version_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.verification_run (6)
-- ---------------------------------------------------------------------------------------------

-- provider_verification_report_run_fk
CREATE INDEX IF NOT EXISTS idx_provider_verification_report_run_id_tenant_id_fk
    ON apiome.provider_verification_report (run_id, tenant_id);

-- security_probe_reports_evidence_run_fk
CREATE INDEX IF NOT EXISTS idx_security_probe_reports_evidence_run_id_tenant_id_fk
    ON apiome.security_probe_reports (evidence_run_id, tenant_id)
    WHERE evidence_run_id IS NOT NULL;

-- verification_run_artifact_run_fk
CREATE INDEX IF NOT EXISTS idx_verification_run_artifact_run_id_tenant_id_fk
    ON apiome.verification_run_artifact (run_id, tenant_id);

-- verification_run_assertion_run_fk
CREATE INDEX IF NOT EXISTS idx_verification_run_assertion_run_id_tenant_id_fk
    ON apiome.verification_run_assertion (run_id, tenant_id);

-- verification_run_mock_run_fk
CREATE INDEX IF NOT EXISTS idx_verification_run_mock_run_id_tenant_id_fk
    ON apiome.verification_run_mock (run_id, tenant_id);

-- verification_run_operation_run_fk
CREATE INDEX IF NOT EXISTS idx_verification_run_operation_run_id_tenant_id_fk
    ON apiome.verification_run_operation (run_id, tenant_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.agent_toolsets (1)
-- ---------------------------------------------------------------------------------------------

-- api_keys_agent_toolset_fk
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_id_toolset_id_fk
    ON apiome.api_keys (tenant_id, toolset_id)
    WHERE toolset_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_agent_descriptors (1)
-- ---------------------------------------------------------------------------------------------

-- api_agent_skills_agent_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_agent_id_fk
    ON apiome.api_agent_skills (agent_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_artifacts (6)
-- ---------------------------------------------------------------------------------------------

-- api_agent_descriptors_artifact_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_agent_descriptors_artifact_id_fk
    ON apiome.api_agent_descriptors (artifact_id);

-- api_agent_skills_artifact_id_fkey (replaces idx_api_agent_skills_artifact_id)
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_artifact_id_fk
    ON apiome.api_agent_skills (artifact_id);
DROP INDEX IF EXISTS apiome.idx_api_agent_skills_artifact_id;

-- api_channels_artifact_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_channels_artifact_id_fk
    ON apiome.api_channels (artifact_id);

-- api_services_artifact_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_services_artifact_id_fk
    ON apiome.api_services (artifact_id);

-- api_types_artifact_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_types_artifact_id_fk
    ON apiome.api_types (artifact_id);

-- api_workflows_artifact_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_workflows_artifact_id_fk
    ON apiome.api_workflows (artifact_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_identity_groups (1)
-- ---------------------------------------------------------------------------------------------

-- api_identity_members_group_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_identity_members_group_id_fk
    ON apiome.api_identity_members (group_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_operations (1)
-- ---------------------------------------------------------------------------------------------

-- api_messages_operation_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_messages_operation_id_fk
    ON apiome.api_messages (operation_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_plans (1)
-- ---------------------------------------------------------------------------------------------

-- api_plans_successor_plan_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_plans_successor_plan_id_fk
    ON apiome.api_plans (successor_plan_id)
    WHERE successor_plan_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_products (2)
-- ---------------------------------------------------------------------------------------------

-- api_plans_product_fk (replaces idx_api_plans_tenant_product)
CREATE INDEX IF NOT EXISTS idx_api_plans_tenant_id_product_id_fk
    ON apiome.api_plans (tenant_id, product_id);
DROP INDEX IF EXISTS apiome.idx_api_plans_tenant_product;

-- api_product_members_product_fk
CREATE INDEX IF NOT EXISTS idx_api_product_members_product_id_tenant_id_fk
    ON apiome.api_product_members (product_id, tenant_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_services (1)
-- ---------------------------------------------------------------------------------------------

-- api_operations_service_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_operations_service_id_fk
    ON apiome.api_operations (service_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_types (1)
-- ---------------------------------------------------------------------------------------------

-- api_fields_type_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_fields_type_id_fk
    ON apiome.api_fields (type_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.api_workflows (1)
-- ---------------------------------------------------------------------------------------------

-- api_workflow_steps_workflow_id_fkey
CREATE INDEX IF NOT EXISTS idx_api_workflow_steps_workflow_id_fk
    ON apiome.api_workflow_steps (workflow_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.catalog_connectors (1)
-- ---------------------------------------------------------------------------------------------

-- catalog_gateway_configs_connector_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_gateway_configs_connector_id_fk
    ON apiome.catalog_gateway_configs (connector_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.catalog_models (1)
-- ---------------------------------------------------------------------------------------------

-- catalog_agents_model_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_agents_model_id_fk
    ON apiome.catalog_agents (model_id)
    WHERE model_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.change_report_template_versions (2)
-- ---------------------------------------------------------------------------------------------

-- projects_change_report_template_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_projects_change_report_template_version_id_fk
    ON apiome.projects (change_report_template_version_id)
    WHERE change_report_template_version_id IS NOT NULL;

-- tenants_change_report_template_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_tenants_change_report_template_version_id_fk
    ON apiome.tenants (change_report_template_version_id)
    WHERE change_report_template_version_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.classes (2)
-- ---------------------------------------------------------------------------------------------

-- path_operation_schema_class_id_fkey
CREATE INDEX IF NOT EXISTS idx_path_operation_schema_class_id_fk
    ON apiome.path_operation_schema (class_id)
    WHERE class_id IS NOT NULL;

-- path_parameter_schema_class_id_fkey
CREATE INDEX IF NOT EXISTS idx_path_parameter_schema_class_id_fk
    ON apiome.path_parameter_schema (class_id)
    WHERE class_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.consumer (2)
-- ---------------------------------------------------------------------------------------------

-- consumer_contract_consumer_fk
CREATE INDEX IF NOT EXISTS idx_consumer_contract_consumer_id_project_id_fk
    ON apiome.consumer_contract (consumer_id, project_id);

-- usage_consumer_binding_consumer_fk
CREATE INDEX IF NOT EXISTS idx_usage_consumer_binding_consumer_id_project_id_fk
    ON apiome.usage_consumer_binding (consumer_id, project_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.domains (1)
-- ---------------------------------------------------------------------------------------------

-- classes_domain_id_fkey
CREATE INDEX IF NOT EXISTS idx_classes_domain_id_fk
    ON apiome.classes (domain_id)
    WHERE domain_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.export_delivery_profiles (4)
-- ---------------------------------------------------------------------------------------------

-- export_git_delivery_runs_delivery_profile_id_fkey
CREATE INDEX IF NOT EXISTS idx_export_git_delivery_runs_delivery_profile_id_fk
    ON apiome.export_git_delivery_runs (delivery_profile_id)
    WHERE delivery_profile_id IS NOT NULL;

-- export_object_storage_delivery_runs_delivery_profile_id_fkey
CREATE INDEX IF NOT EXISTS idx_export_object_storage_delivery_runs_delivery_profile_id_fk
    ON apiome.export_object_storage_delivery_runs (delivery_profile_id)
    WHERE delivery_profile_id IS NOT NULL;

-- export_presets_delivery_profile_id_fkey
CREATE INDEX IF NOT EXISTS idx_export_presets_delivery_profile_id_fk
    ON apiome.export_presets (delivery_profile_id)
    WHERE delivery_profile_id IS NOT NULL;

-- export_webhook_delivery_runs_delivery_profile_id_fkey
CREATE INDEX IF NOT EXISTS idx_export_webhook_delivery_runs_delivery_profile_id_fk
    ON apiome.export_webhook_delivery_runs (delivery_profile_id)
    WHERE delivery_profile_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.export_presets (2)
-- ---------------------------------------------------------------------------------------------

-- export_auto_runs_preset_id_fkey
CREATE INDEX IF NOT EXISTS idx_export_auto_runs_preset_id_fk
    ON apiome.export_auto_runs (preset_id)
    WHERE preset_id IS NOT NULL;

-- export_auto_subscriptions_preset_id_fkey
CREATE INDEX IF NOT EXISTS idx_export_auto_subscriptions_preset_id_fk
    ON apiome.export_auto_subscriptions (preset_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.export_storage_credentials (1)
-- ---------------------------------------------------------------------------------------------

-- export_object_storage_delivery_runs_credential_id_fkey
CREATE INDEX IF NOT EXISTS idx_export_object_storage_delivery_runs_credential_id_fk
    ON apiome.export_object_storage_delivery_runs (credential_id)
    WHERE credential_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.external_auth_providers (1)
-- ---------------------------------------------------------------------------------------------

-- tenant_repositories_linked_account_id_fkey
CREATE INDEX IF NOT EXISTS idx_tenant_repositories_linked_account_id_fk
    ON apiome.tenant_repositories (linked_account_id)
    WHERE linked_account_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.import_export_quality_policies (1)
-- ---------------------------------------------------------------------------------------------

-- import_export_quality_waivers_policy_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_import_export_quality_waivers_policy_version_id_fk
    ON apiome.import_export_quality_waivers (policy_version_id)
    WHERE policy_version_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.mcp_endpoint_credentials (1)
-- ---------------------------------------------------------------------------------------------

-- mcp_probe_targets_test_credential_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_probe_targets_test_credential_id_fk
    ON apiome.mcp_probe_targets (test_credential_id)
    WHERE test_credential_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.mcp_endpoints (4)
-- ---------------------------------------------------------------------------------------------

-- mcp_collection_members_endpoint_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_collection_members_endpoint_id_fk
    ON apiome.mcp_collection_members (endpoint_id);

-- mcp_endpoint_notes_endpoint_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_notes_endpoint_id_fk
    ON apiome.mcp_endpoint_notes (endpoint_id);

-- mcp_endpoint_sources_endpoint_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_sources_endpoint_id_fk
    ON apiome.mcp_endpoint_sources (endpoint_id);

-- mcp_probe_targets_endpoint_id_fkey
CREATE INDEX IF NOT EXISTS idx_mcp_probe_targets_endpoint_id_fk
    ON apiome.mcp_probe_targets (endpoint_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.operational_component_revisions (3)
-- ---------------------------------------------------------------------------------------------

-- component_revision_deprecations_replacement_revision_id_fkey
CREATE INDEX IF NOT EXISTS idx_component_revision_deprecations_replacement_revision_id_fk
    ON apiome.component_revision_deprecations (replacement_revision_id)
    WHERE replacement_revision_id IS NOT NULL;

-- component_revision_deprecations_revision_id_fkey
CREATE INDEX IF NOT EXISTS idx_component_revision_deprecations_revision_id_fk
    ON apiome.component_revision_deprecations (revision_id);

-- version_component_pins_component_revision_id_fkey (replaces idx_version_component_pins_revision)
CREATE INDEX IF NOT EXISTS idx_version_component_pins_component_revision_id_fk
    ON apiome.version_component_pins (component_revision_id);
DROP INDEX IF EXISTS apiome.idx_version_component_pins_revision;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.operational_components (2)
-- ---------------------------------------------------------------------------------------------

-- component_revision_approvals_component_id_fkey
CREATE INDEX IF NOT EXISTS idx_component_revision_approvals_component_id_fk
    ON apiome.component_revision_approvals (component_id);

-- component_revision_deprecations_component_id_fkey
CREATE INDEX IF NOT EXISTS idx_component_revision_deprecations_component_id_fk
    ON apiome.component_revision_deprecations (component_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.primitives (2)
-- ---------------------------------------------------------------------------------------------

-- operational_component_revisions_schema_primitive_id_fkey
CREATE INDEX IF NOT EXISTS idx_operational_component_revisions_schema_primitive_id_fk
    ON apiome.operational_component_revisions (schema_primitive_id)
    WHERE schema_primitive_id IS NOT NULL;

-- primitives_replacement_id_fkey
CREATE INDEX IF NOT EXISTS idx_primitives_replacement_id_fk
    ON apiome.primitives (replacement_id)
    WHERE replacement_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.provider_verification_report (2)
-- ---------------------------------------------------------------------------------------------

-- verification_schedule_last_report_id_fkey
CREATE INDEX IF NOT EXISTS idx_verification_schedule_last_report_id_fk
    ON apiome.verification_schedule (last_report_id)
    WHERE last_report_id IS NOT NULL;

-- verification_schedule_run_report_id_fkey
CREATE INDEX IF NOT EXISTS idx_verification_schedule_run_report_id_fk
    ON apiome.verification_schedule_run (report_id)
    WHERE report_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.push_webhook_subscriptions (1)
-- ---------------------------------------------------------------------------------------------

-- push_webhook_delivery_events_subscription_id_fkey
CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_events_subscription_id_fk
    ON apiome.push_webhook_delivery_events (subscription_id)
    WHERE subscription_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.repository_webhook_subscription (1)
-- ---------------------------------------------------------------------------------------------

-- repository_webhook_event_subscription_id_fkey
CREATE INDEX IF NOT EXISTS idx_repository_webhook_event_subscription_id_fk
    ON apiome.repository_webhook_event (subscription_id)
    WHERE subscription_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.schema_test_suite_payloads (1)
-- ---------------------------------------------------------------------------------------------

-- schema_test_suite_run_results_payload_id_fkey
CREATE INDEX IF NOT EXISTS idx_schema_test_suite_run_results_payload_id_fk
    ON apiome.schema_test_suite_run_results (payload_id)
    WHERE payload_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.schema_test_suite_runs (1)
-- ---------------------------------------------------------------------------------------------

-- schema_test_suite_runs_baseline_run_id_fkey
CREATE INDEX IF NOT EXISTS idx_schema_test_suite_runs_baseline_run_id_fk
    ON apiome.schema_test_suite_runs (baseline_run_id)
    WHERE baseline_run_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.sdk_regen_subscriptions (1)
-- ---------------------------------------------------------------------------------------------

-- sdk_regen_jobs_subscription_id_fkey
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_subscription_id_fk
    ON apiome.sdk_regen_jobs (subscription_id)
    WHERE subscription_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.slate_environments (1)
-- ---------------------------------------------------------------------------------------------

-- slate_personalization_variants_environment_id_fkey
CREATE INDEX IF NOT EXISTS idx_slate_personalization_variants_environment_id_fk
    ON apiome.slate_personalization_variants (environment_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.source_change_audit (1)
-- ---------------------------------------------------------------------------------------------

-- version_source_edits_audit_id_fkey
CREATE INDEX IF NOT EXISTS idx_version_source_edits_audit_id_fk
    ON apiome.version_source_edits (audit_id)
    WHERE audit_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.style_guide_policy_versions (2)
-- ---------------------------------------------------------------------------------------------

-- lint_finding_decision_events_policy_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_lint_finding_decision_events_policy_version_id_fk
    ON apiome.lint_finding_decision_events (policy_version_id)
    WHERE policy_version_id IS NOT NULL;

-- lint_finding_decisions_policy_version_id_fkey
CREATE INDEX IF NOT EXISTS idx_lint_finding_decisions_policy_version_id_fk
    ON apiome.lint_finding_decisions (policy_version_id)
    WHERE policy_version_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.teams (2)
-- ---------------------------------------------------------------------------------------------

-- push_webhook_delivery_events_team_id_fkey
CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_events_team_id_fk
    ON apiome.push_webhook_delivery_events (team_id)
    WHERE team_id IS NOT NULL;

-- tenants_unowned_findings_team_id_fkey
CREATE INDEX IF NOT EXISTS idx_tenants_unowned_findings_team_id_fk
    ON apiome.tenants (unowned_findings_team_id)
    WHERE unowned_findings_team_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.tenant_repositories (4)
-- ---------------------------------------------------------------------------------------------

-- catalog_import_runs_repository_id_fkey
CREATE INDEX IF NOT EXISTS idx_catalog_import_runs_repository_id_fk
    ON apiome.catalog_import_runs (repository_id)
    WHERE repository_id IS NOT NULL;

-- draft_repository_bindings_repository_id_fkey
CREATE INDEX IF NOT EXISTS idx_draft_repository_bindings_repository_id_fk
    ON apiome.draft_repository_bindings (repository_id)
    WHERE repository_id IS NOT NULL;

-- export_git_delivery_runs_repository_id_fkey
CREATE INDEX IF NOT EXISTS idx_export_git_delivery_runs_repository_id_fk
    ON apiome.export_git_delivery_runs (repository_id)
    WHERE repository_id IS NOT NULL;

-- sdk_git_delivery_runs_repository_id_fkey
CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_runs_repository_id_fk
    ON apiome.sdk_git_delivery_runs (repository_id)
    WHERE repository_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.verification_run_operation (2)
-- ---------------------------------------------------------------------------------------------

-- verification_run_artifact_operation_fk
CREATE INDEX IF NOT EXISTS idx_verification_run_artifact_operation_id_tenant_id_fk
    ON apiome.verification_run_artifact (operation_id, tenant_id)
    WHERE operation_id IS NOT NULL;

-- verification_run_assertion_operation_fk
CREATE INDEX IF NOT EXISTS idx_verification_run_assertion_operation_id_tenant_id_fk
    ON apiome.verification_run_assertion (operation_id, tenant_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.verification_schedule (1)
-- ---------------------------------------------------------------------------------------------

-- verification_schedule_run_schedule_fk
CREATE INDEX IF NOT EXISTS idx_verification_schedule_run_schedule_id_tenant_id_fk
    ON apiome.verification_schedule_run (schedule_id, tenant_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.verification_target (2)
-- ---------------------------------------------------------------------------------------------

-- provider_verification_report_target_id_fkey
CREATE INDEX IF NOT EXISTS idx_provider_verification_report_target_id_fk
    ON apiome.provider_verification_report (target_id)
    WHERE target_id IS NOT NULL;

-- verification_schedule_target_id_fkey
CREATE INDEX IF NOT EXISTS idx_verification_schedule_target_id_fk
    ON apiome.verification_schedule (target_id);

-- ---------------------------------------------------------------------------------------------
-- Referencing apiome.version_branches (1)
-- ---------------------------------------------------------------------------------------------

-- merge_requests_source_branch_id_fkey
CREATE INDEX IF NOT EXISTS idx_merge_requests_source_branch_id_fk
    ON apiome.merge_requests (source_branch_id)
    WHERE source_branch_id IS NOT NULL;
