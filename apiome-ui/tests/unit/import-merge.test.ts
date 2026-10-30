/**
 * Merge planner for an import into an existing project — classes, properties (nested too), paths
 * and operations: additive (#591, "add what is new, keep what exists") and override (#592,
 * "imported values take precedence").
 */

import { describe, expect, test } from '@jest/globals';
import { describeImportMerge, planMergeClasses, planMergePaths } from '../../lib/import-merge';
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

describe('planMergeClasses: additive', () => {
  test('a same-named class keeps its existing properties and gains the new ones', () => {
    const existing = cls('Pet', { id: { type: 'integer' }, name: { type: 'string', maxLength: 50 } }, 'Stored pet');
    const imported = cls('Pet', { name: { type: 'string', maxLength: 10 }, tag: { type: 'string' } }, 'Spec pet');

    const plan = planMergeClasses([existing], [imported], 'additive');

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

    const plan = planMergeClasses([existing], [imported], 'additive');

    expect(plan.classes[0].properties[0].children?.map((p) => p.name)).toEqual(['city', 'zip']);
    expect(plan.propertiesAdded).toBe(1);
  });

  test('new classes pass through and classes only the latest version has are carried', () => {
    const plan = planMergeClasses(
      [cls('Pet', { id: { type: 'integer' } }), cls('Owner', { id: { type: 'integer' } })],
      [cls('Pet', { id: { type: 'integer' } }), cls('Tag', { label: { type: 'string' } })], 'additive');

    expect(plan.classes.map((c) => c.name)).toEqual(['Pet', 'Tag']);
    expect(plan.classes[1]).toEqual(cls('Tag', { label: { type: 'string' } }));
    expect(plan.carriedClassNames).toEqual(['Owner']);
    expect(plan.schemasMerged).toBe(1);
    expect(plan.propertiesAdded).toBe(0);
  });

  test('with no latest-version classes the import is unchanged', () => {
    const imported = [cls('Pet', { id: { type: 'integer' } })];
    const plan = planMergeClasses([], imported, 'additive');
    expect(plan.classes).toEqual(imported);
    expect(plan.schemasMerged).toBe(0);
    expect(plan.carriedClassNames).toEqual([]);
  });
});

describe('planMergePaths: additive', () => {
  test('existing operations are kept and new methods added; new paths appended; old paths carried', () => {
    const parent = [path('/pets', op('GET', 'stored list')), path('/owners', op('GET'))];
    const incoming = [path('/pets', op('GET', 'spec list'), op('POST')), path('/tags', op('GET'))];

    const plan = planMergePaths(parent, incoming, 'additive');

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
    const plan = planMergePaths([existing], [path('/pets', op('GET', 'other'))], 'additive');
    expect(plan.paths[0]).toBe(existing);
    expect(plan.operationsAdded).toBe(0);
    expect(plan.pathsCarried).toBe(0);
  });

  test('no latest-version paths gives the spec paths', () => {
    const incoming = [path('/pets', op('GET'))];
    expect(planMergePaths([], incoming, 'additive').paths).toEqual(incoming);
  });
});

describe('planMergeClasses: override (#592)', () => {
  test('the spec wins for a property both define; existing-only properties are kept', () => {
    const existing = cls(
      'Pet',
      { id: { type: 'integer' }, name: { type: 'string', maxLength: 50, format: 'name' }, nickname: { type: 'string' } },
      'Stored pet',
    );
    const imported = cls('Pet', { name: { type: 'string', maxLength: 100 }, tag: { type: 'string' } }, 'Spec pet');

    const plan = planMergeClasses([existing], [imported], 'override');

    const pet = plan.classes[0];
    expect(pet.properties.map((p) => p.name)).toEqual(['id', 'name', 'nickname', 'tag']);
    // The spec's whole definition replaces the stored one — not the "stricter" of the two.
    expect(pet.properties.find((p) => p.name === 'name')?.data).toEqual({ type: 'string', maxLength: 100 });
    expect(pet.description).toBe('Spec pet');
    expect(plan.schemasMerged).toBe(1);
    expect(plan.propertiesAdded).toBe(1);
    expect(plan.propertiesUpdated).toBe(1);
  });

  test('a stored description is kept when the spec has none, and equal definitions are not "updated"', () => {
    const existing = cls('Pet', { id: { type: 'integer' } }, 'Stored pet');
    const imported = cls('Pet', { id: { type: 'integer' } });
    const plan = planMergeClasses([existing], [imported], 'override');
    expect(plan.classes[0].description).toBe('Stored pet');
    expect(plan.propertiesUpdated).toBe(0);
  });

  test('nested properties merge the same way', () => {
    const existing: NormalizedClass = {
      name: 'Order',
      schema: { type: 'object' },
      properties: [
        {
          name: 'address',
          data: { type: 'object' },
          children: [
            { name: 'city', data: { type: 'string', maxLength: 20 } },
            { name: 'country', data: { type: 'string' } },
          ],
        },
      ],
    };
    const imported: NormalizedClass = {
      name: 'Order',
      schema: { type: 'object' },
      properties: [
        {
          name: 'address',
          data: { type: 'object' },
          children: [
            { name: 'city', data: { type: 'string', maxLength: 40 } },
            { name: 'zip', data: { type: 'string' } },
          ],
        },
      ],
    };

    const plan = planMergeClasses([existing], [imported], 'override');

    const children = plan.classes[0].properties[0].children ?? [];
    expect(children.map((p) => p.name)).toEqual(['city', 'country', 'zip']);
    expect(children[0].data).toEqual({ type: 'string', maxLength: 40 });
    expect(plan.propertiesAdded).toBe(1);
    expect(plan.propertiesUpdated).toBe(1);
  });

  test('classes only the latest version has are carried, new ones pass through', () => {
    const plan = planMergeClasses(
      [cls('Pet', { id: { type: 'integer' } }), cls('Owner', { id: { type: 'integer' } })],
      [cls('Tag', { label: { type: 'string' } })],
      'override',
    );
    expect(plan.classes.map((c) => c.name)).toEqual(['Tag']);
    expect(plan.carriedClassNames).toEqual(['Pet', 'Owner']);
  });
});

describe('planMergePaths: override (#592)', () => {
  test("the spec's operation replaces a stored one; other stored operations stay; new ones are added", () => {
    const parent = [path('/pets', op('GET', 'stored list'), op('DELETE')), path('/owners', op('GET'))];
    const incoming = [path('/pets', op('GET', 'spec list'), op('POST')), path('/tags', op('GET'))];

    const plan = planMergePaths(parent, incoming, 'override');

    expect(plan.paths.map((p) => p.path)).toEqual(['/pets', '/owners', '/tags']);
    expect(plan.paths[0].operations.map((o) => [o.method, o.summary])).toEqual([
      ['GET', 'spec list'],
      ['DELETE', undefined],
      ['POST', undefined],
    ]);
    expect(plan.operationsUpdated).toBe(1);
    expect(plan.operationsAdded).toBe(1);
    expect(plan.pathsCarried).toBe(1);
  });

  test('an identical operation (keys set to undefined included) is not counted as updated', () => {
    const stored = { ...op('GET', 'list'), description: undefined };
    const plan = planMergePaths([path('/pets', stored)], [path('/pets', op('GET', 'list'))], 'override');
    expect(plan.operationsUpdated).toBe(0);
  });

  test("the spec's path summary wins, the stored one is kept when the spec has none", () => {
    const parent = [{ ...path('/pets', op('GET')), summary: 'Stored' }, { ...path('/owners', op('GET')), summary: 'Owners' }];
    const incoming = [{ ...path('/pets', op('GET')), summary: 'Spec' }, path('/owners', op('GET'))];
    const plan = planMergePaths(parent, incoming, 'override');
    expect(plan.paths.map((p) => p.summary)).toEqual(['Spec', 'Owners']);
  });
});

describe('describeImportMerge', () => {
  const stats = { propertiesUpdated: 0, operationsUpdated: 0 };

  test('additive: merged schemas, added properties and what was kept', () => {
    expect(
      describeImportMerge({ ...stats, strategy: 'additive', schemasMerged: 2, propertiesAdded: 3, schemasCarried: 4, pathsCarried: 5, operationsAdded: 0 }),
    ).toBe('Additive — 2 schemas merged (3 properties added); 4 schemas and 5 paths kept from the latest version');
  });

  test('additive: singular nouns and added operations', () => {
    expect(
      describeImportMerge({ ...stats, strategy: 'additive', schemasMerged: 1, propertiesAdded: 1, schemasCarried: 1, pathsCarried: 1, operationsAdded: 1 }),
    ).toBe('Additive — 1 schema merged (1 property added), 1 operation added; 1 schema and 1 path kept from the latest version');
  });

  test('override: also says what was updated', () => {
    expect(
      describeImportMerge({
        strategy: 'override',
        schemasMerged: 2,
        propertiesAdded: 1,
        propertiesUpdated: 2,
        schemasCarried: 0,
        pathsCarried: 3,
        operationsAdded: 0,
        operationsUpdated: 1,
      }),
    ).toBe('Override — 2 schemas merged (1 property added, 2 updated), 1 operation updated; 0 schemas and 3 paths kept from the latest version');
  });
});
