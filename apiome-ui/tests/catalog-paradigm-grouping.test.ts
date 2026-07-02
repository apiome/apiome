/**
 * Unit tests for the Catalog paradigm grouper (MFI-24.2, #4082).
 *
 * Asserts the pure grouping/ordering contract the card view relies on: items are bucketed by
 * resolved paradigm, sections come out in the fixed graph→rpc→event→rest→data-schema order, empty
 * paradigms are omitted, unknown/absent/`agent` paradigms fall into a trailing "Other" bucket (never
 * dropped), and input order is preserved within each group (so a sorted list stays sorted).
 */

import {
  groupCatalogItemsByParadigm,
  CATALOG_PARADIGM_ORDER,
  CATALOG_PARADIGM_OTHER_ID,
  type CatalogParadigmItem,
} from '@/app/utils/catalog-paradigm-grouping';

type Item = CatalogParadigmItem & { id: string };

const item = (id: string, protocol: string | null | undefined): Item => ({ id, protocol });

const ids = (groups: ReturnType<typeof groupCatalogItemsByParadigm<Item>>) =>
  groups.map((g) => g.id);
const idsInGroup = (groups: ReturnType<typeof groupCatalogItemsByParadigm<Item>>, id: string) =>
  groups.find((g) => g.id === id)?.items.map((i) => i.id) ?? [];

describe('groupCatalogItemsByParadigm', () => {
  it('returns [] for an empty list', () => {
    expect(groupCatalogItemsByParadigm([])).toEqual([]);
  });

  it('emits sections in the fixed graph→rpc→event→rest→data-schema order regardless of input order', () => {
    const input = [
      item('r1', 'rest'),
      item('d1', 'data-schema'),
      item('g1', 'graph'),
      item('e1', 'event'),
      item('rpc1', 'rpc'),
    ];
    expect(ids(groupCatalogItemsByParadigm(input))).toEqual([
      'graph',
      'rpc',
      'event',
      'rest',
      'dataschema',
    ]);
  });

  it('matches the exported fixed order for a one-of-each list', () => {
    const input = CATALOG_PARADIGM_ORDER.map((id) => item(id, id));
    expect(ids(groupCatalogItemsByParadigm(input))).toEqual([...CATALOG_PARADIGM_ORDER]);
  });

  it('omits empty paradigms', () => {
    const input = [item('g1', 'graph'), item('e1', 'event')];
    const groups = groupCatalogItemsByParadigm(input);
    expect(ids(groups)).toEqual(['graph', 'event']);
  });

  it('reports a live count and label per section', () => {
    const input = [item('g1', 'graph'), item('g2', 'graph'), item('r1', 'rpc')];
    const groups = groupCatalogItemsByParadigm(input);
    const graph = groups.find((g) => g.id === 'graph');
    expect(graph?.items).toHaveLength(2);
    expect(graph?.label).toBe('Graph');
    expect(groups.find((g) => g.id === 'rpc')?.items).toHaveLength(1);
  });

  it('resolves punctuation/case variants of data-schema into one bucket', () => {
    const input = [item('a', 'data-schema'), item('b', 'data_schema'), item('c', 'DataSchema')];
    const groups = groupCatalogItemsByParadigm(input);
    expect(ids(groups)).toEqual(['dataschema']);
    expect(idsInGroup(groups, 'dataschema')).toEqual(['a', 'b', 'c']);
  });

  it('preserves input (sorted) order within a group', () => {
    const input = [item('g3', 'graph'), item('g1', 'graph'), item('g2', 'graph')];
    expect(idsInGroup(groupCatalogItemsByParadigm(input), 'graph')).toEqual(['g3', 'g1', 'g2']);
  });

  it('collects unknown, absent and agent paradigms into a trailing Other bucket', () => {
    const input = [
      item('g1', 'graph'),
      item('u1', 'quantum'),
      item('n1', null),
      item('n2', undefined),
      item('a1', 'agent'),
    ];
    const groups = groupCatalogItemsByParadigm(input);
    expect(ids(groups)).toEqual(['graph', CATALOG_PARADIGM_OTHER_ID]);
    const other = groups.find((g) => g.id === CATALOG_PARADIGM_OTHER_ID);
    expect(other?.label).toBe('Other');
    expect(other?.items.map((i) => i.id)).toEqual(['u1', 'n1', 'n2', 'a1']);
  });

  it('places Other last even when only Other has items', () => {
    const input = [item('a1', 'agent'), item('n1', null)];
    const groups = groupCatalogItemsByParadigm(input);
    expect(ids(groups)).toEqual([CATALOG_PARADIGM_OTHER_ID]);
  });

  it('never drops an item — every input lands in exactly one group', () => {
    const input = [
      item('g1', 'graph'),
      item('r1', 'rpc'),
      item('e1', 'event'),
      item('rest1', 'rest'),
      item('d1', 'data-schema'),
      item('x1', 'mystery'),
    ];
    const total = groupCatalogItemsByParadigm(input).reduce((n, g) => n + g.items.length, 0);
    expect(total).toBe(input.length);
  });
});
