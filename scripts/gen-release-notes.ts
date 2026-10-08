#!/usr/bin/env node
/**
 * Release notes for the documentation site, one post per RC (DOCS-1.12, #5629).
 *
 * Release information lives in two files that never meet: the REST API's Keep-a-Changelog
 * file (`apiome-rest/CHANGELOG.md`, one section per REST version) and the app's What's new
 * feed (`apiome-ui/public/WHATS_NEW.md`, one document per RC). This script merges them by
 * release into `apiome-docs/release-notes/<release>.md` — blog posts of the Docusaurus site —
 * and turns every `#1234` into a link to the issue.
 *
 * Which REST versions belong to which RC is recorded in `apiome-docs/release-notes/releases.json`
 * (`restAfter` < version ≤ `restThrough`), as is the git ref the RC's What's new is read from.
 *
 * Usage (Node ≥ 22.18 runs this file directly; no build step):
 *
 *   node scripts/gen-release-notes.ts
 *       Write the rolling `unreleased.md`: every REST version after the last closed RC, plus the
 *       What's new for the RC in progress. Runs before every docs build, so the page always
 *       matches `main`. The file is generated and not committed.
 *
 *   node scripts/gen-release-notes.ts --close RC6 [--ref RC6] [--milestone 6] [--date 2026-10-31]
 *       Close an RC: record it in `releases.json` (its REST range ends at the newest changelog
 *       version) and write its post, `rc6.md`. Run on tag by `.github/workflows/apiome-release-notes.yml`.
 *
 *   node scripts/gen-release-notes.ts --release RC4
 *       Re-render the post of an RC already in `releases.json` (reads What's new from git).
 */
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

/** The repository root (this file lives in `<root>/scripts/`). */
export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Repository-relative paths of the inputs and outputs. */
export const PATHS = {
  changelog: 'apiome-rest/CHANGELOG.md',
  whatsNew: 'apiome-ui/public/WHATS_NEW.md',
  manifest: 'apiome-docs/release-notes/releases.json',
  outDir: 'apiome-docs/release-notes',
  docsDir: 'apiome-docs/docs',
} as const;

/** File name of the rolling post for work not yet in a closed RC. */
export const UNRELEASED_FILE = 'unreleased.md';

/** One closed RC, as recorded in `releases.json`. */
export interface Release {
  /** The RC's name, which is also its milestone title and its tag, e.g. `RC4`. */
  name: string;
  /** GitHub milestone number, for the "issues in this release" link. Optional. */
  milestone?: number;
  /** The day the RC closed (`YYYY-MM-DD`); the post's date. */
  closed: string;
  /** The last REST version of the previous RC (exclusive lower bound). */
  restAfter: string;
  /** The last REST version in this RC (inclusive upper bound). */
  restThrough: string;
  /** Git ref (tag or commit) at which this RC's `WHATS_NEW.md` is read. */
  whatsNewRef: string;
}

/** The whole of `releases.json`. */
export interface Manifest {
  /** GitHub repository URL; issue, milestone and file links hang off it. */
  repository: string;
  /** Closed RCs, oldest first. */
  releases: Release[];
}

/** One `## [x.y.z] - date` section of the REST changelog. */
export interface ChangelogSection {
  /** The REST version, e.g. `1.263.0`. */
  version: string;
  /** The release date as written (`YYYY-MM-DD`), or `''` when the heading has none. */
  date: string;
  /** Everything under the heading, up to the next version heading. */
  body: string;
}

/** The parts of a What's new document a post uses. */
export interface WhatsNew {
  /** The `# …` title, e.g. `Apiome 08-2026 RC5`. */
  title: string;
  /** From the first `## ` section up to the `---` rule that ends the notes. */
  body: string;
}

/** Where a relative link in a source file should point once it sits in a post. */
export interface LinkContext {
  /** Repository-relative directory of the source file the markdown came from. */
  sourceDir: string;
  /** GitHub repository URL. */
  repository: string;
  /** Repository-relative path of a site page → its route on the site (e.g. `/build/axis-score`). */
  siteRoutes: Map<string, string>;
}

/* -------------------------------------------------------------------------
   Versions
   ------------------------------------------------------------------------- */

/**
 * Compare two dotted versions numerically (`1.212.0` < `1.215.1` < `1.263.0`).
 *
 * @param a First version.
 * @param b Second version.
 * @returns Negative, zero or positive, like any comparator.
 */
export function compareVersions(a: string, b: string): number {
  const left = a.split('.').map(Number);
  const right = b.split('.').map(Number);
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/* -------------------------------------------------------------------------
   Parsing
   ------------------------------------------------------------------------- */

const VERSION_HEADING = /^## \[([^\]]+)\](?:\s*-\s*(\S+))?\s*$/;

/**
 * Split the REST changelog into its version sections.
 *
 * A `## [Unreleased]` section, if one is ever added, is skipped: it has no version to place.
 *
 * @param markdown The whole of `CHANGELOG.md`.
 * @returns The sections, in file order (newest first).
 */
export function parseChangelog(markdown: string): ChangelogSection[] {
  const sections: ChangelogSection[] = [];
  let current: {version: string; date: string; lines: string[]} | null = null;
  let inFence = false;

  const flush = () => {
    if (current && /^\d+(\.\d+)*$/.test(current.version)) {
      sections.push({version: current.version, date: current.date, body: current.lines.join('\n').trim()});
    }
  };

  for (const line of markdown.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    const heading = inFence ? null : VERSION_HEADING.exec(line);
    if (heading) {
      flush();
      current = {version: heading[1], date: heading[2] ?? '', lines: []};
    } else if (current) {
      current.lines.push(line);
    }
  }
  flush();
  return sections;
}

/**
 * The sections whose version lies in `(after, through]`; either bound may be omitted.
 *
 * @param sections Parsed changelog sections.
 * @param after Exclusive lower bound, or `undefined` for none.
 * @param through Inclusive upper bound, or `undefined` for none.
 * @returns The matching sections, newest first.
 */
export function sectionsInRange(
  sections: ChangelogSection[],
  after: string | undefined,
  through: string | undefined,
): ChangelogSection[] {
  return sections
    .filter((section) => after === undefined || compareVersions(section.version, after) > 0)
    .filter((section) => through === undefined || compareVersions(section.version, through) <= 0)
    .sort((a, b) => compareVersions(b.version, a.version));
}

/**
 * Pull the notes out of a What's new document.
 *
 * The feed opens with a `# Apiome <month> <RC>` title and an intro paragraph, and closes with
 * links to videos and a feedback section after a `---` rule. Only the sections in between —
 * *Features/Improvements*, *Bug Fixes* — are release notes.
 *
 * @param markdown The whole of `WHATS_NEW.md`.
 * @returns The title and the notes; the body is `''` when the document has no `## ` section.
 */
export function parseWhatsNew(markdown: string): WhatsNew {
  const lines = markdown.split('\n');
  const title = (lines.find((line) => /^# /.test(line)) ?? '').replace(/^# /, '').trim();
  const start = lines.findIndex((line) => /^## /.test(line));
  if (start === -1) return {title, body: ''};
  const end = lines.findIndex((line, index) => index > start && /^-{3,}\s*$/.test(line));
  return {title, body: lines.slice(start, end === -1 ? undefined : end).join('\n').trim()};
}

/* -------------------------------------------------------------------------
   Rewriting markdown for a post
   ------------------------------------------------------------------------- */

/**
 * Apply `transform` to every line outside fenced code blocks; fenced lines pass through.
 *
 * @param markdown Source markdown.
 * @param transform Called with each prose line.
 * @returns The rewritten markdown.
 */
function mapProseLines(markdown: string, transform: (line: string) => string): string {
  let inFence = false;
  return markdown
    .split('\n')
    .map((line) => {
      if (/^\s*(```|~~~)/.test(line)) {
        inFence = !inFence;
        return line;
      }
      return inFence ? line : transform(line);
    })
    .join('\n');
}

/**
 * Apply `transform` to the parts of a line outside inline code spans.
 *
 * @param line One line of prose.
 * @param transform Called with each run of text between code spans.
 * @returns The rewritten line.
 */
function mapOutsideCode(line: string, transform: (text: string) => string): string {
  return line
    .split(/(`+[^`]*`+)/)
    .map((part, index) => (index % 2 === 1 ? part : transform(part)))
    .join('');
}

/**
 * Push every heading down `levels` levels (`### Added` → `#### Added`), capped at `######`.
 *
 * @param markdown Source markdown.
 * @param levels How many levels to demote by.
 * @returns The markdown with its headings demoted; code blocks untouched.
 */
export function demoteHeadings(markdown: string, levels: number): string {
  return mapProseLines(markdown, (line) =>
    line.replace(/^(#{1,6})(?=\s)/, (hashes) => '#'.repeat(Math.min(6, hashes.length + levels))),
  );
}

/**
 * Turn bare issue references (`#5628`, `(#5628, DOCS-1.11)`) into links to the issue.
 *
 * References inside code, already-linked references (`[#5628](…)`) and URL fragments
 * (`page#12`) are left alone.
 *
 * @param markdown Source markdown.
 * @param repository GitHub repository URL.
 * @returns The markdown with issue links.
 */
export function linkIssues(markdown: string, repository: string): string {
  return mapProseLines(markdown, (line) =>
    mapOutsideCode(line, (text) =>
      text.replace(
        /(^|[\s(,;:])#(\d+)\b(?!\]|\()/g,
        (_match, lead: string, issue: string) => `${lead}[#${issue}](${repository}/issues/${issue})`,
      ),
    ),
  );
}

/**
 * The site route of a page under `apiome-docs/docs/`, honouring an absolute `slug`.
 *
 * @param relPage Path relative to the docs directory, e.g. `build/lint-rules.md`.
 * @param source The page's source, read for a `slug:` in its front matter.
 * @returns The route with a leading slash, e.g. `/build/lint-rules`.
 */
export function siteRoute(relPage: string, source: string): string {
  const frontMatter = /^---\n([\s\S]*?)\n---/.exec(source)?.[1] ?? '';
  const slug = /^slug:\s*['"]?([^'"\n]+?)['"]?\s*$/m.exec(frontMatter)?.[1];
  if (slug && slug.startsWith('/')) return slug;
  return `/${relPage.replace(/\.mdx?$/, '').replace(/(^|\/)index$/, '')}`;
}

/**
 * Map every page of the docs site to its route, keyed by repository-relative path.
 *
 * @param root Repository root.
 * @param docsDir Repository-relative docs directory.
 * @returns Path → route, e.g. `apiome-docs/docs/build/axis-score.md` → `/build/axis-score`.
 */
export function collectSiteRoutes(root: string, docsDir: string): Map<string, string> {
  const routes = new Map<string, string>();
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(path.join(root, dir), {withFileTypes: true})) {
      const rel = path.posix.join(dir, entry.name);
      if (entry.isDirectory()) walk(rel);
      else if (/\.mdx?$/.test(entry.name)) {
        const source = fs.readFileSync(path.join(root, rel), 'utf8');
        routes.set(rel, siteRoute(path.posix.relative(docsDir, rel), source));
      }
    }
  };
  if (fs.existsSync(path.join(root, docsDir))) walk(docsDir);
  return routes;
}

/**
 * Resolve one relative link target to where it should point from a post.
 *
 * - a page of the docs site → its route (the site build then checks it);
 * - `docs/guide/<page>.md`, the folder the guide moved out of → the page of that name on the site;
 * - any other repository file → the file on GitHub.
 *
 * @param target The link target as written, e.g. `../docs/guide/mock-callbacks.md#setup`.
 * @param context Where the markdown came from and what the site holds.
 * @returns The rewritten target.
 */
export function resolveLink(target: string, context: LinkContext): string {
  const [file, anchor] = target.split('#', 2);
  const suffix = anchor ? `#${anchor}` : '';
  const repoPath = path.posix.normalize(path.posix.join(context.sourceDir, file));

  const direct = context.siteRoutes.get(repoPath);
  if (direct) return `${direct}${suffix}`;

  const legacy = /^docs\/guide\/([^/]+)\.mdx?$/.exec(repoPath);
  if (legacy) {
    for (const [page, route] of context.siteRoutes) {
      if (path.posix.basename(page).replace(/\.mdx?$/, '') === legacy[1]) return `${route}${suffix}`;
    }
  }
  return `${context.repository}/blob/main/${repoPath}${suffix}`;
}

/**
 * Rewrite every relative markdown link (`[text](../docs/x.md)`) with {@link resolveLink}.
 *
 * Absolute URLs, site-absolute paths (`/build`) and in-page anchors (`#x`) are left alone.
 *
 * @param markdown Source markdown.
 * @param context Where the markdown came from and what the site holds.
 * @returns The markdown with its relative links rewritten.
 */
export function rewriteRelativeLinks(markdown: string, context: LinkContext): string {
  return mapProseLines(markdown, (line) =>
    mapOutsideCode(line, (text) =>
      text.replace(/\]\(([^)\s]+)\)/g, (match, target: string) =>
        /^([a-z][a-z0-9+.-]*:|\/|#)/i.test(target) ? match : `](${resolveLink(target, context)})`,
      ),
    ),
  );
}

/**
 * Prepare markdown from a source file for a post: links, issue references, heading levels.
 *
 * @param markdown Source markdown.
 * @param context Where it came from (for relative links).
 * @param levels How many levels to demote its headings by.
 * @returns Markdown ready to embed.
 */
export function prepareMarkdown(markdown: string, context: LinkContext, levels: number): string {
  return demoteHeadings(linkIssues(rewriteRelativeLinks(markdown, context), context.repository), levels);
}

/* -------------------------------------------------------------------------
   Rendering posts
   ------------------------------------------------------------------------- */

/** Everything {@link renderPost} needs to write one post. */
export interface PostInput {
  /** URL slug under `/release-notes/`, e.g. `rc4` or `unreleased`. */
  slug: string;
  /** Post title. */
  title: string;
  /** One-line summary for the front matter (lists and search). */
  description: string;
  /** Post date: `YYYY-MM-DD` or an ISO timestamp. */
  date: string;
  /** The opening paragraph, shown on the release-notes index above the fold. */
  intro: string;
  /** The What's new notes, or `null` when there are none for this post. */
  whatsNew: WhatsNew | null;
  /** The REST changelog sections, newest first. */
  rest: ChangelogSection[];
  /** Context for rewriting links in the What's new notes. */
  whatsNewLinks: LinkContext;
  /** Context for rewriting links in the changelog. */
  changelogLinks: LinkContext;
}

/**
 * Render one release-notes post (CommonMark, so changelog text needs no MDX escaping).
 *
 * @param input The post's metadata and content.
 * @returns The file's contents.
 */
export function renderPost(input: PostInput): string {
  const quote = (value: string) => JSON.stringify(value);
  const parts: string[] = [
    '---',
    `slug: ${input.slug}`,
    `title: ${quote(input.title)}`,
    `description: ${quote(input.description)}`,
    `date: ${input.date}`,
    'authors: [apiome]',
    '---',
    '',
    '<!-- Generated by scripts/gen-release-notes.ts (DOCS-1.12) — edit the sources, not this file. -->',
    '',
    input.intro,
    '',
    '<!-- truncate -->',
    '',
    "## What's new in the app",
    '',
  ];

  if (input.whatsNew && input.whatsNew.body) {
    parts.push(`From the in-app **What's new** for *${input.whatsNew.title}*.`, '');
    parts.push(prepareMarkdown(input.whatsNew.body, input.whatsNewLinks, 1), '');
  } else {
    parts.push('Nothing yet: the in-app notes for this release have not been written.', '');
  }

  parts.push('## REST API', '');
  if (input.rest.length === 0) {
    parts.push('No REST API changes.', '');
  }
  for (const section of input.rest) {
    parts.push(`### ${section.version}${section.date ? ` — ${section.date}` : ''}`, '');
    parts.push(prepareMarkdown(section.body, input.changelogLinks, 1), '');
  }
  return `${parts.join('\n').trimEnd()}\n`;
}

/**
 * A sentence naming the REST versions a post covers.
 *
 * @param rest The sections, newest first.
 * @returns E.g. `REST API 1.215.1 to 1.263.0 (32 versions)`, or a sentence saying there are none.
 */
function restSpan(rest: ChangelogSection[]): string {
  if (rest.length === 0) return 'no REST API changes';
  const newest = rest[0].version;
  const oldest = rest[rest.length - 1].version;
  if (rest.length === 1) return `REST API ${newest}`;
  return `REST API ${oldest} to ${newest} (${rest.length} versions)`;
}

/** Inputs shared by both kinds of post. */
export interface Sources {
  manifest: Manifest;
  sections: ChangelogSection[];
  siteRoutes: Map<string, string>;
}

/**
 * Build the post of a closed RC.
 *
 * @param release The RC, from the manifest.
 * @param whatsNew Its What's new, read at `release.whatsNewRef`.
 * @param sources Manifest, changelog and site routes.
 * @returns The post's contents.
 */
export function renderReleasePost(release: Release, whatsNew: WhatsNew | null, sources: Sources): string {
  const {repository} = sources.manifest;
  const rest = sectionsInRange(sources.sections, release.restAfter, release.restThrough);
  const milestone = release.milestone
    ? ` See [every issue in the ${release.name} milestone](${repository}/milestone/${release.milestone}?closed=1).`
    : '';
  return renderPost({
    slug: release.name.toLowerCase(),
    title: `Apiome ${release.name}`,
    description: `Everything in Apiome ${release.name}: the app's What's new and the REST API changes.`,
    date: release.closed,
    intro: `${release.name} closed on ${release.closed}. It brings the app notes below and ${restSpan(rest)}.${milestone}`,
    whatsNew,
    rest,
    whatsNewLinks: {sourceDir: path.posix.dirname(PATHS.whatsNew), repository, siteRoutes: sources.siteRoutes},
    changelogLinks: {sourceDir: path.posix.dirname(PATHS.changelog), repository, siteRoutes: sources.siteRoutes},
  });
}

/**
 * Build the rolling post for everything after the last closed RC.
 *
 * The current What's new is included unless its title names an RC that has already closed
 * (the gap between tagging an RC and starting the next one's notes).
 *
 * @param whatsNew The current What's new.
 * @param sources Manifest, changelog and site routes.
 * @param now When the post is generated; it is dated then so it sorts first.
 * @returns The post's contents.
 */
export function renderUnreleasedPost(whatsNew: WhatsNew | null, sources: Sources, now: Date): string {
  const {repository, releases} = sources.manifest;
  const last = releases[releases.length - 1];
  const rest = sectionsInRange(sources.sections, last?.restThrough, undefined);
  const closedNames = new Set(releases.map((release) => release.name));
  const current =
    whatsNew && !whatsNew.title.split(/\s+/).some((word) => closedNames.has(word)) ? whatsNew : null;
  const since = last ? `since ${last.name}` : 'so far';
  return renderPost({
    slug: 'unreleased',
    title: 'Unreleased',
    description: `What has landed on main ${since} and will ship in the next release.`,
    date: now.toISOString(),
    intro:
      `What has landed on \`main\` ${since}, regenerated on every build of the site: ` +
      `the in-progress app notes and ${restSpan(rest)}.`,
    whatsNew: current,
    rest,
    whatsNewLinks: {sourceDir: path.posix.dirname(PATHS.whatsNew), repository, siteRoutes: sources.siteRoutes},
    changelogLinks: {sourceDir: path.posix.dirname(PATHS.changelog), repository, siteRoutes: sources.siteRoutes},
  });
}

/**
 * Record a newly closed RC: its REST range runs from the previous RC to the newest version.
 *
 * @param manifest The manifest to extend (not mutated).
 * @param sections The changelog at the RC's tag.
 * @param options The RC's name, git ref, milestone number and close date.
 * @returns The new manifest and the release that was added.
 * @throws When the RC is already recorded, or the changelog has no version past the last RC.
 */
export function closeRelease(
  manifest: Manifest,
  sections: ChangelogSection[],
  options: {name: string; ref: string; milestone?: number; closed: string},
): {manifest: Manifest; release: Release} {
  if (manifest.releases.some((release) => release.name === options.name)) {
    throw new Error(`${options.name} is already in releases.json`);
  }
  const last = manifest.releases[manifest.releases.length - 1];
  const newest = [...sections].sort((a, b) => compareVersions(b.version, a.version))[0];
  if (!newest || (last && compareVersions(newest.version, last.restThrough) <= 0)) {
    throw new Error(`no REST version after ${last?.restThrough ?? 'the start'} to close ${options.name} at`);
  }
  const release: Release = {
    name: options.name,
    ...(options.milestone ? {milestone: options.milestone} : {}),
    closed: options.closed,
    restAfter: last?.restThrough ?? '0.0.0',
    restThrough: newest.version,
    whatsNewRef: options.ref,
  };
  return {manifest: {...manifest, releases: [...manifest.releases, release]}, release};
}

/* -------------------------------------------------------------------------
   CLI
   ------------------------------------------------------------------------- */

/**
 * Read a repository file at a git ref.
 *
 * @param root Repository root.
 * @param ref Tag, branch or commit.
 * @param file Repository-relative path.
 * @returns The file's contents.
 */
function readAtRef(root: string, ref: string, file: string): string {
  return execFileSync('git', ['show', `${ref}:${file}`], {cwd: root, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024});
}

/**
 * Parse `--flag value` pairs.
 *
 * @param argv Arguments after the script name.
 * @returns Flag name (without dashes) → value.
 * @throws On a flag without a value or an unknown flag.
 */
export function parseArgs(argv: string[]): Record<string, string> {
  const known = new Set(['close', 'ref', 'milestone', 'date', 'release', 'root']);
  const args: Record<string, string> = {};
  for (let i = 0; i < argv.length; i += 2) {
    const name = argv[i].replace(/^--/, '');
    if (!known.has(name) || argv[i + 1] === undefined) {
      throw new Error(`usage: gen-release-notes.ts [--close RC6 [--ref RC6] [--milestone 6] [--date YYYY-MM-DD]] [--release RC4]`);
    }
    args[name] = argv[i + 1];
  }
  return args;
}

/**
 * Run the generator.
 *
 * @param argv Arguments after the script name.
 * @returns The repository-relative paths written.
 */
export function main(argv: string[]): string[] {
  const args = parseArgs(argv);
  const root = args.root ? path.resolve(args.root) : REPO_ROOT;
  const read = (file: string) => fs.readFileSync(path.join(root, file), 'utf8');
  const write = (file: string, contents: string) => {
    fs.writeFileSync(path.join(root, file), contents);
    return file;
  };

  let manifest: Manifest = JSON.parse(read(PATHS.manifest));
  const sections = parseChangelog(read(PATHS.changelog));
  const siteRoutes = collectSiteRoutes(root, PATHS.docsDir);
  const written: string[] = [];

  if (args.close) {
    const closed = closeRelease(manifest, sections, {
      name: args.close,
      ref: args.ref ?? args.close,
      milestone: args.milestone ? Number(args.milestone) : undefined,
      closed: args.date ?? new Date().toISOString().slice(0, 10),
    });
    manifest = closed.manifest;
    written.push(write(PATHS.manifest, `${JSON.stringify(manifest, null, 2)}\n`));
    args.release = closed.release.name;
  }

  if (args.release) {
    const release = manifest.releases.find((candidate) => candidate.name === args.release);
    if (!release) throw new Error(`${args.release} is not in releases.json`);
    const whatsNew = parseWhatsNew(readAtRef(root, release.whatsNewRef, PATHS.whatsNew));
    const post = renderReleasePost(release, whatsNew, {manifest, sections, siteRoutes});
    written.push(write(path.posix.join(PATHS.outDir, `${release.name.toLowerCase()}.md`), post));
  }

  const whatsNew = fs.existsSync(path.join(root, PATHS.whatsNew)) ? parseWhatsNew(read(PATHS.whatsNew)) : null;
  const unreleased = renderUnreleasedPost(whatsNew, {manifest, sections, siteRoutes}, new Date());
  written.push(write(path.posix.join(PATHS.outDir, UNRELEASED_FILE), unreleased));
  return written;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    for (const file of main(process.argv.slice(2))) console.log(`release notes: wrote ${file}`);
  } catch (error) {
    console.error(`gen-release-notes: ${(error as Error).message}`);
    process.exit(1);
  }
}
