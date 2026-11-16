import { describe, expect, it } from 'vitest';
import { versionHref } from '../anchors';
import {
  buildFindItems,
  findInVersion,
  isFindActive,
  matchesFindItem,
  nextFindAnchor,
  withFindParam,
} from '../findInVersion';
import { parseQuery } from '../query';

const petstore = {
  openapi: '3.1.0',
  info: { title: 'Petstore', version: '1.0.0' },
  paths: {
    '/pets': {
      get: { summary: 'List pets', operationId: 'listPets', tags: ['pets'], responses: { '200': {} } },
      post: { summary: 'Create a pet', tags: ['pets'], responses: { '201': {}, '422': {} } },
    },
    '/pets/{petId}': {
      parameters: [{ name: 'petId', in: 'path' }],
      get: { summary: 'Show pet by id', tags: ['pets', 'admin'], responses: { '200': {}, '404': {} } },
      delete: { summary: 'Remove a pet', description: 'Deletes the pet permanently.', responses: { '204': {} } },
    },
    '/owners/{ownerId}': {
      delete: { summary: 'Remove an owner', parameters: [{ name: 'ownerId', in: 'path' }], responses: { '204': {} } },
    },
  },
  components: {
    schemas: {
      Pet: {
        title: 'A pet',
        description: 'Something with fur.',
        properties: { id: {}, name: {}, tag: {} },
      },
      Owner: { allOf: [{ properties: { email: {} } }, { properties: { nickname: {} } }] },
    },
  },
};

const items = buildFindItems(petstore, 'openapi');
const run = (q: string) => findInVersion(items, parseQuery(q));

describe('buildFindItems', () => {
  it('projects OpenAPI operations then sorted schemas, with the page anchor ids', () => {
    expect(items.map((i) => i.anchorId)).toEqual([
      'op-get-pets',
      'op-post-pets',
      'op-get-pets-petid',
      'op-delete-pets-petid',
      'op-delete-owners-ownerid',
      'schema-Owner',
      'schema-Pet',
    ]);
    expect(items[0]).toMatchObject({ kind: 'operation', method: 'GET', path: '/pets' });
    expect(items[5].kind).toBe('schema');
  });

  it('indexes parameters (path-level too), response codes, tags and descriptions', () => {
    const getById = items.find((i) => i.anchorId === 'op-get-pets-petid')!;
    expect(getById.haystack).toContain('petid');
    expect(getById.haystack).toContain('404');
    expect(getById.haystack).toContain('admin');
    expect(items.find((i) => i.anchorId === 'op-delete-pets-petid')!.haystack).toContain('permanently');
  });

  it('indexes schema properties, including allOf members', () => {
    expect(items.find((i) => i.anchorId === 'schema-Pet')!.haystack).toContain('fur');
    expect(items.find((i) => i.anchorId === 'schema-Owner')!.haystack).toContain('nickname');
  });

  it('reads Arazzo workflows and JSON Schema definitions', () => {
    const wf = buildFindItems({ workflows: [{ workflowId: 'checkout', summary: 'Buy a pet' }] }, 'arazzo');
    expect(wf).toEqual([{ kind: 'workflow', anchorId: 'wf-checkout', haystack: 'checkout\nbuy a pet' }]);
    const defs = buildFindItems({ $defs: { 'Pet Tag': { properties: { label: {} } } } }, 'jsonschema');
    expect(defs).toHaveLength(1);
    expect(defs[0]).toMatchObject({ kind: 'schema', anchorId: 'def-Pet-Tag' });
    expect(defs[0].haystack).toContain('label');
  });

  it('returns nothing for a spec that is not an object', () => {
    expect(buildFindItems(null, 'openapi')).toEqual([]);
    expect(buildFindItems('nope', 'arazzo')).toEqual([]);
    expect(buildFindItems({}, 'jsonschema')).toEqual([]);
  });
});

describe('findInVersion — words', () => {
  it('matches a word anywhere in the item, case-insensitively', () => {
    expect(run('OWNER').anchors).toEqual(['op-delete-owners-ownerid', 'schema-Owner']);
  });

  it('ANDs several words', () => {
    expect(run('remove pet').anchors).toEqual(['op-delete-pets-petid']);
  });

  it('matches a response code and a schema property', () => {
    expect(run('422').anchors).toEqual(['op-post-pets']);
    expect(run('email').anchors).toEqual(['schema-Owner']);
  });

  it('drops items that mention a negated word', () => {
    expect(run('pet -remove').anchors).not.toContain('op-delete-pets-petid');
  });
});

describe('findInVersion — phrases', () => {
  it('matches the words together, in order', () => {
    expect(run('"create a pet"').anchors).toEqual(['op-post-pets']);
    expect(run('"pet a create"').anchors).toEqual([]);
  });
});

describe('findInVersion — method:', () => {
  it('keeps only operations with the method, and drops schemas', () => {
    expect(run('method:delete').anchors).toEqual(['op-delete-pets-petid', 'op-delete-owners-ownerid']);
  });

  it('ORs repeated methods', () => {
    expect(run('method:GET method:POST').anchors).toEqual(['op-get-pets', 'op-post-pets', 'op-get-pets-petid']);
  });

  it('narrows `method:DELETE pets` to DELETE operations on pet paths', () => {
    const result = run('method:DELETE pets');
    expect(result.anchors).toEqual(['op-delete-pets-petid']);
    expect(result.needles).toEqual(['pets']);
  });
});

describe('findInVersion — path:', () => {
  it('keeps operations whose path contains the value', () => {
    expect(run('path:/owners').anchors).toEqual(['op-delete-owners-ownerid']);
    expect(run('path:{petId}').anchors).toEqual(['op-get-pets-petid', 'op-delete-pets-petid']);
  });

  it('is case-insensitive and drops schemas', () => {
    expect(run('path:/PETS').anchors).toHaveLength(4);
    expect(run('path:pet').anchors.some((a) => a.startsWith('schema-'))).toBe(false);
  });
});

describe('findInVersion — type:', () => {
  it('keeps one kind, with the catalog aliases', () => {
    expect(run('type:schema').anchors).toEqual(['schema-Owner', 'schema-Pet']);
    expect(run('type:model').anchors).toEqual(['schema-Owner', 'schema-Pet']);
    expect(run('type:endpoint owner').anchors).toEqual(['op-delete-owners-ownerid']);
  });

  it('maps finer catalog kinds to the item that holds them', () => {
    expect(run('type:property email').anchors).toEqual(['schema-Owner']);
    expect(run('type:response 404').anchors).toEqual(['op-get-pets-petid']);
  });

  it('understands workflow, and matches nothing for an unknown kind', () => {
    const wf = buildFindItems({ workflows: [{ workflowId: 'checkout' }] }, 'arazzo');
    expect(findInVersion(wf, parseQuery('type:workflow')).anchors).toEqual(['wf-checkout']);
    expect(run('type:banana').anchors).toEqual([]);
  });
});

describe('findInVersion — result shape', () => {
  it('returns every item, unfiltered, for an empty query', () => {
    const result = run('');
    expect(result.active).toBe(false);
    expect(result.anchors).toHaveLength(7);
    expect(result.total).toBe(7);
    expect(result.needles).toEqual([]);
  });

  it('ignores catalog-only filters', () => {
    expect(isFindActive(parseQuery('org:acme'))).toBe(false);
    expect(run('org:acme pets').anchors).toEqual(run('pets').anchors);
  });

  it('counts an anchor once even when the item repeats', () => {
    const twice = [...items, items[0]];
    const result = findInVersion(twice, parseQuery('listPets'));
    expect(result.anchors).toEqual(['op-get-pets']);
    expect(result.total).toBe(7);
    expect(result.matched.has('op-get-pets')).toBe(true);
  });

  it('reports no matches', () => {
    const result = run('giraffe');
    expect(result.active).toBe(true);
    expect(result.anchors).toEqual([]);
  });

  it('matchesFindItem agrees with findInVersion', () => {
    const parsed = parseQuery('method:post pet');
    expect(items.filter((i) => matchesFindItem(i, parsed)).map((i) => i.anchorId)).toEqual(['op-post-pets']);
  });
});

describe('nextFindAnchor', () => {
  const anchors = ['a', 'b', 'c'];
  it('starts at the first (or last) match', () => {
    expect(nextFindAnchor(anchors, null)).toBe('a');
    expect(nextFindAnchor(anchors, 'zzz', -1)).toBe('c');
  });
  it('steps and wraps around', () => {
    expect(nextFindAnchor(anchors, 'a')).toBe('b');
    expect(nextFindAnchor(anchors, 'c')).toBe('a');
    expect(nextFindAnchor(anchors, 'a', -1)).toBe('c');
  });
  it('returns null when nothing matches', () => {
    expect(nextFindAnchor([], 'a')).toBeNull();
  });
});

describe('withFindParam / versionHref', () => {
  it('sets, replaces and removes ?find= while keeping other params and the hash', () => {
    expect(withFindParam('/t/p/1?tab=specification#op-get-pets', 'method:DELETE pets')).toBe(
      '/t/p/1?tab=specification&find=method%3ADELETE+pets#op-get-pets'
    );
    expect(withFindParam('/t/p/1?find=old', 'new')).toBe('/t/p/1?find=new');
    expect(withFindParam('/t/p/1?find=old#x', '  ')).toBe('/t/p/1#x');
  });

  it('builds a deep link with an anchor and a pre-filled query', () => {
    expect(versionHref('acme', 'pets', '1.0', 'op-delete-pets-petid', 'method:DELETE pets')).toBe(
      '/tenant/acme/pets/1.0?find=method%3ADELETE%20pets#op-delete-pets-petid'
    );
    expect(versionHref('acme', 'pets', '1.0', null, '  ')).toBe('/tenant/acme/pets/1.0');
  });
});
