# Roadmap Offerings Inventory (Normalized)

This file captures extracted and normalized offering sections from confirmed unmatched `FEATURE_ROADMAP_*.md` sources.

## Normalization Rules

- `source_file`: exact roadmap source path (repo-root relative)
- `raw_sections`: extracted offering-level headings from source
- `normalized_offering_ids`: snake_case canonical IDs for downstream decomposition
- `status_signal`: normalized from markers such as `PLANNED`, `NEW`, `PARTIALLY IMPLEMENTED`, `IN PROGRESS`, `IMPLEMENTED`

Status normalization used:
- `planned`
- `new`
- `partially_implemented`
- `in_progress`
- `implemented`
- `unspecified` (no explicit status marker in heading)

## Coverage (Confirmed Unmatched Sources)

- `FEATURE_ROADMAP_AI.md`
- `FEATURE_ROADMAP_ANALYTICS.md`
- `FEATURE_ROADMAP_API_KEYS.md`
- `FEATURE_ROADMAP_BROWSER.md`
- `FEATURE_ROADMAP_CODE_GENERATION.md`
- `FEATURE_ROADMAP_DASHBOARD.md`
- `FEATURE_ROADMAP_DATABASE_DATA_STORAGE.md`
- `FEATURE_ROADMAP_DATA_TRANSFORM.md`
- `FEATURE_ROADMAP_DETECTIVE.md`
- `FEATURE_ROADMAP_IMPORT.md`
- `FEATURE_ROADMAP_LINTING.md`
- `FEATURE_ROADMAP_MONITORING.md`
- `FEATURE_ROADMAP_NGINX.md`
- `FEATURE_ROADMAP_PATHS.md`
- `FEATURE_ROADMAP_PROFILE.md`
- `FEATURE_ROADMAP_ROLES_PERMISSIONS.md`
- `FEATURE_ROADMAP_SCHEMA_SHOWCASE.md`
- `FEATURE_ROADMAP_SECURITY.md`
- `FEATURE_ROADMAP_TEMPLATES.md`
- `FEATURE_ROADMAP_TEMPLATE_MARKETPLACE.md`
- `FEATURE_ROADMAP_TENANCY.md`
- `FEATURE_ROADMAP_TESTING.md`

## Extracted + Normalized Offerings

### `FEATURE_ROADMAP_AI.md`

- `raw_sections`: AI Assistant & Ollama Integration; Natural Language to Schema; AI Schema Review & Improvement; AI Documentation Generation; AI Learning & Personalization; AI Configuration
- `normalized_offering_ids`: `ai_assistant_ollama_integration`, `natural_language_to_schema`, `ai_schema_review_improvement`, `ai_documentation_generation`, `ai_learning_personalization`, `ai_configuration`
- `status_signal`: `new`, `planned`

### `FEATURE_ROADMAP_ANALYTICS.md`

- `raw_sections`: Advanced Enterprise Analytics; Analytics & Insights; Usage Analytics; Reporting
- `normalized_offering_ids`: `advanced_enterprise_analytics`, `analytics_insights`, `usage_analytics`, `reporting`
- `status_signal`: `new`, `planned` (subitems)

### `FEATURE_ROADMAP_API_KEYS.md`

- `raw_sections`: Rate Limiting; API Key Scopes & Permissions; API Key Security Enhancements; API Key Lifecycle Management; Developer Experience; Multi-Factor Authentication for Keys; API Key Management
- `normalized_offering_ids`: `api_key_rate_limiting`, `api_key_scopes_permissions`, `api_key_security_enhancements`, `api_key_lifecycle_management`, `api_key_developer_experience`, `api_key_mfa`, `api_key_management`
- `status_signal`: `planned`, `implemented`

### `FEATURE_ROADMAP_BROWSER.md`

- `raw_sections`: Discovery & Navigation; Specification Viewing & Editor UX; Version Comparison & Diff; Export, Share & Embed; Search & Filters; Performance & Reliability; Accessibility & Localization; Security & Compliance; Analytics & Observability; Enterprise & White-Label; Keyboard Shortcuts & Power Users; Testing & Quality; Infrastructure & Deployment
- `normalized_offering_ids`: `browser_discovery_navigation`, `browser_spec_viewing_editor_ux`, `browser_version_diff`, `browser_export_share_embed`, `browser_search_filters`, `browser_performance_reliability`, `browser_accessibility_localization`, `browser_security_compliance`, `browser_analytics_observability`, `browser_enterprise_white_label`, `browser_keyboard_power_users`, `browser_testing_quality`, `browser_infrastructure_deployment`
- `status_signal`: `unspecified`

### `FEATURE_ROADMAP_CODE_GENERATION.md`

- `raw_sections`: Code Generation; Schema-to-Code; Code Generation for Paths; CRUD Operation Stubs
- `normalized_offering_ids`: `code_generation_core`, `schema_to_code`, `paths_code_generation`, `crud_operation_stubs`
- `status_signal`: `planned`, `new`, `unspecified`

### `FEATURE_ROADMAP_DASHBOARD.md`

- `raw_sections`: Schema Health Dashboard; Per-User Dashboard Features; Team Dashboard Features; Enterprise Dashboard Features
- `normalized_offering_ids`: `schema_health_dashboard`, `per_user_dashboard_features`, `team_dashboard_features`, `enterprise_dashboard_features`
- `status_signal`: `new`, `planned`

### `FEATURE_ROADMAP_DATABASE_DATA_STORAGE.md`

- `raw_sections`: Core Data Storage Engine; Data Linking & Relationships; Search & Query Engine; Batch Processing & Import/Export; Data History & Auditing; Data Integrity & Transactions; Performance & Optimization; API & Integration; Multi-Tenancy & Isolation; Monitoring & Observability; Data Visualization & Relationship Graphs; Visual Query Builder & Natural Language Queries; Time-Audited Queries; Time-Series Queries & Background Processing; AI & Vector-Powered Features; Enterprise Data Offloading; Future Considerations
- `normalized_offering_ids`: `core_data_storage_engine`, `data_linking_relationships`, `search_query_engine`, `batch_processing_import_export`, `data_history_auditing`, `data_integrity_transactions`, `performance_optimization`, `api_integration`, `multi_tenancy_isolation`, `monitoring_observability`, `data_visualization_relationship_graphs`, `visual_query_builder_nl_queries`, `time_audited_queries`, `time_series_queries_background_processing`, `ai_vector_powered_features`, `enterprise_data_offloading`, `future_considerations`
- `status_signal`: `unspecified`

### `FEATURE_ROADMAP_DATA_TRANSFORM.md`

- `raw_sections`: Schema Comparison & Compatibility; Data Translation Rules; Major Version Safeguards; Visual Migration Step Plans; MongoDB as Interim Database; Spark for Parallel Migration; Integration with Database Data Storage Roadmap; Data Maintainability & Storage Guarantees; Implementation Notes; Open Questions & Future Work
- `normalized_offering_ids`: `schema_comparison_compatibility`, `data_translation_rules`, `major_version_safeguards`, `visual_migration_step_plans`, `mongodb_interim_database`, `spark_parallel_migration`, `database_storage_integration`, `data_maintainability_storage_guarantees`, `implementation_notes`, `open_questions_future_work`
- `status_signal`: `unspecified`

### `FEATURE_ROADMAP_DETECTIVE.md`

- `raw_sections`: Phase A Foundations & Correlation Fabric; Phase B Database Instance Forensics; Phase C ETL & Migration Forensics; Phase D Investigation Experience; Phase E Integrity & Anomaly Signals; Phase F Exports Compliance & Operations; Version 2 Advanced Detective
- `normalized_offering_ids`: `detective_phase_a_foundations`, `detective_phase_b_instance_forensics`, `detective_phase_c_etl_migration_forensics`, `detective_phase_d_investigation_experience`, `detective_phase_e_integrity_anomaly_signals`, `detective_phase_f_exports_compliance_operations`, `detective_v2_advanced`
- `status_signal`: `unspecified`

### `FEATURE_ROADMAP_IMPORT.md`

- `raw_sections`: Import Methods; Supported Formats; Import Execution; Post-Import Actions; Import History & Audit; Import Templates & Presets; Enterprise Features; Suggested Enterprise Improvements (E1-E23)
- `normalized_offering_ids`: `import_methods`, `import_supported_formats`, `import_execution`, `import_post_import_actions`, `import_history_audit`, `import_templates_presets`, `import_enterprise_features`, `import_enterprise_improvements_bundle`
- `status_signal`: `partially_implemented`, `planned`

### `FEATURE_ROADMAP_LINTING.md`

- `raw_sections`: Schema Linting; Real-Time Validation & Linting; Schema Validation & Quality Scoring; Schema Management Features (Schema Quality)
- `normalized_offering_ids`: `schema_linting`, `real_time_validation_linting`, `schema_validation_quality_scoring`, `schema_management_quality_features`
- `status_signal`: `planned`, `new`, `unspecified`

### `FEATURE_ROADMAP_MONITORING.md`

- `raw_sections`: Monitoring & Observability; Application Monitoring; Logging; Audit Logging; API Key Analytics & Monitoring; Alerting; Health Checks; Log Management; Alerting & Incident Management; SLA & SLO Management
- `normalized_offering_ids`: `monitoring_observability`, `application_monitoring`, `logging`, `audit_logging`, `api_key_analytics_monitoring`, `alerting`, `health_checks`, `log_management`, `incident_management`, `sla_slo_management`
- `status_signal`: `partially_implemented`, `planned`, `unspecified`

### `FEATURE_ROADMAP_NGINX.md`

- `raw_sections`: AI Suggested Fixes; Additional Security Hardening Recommendations; Security harden NGINX
- `normalized_offering_ids`: `nginx_ai_suggested_fixes`, `nginx_security_hardening_recommendations`, `nginx_security_harden`
- `status_signal`: `unspecified`

### `FEATURE_ROADMAP_PATHS.md`

- `raw_sections`: Engineer-Focused Features; Testing & Documentation; Code Generation; Enterprise Features; Testing & Validation; Automatic Endpoint Generation; UI/UX Design Considerations; Implementation Phases; Operation Focus Mode; Editor Overlay; Professional Node Visual Redesign; Canvas Toolbar for Paths; Paths Canvas Layout Improvements; Developer-Centered Code Preview; Paths Canvas Search & Filter; Context Menu for Paths Nodes; Keyboard Shortcuts for Paths; Undo/Redo for Paths Canvas; Edge & Connection Visual Improvements; Left Sidebar Improvements; OpenAPI Spec Quality Panel; Minimap for Paths Canvas; Paths Canvas Export Enhancements; Advanced Edge Routing Engine; Node Visual Design System; Canvas Visual Polish & Presentation; Suggested Enterprise Improvements (P1-P16)
- `normalized_offering_ids`: `paths_engineer_focused_features`, `paths_testing_documentation`, `paths_code_generation`, `paths_enterprise_features`, `paths_testing_validation`, `paths_automatic_endpoint_generation`, `paths_uiux_design_considerations`, `paths_implementation_phases`, `paths_operation_focus_mode`, `paths_editor_overlay`, `paths_node_visual_redesign`, `paths_canvas_toolbar`, `paths_canvas_layout_improvements`, `paths_developer_centered_code_preview`, `paths_search_filter`, `paths_context_menu`, `paths_keyboard_shortcuts`, `paths_undo_redo`, `paths_edge_connection_visuals`, `paths_left_sidebar_improvements`, `paths_openapi_quality_panel`, `paths_minimap`, `paths_export_enhancements`, `paths_advanced_edge_routing_engine`, `paths_node_visual_design_system`, `paths_visual_polish_presentation`, `paths_enterprise_improvements_bundle`
- `status_signal`: `planned`, `unspecified`

### `FEATURE_ROADMAP_PROFILE.md`

- `raw_sections`: Current Feature Set; Profile Information; Account Settings; Notification Preferences; Security Settings; Personalization; API & Developer Settings; Enterprise Features; Enterprise Identity & Access; Enterprise Security; Compliance & Governance; Enterprise Profile Management; Delegation & Proxy Access; Enterprise Directory
- `normalized_offering_ids`: `profile_current_feature_set`, `profile_information`, `account_settings`, `notification_preferences`, `profile_security_settings`, `profile_personalization`, `profile_api_developer_settings`, `enterprise_profile_features`, `enterprise_identity_access`, `enterprise_security`, `enterprise_compliance_governance`, `enterprise_profile_management`, `enterprise_delegation_proxy_access`, `enterprise_directory`
- `status_signal`: `planned`, `unspecified`

### `FEATURE_ROADMAP_ROLES_PERMISSIONS.md`

- `raw_sections`: Design Alignment for objectified-commercial; Ordered Ticket Sequence; RP-01..RP-16 implementation tickets
- `normalized_offering_ids`: `roles_permissions_design_alignment`, `roles_permissions_ordered_ticket_sequence`, `roles_permissions_rp01_to_rp16`
- `status_signal`: `unspecified`

### `FEATURE_ROADMAP_SCHEMA_SHOWCASE.md`

- `raw_sections`: Schema Showcase; Browse Site Showcase Feature
- `normalized_offering_ids`: `schema_showcase`, `browse_site_showcase`
- `status_signal`: `new`

### `FEATURE_ROADMAP_SECURITY.md`

- `raw_sections`: Security & Authentication; Advanced Security; User Permissions & Access Control
- `normalized_offering_ids`: `security_authentication`, `advanced_security`, `user_permissions_access_control`
- `status_signal`: `partially_implemented`, `planned`

### `FEATURE_ROADMAP_TEMPLATES.md`

- `raw_sections`: Group Templates; Schema Templates & Snippets; Property Templates; Template Library; Custom Templates
- `normalized_offering_ids`: `group_templates`, `schema_templates_snippets`, `property_templates`, `template_library`, `custom_templates`
- `status_signal`: `planned`, `partially_implemented`

### `FEATURE_ROADMAP_TEMPLATE_MARKETPLACE.md`

- `raw_sections`: Template Marketplace; Community Template Library; Template Import & Customization
- `normalized_offering_ids`: `template_marketplace`, `community_template_library`, `template_import_customization`
- `status_signal`: `new`, `unspecified`

### `FEATURE_ROADMAP_TENANCY.md`

- `raw_sections`: Multi-Tenancy & Organizations; Organization Management; Advanced Tenant Management; Tenant Industry Tagging; Industry Classification
- `normalized_offering_ids`: `multi_tenancy_organizations`, `organization_management`, `advanced_tenant_management`, `tenant_industry_tagging`, `industry_classification`
- `status_signal`: `partially_implemented`, `new`, `planned`, `unspecified`

### `FEATURE_ROADMAP_TESTING.md`

- `raw_sections`: Advanced Testing & Quality; Testing & Quality Assurance; Automated Testing; CI/CD Pipeline; Swagger/OpenAPI Testing Integration; Testing & Validation; Contract Testing; Consumer-Driven Contracts; Performance Testing; API Quality Scoring
- `normalized_offering_ids`: `advanced_testing_quality`, `testing_quality_assurance`, `automated_testing`, `cicd_pipeline`, `swagger_openapi_testing_integration`, `testing_validation`, `contract_testing`, `consumer_driven_contracts`, `performance_testing`, `api_quality_scoring`
- `status_signal`: `new`, `in_progress`, `planned`, `unspecified`

## Notes

- Extraction intentionally ignores `# Completed` sections unless they introduce an active offering grouping relevant to normalization.
- Large roadmap sources with repeated subsections were collapsed into canonical bundle IDs where the source acts as an extension pack (for example, Import E1-E23, Paths P1-P16).
