/**
 * The release-notes generator (`scripts/gen-release-notes.ts`, DOCS-1.12, #5629): parsing the
 * REST changelog and the What's new feed, rewriting their markdown for a post, and the posts
 * and manifest it writes.
 */
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

import {
  closeRelease,
  collectSiteRoutes,
  compareVersions,
  demoteHeadings,
  linkIssues,
  main,
  parseArgs,
  parseChangelog,
  parseWhatsNew,
  renderReleasePost,
  renderUnreleasedPost,
  resolveLink,
  rewriteRelativeLinks,
  sectionsInRange,
  siteRoute,
} from '../../scripts/gen-release-notes.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const siteDir = path.join(here, '..');
const REPO = 'https://github.com/apiome/apiome';

const CHANGELOG = `# Changelog

Intro text.

## [1.3.0] - 2026-09-02

### Added
- **Thing (#12, DOCS-1.1)**: see [the guide](../docs/guide/axis-score.md#weights).

  \`\`\`markdown
  ## [9.9.9] - not a version heading, it is in a fence
  \`\`\`

## [1.2.1] - 2026-08-20

### Fixed
- Fix for #11.

## [1.2.0] - 2026-08-01

### Changed
- Old.
`;

const WHATS_NEW = `# Apiome 08-2026 RC5

We continue to improve the platform.

---

## Features/Improvements

- New thing (#40)

## Bug Fixes

- Fixed a thing

---

View our YouTube channel [here](https://www.youtube.com/).

## Feedback
`;

const siteRoutes = new Map([
  ['apiome-docs/docs/build/axis-score.md', '/build/axis-score'],
  ['apiome-docs/docs/getting-started/index.mdx', '/'],
]);
const changelogLinks = {sourceDir: 'apiome-rest', repository: REPO, siteRoutes};

const manifest = {
  repository: REPO,
  releases: [
    {name: 'RC4', milestone: 1, closed: '2026-08-20', restAfter: '1.2.0', restThrough: '1.2.1', whatsNewRef: 'RC4'},
  ],
};

test('versions compare numerically, not as strings', () => {
  assert.ok(compareVersions('1.212.0', '1.215.1') < 0);
  assert.ok(compareVersions('1.99.0', '1.100.0') < 0);
  assert.equal(compareVersions('1.2', '1.2.0'), 0);
  assert.ok(compareVersions('2.0.0', '1.999.9') > 0);
});

test('the changelog splits into version sections, ignoring headings inside code fences', () => {
  const sections = parseChangelog(CHANGELOG);
  assert.deepEqual(
    sections.map((section) => [section.version, section.date]),
    [
      ['1.3.0', '2026-09-02'],
      ['1.2.1', '2026-08-20'],
      ['1.2.0', '2026-08-01'],
    ],
  );
  assert.match(sections[0].body, /^### Added/);
  assert.match(sections[0].body, /9\.9\.9/);
  assert.doesNotMatch(sections[0].body, /1\.2\.1/);
});

test('an [Unreleased] changelog heading is skipped, not mistaken for a version', () => {
  const sections = parseChangelog('## [Unreleased]\n\n- wip\n\n## [1.0.0] - 2026-01-01\n\n- one\n');
  assert.deepEqual(sections.map((section) => section.version), ['1.0.0']);
});

test('a range is (after, through], newest first, either bound optional', () => {
  const sections = parseChangelog(CHANGELOG);
  assert.deepEqual(sectionsInRange(sections, '1.2.0', '1.2.1').map((s) => s.version), ['1.2.1']);
  assert.deepEqual(sectionsInRange(sections, '1.2.1', undefined).map((s) => s.version), ['1.3.0']);
  assert.deepEqual(sectionsInRange(sections, undefined, '1.2.0').map((s) => s.version), ['1.2.0']);
});

test("What's new keeps only the notes between the intro and the closing rule", () => {
  const notes = parseWhatsNew(WHATS_NEW);
  assert.equal(notes.title, 'Apiome 08-2026 RC5');
  assert.match(notes.body, /^## Features\/Improvements/);
  assert.match(notes.body, /## Bug Fixes\n\n- Fixed a thing$/);
  assert.doesNotMatch(notes.body, /YouTube|Feedback|continue to improve/);
});

test("a What's new without sections has an empty body", () => {
  assert.deepEqual(parseWhatsNew('# Apiome RC9\n\nComing soon.\n'), {title: 'Apiome RC9', body: ''});
});

test('headings are demoted outside code fences only, and never past h6', () => {
  const source = '## A\n\n```\n## not a heading\n```\n\n###### Deep';
  assert.equal(demoteHeadings(source, 1), '### A\n\n```\n## not a heading\n```\n\n###### Deep');
});

test('bare issue references become issue links; code, links and fragments are left alone', () => {
  const source = [
    '- Thing (#12, DOCS-1.1) and #13.',
    '- Already [#14](https://example.com) linked; `#15` in code; see page#16.',
    '```',
    '#17 in a fence',
    '```',
  ].join('\n');
  const linked = linkIssues(source, REPO);
  assert.match(linked, /\(\[#12\]\(https:\/\/github\.com\/apiome\/apiome\/issues\/12\), DOCS-1\.1\)/);
  assert.match(linked, / \[#13\]\(https:\/\/github\.com\/apiome\/apiome\/issues\/13\)\./);
  assert.match(linked, /Already \[#14\]\(https:\/\/example\.com\)/);
  assert.match(linked, /`#15`/);
  assert.match(linked, /page#16/);
  assert.match(linked, /\n#17 in a fence\n/);
});

test('a site page links to its route, honouring an absolute slug', () => {
  assert.equal(siteRoute('build/axis-score.md', '---\ntitle: x\n---\n'), '/build/axis-score');
  assert.equal(siteRoute('build/index.mdx', '---\ntitle: x\n---\n'), '/build');
  assert.equal(siteRoute('getting-started/index.mdx', '---\nslug: /\n---\n'), '/');
});

test('relative links resolve to the site, the moved guide, or GitHub', () => {
  assert.equal(resolveLink('../apiome-docs/docs/build/axis-score.md', changelogLinks), '/build/axis-score');
  assert.equal(resolveLink('../docs/guide/axis-score.md#weights', changelogLinks), '/build/axis-score#weights');
  assert.equal(resolveLink('./docs/contract_suite.md', changelogLinks), `${REPO}/blob/main/apiome-rest/docs/contract_suite.md`);
});

test('only relative links are rewritten', () => {
  const source = '[a](./docs/x.md) [b](https://example.com) [c](/build) [d](#here) `[e](./code.md)`';
  assert.equal(
    rewriteRelativeLinks(source, changelogLinks),
    `[a](${REPO}/blob/main/apiome-rest/docs/x.md) [b](https://example.com) [c](/build) [d](#here) \`[e](./code.md)\``,
  );
});

test("an RC's post carries its What's new and only its own REST versions", () => {
  const post = renderReleasePost(manifest.releases[0], parseWhatsNew(WHATS_NEW), {
    manifest,
    sections: parseChangelog(CHANGELOG),
    siteRoutes,
  });
  assert.match(post, /^---\nslug: rc4\ntitle: "Apiome RC4"\n/);
  assert.match(post, /\ndate: 2026-08-20\n/);
  assert.match(post, /milestone\/1\?closed=1/);
  assert.match(post, /<!-- truncate -->/);
  assert.match(post, /\n### Features\/Improvements\n/);
  assert.match(post, /\n### 1\.2\.1 — 2026-08-20\n\n#### Fixed\n/);
  assert.match(post, /issues\/11\)/);
  assert.doesNotMatch(post, /### 1\.3\.0|### 1\.2\.0/);
});

test('the Unreleased post covers everything after the last RC, dated when generated', () => {
  const now = new Date('2026-10-07T12:00:00Z');
  const post = renderUnreleasedPost(parseWhatsNew(WHATS_NEW), {manifest, sections: parseChangelog(CHANGELOG), siteRoutes}, now);
  assert.match(post, /^---\nslug: unreleased\n/);
  assert.match(post, /\ndate: 2026-10-07T12:00:00\.000Z\n/);
  assert.match(post, /since RC4/);
  assert.match(post, /What's new\*\* for \*Apiome 08-2026 RC5\*/);
  assert.match(post, /### 1\.3\.0 — 2026-09-02/);
  assert.match(post, /\[the guide\]\(\/build\/axis-score#weights\)/);
  assert.doesNotMatch(post, /### 1\.2\.1/);
});

test("the Unreleased post drops a What's new that still names a closed RC", () => {
  const stale = parseWhatsNew(WHATS_NEW.replace('RC5', 'RC4'));
  const post = renderUnreleasedPost(stale, {manifest, sections: parseChangelog(CHANGELOG), siteRoutes}, new Date());
  assert.match(post, /have not been written/);
  assert.doesNotMatch(post, /Features\/Improvements/);
});

test('closing an RC records its REST range from the last RC to the newest version', () => {
  const {manifest: next, release} = closeRelease(manifest, parseChangelog(CHANGELOG), {
    name: 'RC5',
    ref: 'RC5',
    milestone: 2,
    closed: '2026-10-31',
  });
  assert.deepEqual(release, {
    name: 'RC5',
    milestone: 2,
    closed: '2026-10-31',
    restAfter: '1.2.1',
    restThrough: '1.3.0',
    whatsNewRef: 'RC5',
  });
  assert.equal(next.releases.length, 2);
  assert.equal(manifest.releases.length, 1, 'the input manifest is not mutated');
});

test('closing an RC twice, or with no new REST version, is refused', () => {
  const sections = parseChangelog(CHANGELOG);
  assert.throws(() => closeRelease(manifest, sections, {name: 'RC4', ref: 'RC4', closed: '2026-08-20'}), /already/);
  const upToDate = {...manifest, releases: [{...manifest.releases[0], restThrough: '1.3.0'}]};
  assert.throws(() => closeRelease(upToDate, sections, {name: 'RC5', ref: 'RC5', closed: '2026-10-31'}), /no REST version/);
});

test('unknown flags and flags without values are refused', () => {
  assert.deepEqual(parseArgs(['--close', 'RC6', '--milestone', '6']), {close: 'RC6', milestone: '6'});
  assert.throws(() => parseArgs(['--bogus', 'x']), /usage/);
  assert.throws(() => parseArgs(['--close']), /usage/);
});

test('the CLI closes an RC end to end in a repository, reading What’s new at the tag', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'release-notes-'));
  const put = (file, contents) => {
    fs.mkdirSync(path.dirname(path.join(root, file)), {recursive: true});
    fs.writeFileSync(path.join(root, file), contents);
  };
  const git = (...args) =>
    execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', ...args], {cwd: root, stdio: 'pipe'});
  try {
    put('apiome-rest/CHANGELOG.md', CHANGELOG);
    put('apiome-ui/public/WHATS_NEW.md', WHATS_NEW);
    put('apiome-docs/release-notes/releases.json', JSON.stringify(manifest));
    put('apiome-docs/docs/build/axis-score.md', '---\ntitle: Axis\n---\n');
    git('init', '-q');
    git('add', '-A');
    git('commit', '-qm', 'rc5');
    git('tag', 'RC5');
    // The next RC's notes start after the tag; the RC5 post must still show RC5's.
    put('apiome-ui/public/WHATS_NEW.md', WHATS_NEW.replace('RC5', 'RC6').replace('New thing', 'Newer thing'));

    const written = main(['--root', root, '--close', 'RC5', '--milestone', '2', '--date', '2026-10-31']);
    assert.deepEqual(written, [
      'apiome-docs/release-notes/releases.json',
      'apiome-docs/release-notes/rc5.md',
      'apiome-docs/release-notes/unreleased.md',
    ]);
    const rc5 = fs.readFileSync(path.join(root, 'apiome-docs/release-notes/rc5.md'), 'utf8');
    assert.match(rc5, /- New thing/);
    assert.match(rc5, /### 1\.3\.0/);
    const unreleased = fs.readFileSync(path.join(root, 'apiome-docs/release-notes/unreleased.md'), 'utf8');
    assert.match(unreleased, /- Newer thing/);
    assert.match(unreleased, /no REST API changes/);
    const recorded = JSON.parse(fs.readFileSync(path.join(root, 'apiome-docs/release-notes/releases.json'), 'utf8'));
    assert.equal(recorded.releases[1].restThrough, '1.3.0');
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
  }
});

test('the committed manifest is contiguous and every closed RC has its post', () => {
  const committed = JSON.parse(fs.readFileSync(path.join(siteDir, 'release-notes', 'releases.json'), 'utf8'));
  committed.releases.forEach((release, index) => {
    assert.ok(compareVersions(release.restAfter, release.restThrough) < 0, `${release.name}: empty REST range`);
    if (index > 0) assert.equal(release.restAfter, committed.releases[index - 1].restThrough, `${release.name}: gap`);
    const post = path.join(siteDir, 'release-notes', `${release.name.toLowerCase()}.md`);
    assert.ok(fs.existsSync(post), `${release.name}: run node scripts/gen-release-notes.ts --release ${release.name}`);
  });
});

test('the site routes cover the real docs tree', () => {
  const routes = collectSiteRoutes(path.join(siteDir, '..'), 'apiome-docs/docs');
  assert.equal(routes.get('apiome-docs/docs/getting-started/index.mdx'), '/');
  assert.equal(routes.get('apiome-docs/docs/build/axis-score.md'), '/build/axis-score');
});
