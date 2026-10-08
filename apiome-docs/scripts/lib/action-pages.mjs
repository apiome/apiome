/**
 * The CI action pages — DOCS-1.11 (#5628).
 *
 * `diff-action/README.md` and `mock-action/README.md` stay where GitHub expects an action's
 * README; the docs site shows the same text under Reference → CI. This module turns a README
 * into its page: front matter added, the `# Title` line moved into it, and every relative link
 * rewritten — to the docs page when it points into `apiome-docs/docs/`, otherwise to the file on
 * GitHub — so the page cannot link to a path the site does not serve. `scripts/sync-action-pages.mjs`
 * writes the pages and, with `--check`, fails when a committed page no longer matches its README.
 */
import path from 'node:path';

/** Where repository files are browsed on GitHub. */
export const REPO_BLOB_URL = 'https://github.com/apiome/apiome/blob/main';

/** The pages' folder, relative to the repository root. */
export const ACTION_PAGES_DIR = 'apiome-docs/docs/reference/ci';

/**
 * @typedef {object} ActionPage
 * @property {string} readme - The README, relative to the repository root.
 * @property {string} page - The page's file name inside {@link ACTION_PAGES_DIR}.
 * @property {string} title - The page title.
 * @property {string} description - Front-matter description (14 words or fewer).
 * @property {number} position - `sidebar_position`.
 */

/** @type {ReadonlyArray<ActionPage>} */
export const ACTION_PAGES = Object.freeze([
  {
    readme: 'diff-action/README.md',
    page: 'diff-action.md',
    title: 'diff-action (GitHub Action)',
    description: 'Inputs, outputs and behaviour of the apiome/diff-action pull-request contract gate.',
    position: 3,
  },
  {
    readme: 'mock-action/README.md',
    page: 'mock-action.md',
    title: 'mock-action (GitHub Action)',
    description: 'Inputs, outputs and behaviour of the apiome/mock-action portable mock runtime.',
    position: 4,
  },
]);

/** The docs tree, relative to the repository root. */
const DOCS_ROOT = 'apiome-docs/docs/';

/**
 * Rewrite one relative link target found in a README.
 *
 * @param {string} target - The link target as written, e.g. `../apiome-cli/README.md#diff`.
 * @param {string} readme - The README's path relative to the repository root.
 * @returns {string} The target to use on the page: unchanged for absolute URLs and same-page
 *   anchors; a relative docs-page link when it resolves into `apiome-docs/docs/`; otherwise the
 *   file's GitHub URL.
 */
export function rewriteLink(target, readme) {
  if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith('#')) return target;
  const [file, anchor] = target.split(/#(.*)/s, 2);
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(readme), file));
  const suffix = anchor ? `#${anchor}` : '';
  if (resolved.startsWith(DOCS_ROOT)) {
    return `${path.posix.relative(ACTION_PAGES_DIR, resolved)}${suffix}`;
  }
  return `${REPO_BLOB_URL}/${resolved}${suffix}`;
}

/**
 * Render one action page from its README text.
 *
 * @param {ActionPage} spec - Which README, and the page's front matter.
 * @param {string} source - The README's contents.
 * @returns {string} The page, ending in a newline.
 */
export function renderActionPage(spec, source) {
  const body = source
    .replace(/^﻿/, '')
    // The first `# Title` line becomes the front-matter title.
    .replace(/^# [^\n]*\n+/, '')
    .replace(/(\]\()([^)\s]+)(\))/g, (_match, open, target, close) => `${open}${rewriteLink(target, spec.readme)}${close}`)
    .trimEnd();
  const frontMatter = [
    '---',
    `title: ${JSON.stringify(spec.title)}`,
    `description: ${JSON.stringify(spec.description)}`,
    `sidebar_position: ${spec.position}`,
    'tags: [ci, reference]',
    `generated: apiome-docs/scripts/sync-action-pages.mjs from ${spec.readme}`,
    '---',
  ].join('\n');
  const note =
    `> This page is [\`${spec.readme}\`](${REPO_BLOB_URL}/${spec.readme}), copied by ` +
    '`yarn workspace apiome-docs sync:action-pages` — edit the README, not this page.';
  return `${frontMatter}\n\n${note}\n\n${body}\n`;
}
