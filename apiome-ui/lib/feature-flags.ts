/**
 * Build-time feature flags for apiome-ui.
 *
 * Plain constants, no `'use client'` — safe to import from both client
 * components and server route handlers / middleware.
 *
 * --------------------------------------------------------------------
 * FEATURE_GITLIKE
 *   Master switch for the "git-like" feature set:
 *     - branches, tags, commit/revision flow
 *     - push / pull / divergence / merge / rollback
 *     - on-canvas git menu, git command palette
 *     - draft locks, server-ahead banners, push-conflict provider
 *     - dashboard history graph, change-report tabs
 *
 *   Project & version selection, viewing existing revisions, and editing
 *   the current draft are NOT git-like and remain enabled.
 *
 *   When false:
 *     - All gitlike UI render sites are gated off.
 *     - The middleware short-circuits gitlike API routes with 404.
 *     - Underlying logic (hooks, utils, tests) stays compiled and verified
 *       so re-enabling is a one-line change here.
 *
 *   To re-enable, flip to true. To re-enable selectively, split this flag
 *   into per-area constants (gitlikeBranches, gitlikeTags, gitlikeCommit,
 *   gitlikePushPull, ...) and update consumers.
 */
export const FEATURE_GITLIKE = false;

/**
 * --------------------------------------------------------------------
 * FEATURE_LEGACY_POSTMAN_IMPORT  (MFI-32.7, #4409)
 *   The retired in-browser Postman → OpenAPI converter
 *   (`src/app/utils/postman-to-openapi.ts`).
 *
 *   When false (shipped): the **Postman Collection** import card sends the collection to
 *   `POST /api/import/postman/openapi`, which runs the REST Postman import adapter — schemas
 *   inferred from example bodies, credentials scrubbed, warnings for what it leaves out — and
 *   continues into the Projects wizard with the OpenAPI it returns.
 *
 *   When true: the card converts in the browser again, as before MFI-32.7 (no schemas, no
 *   scrubbing, no warnings). Kept only as a fallback; delete it with the legacy converter once
 *   nothing needs it.
 */
export const FEATURE_LEGACY_POSTMAN_IMPORT = false;
