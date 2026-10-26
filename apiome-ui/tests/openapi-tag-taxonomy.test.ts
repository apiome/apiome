/**
 * OA5 (#3502) — Import the OpenAPI 3.2.0 hierarchical tag taxonomy.
 *
 * Covers parsing the full Tag Object, the parent hierarchy (multi-level tree, unknown
 * parents, cycles), what the import keeps (project metadata, class and operation tag
 * associations) and the analyzer report.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import { parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { analyzeSpecification } from '../src/app/utils/openapi-analyzer';
import { convertOpenAPI32ToOpenAPI31 } from '../src/app/utils/openapi32-converter';
import { openApiImporter } from '../lib/importers/openapi';
import { mergeOpenApiDocumentIntoCatalogTargets } from '../lib/rest-spec-import-merge';
import {
  buildTagTaxonomy,
  CLASS_TAGS_EXTENSION,
  parseTagObjects,
  TAG_TAXONOMY_METADATA_KEY,
  toStoredTagTaxonomy,
  type TagTreeNode,
} from '../src/app/utils/openapi-tag-taxonomy';

const FIXTURES = path.join(__dirname, 'fixtures/openapi32-tags');

/** Read a tag fixture as text. */
function fixture(name: string): string {
  return fs.readFileSync(path.join(FIXTURES, name), 'utf-8');
}

/** Read a tag fixture as a parsed document. */
function fixtureDoc(name: string): any {
  return YAML.parse(fixture(name));
}

/** Render a tree as `name@depth` lines with children nested, for compact assertions. */
function outline(nodes: TagTreeNode[]): any[] {
  return nodes.map((n) => (n.children.length > 0 ? { [`${n.name}@${n.depth}`]: outline(n.children) } : `${n.name}@${n.depth}`));
}

/** Whether an import warning comes from the tag hierarchy (unknown parent or cycle). */
function isTagHierarchyWarning(w: string): boolean {
  return w.startsWith('Tag "') || w.startsWith('Tag parent cycle');
}

/** Import metadata used by the project-metadata merge. */
const META = { project: { name: 'P', slug: 'p' }, version: { versionId: '1.0.0' } };

describe('parseTagObjects', () => {
  it('reads every Tag Object field and trims values', () => {
    const { tags, warnings } = parseTagObjects([
      {
        name: ' billing ',
        summary: 'Billing',
        description: 'Money',
        parent: ' root ',
        kind: 'nav',
        externalDocs: { url: 'https://example.com', description: 'Docs' },
      },
    ]);
    expect(tags).toEqual([
      {
        name: 'billing',
        summary: 'Billing',
        description: 'Money',
        parent: 'root',
        kind: 'nav',
        externalDocs: { url: 'https://example.com', description: 'Docs' },
      },
    ]);
    expect(warnings).toEqual([]);
  });

  it('skips nameless entries, drops empty fields and keeps the first of a duplicate name', () => {
    const { tags, warnings } = parseTagObjects([
      null,
      'billing',
      { description: 'no name' },
      { name: 'a', summary: '  ', externalDocs: { description: 'no url' } },
      { name: 'a', summary: 'second' },
    ]);
    expect(tags).toEqual([{ name: 'a' }]);
    expect(warnings).toEqual(['Tag "a" is declared more than once; the first declaration was kept.']);
  });

  it('returns nothing for a missing or non-array tags field', () => {
    expect(parseTagObjects(undefined)).toEqual({ tags: [], warnings: [] });
    expect(parseTagObjects({ name: 'x' })).toEqual({ tags: [], warnings: [] });
  });
});

describe('buildTagTaxonomy — multi-level tree', () => {
  it('builds the hierarchy from parent links in document order', () => {
    const taxonomy = buildTagTaxonomy(fixtureDoc('tag-tree.yaml'));
    expect(outline(taxonomy.roots)).toEqual([
      { 'billing@0': [{ 'invoices@1': ['invoice-lines@2'] }, 'refunds@1'] },
      'internal@0',
    ]);
    expect(taxonomy.warnings).toEqual([]);
  });

  it('keeps summary, kind and externalDocs on the tree nodes', () => {
    const [billing] = buildTagTaxonomy(fixtureDoc('tag-tree.yaml')).roots;
    expect(billing).toMatchObject({
      name: 'billing',
      summary: 'Billing',
      kind: 'nav',
      externalDocs: { url: 'https://example.com/docs/billing' },
    });
    expect(billing.children[0]).toMatchObject({ name: 'invoices', parent: 'billing', summary: 'Invoices' });
  });

  it('reads the tags of an OA2-normalized document the same way', () => {
    const normalized = convertOpenAPI32ToOpenAPI31(fixtureDoc('tag-tree.yaml')).document;
    expect(buildTagTaxonomy(normalized)).toEqual(buildTagTaxonomy(fixtureDoc('tag-tree.yaml')));
  });

  it('handles a document with no tags', () => {
    expect(buildTagTaxonomy({ openapi: '3.2.0' })).toEqual({ tags: [], roots: [], warnings: [] });
    expect(buildTagTaxonomy(null)).toEqual({ tags: [], roots: [], warnings: [] });
  });
});

describe('buildTagTaxonomy — cyclic-tag guard', () => {
  it('rejects cycles and unknown parents with warnings, flattening them to top-level tags', () => {
    const taxonomy = buildTagTaxonomy(fixtureDoc('tag-cycle.yaml'));
    expect(taxonomy.warnings).toEqual([
      'Tag "orphan" names an undeclared parent "missing"; it was imported as a top-level tag.',
      'Tag parent cycle "a" → "c" → "b" → "a"; their parent links were ignored and they were imported as top-level tags.',
      'Tag parent cycle "self" → "self"; their parent links were ignored and they were imported as top-level tags.',
    ]);
    expect(outline(taxonomy.roots)).toEqual(['a@0', { 'b@0': ['leaf@1'] }, 'c@0', 'self@0', 'orphan@0']);
  });

  it('drops only the rejected parent links from the tags', () => {
    const { tags } = buildTagTaxonomy(fixtureDoc('tag-cycle.yaml'));
    expect(tags.map((t) => [t.name, t.parent])).toEqual([
      ['a', undefined],
      ['b', undefined],
      ['c', undefined],
      ['leaf', 'b'],
      ['self', undefined],
      ['orphan', undefined],
    ]);
  });

  it('does not mutate the input document', () => {
    const doc = fixtureDoc('tag-cycle.yaml');
    const before = JSON.stringify(doc);
    buildTagTaxonomy(doc);
    expect(JSON.stringify(doc)).toBe(before);
  });
});

describe('toStoredTagTaxonomy', () => {
  it('stores the tags with their resolved parents', () => {
    expect(toStoredTagTaxonomy(buildTagTaxonomy(fixtureDoc('tag-cycle.yaml')))).toEqual({
      version: 1,
      tags: [{ name: 'a' }, { name: 'b' }, { name: 'c' }, { name: 'leaf', parent: 'b' }, { name: 'self' }, { name: 'orphan' }],
    });
  });

  it('stores nothing when the document declares no tags', () => {
    expect(toStoredTagTaxonomy(buildTagTaxonomy({}))).toBeUndefined();
  });
});

describe('parseOpenAPISpec — tags on the import result', () => {
  it('returns the full tags and a navigable hierarchy', () => {
    const result = parseOpenAPISpec(fixture('tag-tree.yaml'));
    expect(result.success).toBe(true);
    expect(result.tags?.find((t) => t.name === 'invoice-lines')).toEqual({ name: 'invoice-lines', parent: 'invoices', kind: 'nav' });
    expect(outline(result.tagHierarchy ?? [])).toEqual([
      { 'billing@0': [{ 'invoices@1': ['invoice-lines@2'] }, 'refunds@1'] },
      'internal@0',
    ]);
  });

  it('adds cycle and unknown-parent warnings to the import warnings', () => {
    const result = parseOpenAPISpec(fixture('tag-cycle.yaml'));
    expect(result.success).toBe(true);
    expect(result.warnings.filter(isTagHierarchyWarning)).toHaveLength(3);
  });

  it('keeps operation tag associations', () => {
    const result = parseOpenAPISpec(fixture('tag-tree.yaml'));
    const ops = result.paths?.flatMap((p) => p.operations.map((o) => [o.operationId, o.tags]));
    expect(ops).toEqual([
      ['listInvoices', ['invoices']],
      ['createRefund', ['refunds', 'internal']],
    ]);
  });

  it('omits the hierarchy when the document has no tags', () => {
    const doc = fixtureDoc('tag-tree.yaml');
    delete doc.tags;
    const result = parseOpenAPISpec(JSON.stringify(doc));
    expect(result.tags).toBeUndefined();
    expect(result.tagHierarchy).toBeUndefined();
  });
});

describe('openApiImporter.normalize — class tag associations', () => {
  it('records the tags a schema declares as x-apiome-tags provenance', () => {
    const { classes } = openApiImporter.normalize({ document: fixtureDoc('tag-tree.yaml'), options: {} as any });
    const byKey = new Map(classes.map((c) => [c.originalSchemaKey, c]));
    expect(byKey.get('Invoice')?.schema[CLASS_TAGS_EXTENSION]).toEqual(['invoices', 'billing']);
    expect(byKey.get('Refund')?.schema[CLASS_TAGS_EXTENSION]).toEqual(['refunds']);
    expect(byKey.get('Untagged')?.schema).not.toHaveProperty(CLASS_TAGS_EXTENSION);
  });

  it('does not change the source document', () => {
    const doc = fixtureDoc('tag-tree.yaml');
    openApiImporter.normalize({ document: doc, options: {} as any });
    expect(doc.components.schemas.Invoice).not.toHaveProperty(CLASS_TAGS_EXTENSION);
  });

  it('reports tag hierarchy problems with the import warnings', () => {
    const { warnings } = openApiImporter.normalize({ document: fixtureDoc('tag-cycle.yaml'), options: {} as any });
    expect(warnings.filter(isTagHierarchyWarning)).toHaveLength(3);
  });
});

describe('mergeOpenApiDocumentIntoCatalogTargets — project metadata', () => {
  it('keeps the taxonomy beside the info metadata', () => {
    const doc = fixtureDoc('tag-tree.yaml');
    doc.info.termsOfService = 'https://example.com/tos';
    const merged = mergeOpenApiDocumentIntoCatalogTargets(META, doc, 'openapi');
    expect(merged.projectMetadata?.termsOfService).toBe('https://example.com/tos');
    const stored = merged.projectMetadata?.[TAG_TAXONOMY_METADATA_KEY] as any;
    expect(stored.version).toBe(1);
    expect(stored.tags.map((t: any) => [t.name, t.parent ?? null, t.kind ?? null])).toEqual([
      ['billing', null, 'nav'],
      ['invoices', 'billing', null],
      ['invoice-lines', 'invoices', 'nav'],
      ['refunds', 'billing', null],
      ['internal', null, 'audience'],
    ]);
  });

  it('keeps the taxonomy even without an info object', () => {
    const doc = fixtureDoc('tag-tree.yaml');
    delete doc.info;
    const merged = mergeOpenApiDocumentIntoCatalogTargets(META, doc, 'openapi');
    expect(Object.keys(merged.projectMetadata ?? {})).toEqual([TAG_TAXONOMY_METADATA_KEY]);
  });

  it('adds nothing for a document without tags or for Arazzo', () => {
    const doc = fixtureDoc('tag-tree.yaml');
    expect(mergeOpenApiDocumentIntoCatalogTargets(META, doc, 'arazzo').projectMetadata).toBeUndefined();
    delete doc.tags;
    expect(mergeOpenApiDocumentIntoCatalogTargets(META, doc, 'openapi').projectMetadata).toBeUndefined();
  });
});

describe('analyzeSpecification — tag taxonomy report', () => {
  it('summarizes a tag tree as information', async () => {
    const analysis = await analyzeSpecification(fixture('tag-tree.yaml'), 'tags.yaml');
    const feature = analysis.unsupportedFeatures.find((f) => f.id === 'tag-taxonomy');
    expect(feature).toMatchObject({ severity: 'info', count: 5, path: 'tags' });
    expect(feature?.description).toContain('5 tags in 3 levels (2 top-level); kinds: nav, audience.');
    // Superseded by the tag-taxonomy feature: not listed twice.
    expect(analysis.unsupportedFeatures.some((f) => f.id === 'openapi32-tag-metadata')).toBe(false);
  });

  it('is a warning that names the problems when parents are cyclic or unknown', async () => {
    const analysis = await analyzeSpecification(fixture('tag-cycle.yaml'), 'cycle.yaml');
    const feature = analysis.unsupportedFeatures.find((f) => f.id === 'tag-taxonomy');
    expect(feature?.severity).toBe('warning');
    expect(feature?.description).toContain('Tag parent cycle "a" → "c" → "b" → "a"');
    expect(feature?.description).toContain('undeclared parent "missing"');
  });

  it('is omitted for plain name/description tags', async () => {
    const doc = { openapi: '3.1.0', info: { title: 'T', version: '1' }, tags: [{ name: 'pets', description: 'Pets' }], paths: {} };
    const analysis = await analyzeSpecification(JSON.stringify(doc), 'plain.json');
    expect(analysis.unsupportedFeatures.some((f) => f.id === 'tag-taxonomy')).toBe(false);
  });
});
