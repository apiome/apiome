/**
 * OpenAPI example round-trip: examples/openapi → import pipeline → class schemas.
 *
 * Uses the same steps as a database import for schema data: the YAML document is normalized with
 * `openApiImporter.normalize()` (as in importClassesToVersion), the class/property rows are
 * flattened to the shape returned by getClassesForVersion / getPropertiesForClass, and each class's
 * schema is rebuilt from those rows with `buildClassSchema`.
 *
 * The UI no longer generates whole OpenAPI documents (COA-5.13, #7089): a revision's document is
 * rendered by apiome-rest alone, whose own corpus round-trip covers paths, servers and security
 * schemes. What stays here is what the import pipeline itself must not lose: every field of every
 * imported schema.
 *
 * A live Postgres project is not created here because importClassesToVersion creates library
 * properties via authenticated HTTP to the Next API; this suite validates the pipeline without
 * that coupling.
 */

import * as fs from 'fs';
import * as path from 'path';
import { describe, it, expect, beforeAll, afterAll } from '@jest/globals';
import YAML from 'yaml';

import { buildClassSchema } from '../src/app/utils/openapi';
import { parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { isOpenAPI30, convertOpenAPI30ToOpenAPI31 } from '../src/app/utils/openapi30-converter';
import { openApiImporter } from '../lib/importers';
import type { NormalizedClass, NormalizedProperty } from '../lib/importers';

const EXAMPLES_DIR = path.join(__dirname, '../examples/openapi');

interface SubsetMismatch {
  jsonPath: string;
  kind: string;
  detail: string;
}

function allStrings(a: unknown[]): boolean {
  return a.every((x) => typeof x === 'string');
}

/** JSON Schema `required` arrays are unordered sets of property names. */
function assertRequiredNameMultisetSubset(
  source: string[],
  generated: string[],
  jsonPath: string,
  out: SubsetMismatch[]
): void {
  const gen = [...generated];
  for (const name of source) {
    const i = gen.indexOf(name);
    if (i === -1) {
      out.push({
        jsonPath,
        kind: 'required_name_missing',
        detail: `required name ${JSON.stringify(name)} missing in generated (subset / no omissions)`,
      });
    } else {
      gen.splice(i, 1);
    }
  }
}

/** Every value in `source` must appear identically under `generated`; extra keys in `generated` are allowed. */
function assertSourceSubsetOfGenerated(
  source: unknown,
  generated: unknown,
  jsonPath: string,
  out: SubsetMismatch[]
): void {
  if (source === null || source === undefined) {
    return;
  }
  if (generated === null || generated === undefined) {
    out.push({
      jsonPath,
      kind: 'omission',
      detail: `source has ${JSON.stringify(source)} but generated is null/undefined`,
    });
    return;
  }
  if (typeof source !== 'object') {
    if (source !== generated) {
      out.push({
        jsonPath,
        kind: 'value_mismatch',
        detail: `source ${JSON.stringify(source)} !== generated ${JSON.stringify(generated)}`,
      });
    }
    return;
  }
  if (Array.isArray(source)) {
    if (!Array.isArray(generated)) {
      out.push({ jsonPath, kind: 'type', detail: 'source is array but generated is not' });
      return;
    }
    if (
      jsonPath.endsWith('.required') &&
      allStrings(source) &&
      allStrings(generated as unknown[])
    ) {
      assertRequiredNameMultisetSubset(source as string[], generated as string[], jsonPath, out);
      return;
    }
    if (generated.length < source.length) {
      out.push({
        jsonPath,
        kind: 'array_shorter',
        detail: `source length ${source.length}, generated length ${generated.length} (omissions not allowed)`,
      });
    }
    const n = Math.min(source.length, generated.length);
    for (let i = 0; i < n; i++) {
      assertSourceSubsetOfGenerated(source[i], generated[i], `${jsonPath}[${i}]`, out);
    }
    return;
  }
  if (typeof generated !== 'object' || Array.isArray(generated)) {
    out.push({ jsonPath, kind: 'type', detail: 'source is object but generated is not a plain object' });
    return;
  }
  const s = source as Record<string, unknown>;
  const g = generated as Record<string, unknown>;
  for (const key of Object.keys(s)) {
    const p = jsonPath ? `${jsonPath}.${key}` : key;
    if (!(key in g)) {
      out.push({ jsonPath: p, kind: 'missing_key', detail: 'key present in source but omitted in generated' });
      continue;
    }
    assertSourceSubsetOfGenerated(s[key], g[key], p, out);
  }
}

function stableStringify(value: unknown): string {
  if (value === null || value === undefined) return JSON.stringify(value);
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((x) => stableStringify(x)).join(',')}]`;
  }
  const o = value as Record<string, unknown>;
  const keys = Object.keys(o).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`).join(',')}}`;
}

function prepareDocument(raw: unknown): Record<string, unknown> {
  const doc = raw as Record<string, unknown>;
  if (isOpenAPI30(doc)) {
    const conv = convertOpenAPI30ToOpenAPI31(doc);
    if (conv.success && conv.document) {
      return conv.document as Record<string, unknown>;
    }
  }
  return doc;
}

function flattenNormalizedProperties(props: NormalizedProperty[], parentId: string | null, idCounter: { n: number }): any[] {
  const rows: any[] = [];
  for (const p of props) {
    const id = `test-prop-${idCounter.n++}`;
    rows.push({
      id,
      parent_id: parentId,
      name: p.name,
      data: p.data,
      description: p.description ?? null,
    });
    if (p.children?.length) {
      rows.push(...flattenNormalizedProperties(p.children, id, idCounter));
    }
  }
  return rows;
}

function normalizedClassesToGeneratorRows(classes: NormalizedClass[]): any[] {
  const idCounter = { n: 0 };
  return classes.map((cls, idx) => ({
    id: `test-class-${idx}`,
    name: cls.name,
    description: cls.description ?? undefined,
    schema: cls.schema,
    properties: flattenNormalizedProperties(cls.properties || [], null, idCounter),
  }));
}

function formatGitHubIssueBody(params: {
  exampleFile: string;
  mismatches: SubsetMismatch[];
  sourceBlock: string;
  generatedBlock: string;
}): string {
  const diffLines = params.mismatches.map((m) => `- **${m.jsonPath}** (${m.kind}): ${m.detail}`).join('\n');
  return [
    `## Bug: OpenAPI import/export parity — \`${params.exampleFile}\``,
    '',
    '### What to fix',
    'Schemas rebuilt after import (normalize → DB-shaped classes → buildClassSchema) must preserve every field of the source schemas (subset rule: no omissions; extra fields on the rebuilt schema are OK).',
    '',
    '### Differences',
    diffLines || '(none)',
    '',
    '### Source fragment (relevant slice)',
    '```yaml',
    params.sourceBlock.trimEnd(),
    '```',
    '',
    '### Generated fragment',
    '```json',
    params.generatedBlock.trimEnd(),
    '```',
  ].join('\n');
}

function listExampleYamlFiles(): string[] {
  if (!fs.existsSync(EXAMPLES_DIR)) return [];
  return fs
    .readdirSync(EXAMPLES_DIR)
    .filter((f) => f.endsWith('.yaml') || f.endsWith('.yml'))
    .map((f) => path.join(EXAMPLES_DIR, f))
    .sort();
}

describe('OpenAPI examples import/export round-trip (examples/openapi)', () => {
  beforeAll(() => {
    jest.spyOn(console, 'log').mockImplementation(() => {});
    jest.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterAll(() => {
    jest.restoreAllMocks();
  });

  const files = listExampleYamlFiles();
  expect(files.length).toBeGreaterThan(0);

  it.each(files)('%s', async (filePath) => {
    const basename = path.basename(filePath);
    const rawContent = fs.readFileSync(filePath, 'utf-8');
    const parseResult = parseOpenAPISpec(rawContent);
    expect(parseResult.success).toBe(true);

    const supportedKeys = new Set(
      parseResult.classes.filter((c) => c.isSupported).map((c) => c.name)
    );
    const doc = prepareDocument(YAML.parse(rawContent)) as Record<string, unknown>;
    const schemasObj = (doc.components as Record<string, unknown> | undefined)?.schemas as
      | Record<string, unknown>
      | undefined;
    const allSchemaKeys = schemasObj ? Object.keys(schemasObj) : [];
    const selectedSchemas = allSchemaKeys.filter((k) => supportedKeys.has(k));
    expect(selectedSchemas.length).toBeGreaterThan(0);

    const norm = openApiImporter.normalize({
      document: doc,
      options: {
        selectedSchemas,
        applyNamingConvention: false,
        generateExamples: false,
      },
    });

    const classesForGen = normalizedClassesToGeneratorRows(norm.classes);
    const generated: Record<string, unknown> = {
      components: {
        schemas: Object.fromEntries(
          classesForGen.map((cls: { name: string }) => [cls.name, buildClassSchema(cls)])
        ),
      },
    };
    const mismatches: SubsetMismatch[] = [];

    const sourceComponents = (doc.components || {}) as Record<string, unknown>;
    const genComponents = (generated.components || {}) as Record<string, unknown>;

    const schemaKeyToExported = new Map<string, string>();
    for (const cls of norm.classes) {
      const srcKey = cls.originalSchemaKey ?? cls.name;
      schemaKeyToExported.set(srcKey, cls.name);
    }

    const sourceSchemas = (sourceComponents.schemas || {}) as Record<string, unknown>;
    const genSchemas = (genComponents.schemas || {}) as Record<string, unknown>;
    for (const srcKey of selectedSchemas) {
      const genKey = schemaKeyToExported.get(srcKey) ?? srcKey;
      const sSch = sourceSchemas[srcKey];
      const gSch = genSchemas[genKey];
      if (gSch === undefined) {
        mismatches.push({
          jsonPath: `components.schemas.${genKey}`,
          kind: 'missing_schema',
          detail: `source schema "${srcKey}" has no exported schema under "${genKey}"`,
        });
        continue;
      }
      assertSourceSubsetOfGenerated(sSch, gSch, `components.schemas.${srcKey}`, mismatches);
    }

    if (mismatches.length > 0) {
      const sourceSlice = stableStringify({ schemas: sourceSchemas });
      const genSlice = stableStringify({ schemas: genSchemas });
      const issue = formatGitHubIssueBody({
        exampleFile: basename,
        mismatches,
        sourceBlock: sourceSlice.length > 12000 ? `${sourceSlice.slice(0, 12000)}\n… (truncated)` : sourceSlice,
        generatedBlock: genSlice.length > 12000 ? `${genSlice.slice(0, 12000)}\n… (truncated)` : genSlice,
      });
      const summary = mismatches
        .slice(0, 25)
        .map((m) => `${m.jsonPath} (${m.kind}): ${m.detail}`)
        .join('\n');
      throw new Error(
        `OpenAPI import/export round-trip failed for ${basename} (${mismatches.length} mismatch(es)).\n\n` +
          `--- GitHub issue body (copy into a new issue) ---\n\n${issue}\n\n` +
          `--- First mismatches ---\n${summary}${mismatches.length > 25 ? '\n…' : ''}`
      );
    }
  });
});
