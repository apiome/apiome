/**
 * Additive merge planner (#591): "add what is new, keep what exists" for an import into an
 * existing project — classes, properties (nested too), paths and operations.
 */

import { describe, expect, test } from '@jest/globals';
import {
  describeAdditiveMerge,
  planAdditiveClasses,
  planAdditivePaths,
} from '../../lib/import-additive-merge';
import type { NormalizedClass } from '../../lib/importers';
import type { ParsedOperation, ParsedPath } from '../../src/app/utils/openapi-import';

/** A class with the given root properties (name → JSON Schema). */
function cls(name: string, props: Record<string, Record<string, unknown>>, description?: string): NormalizedClass {
  return {
    name,
    description,
    schema: { type: 'object' },
    properties: Object.entries(props).map(([n, data]) => ({ name: n, data })),
  };
}

/** An operation with the given method. */
function op(method: string, summary?: string): ParsedOperation {
  return { method, summary, parameters: [], responses: {} };
}

/** A path with the given operations. */
function path(p: string, ...operations: ParsedOperation[]): ParsedPath {
  return { path: p, operations };
}

describe('planAdditiveClasses', () => {
  test('a same-named class keeps its existing properties and gains the new ones', () => {
    const existing = cls('Pet', { id: { type: 'integer' }, name: { type: 'string', maxLength: 50 } }, 'Stored pet');
    const imported = cls('Pet', { name: { type: 'string', maxLength: 10 }, tag: { type: 'string' } }, 'Spec pet');

    const plan = planAdditiveClasses([existing], [imported]);

    const pet = plan.classes[0];
    expect(pet.properties.map((p) => p.name)).toEqual(['id', 'name', 'tag']);
    // The existing definition wins for a property both sides have.
    expect(pet.properties.find((p) => p.name === 'name')?.data).toEqual({ type: 'string', maxLength: 50 });
    expect(pet.description).toBe('Stored pet');
    expect(plan.schemasMerged).toBe(1);
    expect(plan.propertiesAdded).toBe(1);
    expect(plan.carriedClassNames).toEqual([]);
  });

  test('nested properties the spec adds are counted', () => {
    const existing: NormalizedClass = {
      name: 'Order',
      schema: { type: 'object' },
      properties: [{ name: 'address', data: { type: 'object' }, children: [{ name: 'city', data: { type: 'string' } }] }],
    };
    const imported: NormalizedClass = {
      name: 'Order',
      schema: { type: 'object' },
      properties: [
        {
          name: 'address',
          data: { type: 'object' },
          children: [
            { name: 'city', data: { type: 'string' } },
            { name: 'zip', data: { type: 'string' } },
          ],
        },
      ],
    };

    const plan = planAdditiveClasses([existing], [imported]);

    expect(plan.classes[0].properties[0].children?.map((p) => p.name)).toEqual(['city', 'zip']);
    expect(plan.propertiesAdded).toBe(1);
  });

  test('new classes pass through and classes only the latest version has are carried', () => {
    const plan = planAdditiveClasses(
      [cls('Pet', { id: { type: 'integer' } }), cls('Owner', { id: { type: 'integer' } })],
      [cls('Pet', { id: { type: 'integer' } }), cls('Tag', { label: { type: 'string' } })],
    );

    expect(plan.classes.map((c) => c.name)).toEqual(['Pet', 'Tag']);
    expect(plan.classes[1]).toEqual(cls('Tag', { label: { type: 'string' } }));
    expect(plan.carriedClassNames).toEqual(['Owner']);
    expect(plan.schemasMerged).toBe(1);
    expect(plan.propertiesAdded).toBe(0);
  });

  test('with no latest-version classes the import is unchanged', () => {
    const imported = [cls('Pet', { id: { type: 'integer' } })];
    const plan = planAdditiveClasses([], imported);
    expect(plan.classes).toEqual(imported);
    expect(plan.schemasMerged).toBe(0);
    expect(plan.carriedClassNames).toEqual([]);
  });
});

describe('planAdditivePaths', () => {
  test('existing operations are kept and new methods added; new paths appended; old paths carried', () => {
    const parent = [path('/pets', op('GET', 'stored list')), path('/owners', op('GET'))];
    const incoming = [path('/pets', op('GET', 'spec list'), op('POST')), path('/tags', op('GET'))];

    const plan = planAdditivePaths(parent, incoming);

    expect(plan.paths.map((p) => p.path)).toEqual(['/pets', '/owners', '/tags']);
    expect(plan.paths[0].operations.map((o) => [o.method, o.summary])).toEqual([
      ['GET', 'stored list'],
      ['POST', undefined],
    ]);
    expect(plan.pathsCarried).toBe(1);
    expect(plan.operationsAdded).toBe(1);
  });

  test('a path with no new operation is the existing one, unchanged', () => {
    const existing = path('/pets', op('GET'));
    const plan = planAdditivePaths([existing], [path('/pets', op('GET', 'other'))]);
    expect(plan.paths[0]).toBe(existing);
    expect(plan.operationsAdded).toBe(0);
    expect(plan.pathsCarried).toBe(0);
  });

  test('no latest-version paths gives the spec paths', () => {
    const incoming = [path('/pets', op('GET'))];
    expect(planAdditivePaths([], incoming).paths).toEqual(incoming);
  });
});

describe('describeAdditiveMerge', () => {
  test('lists merged schemas, added properties and what was kept', () => {
    expect(
      describeAdditiveMerge({ schemasMerged: 2, propertiesAdded: 3, schemasCarried: 4, pathsCarried: 5, operationsAdded: 0 }),
    ).toBe('Additive — 2 schemas merged (3 properties added); 4 schemas and 5 paths kept from the latest version');
  });

  test('singular nouns and added operations', () => {
    expect(
      describeAdditiveMerge({ schemasMerged: 1, propertiesAdded: 1, schemasCarried: 1, pathsCarried: 1, operationsAdded: 1 }),
    ).toBe('Additive — 1 schema merged (1 property added), 1 operation added; 1 schema and 1 path kept from the latest version');
  });
});
