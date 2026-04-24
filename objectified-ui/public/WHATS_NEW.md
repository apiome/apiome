# Objectified 05-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## Repositories
- Added REPO-5.3 commit-SHA version auto-creation so repository scan import jobs now bind to idempotent draft versions named `<datestamp>-<short-sha>`, capture `metadata.repositorySource` (repository/branch/SHA/path), and allow manifest-declared missing project auto-creation only when a tenant-admin feature flag is enabled.
- Added REPO-5.2 project/version mapping rules so manifest `specs[].project` + `specs[].versionStrategy` now take precedence, auto mapping falls back to path-derived project + `commit-sha`, and unmapped root-level specs persist `tracked=false` with `settingsJson.mappingRequired=true` for UI mapping prompts.
- Added REPO-5.1 discovered-file import binding so repository scan completion now dispatches dry-run git import jobs for `new`/`modified` files (tracked files only), creates manual approval `removal` jobs for `removed` files, skips `unchanged` and untracked files, and records sync audit outcomes (`repository.sync_committed` / `repository.sync_pending_review`) with parse failures setting `repository_file.status='parse_error'`.
- Added REPO-4.5 failure backoff + auto-pause behavior so repeated provider head-check failures exponentially back off scheduler cadence, reset on success, and auto-pause repositories with `repository.auto_paused` audit events after eight consecutive failures.
- Added REPO-4.4 multi-branch tracking so wildcard branch templates (for example `release/*`) expand at scheduler time into tracked concrete repository branches without deleting historical scan records for previously seen branches.
- Added poll-time branch HEAD SHA change detection with GitHub conditional `If-None-Match` checks so unchanged branches write `skipped_unchanged` scan history entries and skip downstream scan dispatch while still advancing poll cadence.
- Added a repository poll scheduler tick that atomically reserves due tracked branches, skips paused repositories, enforces enterprise/free poll interval floors, dispatches `repo.poll.<priority>` jobs, and records `repository.polled` workflow audits.
- Added the REPO-3.8 in-scan virtual filesystem resolver for repository imports, with dependency-ordered cross-file `$ref` resolution (relative paths + JSON pointers), per-scan memoization, and deterministic cycle detection errors.
- Added standalone repository JSON Schema importer support for Draft 7, 2019-09, and 2020-12 schemas, preserving source `$id`/draft metadata while delegating sibling `$ref` resolution through the REPO-3.8 resolver contract.
- Added repository importer support for `swagger_2_0`, routing Swagger 2.0 specs through the same conversion/parser pipeline as OpenAPI 3.x with semantic parity coverage for schemas, paths, parameters, and security mappings.
- Added a repository OpenAPI importer hook for OpenAPI 3.0/3.1 that reuses the existing dialog converter with normalized `{source, format, content, refs}` input and parity-checked fixture coverage, while delegating cross-file `$ref` resolution through the REPO-3.8 resolver contract.
- Added previous-scan diffing for repository scans so completed scans classify files as `new`/`unchanged`/`modified`/`removed`, retain removed rows with prior blob SHA, and store `{added, modified, removed, unchanged}` summary counts.
- Added repository scan history models (`repository_scan`/`repository_file`) with cursor-paginated scan/file REST endpoints, `force` re-scan support, and `skipped_unchanged` tracking.
- Added `.objectified/repo.yaml` manifest support with published schema validation, non-fatal `manifest_error` recording, per-spec format/polling overrides, and untracked discovery rows for files not listed in the manifest.
- Added provider-agnostic spec format detection with filename heuristics plus 64 KB content sniffing, confidence/discriminator output, and stream-mode sniffing for files over 5 MB.
- Added scanner include/exclude rules with published default ignore patterns, manifest-level ignore merges, `files_skipped_by_ignore` telemetry, and explicit spec precedence over ignores.
- Added a streaming repository tree walker for connector scans with commit-SHA traversal, boundary glob filtering, typed scan-limit errors, and `repository.scan.walked` workflow audit emission.
- Added repository connector MVP database tables for repository registration, branch tracking, and linked-account credential references.
- Added a provider abstraction layer for repository connectors with a GitHub adapter, shared provider error taxonomy, and cross-provider contract tests.
- Added a GitLab repository provider (`@gitbeaker/rest`) with full contract support, keyset repository pagination, and GitLab webhook secret verification.
- Added a Bitbucket Cloud repository provider adapter with contract-test coverage, REST API 2.0 tree/file handling, and UUID-based webhook verification.
- Added a server-only `resolveRepositoryToken` helper that resolves linked-account repository credentials, refreshes supported expired tokens, emits typed resolver errors, and writes token-safe workflow audit rows.
- Added a new ADE Repositories page with a four-step GitHub registration wizard and initial scan timeline flow.
- Added per-repository branch management so tracked branches can be added/removed with per-branch subpath glob and polling settings, defaulting to the provider default branch and supporting wildcard branch patterns.
- Added repository lifecycle management for edit/archive/unarchive/delete with typed delete confirmation, dashboard controls, and REST audit/cascade handling.

## UI
- Branch workflow is its own button in the canvas now, and compacted to fit most functionality that's in Versions now.
- Compacted the trending view in the projects page in the dashboard.
- Moved the add, import, and template buttons to the bottom of the classes and properties sidebar list so they don't obscure the lists.
- Added bottom header to show status of the canvas editor screens.
- Gitlike functionality will be redesigned; currently not working as expected, and will be perfected in a later release.
- Clicking on the warning chevron now eases in/out the warning for the project for sunset indicators.
- Clicking the tools chevron in the designer canvas now animates instead of just (dis)appearing.
- Layout form now looks associated with the button from which it appears.
- Clicking outside the layout form now dismisses it from the canvas.
- Added the ability to decide whether or not to save the layout image on a layout persist.
- Corrects schema metrics display when the schema list is empty.
- Corrects opacity of overlay buttons in canvas.

---

## Studio AI
- Added the Studio AI chatbot launcher and panel: a floating bubble in the bottom right of the canvas opens a slide-out panel with full-screen mode, toggled with `Cmd+Shift+A` / `Ctrl+Shift+A`.
- Filled out the Studio AI chat surface to the design guidelines: distinct user/assistant bubbles, typing indicator, markdown rendering, syntax-highlighted code blocks with a copy button, regenerate / thumbs up / thumbs down message actions, and a one-click import button when an assistant reply contains an OpenAPI spec in a ```json``` block.
- The Studio AI chatbot is now context-aware: each message you send carries a snapshot of your current project, version, classes, reusable properties, and canvas selection, and a "Sharing context" chip in the panel lets you inspect exactly what the assistant can see.
- The Studio AI chatbot now handles multi-turn conversations: follow-up prompts like "add a phone field", "remove priceCents", "make name required", "rename id to productId", "make it more like Stripe Charges", or simple clarification questions are recognized as edits to the previous reply, and the refined OpenAPI spec is re-shipped so you can keep iterating without restarting the thread.
- The Studio AI chatbot now persists conversations per project and version: a new toolbar above the chat surfaces "New", "History", "Export", and "Clear" actions, the history view lets you browse and search every saved thread, exporting downloads the active conversation as a markdown file, and the chat automatically restores your most recent thread when you reopen the panel.

---

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: April 24, 2026*

