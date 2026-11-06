/**
 * The CI action pages — DOCS-1.11 (#5628).
 *
 * `diff-action/README.md` and `mock-action/README.md` stay where GitHub expects an action's
 * README; the docs site shows the same text under Reference → CI. This module turns a README
 * into its page: front matter added, the `# Title` line moved into it, and every relative link
 * rewritten — to the docs page when it points into `apiome-docs/docs/` or at a file the site
 * carries (`repo-links.mjs`); any other file keeps its text and loses its link, because the docs
 * never link to GitHub. `scripts/sync-action-pages.mjs`
 * writes the pages and, with `--check`, fails when a committed page no longer matches its README.
 */
import path from 'node:path';
import {sitePageForRepoPath} from './repo-links.mjs';


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
 * @returns {string | null} The target to use on the page: unchanged for absolute URLs and
 *   same-page anchors; a relative docs-page link when it resolves into `apiome-docs/docs/` or to a
 *   file the site carries; otherwise `null` — the caller keeps the text and drops the link.
 */
export function rewriteLink(target, readme) {
  if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith('#')) return target;
  const [file, anchor] = target.split(/#(.*)/s, 2);
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(readme), file));
  const suffix = anchor ? `#${anchor}` : '';
  if (resolved.startsWith(DOCS_ROOT)) {
    return `${path.posix.relative(ACTION_PAGES_DIR, resolved)}${suffix}`;
  }
  const page = sitePageForRepoPath(file.endsWith('/') ? `${resolved}/` : resolved, anchor ?? '');
  if (page === null) return null;
  return path.posix.relative(ACTION_PAGES_DIR, `${DOCS_ROOT}${page}`);
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
    .replace(/\[([^\]]*)\]\(([^)\s]+)\)/g, (_match, label, target) => {
      const rewritten = rewriteLink(target, spec.readme);
      return rewritten === null ? label : `[${label}](${rewritten})`;
    })
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
    `> This page is \`${spec.readme}\`, copied by ` +
    '`yarn workspace apiome-docs sync:action-pages` — edit the README, not this page.';
  return `${frontMatter}\n\n${note}\n\n${body}\n`;
}
