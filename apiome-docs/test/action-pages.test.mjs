import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {describe, it} from 'node:test';
import {fileURLToPath} from 'node:url';

import {ACTION_PAGES, ACTION_PAGES_DIR, REPO_BLOB_URL, renderActionPage, rewriteLink} from '../scripts/lib/action-pages.mjs';

const REPO_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

describe('rewriteLink', () => {
  it('leaves absolute URLs and same-page anchors alone', () => {
    assert.equal(rewriteLink('https://example.com/x', 'diff-action/README.md'), 'https://example.com/x');
    assert.equal(rewriteLink('#usage', 'diff-action/README.md'), '#usage');
  });
  it('points a link into the docs tree at the page, relative to Reference → CI', () => {
    assert.equal(
      rewriteLink('../apiome-docs/docs/reference/mock-runtime/mock-bundle-format.md#fields', 'mock-action/README.md'),
      '../mock-runtime/mock-bundle-format.md#fields',
    );
    assert.equal(rewriteLink('../apiome-docs/docs/reference/ci/ci-diff-gate.md', 'diff-action/README.md'), 'ci-diff-gate.md');
  });
  it('points any other repository file at GitHub', () => {
    assert.equal(rewriteLink('recipes/.gitlab-ci.yml', 'diff-action/README.md'), `${REPO_BLOB_URL}/diff-action/recipes/.gitlab-ci.yml`);
    assert.equal(rewriteLink('../apiome-cli/README.md', 'diff-action/README.md'), `${REPO_BLOB_URL}/apiome-cli/README.md`);
  });
});

describe('renderActionPage', () => {
  const spec = {readme: 'diff-action/README.md', page: 'x.md', title: 'T', description: 'D.', position: 3};
  const page = renderActionPage(spec, '# apiome/diff-action\n\nRuns [`apiome diff`](../apiome-cli/README.md).\n\n## Usage\n');

  it('moves the title into front matter and marks the page generated', () => {
    assert.match(page, /^---\ntitle: "T"\ndescription: "D\."\nsidebar_position: 3\n/);
    assert.match(page, /generated: apiome-docs\/scripts\/sync-action-pages\.mjs from diff-action\/README\.md/);
    assert.doesNotMatch(page, /^# apiome\/diff-action/m);
  });
  it('rewrites the links and keeps the rest', () => {
    assert.match(page, new RegExp(`\\(${REPO_BLOB_URL.replace(/[/.]/g, '\\$&')}/apiome-cli/README\\.md\\)`));
    assert.match(page, /\n## Usage\n$/);
  });
});

describe('the committed action pages', () => {
  it('match their READMEs (run `yarn workspace apiome-docs sync:action-pages`)', () => {
    for (const spec of ACTION_PAGES) {
      const expected = renderActionPage(spec, fs.readFileSync(path.join(REPO_ROOT, spec.readme), 'utf8'));
      assert.equal(fs.readFileSync(path.join(REPO_ROOT, ACTION_PAGES_DIR, spec.page), 'utf8'), expected, spec.page);
    }
  });
  it('have descriptions of 14 words or fewer', () => {
    for (const spec of ACTION_PAGES) assert.ok(spec.description.split(/\s+/).length <= 14, spec.page);
  });
});
