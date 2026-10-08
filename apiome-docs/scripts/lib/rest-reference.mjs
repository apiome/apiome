/**
 * The REST reference drift check — DOCS-1.11 (#5628).
 *
 * `apiome-rest/scripts/generate_rest_reference_docs.py` writes `docs/reference/rest/` from
 * `apiome-rest/openapi.yaml` and records the document's SHA-256 in the index page's front matter
 * (`openapi_sha256`). `yarn docs:check` compares that hash with the file on disk, so the site build
 * fails whenever the OpenAPI document changed and the reference was not regenerated — the case
 * AGENTS.md's "bump the OpenAPI version on every REST change" rule makes routine.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import matter from 'gray-matter';

/** The command that regenerates the reference, named in the failure. */
export const REST_REGENERATE_COMMAND = 'cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py';

/**
 * SHA-256 of a file's bytes, as lower-case hex.
 *
 * @param {string} file - Absolute path.
 * @returns {string} 64 hex characters.
 */
export function sha256File(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

/**
 * Check that the generated REST reference was produced from the current OpenAPI document.
 *
 * @param {object} options - Inputs.
 * @param {string} options.docsDir - Absolute path of `apiome-docs/docs`.
 * @param {string} options.openapiFile - Absolute path of `apiome-rest/openapi.yaml`.
 * @returns {string[]} Problems: the index page is missing, has no hash, or its hash is not the
 *   document's. Empty when the OpenAPI document itself is absent (nothing to compare).
 */
export function checkRestReference({docsDir, openapiFile}) {
  if (!fs.existsSync(openapiFile)) return [];
  const index = path.join(docsDir, 'reference', 'rest', 'index.mdx');
  const label = 'docs/reference/rest/index.mdx';
  if (!fs.existsSync(index)) {
    return [`${label} is missing; generate the REST reference: \`${REST_REGENERATE_COMMAND}\``];
  }
  const recorded = matter(fs.readFileSync(index, 'utf8')).data.openapi_sha256;
  if (typeof recorded !== 'string' || !/^[0-9a-f]{64}$/.test(recorded)) {
    return [`${label} has no \`openapi_sha256\` in its front matter; regenerate it: \`${REST_REGENERATE_COMMAND}\``];
  }
  if (recorded !== sha256File(openapiFile)) {
    return [
      `${label} was generated from an older apiome-rest/openapi.yaml; regenerate it: \`${REST_REGENERATE_COMMAND}\``,
    ];
  }
  return [];
}
