/**
 * Internal links and orphan pages — two of the `yarn docs:check` rules (DOCS-1.13, #5630).
 *
 * The production build also fails on a broken link (`onBrokenLinks: "throw"`), but only after a
 * full build, and it cannot be pointed at a test fixture. These rules read the sources directly, so
 * `docs:check` names the page and the link within a second and the failure modes are unit-tested.
 * Anchors (`#section`) are left to the build, which knows every heading id.
 */
import fs from 'node:fs';
import path from 'node:path';

import matter from 'gray-matter';

import {listPages} from './pages.mjs';

/**
 * Remove fenced code blocks and inline code: a link shown as an example is not a link.
 *
 * @param {string} source - Markdown / MDX source.
 * @returns {string} The prose only.
 */
export function stripCode(source) {
  return source.replace(/^(\s*)(```|~~~)[^\n]*\n[\s\S]*?^\1\2[^\n]*$/gm, '').replace(/`[^`\n]*`/g, '');
}

/**
 * Every Markdown link target in a page's prose (`[text](target)`), without its anchor.
 *
 * External URLs (`https:`, `mailto:` …) and in-page anchors (`#x`) are not returned.
 *
 * @param {string} source - Markdown / MDX source.
 * @returns {string[]} Targets as written, e.g. `../ship/publish-a-version.md` or `/reference`.
 */
export function findInternalLinks(source) {
  const targets = [];
  for (const match of stripCode(source).matchAll(/\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/g)) {
    const target = match[1].split('#')[0];
    if (target === '' || /^[a-z][a-z0-9+.-]*:/i.test(target)) continue;
    targets.push(target);
  }
  return targets;
}

/**
 * The URL route Docusaurus serves a doc page at.
 *
 * An absolute `slug` wins; otherwise the path without its extension, with a trailing `index`
 * dropped (`build/index.mdx` → `/build`).
 *
 * @param {string} relative - Page path relative to the docs directory.
 * @param {string} source - The page's source (read for `slug`).
 * @returns {string} The route, with a leading slash.
 */
export function docRoute(relative, source) {
  let slug;
  try {
    slug = matter(source).data.slug;
  } catch {
    slug = undefined;
  }
  if (typeof slug === 'string' && slug.startsWith('/')) return slug;
  const route = relative.split(path.sep).join('/').replace(/\.mdx?$/, '').replace(/(^|\/)index$/, '');
  return `/${route}`;
}

/**
 * The slug of a release-notes post: its `slug` front matter, else its file name without the date.
 *
 * @param {string} file - The post's file name, e.g. `2026-10-07-workspace-pages.mdx`.
 * @param {string} source - The post's source.
 * @returns {string} The slug, e.g. `workspace-pages`.
 */
export function postSlug(file, source) {
  let slug;
  try {
    slug = matter(source).data.slug;
  } catch {
    slug = undefined;
  }
  if (typeof slug === 'string' && slug.trim() !== '') return slug.replace(/^\//, '');
  return path.basename(file).replace(/\.mdx?$/, '').replace(/^\d{4}-\d{2}-\d{2}-/, '');
}

/**
 * The slugs of category landing pages declared in `_category_.json` (`link.slug`), e.g. a
 * `generated-index` such as `/reference/mock-runtime`.
 *
 * @param {string} docsDir - Absolute path of `docs/`.
 * @returns {string[]} The slugs, with a leading slash.
 */
export function categorySlugs(docsDir) {
  const slugs = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name === '_category_.json') {
        try {
          const slug = JSON.parse(fs.readFileSync(full, 'utf8')).link?.slug;
          if (typeof slug === 'string') slugs.push(slug.startsWith('/') ? slug : `/${slug}`);
        } catch {
          // An unreadable category file is reported by the group rules.
        }
      }
    }
  };
  walk(docsDir);
  return slugs;
}

/**
 * Every route the site serves from its sources: doc pages, category landing pages, release-notes
 * posts, and the release-notes index with its `archive` and `authors` listings.
 *
 * @param {object} options - Inputs.
 * @param {string} options.docsDir - Absolute path of `docs/`.
 * @param {string} [options.releaseNotesDir] - Absolute path of `release-notes/`, when there is one.
 * @returns {Set<string>} Routes with a leading slash and no trailing slash (`/` for the root).
 */
export function collectRoutes({docsDir, releaseNotesDir}) {
  const routes = new Set();
  for (const page of listPages(docsDir)) {
    routes.add(docRoute(path.relative(docsDir, page), fs.readFileSync(page, 'utf8')));
  }
  for (const slug of categorySlugs(docsDir)) routes.add(slug);
  if (releaseNotesDir && fs.existsSync(releaseNotesDir)) {
    for (const route of ['/release-notes', '/release-notes/archive', '/release-notes/authors']) routes.add(route);
    for (const post of listPages(releaseNotesDir)) {
      routes.add(`/release-notes/${postSlug(post, fs.readFileSync(post, 'utf8'))}`);
    }
  }
  return routes;
}

/**
 * Check every internal link on every page.
 *
 * - a relative link to a `.md` / `.mdx` file must name a file that exists;
 * - a site-absolute link (`/ship/export-a-spec`) must be a route the site serves, or a file under
 *   `static/` (`/img/bee-logo.png`).
 *
 * @param {object} options - Inputs.
 * @param {string} options.siteDir - Absolute path of the site (`apiome-docs/`).
 * @param {string} options.docsDir - Absolute path of `docs/`.
 * @returns {string[]} Problems, each naming the page (relative to `siteDir`) and the link.
 */
export function checkInternalLinks({siteDir, docsDir}) {
  const releaseNotesDir = path.join(siteDir, 'release-notes');
  const staticDir = path.join(siteDir, 'static');
  const routes = collectRoutes({docsDir, releaseNotesDir});
  const pages = [docsDir, releaseNotesDir].filter((dir) => fs.existsSync(dir)).flatMap((dir) => listPages(dir));

  const problems = [];
  for (const page of pages) {
    const relative = path.relative(siteDir, page);
    for (const target of findInternalLinks(fs.readFileSync(page, 'utf8'))) {
      if (target.startsWith('/')) {
        const route = target.length > 1 ? target.replace(/\/$/, '') : target;
        if (!routes.has(route) && !fs.existsSync(path.join(staticDir, decodeURI(route)))) {
          problems.push(`${relative}: broken link \`${target}\` — no page or static file serves that path`);
        }
      } else if (/\.mdx?$/.test(target)) {
        if (!fs.existsSync(path.resolve(path.dirname(page), decodeURI(target)))) {
          problems.push(`${relative}: broken link \`${target}\` — no such file`);
        }
      }
    }
  }
  return problems;
}

/**
 * The folders the sidebar generates its items from: every `{type: 'autogenerated', dirName}` in
 * `sidebars.ts`, relative to `docs/`.
 *
 * @param {string} sidebarsSource - The source of `sidebars.ts`.
 * @returns {string[]} The `dirName`s, e.g. `['.']`.
 */
export function autogeneratedDirs(sidebarsSource) {
  return [...sidebarsSource.matchAll(/type:\s*['"]autogenerated['"]\s*,\s*dirName:\s*['"]([^'"]+)['"]/g)].map(
    (match) => match[1],
  );
}

/**
 * Doc ids the sidebar lists by hand (`'build/axis-score'` or `{type: 'doc', id: 'build/axis-score'}`).
 *
 * @param {string} sidebarsSource - The source of `sidebars.ts`.
 * @returns {Set<string>} The ids named.
 */
export function explicitDocIds(sidebarsSource) {
  const ids = new Set();
  for (const match of sidebarsSource.matchAll(/\bid:\s*['"]([^'"]+)['"]/g)) ids.add(match[1]);
  // A bare id is a quoted `group/page` path; `dirName:` values are folders, not ids.
  for (const match of sidebarsSource.matchAll(/(?<!dirName:\s*)['"]([a-z0-9-]+(?:\/[a-z0-9-]+)+)['"]/g)) {
    ids.add(match[1]);
  }
  return ids;
}

/**
 * Pages that are in no sidebar, so a reader can only reach them by a direct link.
 *
 * A page is in the sidebar when it sits under a folder the sidebar autogenerates from, or the
 * sidebar names its id; and it is not hidden by `unlisted: true`, `draft: true` or
 * `displayed_sidebar: null` front matter. A page directly in `docs/`, outside every group folder,
 * is an orphan too: every page belongs to one of the jobs.
 *
 * @param {object} options - Inputs.
 * @param {string} options.docsDir - Absolute path of `docs/`.
 * @param {string} options.sidebarsSource - The source of `sidebars.ts`.
 * @returns {string[]} Problems, each naming the page relative to `docsDir`.
 */
export function checkOrphans({docsDir, sidebarsSource}) {
  const dirs = autogeneratedDirs(sidebarsSource).map((dir) => path.normalize(dir));
  const ids = explicitDocIds(sidebarsSource);
  const problems = [];

  for (const page of listPages(docsDir)) {
    const relative = path.relative(docsDir, page);
    const id = relative.split(path.sep).join('/').replace(/\.mdx?$/, '');
    let data = {};
    try {
      ({data} = matter(fs.readFileSync(page, 'utf8')));
    } catch {
      // Invalid front matter is reported by the page rules.
    }

    if (data.unlisted === true || data.draft === true || data.displayed_sidebar === null) {
      const flag = data.unlisted === true ? 'unlisted: true' : data.draft === true ? 'draft: true' : 'displayed_sidebar: null';
      problems.push(`${relative}: orphan page — \`${flag}\` keeps it out of the sidebar`);
      continue;
    }
    if (!relative.includes(path.sep)) {
      problems.push(`${relative}: orphan page — move it into a group folder (docs/<group>/)`);
      continue;
    }
    const covered =
      ids.has(id) || dirs.some((dir) => dir === '.' || relative === dir || relative.startsWith(`${dir}${path.sep}`));
    if (!covered) problems.push(`${relative}: orphan page — no sidebar lists it`);
  }
  return problems;
}
