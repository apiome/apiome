/**
 * OA6 (#3503) — Resolve OpenAPI 3.2.0 `$self` and `$ref` sibling summary/description.
 *
 * Covers `$self`-based reference resolution (and unchanged behavior without it), the
 * sibling local override on properties and composed classes, circular references, and
 * the analyzer's reference reporting.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import { extractPaths, parseOpenAPISpec } from '../src/app/utils/openapi-import';
import { analyzeSpecification } from '../src/app/utils/openapi-analyzer';
import { convertOpenAPI32ToOpenAPI31 } from '../src/app/utils/openapi32-converter';
import { openApiImporter } from '../lib/importers/openapi';
import {
  applyRefSiblingOverrides,
  describeExternalSelfReferences,
  getDocumentSelf,
  resolveSelfReferences,
} from '../src/app/utils/openapi-self-references';

const FIXTURE = path.join(__dirname, 'fixtures/openapi32-refs/self-and-siblings.yaml');
const SELF = 'https://api.example.com/specs/orders.yaml';

/** Read the fixture as text. */
function fixture(): string {
  return fs.readFileSync(FIXTURE, 'utf-8');
}

/** Read the fixture as a parsed document. */
function fixtureDoc(): any {
  return YAML.parse(fixture());
}

/** The fixture without its `$self`, to check that behavior is unchanged without one. */
function fixtureDocWithoutSelf(): any {
  const doc = fixtureDoc();
  delete doc.$self;
  return doc;
}

describe('getDocumentSelf', () => {
  it('reads a trimmed string $self', () => {
    expect(getDocumentSelf({ $self: `  ${SELF} ` })).toBe(SELF);
  });

  it('ignores a missing, empty or non-string $self', () => {
    expect(getDocumentSelf({})).toBeUndefined();
    expect(getDocumentSelf({ $self: ' ' })).toBeUndefined();
    expect(getDocumentSelf({ $self: 42 })).toBeUndefined();
    expect(getDocumentSelf(null)).toBeUndefined();
  });
});

describe('resolveSelfReferences', () => {
  it('rewrites every same-document reference to its local fragment', () => {
    const { document, self, rewritten } = resolveSelfReferences(fixtureDoc());
    expect(self).toBe(SELF);
    expect(rewritten).toBe(7);
    const order = document.components.schemas.Order.properties;
    expect(order.customer.$ref).toBe('#/components/schemas/Customer');
    expect(order.shipping.$ref).toBe('#/components/schemas/Address');
    expect(order.billing.$ref).toBe('#/components/schemas/Address');
    expect(order.local.$ref).toBe('#/components/schemas/Address');
    expect(document.components.schemas.Composite.allOf[0].$ref).toBe('#/components/schemas/Customer');
    expect(document.paths['/orders'].get.responses['200'].content['application/json'].schema.$ref).toBe(
      '#/components/schemas/Order'
    );
  });

  it('keeps siblings beside a rewritten reference', () => {
    const { document } = resolveSelfReferences(fixtureDoc());
    expect(document.components.schemas.Order.properties.customer).toEqual({
      $ref: '#/components/schemas/Customer',
      summary: 'Billing customer',
      description: 'Overrides Customer.description for this field',
    });
  });

  it('lists references to other documents and leaves them as written', () => {
    const { document, external } = resolveSelfReferences(fixtureDoc());
    expect(external).toEqual(['common.yaml#/components/schemas/Customer']);
    expect(document.components.schemas.Order.properties.supplier.$ref).toBe('common.yaml#/components/schemas/Customer');
  });

  it('does not mutate the input', () => {
    const doc = fixtureDoc();
    const before = JSON.stringify(doc);
    resolveSelfReferences(doc);
    expect(JSON.stringify(doc)).toBe(before);
  });

  it('returns the very same document without $self (current behavior preserved)', () => {
    const doc = fixtureDocWithoutSelf();
    expect(resolveSelfReferences(doc)).toEqual({ document: doc, rewritten: 0, external: [] });
    expect(resolveSelfReferences(doc).document).toBe(doc);
  });

  it('resolves against a relative $self', () => {
    const doc = {
      $self: '/specs/orders.yaml',
      components: { schemas: { A: { properties: { b: { $ref: '../specs/orders.yaml#/components/schemas/B' } } }, B: {} } },
    };
    const { document, rewritten } = resolveSelfReferences(doc);
    expect(rewritten).toBe(1);
    expect(document.components.schemas.A.properties.b.$ref).toBe('#/components/schemas/B');
  });

  it('rewrites a whole-document reference to "#" and keeps escaped fragments verbatim', () => {
    const doc = {
      $self: SELF,
      components: {
        schemas: {
          Whole: { $ref: SELF },
          Escaped: { $ref: `${SELF}#/components/schemas/a~1b%20c` },
        },
      },
    };
    const { document } = resolveSelfReferences(doc);
    expect(document.components.schemas.Whole.$ref).toBe('#');
    expect(document.components.schemas.Escaped.$ref).toBe('#/components/schemas/a~1b%20c');
  });

  it('returns the input unchanged when nothing points back into the document', () => {
    const doc = { $self: SELF, components: { schemas: { A: { $ref: '#/components/schemas/B' }, B: {} } } };
    const result = resolveSelfReferences(doc);
    expect(result.document).toBe(doc);
    expect(result).toMatchObject({ self: SELF, rewritten: 0, external: [] });
  });

  it('reads the $self of an OA2-normalized document the same way', () => {
    const normalized = convertOpenAPI32ToOpenAPI31(fixtureDoc()).document;
    const { document, rewritten } = resolveSelfReferences(normalized);
    expect(rewritten).toBe(7);
    expect(document.components.schemas.Order.properties.customer.$ref).toBe('#/components/schemas/Customer');
  });
});

describe('describeExternalSelfReferences', () => {
  it('names the references that leave the document', () => {
    expect(describeExternalSelfReferences(resolveSelfReferences(fixtureDoc()))).toBe(
      `1 reference resolves outside this document against $self "${SELF}" ` +
        '(common.yaml#/components/schemas/Customer); they are kept as written and not followed by the import.'
    );
  });

  it('says nothing when every reference stays in the document', () => {
    expect(describeExternalSelfReferences(resolveSelfReferences(fixtureDocWithoutSelf()))).toBeUndefined();
  });
});

describe('applyRefSiblingOverrides', () => {
  const target = { type: 'object', summary: 'Target summary', description: 'Target description' };

  it('lets siblings override the target', () => {
    expect(applyRefSiblingOverrides(target, { $ref: '#/x', summary: 'Local', description: 'Local d' })).toEqual({
      type: 'object',
      summary: 'Local',
      description: 'Local d',
    });
  });

  it('keeps the target value when the $ref has no sibling', () => {
    expect(applyRefSiblingOverrides(target, { $ref: '#/x' })).toBe(target);
    expect(applyRefSiblingOverrides(target, { $ref: '#/x', description: '  ' })).toBe(target);
    expect(applyRefSiblingOverrides(target, { $ref: '#/x', summary: 'Only summary' })).toEqual({
      ...target,
      summary: 'Only summary',
    });
  });

  it('never mutates the target', () => {
    const copy = { ...target };
    applyRefSiblingOverrides(copy, { description: 'x' });
    expect(copy).toEqual(target);
  });
});

describe('parseOpenAPISpec — $self and sibling overrides', () => {
  it('resolves $self-based references so classes are supported', () => {
    const result = parseOpenAPISpec(fixture());
    expect(result.success).toBe(true);
    const order = result.classes.find((c) => c.name === 'Order');
    expect(order?.isSupported).toBe(true);
    expect(order?.warnings).toEqual([]);
  });

  it('keeps the sibling description and summary on the referencing property', () => {
    const order = parseOpenAPISpec(fixture()).classes.find((c) => c.name === 'Order');
    const customer = order?.properties.find((p) => p.name === 'customer');
    expect(customer?.description).toBe('Overrides Customer.description for this field');
    expect(customer?.data).toEqual({ $ref: '#/components/schemas/Customer', summary: 'Billing customer' });
  });

  it('uses an allOf $ref sibling description over the target description', () => {
    const composite = parseOpenAPISpec(fixture()).classes.find((c) => c.name === 'Composite');
    expect(composite?.description).toBe('Composite override');
    const withoutSibling = fixtureDoc();
    delete withoutSibling.components.schemas.Composite.allOf[0].description;
    expect(parseOpenAPISpec(JSON.stringify(withoutSibling)).classes.find((c) => c.name === 'Composite')?.description).toBe(
      'A customer'
    );
  });

  it('terminates on circular references', () => {
    const result = parseOpenAPISpec(fixture());
    expect(result.classes.find((c) => c.name === 'Loop')?.isSupported).toBe(true);
    expect(result.classes.find((c) => c.name === 'Loop2')?.isSupported).toBe(true);
  });

  it('warns about references that point at other documents', () => {
    expect(parseOpenAPISpec(fixture()).warnings).toContain(
      describeExternalSelfReferences(resolveSelfReferences(fixtureDoc()))
    );
  });

  it('links path content written against $self to the class', () => {
    const content = parseOpenAPISpec(fixture()).paths?.[0].operations[0].responses['200'].content;
    expect(content?.['application/json']).toEqual({ $ref: '#/components/schemas/Order' });
    expect(extractPaths(fixtureDoc())[0].operations[0].responses['200'].content?.['application/json']).toEqual({
      $ref: '#/components/schemas/Order',
    });
  });

  it('keeps the old reading of a document without $self', () => {
    const result = parseOpenAPISpec(JSON.stringify(fixtureDocWithoutSelf()));
    const order = result.classes.find((c) => c.name === 'Order');
    expect(order?.properties.find((p) => p.name === 'shipping')?.data).toEqual({
      $ref: 'orders.yaml#/components/schemas/Address',
    });
    expect(result.warnings.some((w) => w.includes('$self'))).toBe(false);
  });
});

describe('openApiImporter.normalize — $self and sibling overrides', () => {
  it('imports local references and the sibling override on the property', () => {
    const { classes, warnings } = openApiImporter.normalize({ document: fixtureDoc(), options: {} as any });
    const order = classes.find((c) => c.originalSchemaKey === 'Order');
    const byName = new Map(order?.properties.map((p) => [p.name, p]));
    expect(byName.get('customer')).toMatchObject({
      description: 'Overrides Customer.description for this field',
      data: { $ref: '#/components/schemas/Customer', summary: 'Billing customer' },
    });
    expect(byName.get('billing')?.data).toEqual({ $ref: '#/components/schemas/Address' });
    expect(byName.get('supplier')?.data).toEqual({ $ref: 'common.yaml#/components/schemas/Customer' });
    expect(warnings).toContain(describeExternalSelfReferences(resolveSelfReferences(fixtureDoc())));
  });

  it('keeps the sibling override on a class that is a $ref alias', () => {
    const doc = fixtureDoc();
    doc.components.schemas.Alias = { $ref: `${SELF}#/components/schemas/Customer`, description: 'Alias of Customer' };
    const alias = openApiImporter.normalize({ document: doc, options: {} as any }).classes.find(
      (c) => c.originalSchemaKey === 'Alias'
    );
    expect(alias?.description).toBe('Alias of Customer');
    expect(alias?.schema).toEqual({ $ref: '#/components/schemas/Customer', description: 'Alias of Customer' });
  });
});

describe('analyzeSpecification — reference reporting', () => {
  it('reports $self with the local and external reference counts', async () => {
    const analysis = await analyzeSpecification(fixture(), 'orders.yaml');
    const feature = analysis.unsupportedFeatures.find((f) => f.id === 'self-base-uri');
    expect(feature).toMatchObject({ severity: 'warning', count: 8, path: '$self' });
    expect(feature?.description).toContain(`References resolve against $self "${SELF}". 7 references back into this document`);
    expect(feature?.description).toContain('1 points to another document and is not followed: common.yaml#/components/schemas/Customer.');
  });

  it('does not count same-document absolute references as external', async () => {
    const analysis = await analyzeSpecification(fixture(), 'orders.yaml');
    expect(analysis.metrics.externalReferences).toEqual([]);
    expect(analysis.unsupportedFeatures.some((f) => f.id === 'external-refs')).toBe(false);
  });

  it('is information when every reference stays in the document', async () => {
    const doc = fixtureDoc();
    delete doc.components.schemas.Order.properties.supplier;
    const feature = (await analyzeSpecification(JSON.stringify(doc), 'orders.json')).unsupportedFeatures.find(
      (f) => f.id === 'self-base-uri'
    );
    expect(feature).toMatchObject({ severity: 'info', count: 7 });
  });

  it('keeps the old report without $self', async () => {
    const analysis = await analyzeSpecification(JSON.stringify(fixtureDocWithoutSelf()), 'orders.json');
    expect(analysis.unsupportedFeatures.some((f) => f.id === 'self-base-uri')).toBe(false);
    expect(analysis.metrics.externalReferences).toEqual([`${SELF}#/components/schemas/Order`, `${SELF}#/components/schemas/Customer`]);
  });

  it('reports the sibling metadata as imported overrides', async () => {
    const analysis = await analyzeSpecification(fixture(), 'orders.yaml');
    const siblings = analysis.unsupportedFeatures.find((f) => f.id === 'openapi32-ref-sibling-metadata');
    expect(siblings?.description).toContain('imported as local overrides');
  });
});
