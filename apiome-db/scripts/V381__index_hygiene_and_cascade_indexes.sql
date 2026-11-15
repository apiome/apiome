-- Index hygiene and cascade-delete indexes.
--
-- A catalog review of the migrated schema (1,479 indexes on 381 tables) found three things worth
-- fixing in one pass:
--
--   1. 84 indexes that can never be the planner's best choice, because another index on the same
--      table already answers every query they could: 21 share another index's exact definition
--      (usually a hand-written index next to the UNIQUE constraint's own), and 63 are a leading
--      prefix of a wider b-tree. They cost a write on every INSERT / non-HOT UPDATE and buy nothing.
--   2. idx_api_keys_last_used_at. Nothing sorts or filters on last_used_at, but API-key auth stamps
--      the column on use, and an indexed column rules out a HOT update — so each stamp rewrote an
--      entry in every index on api_keys.
--   3. 96 foreign keys with no index on the referencing column, on the tables a project or
--      version delete reaches: the 44 that cascade straight from projects / versions, and 52 more
--      on the tables those cascades reach in turn (cascade, SET NULL and RESTRICT alike — each one
--      is a lookup by the referencing column, and without an index a sequential scan of the
--      table). Deleting one project scanned every one of those tables in full.
--
-- It also adds two indexes for queries that had nothing to use (see each one below).
--
-- Only non-unique indexes are dropped, so no constraint and no ON CONFLICT target changes.
--
-- Large databases: a migration runs in one transaction, so these are plain CREATE INDEX statements
-- and each blocks writes to its table while it builds. Every statement is IF [NOT] EXISTS on
-- purpose — to avoid the write block, run the CREATE INDEX statements below by hand first as
-- CREATE INDEX CONCURRENTLY (same names), and this migration then only drops.
--
-- Rollback notes: recreate a dropped index from the migration that introduced it; DROP INDEX the
-- ones created here.

-- ---------------------------------------------------------------------------------------------
-- 1. Redundant indexes (the comment names the index that covers each one)
-- ---------------------------------------------------------------------------------------------

DROP INDEX IF EXISTS apiome.idx_api_identity_members_project;  -- same definition as api_identity_members_project_unique
DROP INDEX IF EXISTS apiome.idx_canvas_layout_revisions_layout_id;  -- leading prefix of canvas_layout_revisions_unique_rev
DROP INDEX IF EXISTS apiome.idx_catalog_edges_from;  -- leading prefix of catalog_edges_identity_key
DROP INDEX IF EXISTS apiome.idx_class_properties_class_id;  -- leading prefix of class_properties_parent_name_unique
DROP INDEX IF EXISTS apiome.idx_class_schema_version_id;  -- leading prefix of class_schema_version_class_unique
DROP INDEX IF EXISTS apiome.idx_class_tags_class_id;  -- leading prefix of class_tags_class_tag_unique
DROP INDEX IF EXISTS apiome.idx_class_template_deps_template_id;  -- leading prefix of class_template_deps_unique
DROP INDEX IF EXISTS apiome.idx_component_revision_approvals_revision;  -- leading prefix of uq_component_revision_approval
DROP INDEX IF EXISTS apiome.idx_export_field_identities_project_target;  -- leading prefix of uq_export_field_identities_scope
DROP INDEX IF EXISTS apiome.idx_export_schema_baselines_project;  -- leading prefix of uq_export_schema_baselines_scope
DROP INDEX IF EXISTS apiome.idx_external_auth_providers_provider;  -- leading prefix of external_auth_providers_provider_provider_user_id_key
DROP INDEX IF EXISTS apiome.idx_external_auth_providers_provider_user_id;  -- same definition as external_auth_providers_provider_provider_user_id_key
DROP INDEX IF EXISTS apiome.idx_external_auth_providers_user_id;  -- leading prefix of external_auth_providers_user_id_provider_key
DROP INDEX IF EXISTS apiome.idx_ffgm_group_id;  -- leading prefix of feature_flag_group_members_pkey
DROP INDEX IF EXISTS apiome.idx_feature_flag_groups_name;  -- same definition as feature_flag_groups_name_key
DROP INDEX IF EXISTS apiome.idx_feature_flags_name;  -- same definition as feature_flags_name_key
DROP INDEX IF EXISTS apiome.idx_group_classes_group_id;  -- leading prefix of group_classes_unique
DROP INDEX IF EXISTS apiome.idx_groups_version_id;  -- leading prefix of groups_version_name_unique
DROP INDEX IF EXISTS apiome.idx_lff_license_id;  -- leading prefix of license_feature_flags_pkey
DROP INDEX IF EXISTS apiome.mcp_source_sboms_source_idx;  -- leading prefix of mcp_source_sboms_subject_unique
DROP INDEX IF EXISTS apiome.idx_migration_plan_rules_class;  -- leading prefix of migration_plan_rules_plan_class_prop_unique
DROP INDEX IF EXISTS apiome.idx_migration_plan_rules_plan;  -- leading prefix of migration_plan_rules_plan_class_prop_unique
DROP INDEX IF EXISTS apiome.idx_migration_plans_project;  -- leading prefix of migration_plans_version_pair_unique
DROP INDEX IF EXISTS apiome.idx_mock_session_state_session;  -- leading prefix of mock_session_state_pkey
DROP INDEX IF EXISTS apiome.idx_path_operation_version_path_id;  -- leading prefix of path_operation_version_path_id_operation_key
DROP INDEX IF EXISTS apiome.idx_path_operation_description_path_operation_id;  -- same definition as path_operation_description_path_operation_id_key
DROP INDEX IF EXISTS apiome.idx_path_operation_parameter_link_operation;  -- leading prefix of path_operation_parameter_link_path_operation_id_shared_path_key
DROP INDEX IF EXISTS apiome.idx_path_operation_request_body_link_operation;  -- same definition as path_operation_request_body_link_path_operation_id_key
DROP INDEX IF EXISTS apiome.idx_path_operation_response_link_operation;  -- leading prefix of path_operation_response_link_path_operation_id_shared_path__key
DROP INDEX IF EXISTS apiome.idx_path_operation_schema_path_operation_id;  -- leading prefix of path_operation_schema_unique
DROP INDEX IF EXISTS apiome.idx_path_parameter_path_operation_id;  -- leading prefix of path_parameter_path_operation_id_name_in_location_key
DROP INDEX IF EXISTS apiome.idx_path_parameter_schema_path_response_content_id;  -- same definition as path_response_content_id_unique
DROP INDEX IF EXISTS apiome.idx_path_response_path_operation_id;  -- leading prefix of path_response_path_operation_id_status_code_key
DROP INDEX IF EXISTS apiome.idx_path_response_content_path_response_id;  -- leading prefix of path_response_content_path_response_id_media_type_key
DROP INDEX IF EXISTS apiome.idx_platform_administrators_user_id;  -- same definition as platform_administrators_user_id_key
DROP INDEX IF EXISTS apiome.idx_primitives_namespace;  -- leading prefix of idx_primitives_namespace_name_tenant
DROP INDEX IF EXISTS apiome.idx_primitives_tags_gin;  -- same definition as idx_primitives_tags
DROP INDEX IF EXISTS apiome.idx_push_webhook_delivery_attempts_event;  -- same definition as push_webhook_delivery_attempt_delivery_event_id_attempt_num_key
DROP INDEX IF EXISTS apiome.idx_review_reviewers_review_round;  -- leading prefix of review_reviewers_round_user_key
DROP INDEX IF EXISTS apiome.idx_role_permissions_role_id;  -- leading prefix of role_permissions_role_id_resource_action_key
DROP INDEX IF EXISTS apiome.idx_roles_tenant_id;  -- leading prefix of roles_tenant_id_slug_key
DROP INDEX IF EXISTS apiome.idx_shared_path_parameter_version_path;  -- leading prefix of shared_path_parameter_version_path_id_name_in_location_key
DROP INDEX IF EXISTS apiome.idx_shared_path_request_body_version_path;  -- leading prefix of shared_path_request_body_version_path_id_name_key
DROP INDEX IF EXISTS apiome.idx_shared_path_request_body_content_request_body;  -- leading prefix of shared_path_request_body_cont_shared_path_request_body_id_m_key
DROP INDEX IF EXISTS apiome.idx_shared_path_response_version_path_id;  -- leading prefix of shared_path_response_version_path_id_status_code_key
DROP INDEX IF EXISTS apiome.idx_shared_path_response_content_response_id;  -- leading prefix of shared_path_response_content_shared_path_response_id_media__key
DROP INDEX IF EXISTS apiome.idx_signup_email_address;  -- same definition as idx_signup_email_unique
DROP INDEX IF EXISTS apiome.idx_slate_branch_aliases_connection;  -- same definition as slate_branch_aliases_connection_id_branch_key
DROP INDEX IF EXISTS apiome.idx_slate_cache_rules_environment;  -- same definition as slate_cache_rules_environment_id_ordinal_key
DROP INDEX IF EXISTS apiome.idx_slate_function_approvals_subject;  -- leading prefix of slate_function_approvals_subject_id_digest_approver_actor_k_key
DROP INDEX IF EXISTS apiome.idx_slate_function_capabilities_function;  -- leading prefix of slate_function_capabilities_function_id_capability_key
DROP INDEX IF EXISTS apiome.idx_slate_function_egress_rules_function;  -- leading prefix of slate_function_egress_rules_function_id_destination_kind_de_key
DROP INDEX IF EXISTS apiome.idx_slate_function_secret_refs_function;  -- leading prefix of slate_function_secret_refs_function_id_alias_key
DROP INDEX IF EXISTS apiome.idx_slate_functions_environment;  -- same definition as slate_functions_environment_id_ordinal_key
DROP INDEX IF EXISTS apiome.idx_slate_git_connections_tenant;  -- leading prefix of slate_git_connections_tenant_id_provider_repo_full_name_key
DROP INDEX IF EXISTS apiome.idx_slate_insight_budgets_environment;  -- leading prefix of slate_insight_budgets_environment_id_label_key
DROP INDEX IF EXISTS apiome.idx_slate_insight_otlp_exports_environment;  -- leading prefix of slate_insight_otlp_exports_environment_id_label_key
DROP INDEX IF EXISTS apiome.idx_slate_insight_synthetic_checks_environment;  -- leading prefix of slate_insight_synthetic_checks_environment_id_label_key
DROP INDEX IF EXISTS apiome.idx_slate_personalization_variants_function;  -- same definition as slate_personalization_variants_function_id_ordinal_key
DROP INDEX IF EXISTS apiome.idx_slate_preview_changed_pages_build;  -- same definition as slate_preview_changed_pages_preview_build_id_route_key
DROP INDEX IF EXISTS apiome.idx_slate_release_changed_pages_release;  -- same definition as slate_release_changed_pages_release_id_route_key
DROP INDEX IF EXISTS apiome.idx_slate_residency_lanes_environment;  -- leading prefix of slate_residency_lanes_environment_id_stage_key
DROP INDEX IF EXISTS apiome.idx_slate_security_approvals_subject;  -- leading prefix of slate_security_approvals_subject_id_digest_approver_actor_k_key
DROP INDEX IF EXISTS apiome.idx_slate_security_managed_groups_environment;  -- leading prefix of slate_security_managed_groups_environment_id_group_id_key
DROP INDEX IF EXISTS apiome.idx_slate_security_rules_environment;  -- same definition as slate_security_rules_environment_id_ordinal_key
DROP INDEX IF EXISTS apiome.style_guides_tenant_idx;  -- leading prefix of style_guides_tenant_name_uq
DROP INDEX IF EXISTS apiome.idx_tags_project_id;  -- leading prefix of tags_project_name_unique
DROP INDEX IF EXISTS apiome.idx_tenant_administrators_tenant_id;  -- leading prefix of tenant_administrators_tenant_id_user_id_key
DROP INDEX IF EXISTS apiome.idx_tff_tenant_id;  -- leading prefix of tenant_feature_flags_pkey
DROP INDEX IF EXISTS apiome.idx_tenant_mcp_policy_tools_tenant;  -- leading prefix of tenant_mcp_policy_tools_pk
DROP INDEX IF EXISTS apiome.idx_tenant_repo_file_scan_jobs_repository;  -- leading prefix of idx_tenant_repo_file_scan_jobs_repo_recent
DROP INDEX IF EXISTS apiome.idx_tenant_repository_files_repo_branch;  -- leading prefix of uq_tenant_repository_files_repo_branch_path
DROP INDEX IF EXISTS apiome.idx_tenant_repository_scan_cursors_repository;  -- leading prefix of uq_tenant_repository_scan_cursors_repo_branch
DROP INDEX IF EXISTS apiome.idx_tenant_user_roles_tenant_id;  -- leading prefix of tenant_user_roles_tenant_id_user_id_key
DROP INDEX IF EXISTS apiome.idx_tenant_users_tenant_id;  -- leading prefix of tenant_users_tenant_id_user_id_key
DROP INDEX IF EXISTS apiome.idx_uff_user_id;  -- leading prefix of user_feature_flags_pkey
DROP INDEX IF EXISTS apiome.idx_verification_run_assertion_operation;  -- same definition as verification_run_assertion_sequence_key
DROP INDEX IF EXISTS apiome.idx_verification_run_mock_run;  -- same definition as verification_run_mock_run_key
DROP INDEX IF EXISTS apiome.idx_verification_run_operation_run;  -- same definition as verification_run_operation_sequence_key
DROP INDEX IF EXISTS apiome.idx_version_branches_project_id;  -- leading prefix of version_branches_project_name_unique
DROP INDEX IF EXISTS apiome.idx_version_path_version_id;  -- leading prefix of version_path_version_id_pathname_key
DROP INDEX IF EXISTS apiome.idx_version_security_scheme_version_id;  -- leading prefix of version_security_scheme_version_id_scheme_name_key
DROP INDEX IF EXISTS apiome.idx_version_tags_project_id;  -- leading prefix of version_tags_project_name_unique
DROP INDEX IF EXISTS apiome.idx_versions_project_id;  -- leading prefix of versions_project_id_version_id_key

-- ---------------------------------------------------------------------------------------------
-- 2. The index that made every API-key last_used_at stamp a non-HOT update
-- ---------------------------------------------------------------------------------------------

DROP INDEX IF EXISTS apiome.idx_api_keys_last_used_at;

-- ---------------------------------------------------------------------------------------------
-- 3. Query indexes
-- ---------------------------------------------------------------------------------------------

-- "Latest revision of a project" — the per-project lateral in the project and catalog lists
-- (ORDER BY created_at DESC NULLS LAST, id DESC LIMIT 1). With only (project_id) to go on, each
-- lookup fetched and sorted every revision of the project. NULLS LAST matches what those queries
-- ask for; an index in the default order could not serve them.
CREATE INDEX IF NOT EXISTS idx_versions_project_created
    ON apiome.versions (project_id, created_at DESC NULLS LAST, id DESC)
    WHERE deleted_at IS NULL;

-- The export webhook claim also picks up 'delivering' rows whose attempt went stale; the due index
-- only covers pending / retrying, so the claim scanned the whole delivery history every tick.
CREATE INDEX IF NOT EXISTS idx_export_webhook_delivery_runs_stale
    ON apiome.export_webhook_delivery_runs (updated_at)
    WHERE status = 'delivering';

-- ---------------------------------------------------------------------------------------------
-- 4. Referencing-column indexes for ON DELETE CASCADE foreign keys to projects and versions
-- ---------------------------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_api_check_suite_policy_project_id_fk ON apiome.api_check_suite_policy (project_id);
CREATE INDEX IF NOT EXISTS idx_api_check_suite_runs_project_id_fk ON apiome.api_check_suite_runs (project_id);
CREATE INDEX IF NOT EXISTS idx_api_identity_members_project_id_fk ON apiome.api_identity_members (project_id);
CREATE INDEX IF NOT EXISTS idx_catalog_agent_consumers_project_id_fk ON apiome.catalog_agent_consumers (project_id);
CREATE INDEX IF NOT EXISTS idx_change_reports_project_id_fk ON apiome.change_reports (project_id);
CREATE INDEX IF NOT EXISTS idx_conversion_provenance_target_project_id_fk ON apiome.conversion_provenance (target_project_id);
CREATE INDEX IF NOT EXISTS idx_deploy_gate_policy_project_id_fk ON apiome.deploy_gate_policy (project_id);
CREATE INDEX IF NOT EXISTS idx_draft_sync_plans_project_id_fk ON apiome.draft_sync_plans (project_id);
CREATE INDEX IF NOT EXISTS idx_export_auto_runs_project_id_fk ON apiome.export_auto_runs (project_id);
CREATE INDEX IF NOT EXISTS idx_export_auto_subscriptions_project_id_fk ON apiome.export_auto_subscriptions (project_id);
CREATE INDEX IF NOT EXISTS idx_export_field_identities_project_id_fk ON apiome.export_field_identities (project_id);
CREATE INDEX IF NOT EXISTS idx_export_schema_baselines_project_id_fk ON apiome.export_schema_baselines (project_id);
CREATE INDEX IF NOT EXISTS idx_notifications_project_id_fk ON apiome.notifications (project_id);
CREATE INDEX IF NOT EXISTS idx_payload_analysis_project_id_fk ON apiome.payload_analysis (project_id);
CREATE INDEX IF NOT EXISTS idx_provider_check_runs_project_id_fk ON apiome.provider_check_runs (project_id);
CREATE INDEX IF NOT EXISTS idx_review_suggestions_project_id_fk ON apiome.review_suggestions (project_id);
CREATE INDEX IF NOT EXISTS idx_schema_registry_schemas_project_id_fk ON apiome.schema_registry_schemas (project_id);
CREATE INDEX IF NOT EXISTS idx_schema_subject_versions_project_id_fk ON apiome.schema_subject_versions (project_id);
CREATE INDEX IF NOT EXISTS idx_sdk_generation_settings_project_id_fk ON apiome.sdk_generation_settings (project_id);
CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_runs_project_id_fk ON apiome.sdk_git_delivery_runs (project_id);
CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_targets_project_id_fk ON apiome.sdk_git_delivery_targets (project_id);
CREATE INDEX IF NOT EXISTS idx_sdk_publish_runs_project_id_fk ON apiome.sdk_publish_runs (project_id);
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_project_id_fk ON apiome.sdk_regen_jobs (project_id);
CREATE INDEX IF NOT EXISTS idx_sdk_regen_runs_project_id_fk ON apiome.sdk_regen_runs (project_id);
CREATE INDEX IF NOT EXISTS idx_sdk_regen_subscriptions_project_id_fk ON apiome.sdk_regen_subscriptions (project_id);
CREATE INDEX IF NOT EXISTS idx_sdk_registry_credentials_project_id_fk ON apiome.sdk_registry_credentials (project_id);
CREATE INDEX IF NOT EXISTS idx_tenant_repository_imports_project_id_fk ON apiome.tenant_repository_imports (project_id);
CREATE INDEX IF NOT EXISTS idx_usage_daily_project_id_fk ON apiome.usage_daily (project_id);
CREATE INDEX IF NOT EXISTS idx_usage_field_daily_project_id_fk ON apiome.usage_field_daily (project_id);
CREATE INDEX IF NOT EXISTS idx_usage_hourly_project_id_fk ON apiome.usage_hourly (project_id);
CREATE INDEX IF NOT EXISTS idx_usage_sample_project_id_fk ON apiome.usage_sample (project_id);
CREATE INDEX IF NOT EXISTS idx_usage_sdk_beacon_daily_project_id_fk ON apiome.usage_sdk_beacon_daily (project_id);
CREATE INDEX IF NOT EXISTS idx_usage_source_project_id_fk ON apiome.usage_source (project_id);
CREATE INDEX IF NOT EXISTS idx_usage_unattributed_client_daily_project_id_fk ON apiome.usage_unattributed_client_daily (project_id);
CREATE INDEX IF NOT EXISTS idx_usage_unmatched_daily_project_id_fk ON apiome.usage_unmatched_daily (project_id);
CREATE INDEX IF NOT EXISTS idx_verification_policy_evaluations_project_id_fk ON apiome.verification_policy_evaluations (project_id);
CREATE INDEX IF NOT EXISTS idx_notifications_version_id_fk ON apiome.notifications (version_id);
CREATE INDEX IF NOT EXISTS idx_preservation_audit_version_id_fk ON apiome.preservation_audit (version_id);
CREATE INDEX IF NOT EXISTS idx_review_suggestions_version_id_fk ON apiome.review_suggestions (version_id);
CREATE INDEX IF NOT EXISTS idx_schema_registry_schemas_version_record_id_fk ON apiome.schema_registry_schemas (version_record_id);
CREATE INDEX IF NOT EXISTS idx_tenant_repository_imports_version_id_fk ON apiome.tenant_repository_imports (version_id);
CREATE INDEX IF NOT EXISTS idx_usage_sdk_beacon_daily_spec_revision_id_fk ON apiome.usage_sdk_beacon_daily (spec_revision_id);
CREATE INDEX IF NOT EXISTS idx_verification_policy_evaluations_version_record_id_fk ON apiome.verification_policy_evaluations (version_record_id);
CREATE INDEX IF NOT EXISTS idx_version_source_edits_version_id_fk ON apiome.version_source_edits (version_id);

-- ---------------------------------------------------------------------------------------------
-- 5. Referencing-column indexes for the other foreign keys a project or version delete checks:
--    every table the cascades above reach. A nullable column is indexed only where it is set —
--    the referential-integrity lookup is an equality, which a NULL never matches.
-- ---------------------------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_catalog_drift_events_parent_version_id_fk ON apiome.catalog_drift_events (parent_version_id) WHERE parent_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_change_reports_baseline_revision_id_fk ON apiome.change_reports (baseline_revision_id) WHERE baseline_revision_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cli_login_requests_api_key_id_fk ON apiome.cli_login_requests (api_key_id) WHERE api_key_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_consumer_contract_version_id_fk ON apiome.consumer_contract (version_id) WHERE version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversion_provenance_source_project_id_fk ON apiome.conversion_provenance (source_project_id) WHERE source_project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversion_provenance_source_version_id_fk ON apiome.conversion_provenance (source_version_id) WHERE source_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversion_provenance_target_version_id_fk ON apiome.conversion_provenance (target_version_id) WHERE target_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_export_auto_runs_subscription_id_fk ON apiome.export_auto_runs (subscription_id) WHERE subscription_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lint_policy_evaluations_axis_evaluation_id_fk ON apiome.lint_policy_evaluations (axis_evaluation_id) WHERE axis_evaluation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lint_policy_evaluations_evidence_run_id_fk ON apiome.lint_policy_evaluations (evidence_run_id) WHERE evidence_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_merge_requests_merge_session_id_fk ON apiome.merge_requests (merge_session_id) WHERE merge_session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_merge_requests_merged_version_id_fk ON apiome.merge_requests (merged_version_id) WHERE merged_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_merge_requests_review_id_fk ON apiome.merge_requests (review_id) WHERE review_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_merge_requests_target_branch_id_fk ON apiome.merge_requests (target_branch_id) WHERE target_branch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_merge_sessions_merge_base_version_id_fk ON apiome.merge_sessions (merge_base_version_id);
CREATE INDEX IF NOT EXISTS idx_merge_sessions_source_branch_id_fk ON apiome.merge_sessions (source_branch_id) WHERE source_branch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_merge_sessions_source_tip_version_id_fk ON apiome.merge_sessions (source_tip_version_id);
CREATE INDEX IF NOT EXISTS idx_merge_sessions_target_tip_version_id_fk ON apiome.merge_sessions (target_tip_version_id);
CREATE INDEX IF NOT EXISTS idx_mock_capture_exchange_captured_by_fk ON apiome.mock_capture_exchange (captured_by) WHERE captured_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mock_instances_version_id_fk ON apiome.mock_instances (version_id) WHERE version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_project_federation_merges_parent_version_id_fk ON apiome.project_federation_merges (parent_version_id) WHERE parent_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_project_federation_merges_version_id_fk ON apiome.project_federation_merges (version_id) WHERE version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_project_repository_sources_first_version_id_fk ON apiome.project_repository_sources (first_version_id) WHERE first_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_project_repository_sources_last_version_id_fk ON apiome.project_repository_sources (last_version_id) WHERE last_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_quality_rank_observations_project_id_fk ON apiome.quality_rank_observations (project_id) WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_quality_rank_observations_version_record_id_fk ON apiome.quality_rank_observations (version_record_id) WHERE version_record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_runs_target_id_fk ON apiome.sdk_git_delivery_runs (target_id) WHERE target_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sdk_git_delivery_runs_version_id_fk ON apiome.sdk_git_delivery_runs (version_id) WHERE version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sdk_publish_runs_version_id_fk ON apiome.sdk_publish_runs (version_id) WHERE version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_delivery_run_id_fk ON apiome.sdk_regen_jobs (delivery_run_id) WHERE delivery_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_publish_run_id_fk ON apiome.sdk_regen_jobs (publish_run_id) WHERE publish_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sdk_regen_runs_version_id_fk ON apiome.sdk_regen_runs (version_id) WHERE version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_activations_from_release_id_fk ON apiome.slate_activations (from_release_id) WHERE from_release_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_branch_aliases_current_build_id_fk ON apiome.slate_branch_aliases (current_build_id) WHERE current_build_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_cache_traces_release_id_fk ON apiome.slate_cache_traces (release_id) WHERE release_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_cache_traces_winning_rule_id_fk ON apiome.slate_cache_traces (winning_rule_id) WHERE winning_rule_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_cdn_providers_site_id_fk ON apiome.slate_cdn_providers (site_id);
CREATE INDEX IF NOT EXISTS idx_slate_cdn_purge_dispatches_cache_purge_id_fk ON apiome.slate_cdn_purge_dispatches (cache_purge_id) WHERE cache_purge_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_cdn_purge_dispatches_release_id_fk ON apiome.slate_cdn_purge_dispatches (release_id) WHERE release_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_environments_active_release_id_fk ON apiome.slate_environments (active_release_id) WHERE active_release_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_function_versions_environment_id_fk ON apiome.slate_function_versions (environment_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_synthetic_results_environment_id_fk ON apiome.slate_insight_synthetic_results (environment_id);
CREATE INDEX IF NOT EXISTS idx_slate_preview_builds_environment_id_fk ON apiome.slate_preview_builds (environment_id) WHERE environment_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tenant_repository_refresh_jobs_import_spec_id_fk ON apiome.tenant_repository_refresh_jobs (import_spec_id) WHERE import_spec_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_usage_daily_source_id_fk ON apiome.usage_daily (source_id);
CREATE INDEX IF NOT EXISTS idx_usage_field_daily_source_id_fk ON apiome.usage_field_daily (source_id);
CREATE INDEX IF NOT EXISTS idx_usage_hourly_source_id_fk ON apiome.usage_hourly (source_id);
CREATE INDEX IF NOT EXISTS idx_usage_sdk_beacon_daily_source_id_fk ON apiome.usage_sdk_beacon_daily (source_id);
CREATE INDEX IF NOT EXISTS idx_usage_unmatched_daily_source_id_fk ON apiome.usage_unmatched_daily (source_id);
CREATE INDEX IF NOT EXISTS idx_version_changelogs_baseline_revision_id_fk ON apiome.version_changelogs (baseline_revision_id) WHERE baseline_revision_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_version_entity_sources_carried_from_version_id_fk ON apiome.version_entity_sources (carried_from_version_id) WHERE carried_from_version_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_version_protection_audit_project_id_fk ON apiome.version_protection_audit (project_id) WHERE project_id IS NOT NULL;
