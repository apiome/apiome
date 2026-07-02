/**
 * Unit tests for the parsed-model helpers (MFI-25.3, #4088).
 *
 * These pin the two pure, presentation-agnostic pieces the Overview relies on: the tag → tone color
 * map (`parsedTagToneClass`) and the `summaryNote` derivation (`deriveParsedSummaryNote`), including
 * pluralization, first-seen tag order, and the empty/absent degradation.
 */

import {
  deriveParsedSummaryNote,
  filterParsedEntities,
  parsedEntityDefaultOpen,
  parsedEntityMatchesFilter,
  parsedGroupToJson,
  parsedTagToneClass,
  PARSED_LARGE_GROUP_ENTITY_COUNT,
  PARSED_SMALL_ENTITY_MAX_FIELDS,
  type CatalogParsedEntity,
  type CatalogParsedGroup,
} from '../src/app/components/ade/dashboard/catalog/CatalogParsedModel';

/** Build a parsed entity with `n` throwaway fields for the default-open / JSON helpers. */
function entity(
  name: string,
  tag: string,
  fieldCount: number,
  meta: string | null = null,
): CatalogParsedEntity {
  return {
    name,
    tag,
    meta,
    fields: Array.from({ length: fieldCount }, (_, i) => ({
      name: `f${i}`,
      type: 'String',
      description: null,
      required: false,
    })),
  };
}

describe('parsedTagToneClass', () => {
  it('maps known tags to their tone (case-insensitive)', () => {
    expect(parsedTagToneClass('QUERY')).toContain('bg-blue-100');
    expect(parsedTagToneClass('mutation')).toContain('bg-amber-100');
    expect(parsedTagToneClass('Subscription')).toContain('bg-violet-100');
    expect(parsedTagToneClass('SERVICE')).toContain('bg-emerald-100');
    expect(parsedTagToneClass('CHANNEL')).toContain('bg-violet-100');
    expect(parsedTagToneClass('DELETE')).toContain('bg-rose-100');
  });

  it('falls back to slate for unknown or empty tags', () => {
    expect(parsedTagToneClass('WIDGET')).toContain('bg-slate-100');
    expect(parsedTagToneClass('')).toContain('bg-slate-100');
    expect(parsedTagToneClass(null)).toContain('bg-slate-100');
    expect(parsedTagToneClass(undefined)).toContain('bg-slate-100');
  });
});

describe('deriveParsedSummaryNote', () => {
  it('tallies entities per tag in first-seen order across groups, pluralizing', () => {
    const groups: CatalogParsedGroup[] = [
      {
        title: 'Operations',
        subtitle: null,
        entities: [
          { name: 'a', tag: 'QUERY', meta: null, fields: [] },
          { name: 'b', tag: 'QUERY', meta: null, fields: [] },
          { name: 'c', tag: 'MUTATION', meta: null, fields: [] },
        ],
      },
      {
        title: 'Types',
        subtitle: null,
        entities: [{ name: 'T', tag: 'OBJECT', meta: null, fields: [] }],
      },
    ];
    expect(deriveParsedSummaryNote(groups)).toBe('2 queries · 1 mutation · 1 object');
  });

  it('pluralizes tags ending in a consonant + y and sibilants correctly', () => {
    const groups: CatalogParsedGroup[] = [
      {
        title: 'Mixed',
        subtitle: null,
        entities: [
          { name: 'e1', tag: 'ENTITY SET', meta: null, fields: [] },
          { name: 'e2', tag: 'ENTITY SET', meta: null, fields: [] },
          { name: 'm1', tag: 'MESSAGE', meta: null, fields: [] },
          { name: 'm2', tag: 'MESSAGE', meta: null, fields: [] },
        ],
      },
    ];
    expect(deriveParsedSummaryNote(groups)).toBe('2 entity sets · 2 messages');
  });

  it('ignores blank tags and returns null when there is nothing to summarize', () => {
    expect(deriveParsedSummaryNote(null)).toBeNull();
    expect(deriveParsedSummaryNote(undefined)).toBeNull();
    expect(deriveParsedSummaryNote([])).toBeNull();
    expect(
      deriveParsedSummaryNote([{ title: 'Empty', subtitle: null, entities: [] }]),
    ).toBeNull();
    expect(
      deriveParsedSummaryNote([
        { title: 'Blanks', subtitle: null, entities: [{ name: 'x', tag: '  ', meta: null, fields: [] }] },
      ]),
    ).toBeNull();
  });
});

describe('parsedEntityDefaultOpen (MFI-28.3)', () => {
  it('never opens a field-less entity (nothing to mount)', () => {
    expect(parsedEntityDefaultOpen(0, 1)).toBe(false);
    expect(parsedEntityDefaultOpen(0, 200)).toBe(false);
  });

  it('opens a small entity in a small group but not a big one', () => {
    expect(parsedEntityDefaultOpen(PARSED_SMALL_ENTITY_MAX_FIELDS, 5)).toBe(true);
    expect(parsedEntityDefaultOpen(1, 5)).toBe(true);
    expect(parsedEntityDefaultOpen(PARSED_SMALL_ENTITY_MAX_FIELDS + 1, 5)).toBe(false);
  });

  it('keeps every entity collapsed in a large group so it renders fast', () => {
    const big = PARSED_LARGE_GROUP_ENTITY_COUNT + 1;
    expect(parsedEntityDefaultOpen(1, big)).toBe(false);
    expect(parsedEntityDefaultOpen(PARSED_SMALL_ENTITY_MAX_FIELDS, big)).toBe(false);
    // A 200-entity model: nothing defaults open.
    expect(parsedEntityDefaultOpen(2, 200)).toBe(false);
  });
});

describe('parsedEntityMatchesFilter / filterParsedEntities (MFI-28.3)', () => {
  const entities = [
    entity('OrderLine', 'OBJECT', 3),
    entity('placeOrder', 'MUTATION', 0),
    entity('Payment', 'OBJECT', 2),
  ];

  it('matches on name or tag, case-insensitively', () => {
    expect(parsedEntityMatchesFilter(entities[0], 'order')).toBe(true); // name
    expect(parsedEntityMatchesFilter(entities[0], 'OBJECT')).toBe(true); // tag
    expect(parsedEntityMatchesFilter(entities[2], 'mutation')).toBe(false);
  });

  it('treats a blank query as "everything matches"', () => {
    expect(parsedEntityMatchesFilter(entities[2], '')).toBe(true);
    expect(parsedEntityMatchesFilter(entities[2], '   ')).toBe(true);
    expect(filterParsedEntities(entities, '')).toHaveLength(3);
  });

  it('narrows the list live by name or tag', () => {
    expect(filterParsedEntities(entities, 'order').map((e) => e.name)).toEqual([
      'OrderLine',
      'placeOrder',
    ]);
    expect(filterParsedEntities(entities, 'object').map((e) => e.name)).toEqual([
      'OrderLine',
      'Payment',
    ]);
    expect(filterParsedEntities(entities, 'nope')).toHaveLength(0);
  });
});

describe('parsedGroupToJson (MFI-28.3)', () => {
  it('serializes the group title/subtitle/entities as pretty normalized JSON', () => {
    const group: CatalogParsedGroup = {
      title: 'Types',
      subtitle: 'reconstructed',
      entities: [entity('Order', 'OBJECT', 1, '1 field')],
    };
    const json = parsedGroupToJson(group);
    const parsed = JSON.parse(json);
    expect(parsed.title).toBe('Types');
    expect(parsed.subtitle).toBe('reconstructed');
    expect(parsed.entities[0]).toMatchObject({ name: 'Order', tag: 'OBJECT', meta: '1 field' });
    expect(parsed.entities[0].fields).toHaveLength(1);
    // Pretty-printed (indented), not a single line.
    expect(json).toContain('\n');
  });

  it('normalizes an absent subtitle to null', () => {
    const json = parsedGroupToJson({ title: 'Ops', entities: [] });
    expect(JSON.parse(json).subtitle).toBeNull();
  });
});
