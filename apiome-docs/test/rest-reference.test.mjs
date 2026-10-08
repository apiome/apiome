import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {afterEach, beforeEach, describe, it} from 'node:test';

import {checkRestReference, sha256File} from '../scripts/lib/rest-reference.mjs';

describe('checkRestReference', () => {
  let root;
  let docsDir;
  let openapiFile;

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-rest-'));
    docsDir = path.join(root, 'docs');
    fs.mkdirSync(path.join(docsDir, 'reference', 'rest'), {recursive: true});
    openapiFile = path.join(root, 'openapi.yaml');
    fs.writeFileSync(openapiFile, 'openapi: 3.1.0\n');
  });
  afterEach(() => fs.rmSync(root, {recursive: true, force: true}));

  /** Write the index page with a given front-matter hash line. */
  const writeIndex = (line) =>
    fs.writeFileSync(path.join(docsDir, 'reference', 'rest', 'index.mdx'), `---\ntitle: REST\n${line}\n---\n`);

  it('passes when the recorded hash is the document’s', () => {
    writeIndex(`openapi_sha256: ${sha256File(openapiFile)}`);
    assert.deepEqual(checkRestReference({docsDir, openapiFile}), []);
  });
  it('fails when the document changed after the reference was generated', () => {
    writeIndex(`openapi_sha256: ${sha256File(openapiFile)}`);
    fs.appendFileSync(openapiFile, 'info: {}\n');
    const [problem] = checkRestReference({docsDir, openapiFile});
    assert.match(problem, /generated from an older apiome-rest\/openapi\.yaml/);
    assert.match(problem, /generate_rest_reference_docs\.py/);
  });
  it('fails when the index is missing or carries no hash', () => {
    fs.rmSync(path.join(docsDir, 'reference', 'rest'), {recursive: true});
    assert.match(checkRestReference({docsDir, openapiFile})[0], /is missing/);
    fs.mkdirSync(path.join(docsDir, 'reference', 'rest'), {recursive: true});
    writeIndex('tags: [rest]');
    assert.match(checkRestReference({docsDir, openapiFile})[0], /no `openapi_sha256`/);
  });
  it('has nothing to compare without an OpenAPI document', () => {
    assert.deepEqual(checkRestReference({docsDir, openapiFile: path.join(root, 'absent.yaml')}), []);
  });
});
