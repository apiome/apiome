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
