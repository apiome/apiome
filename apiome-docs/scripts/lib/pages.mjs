/**
 * Page rules for the Apiome docs site — the checks `yarn docs:check` runs before the build.
 *
 * The build itself fails on broken links and anchors (`onBrokenLinks: "throw"`); these rules cover
 * what the build cannot see: front matter and the sidebar skeleton. DOCS-1.13 (#5630) extends the
 * gate with orphan pages and screenshot checks.
 */
import fs from 'node:fs';
import path from 'node:path';

import matter from 'gray-matter';

/** The longest a front-matter `description` may be, in words (copy-voice rule). */
export const MAX_DESCRIPTION_WORDS = 14;

/** File extensions Docusaurus treats as doc pages. */
const PAGE_EXTENSIONS = new Set(['.md', '.mdx']);

/**
 * Count the words in a string.
 *
 * @param {string} text - Any text.
 * @returns {number} The number of whitespace-separated words (0 for blank text).
 */
export function countWords(text) {
  const trimmed = String(text ?? '').trim();
  return trimmed === '' ? 0 : trimmed.split(/\s+/).length;
}

/**
 * Check one page's front matter.
 *
 * @param {string} source - The page's raw Markdown / MDX source.
 * @returns {string[]} Problems found; empty when the page is valid.
 */
export function checkFrontMatter(source) {
  let data;
  try {
    ({data} = matter(source));
  } catch (error) {
    return [`front matter is not valid YAML: ${error.message}`];
  }
  const problems = [];
  if (typeof data.title !== 'string' || data.title.trim() === '') {
    problems.push('front matter needs a `title`');
  }
  if (typeof data.description !== 'string' || data.description.trim() === '') {
    problems.push('front matter needs a `description`');
  } else if (countWords(data.description) > MAX_DESCRIPTION_WORDS) {
    problems.push(
      `description is ${countWords(data.description)} words; keep it to ${MAX_DESCRIPTION_WORDS} or fewer`,
    );
  }
  return problems;
}

/**
 * List every doc page under a directory, recursively, skipping `_`-prefixed partials.
 *
 * @param {string} dir - Absolute path of the docs directory.
 * @returns {string[]} Absolute paths of `.md` / `.mdx` pages, sorted.
 */
export function listPages(dir) {
  const pages = [];
  for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
    if (entry.name.startsWith('_')) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      pages.push(...listPages(full));
    } else if (PAGE_EXTENSIONS.has(path.extname(entry.name))) {
      pages.push(full);
    }
  }
  return pages.sort();
}

/**
 * Check that every top-level folder under `docs/` is a sidebar group: it has a
 * `_category_.json` with a label and an `index.md(x)` landing page.
 *
 * @param {string} dir - Absolute path of the docs directory.
 * @returns {string[]} Problems found, each naming the folder; empty when all groups are valid.
 */
export function checkGroups(dir) {
  const problems = [];
  for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
    if (!entry.isDirectory()) continue;
    const group = path.join(dir, entry.name);
    const categoryFile = path.join(group, '_category_.json');
    if (!fs.existsSync(categoryFile)) {
      problems.push(`${entry.name}/: missing _category_.json`);
    } else {
      try {
        const category = JSON.parse(fs.readFileSync(categoryFile, 'utf8'));
        if (typeof category.label !== 'string' || category.label.trim() === '') {
          problems.push(`${entry.name}/_category_.json: needs a \`label\``);
        }
      } catch (error) {
        problems.push(`${entry.name}/_category_.json: not valid JSON (${error.message})`);
      }
    }
    const hasIndex = ['index.md', 'index.mdx'].some((name) => fs.existsSync(path.join(group, name)));
    if (!hasIndex) {
      problems.push(`${entry.name}/: missing index.mdx (every group needs a landing page)`);
    }
  }
  return problems;
}

/**
 * Run every page rule over a docs directory.
 *
 * @param {string} dir - Absolute path of the docs directory.
 * @returns {string[]} Problems found, each prefixed with the path relative to `dir`.
 */
export function checkDocs(dir) {
  const problems = [...checkGroups(dir)];
  for (const page of listPages(dir)) {
    const relative = path.relative(dir, page);
    for (const problem of checkFrontMatter(fs.readFileSync(page, 'utf8'))) {
      problems.push(`${relative}: ${problem}`);
    }
  }
  return problems;
}
