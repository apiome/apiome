import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {afterEach, beforeEach, describe, it} from 'node:test';
import {fileURLToPath} from 'node:url';

import {
  MAX_DESCRIPTION_WORDS,
  checkDocs,
  checkFrontMatter,
  checkGroups,
  countWords,
  listPages,
} from '../scripts/lib/pages.mjs';

const SITE_DOCS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'docs');

/** The nine job groups: eight doc folders plus the release-notes blog. */
const GROUP_FOLDERS = [
  'getting-started',
  'build',
  'bring-in',
  'ship',
  'govern',
  'workspace',
  'admin',
  'reference',
];

/**
 * Build a page source with the given front matter.
 *
 * @param {Record<string, string>} fields - Front-matter keys and values.
 * @returns {string} Markdown source.
 */
function page(fields) {
  const lines = Object.entries(fields).map(([key, value]) => `${key}: ${value}`);
  return `---\n${lines.join('\n')}\n---\n\nBody.\n`;
}

describe('countWords', () => {
  it('counts whitespace-separated words', () => {
    assert.equal(countWords('one two  three\nfour'), 4);
  });
  it('treats blank and missing text as zero words', () => {
    assert.equal(countWords('   '), 0);
    assert.equal(countWords(undefined), 0);
  });
});

describe('checkFrontMatter', () => {
  it('accepts a title and a short description', () => {
    assert.deepEqual(checkFrontMatter(page({title: 'Build', description: 'Model APIs.'})), []);
  });
  it('requires a title', () => {
    assert.deepEqual(checkFrontMatter(page({description: 'Model APIs.'})), [
      'front matter needs a `title`',
    ]);
  });
  it('requires a description', () => {
    assert.deepEqual(checkFrontMatter(page({title: 'Build'})), [
      'front matter needs a `description`',
    ]);
  });
  it('reports a page with no front matter at all', () => {
    assert.equal(checkFrontMatter('# Heading\n').length, 2);
  });
  it(`allows exactly ${MAX_DESCRIPTION_WORDS} words`, () => {
    const description = Array(MAX_DESCRIPTION_WORDS).fill('word').join(' ');
    assert.deepEqual(checkFrontMatter(page({title: 'T', description})), []);
  });
  it(`rejects a description over ${MAX_DESCRIPTION_WORDS} words`, () => {
    const description = Array(MAX_DESCRIPTION_WORDS + 1).fill('word').join(' ');
    const [problem] = checkFrontMatter(page({title: 'T', description}));
    assert.match(problem, /15 words/);
  });
  it('reports invalid YAML instead of throwing', () => {
    const [problem] = checkFrontMatter('---\ntitle: [unclosed\n---\n');
    assert.match(problem, /not valid YAML/);
  });
});

describe('on a temporary docs tree', () => {
  let dir;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'apiome-docs-'));
  });
  afterEach(() => {
    fs.rmSync(dir, {recursive: true, force: true});
  });

  /**
   * Write a file under the temporary docs tree.
   *
   * @param {string} relative - Path relative to the tree root.
   * @param {string} contents - File contents.
   */
  function write(relative, contents) {
    fs.mkdirSync(path.dirname(path.join(dir, relative)), {recursive: true});
    fs.writeFileSync(path.join(dir, relative), contents);
  }

  it('listPages finds .md and .mdx recursively and skips partials', () => {
    write('a.md', '');
    write('g/b.mdx', '');
    write('g/_partial.mdx', '');
    write('g/notes.txt', '');
    assert.deepEqual(
      listPages(dir).map((p) => path.relative(dir, p)),
      ['a.md', path.join('g', 'b.mdx')],
    );
  });

  it('checkGroups wants a _category_.json and an index page per folder', () => {
    write('good/_category_.json', '{"label": "Good"}');
    write('good/index.mdx', '');
    write('bare/page.md', '');
    write('unlabelled/_category_.json', '{}');
    write('unlabelled/index.md', '');
    write('broken/_category_.json', '{');
    write('broken/index.md', '');
    const problems = checkGroups(dir);
    assert.ok(problems.includes('bare/: missing _category_.json'));
    assert.ok(problems.includes('bare/: missing index.mdx (every group needs a landing page)'));
    assert.ok(problems.includes('unlabelled/_category_.json: needs a `label`'));
    assert.ok(problems.some((p) => p.startsWith('broken/_category_.json: not valid JSON')));
    assert.ok(!problems.some((p) => p.startsWith('good/')));
  });

  it('checkDocs prefixes page problems with the relative path', () => {
    write('g/_category_.json', '{"label": "G"}');
    write('g/index.mdx', page({title: 'G'}));
    assert.deepEqual(checkDocs(dir), [
      `${path.join('g', 'index.mdx')}: front matter needs a \`description\``,
    ]);
  });
});

describe('the site itself', () => {
  it('passes every page rule', () => {
    assert.deepEqual(checkDocs(SITE_DOCS), []);
  });
  it('has the eight doc groups of the sidebar skeleton, each with an index page', () => {
    for (const folder of GROUP_FOLDERS) {
      assert.ok(fs.existsSync(path.join(SITE_DOCS, folder, 'index.mdx')), `${folder}/index.mdx`);
    }
  });
});
