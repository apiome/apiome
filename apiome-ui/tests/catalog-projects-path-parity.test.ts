/**
 * Catalog ↔ Projects import-path parity — COA-4.2 (#7059).
 *
 * Imports each fixture in `apiome-rest/tests/golden/path_parity/` on the **Projects** path (the
 * importer this app runs: `openApiImporter`, `extractPaths`, `buildTagTaxonomy`,
 * `resolveSelfReferences` and `resolveArazzoSources`), reduces the result to the same
 * language-neutral projection the REST suite `apiome-rest/tests/test_catalog_projects_path_parity.py`
 * builds for the **Catalog** path, and compares it with the shared `expected.json`. Both suites
 * read one file, so when both pass the two paths import every case the same way.
 *
 * Differences in how the result is stored (not in what is imported) are listed under
 * `differences` in `expected.json` and on the docs page `bring-in/import-a-spec.md` (**The same result in the catalog**).
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import { readFileSync } from 'fs';
import path from 'path';
import { parse as parseYaml } from 'yaml';

import { openApiImporter } from '../lib/importers/openapi';
import { resolveArazzoSources } from '../lib/importers/arazzo-sources';
import { extractPaths, type ParsedMediaTypeContent } from '../src/app/utils/openapi-import';
import { resolveSelfReferences } from '../src/app/utils/openapi-self-references';
import { buildTagTaxonomy } from '../src/app/utils/openapi-tag-taxonomy';

const FIXTURES = path.join(__dirname, '..', '..', 'apiome-rest', 'tests', 'golden', 'path_parity');

/** Parse one fixture file (YAML or JSON). */
function load(relative: string): any {
  return parseYaml(readFileSync(path.join(FIXTURES, relative), 'utf-8'));
}

/** Last segment of a local component `$ref`, or undefined. */
function localRefName(ref: unknown): string | undefined {
  const match = typeof ref === 'string' ? ref.match(/^#\/components\/schemas\/(.+)$/) : null;
  return match ? match[1] : undefined;
}

/** Sort an object's keys, so it compares equal to the JSON file regardless of build order. */
function sortedObject<T>(entries: [string, T][]): Record<string, T> {
  return Object.fromEntries(entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

/** Compare two strings the way Python's `sorted` does (code point order). */
function byCodePoint(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * OA3: every streamed media type with its kind and element. A class hoisted from an inline
 * element (one the source document's components do not declare) projects as `inline-object`,
 * which is what the Catalog path keeps it as.
 */
function projectStreams(doc: any) {
  const declared = new Set(Object.keys(doc?.components?.schemas ?? {}));
  const rows: Record<string, string>[] = [];
  const visit = (operation: string, message: string, content?: Record<string, ParsedMediaTypeContent>) => {
    for (const [mediaType, entry] of Object.entries(content ?? {})) {
      if (!entry.streamKind) continue;
      const name = localRefName(entry.$ref);
      const element = name ? (declared.has(name) ? name : 'inline-object') : 'inline';
      rows.push({ operation, message, mediaType, kind: entry.streamKind, element });
    }
  };
  for (const parsedPath of extractPaths(doc)) {
    for (const op of parsedPath.operations) {
      const operation = `${op.method} ${parsedPath.path}`;
      visit(operation, 'request', op.requestBody?.content);
      for (const [status, response] of Object.entries(op.responses)) {
        visit(operation, `response ${status}`, response.content);
      }
    }
  }
  return rows.sort(
    (a, b) =>
      byCodePoint(a.operation, b.operation) ||
      byCodePoint(a.message, b.message) ||
      byCodePoint(a.mediaType, b.mediaType)
  );
}

/** OA4: every operation (method, path, token as written, operationId) and the repeats. */
function projectOperations(doc: any) {
  const operations: Record<string, string | undefined>[] = [];
  const duplicates: [string, string[]][] = [];
  for (const parsedPath of extractPaths(doc)) {
    for (const op of parsedPath.operations) {
      operations.push({
        operation: `${op.method} ${parsedPath.path}`,
        token: op.httpMethod ?? op.method,
        operationId: op.operationId,
      });
    }
    if (parsedPath.duplicateMethods?.length) duplicates.push([parsedPath.path, parsedPath.duplicateMethods]);
  }
  return {
    operations: operations.sort((a, b) => byCodePoint(a.operation!, b.operation!)),
    duplicates: sortedObject(duplicates),
  };
}

/** OA5: the effective tag tree (parent / summary / kind) and each operation's tags. */
function projectTags(doc: any) {
  const tags: [string, Record<string, string>][] = [];
  for (const tag of buildTagTaxonomy(doc).tags) {
    const meta: Record<string, string> = {};
    for (const key of ['parent', 'summary', 'kind'] as const) if (tag[key]) meta[key] = tag[key]!;
    if (Object.keys(meta).length > 0) tags.push([tag.name, meta]);
  }
  const operationTags: [string, string[]][] = [];
  for (const parsedPath of extractPaths(doc)) {
    for (const op of parsedPath.operations) {
      if (op.tags?.length) operationTags.push([`${op.method} ${parsedPath.path}`, op.tags]);
    }
  }
  return { tags: sortedObject(tags), operationTags: sortedObject(operationTags) };
}

/** OA6: what each referencing property links to, its description, and external refs. */
function projectReferences(doc: any) {
  const { classes } = openApiImporter.normalize({ document: doc, options: { selectedSchemas: [] } });
  const fields: [string, { ref: string; description: string | null }][] = [];
  for (const cls of classes) {
    for (const prop of cls.properties) {
      const ref = prop.data?.$ref;
      if (typeof ref !== 'string') continue;
      const target = localRefName(ref) ?? `external:${ref}`;
      fields.push([`${cls.name}.${prop.name}`, { ref: target, description: prop.description ?? null }]);
    }
  }
  return {
    fields: sortedObject(fields),
    externalReferences: [...resolveSelfReferences(doc).external].sort(byCodePoint),
  };
}

/** AZ2: how each source and each step resolved against the documents imported with it. */
function projectArazzo(directory: string, flow: string, members: string[]) {
  const sourceDocuments = Object.fromEntries(members.map((m) => [m, load(`${directory}/${m}`)]));
  const resolution = resolveArazzoSources({
    document: load(`${directory}/${flow}`),
    sourceDocuments,
    documentPath: flow,
  });
  const sources = sortedObject(
    resolution.sources.map((s): [string, string] => [s.name, s.status === 'resolved' ? 'resolved' : 'unresolved'])
  );
  const steps = sortedObject(
    resolution.steps.map((s): [string, Record<string, string>] => [
      `${s.workflowId}/${s.stepId}`,
      s.operation
        ? { status: s.status, operation: `${s.operation.method} ${s.operation.path}` }
        : { status: s.status },
    ])
  );
  return { sources, steps };
}

/** The Projects path's projection of every parity case. */
function projectsProjection(): Record<string, unknown> {
  return {
    'oa3-streaming': { streams: projectStreams(load('oa3-streaming.yaml')) },
    'oa4-methods': projectOperations(load('oa4-methods.yaml')),
    'oa5-tag-hierarchy': projectTags(load('oa5-tag-hierarchy.yaml')),
    'oa6-self-references': projectReferences(load('oa6-self-references.yaml')),
    'az2-arazzo': projectArazzo('az2-arazzo', 'flow.arazzo.yaml', ['petstore.yaml']),
  };
}

const expected = JSON.parse(readFileSync(path.join(FIXTURES, 'expected.json'), 'utf-8'));

describe('Catalog ↔ Projects path parity (COA-4.2)', () => {
  const actual = projectsProjection();

  it('covers every case in the shared expected file', () => {
    expect(Object.keys(actual).sort()).toEqual(Object.keys(expected.cases).sort());
  });

  it.each(Object.keys(expected.cases))('%s imports on the Projects path as on the Catalog path', (name) => {
    expect(actual[name]).toEqual(expected.cases[name]);
  });

  it('documents every difference the projection leaves out', () => {
    for (const difference of expected.differences) {
      expect(Object.keys(expected.cases)).toContain(difference.case);
      expect(difference.projects.trim()).not.toBe('');
      expect(difference.catalog.trim()).not.toBe('');
    }
  });
});
