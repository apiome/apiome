/** Tests for the pact badge helpers — PFX-1.10 (#6923). */

import { describe, expect, it } from 'vitest';
import { consumersSummary, pactBadgesUrl, parsePactBadges } from '../pactBadges';

const item = { slug: 'ledger-api', name: 'Ledger', status: 'verified', pacts: 2, badge_url: 'https://x.test/b.svg' };

describe('pactBadgesUrl', () => {
  it('builds the route and encodes the slugs', () => {
    expect(pactBadgesUrl('http://api/v1', 'acme', 'led ger')).toBe(
      'http://api/v1/browse/tenants/acme/projects/led%20ger/pact-badges'
    );
  });
});

describe('parsePactBadges', () => {
  it('keeps well-formed items in order', () => {
    expect(parsePactBadges({ pacticipants: [item, { ...item, slug: 'b', status: 'failing' }] })).toHaveLength(2);
  });

  it('is empty for anything that is not a list', () => {
    expect(parsePactBadges(null)).toEqual([]);
    expect(parsePactBadges({})).toEqual([]);
    expect(parsePactBadges({ pacticipants: 'x' })).toEqual([]);
  });

  it('drops an unknown status, a missing field and a non-http badge url', () => {
    const bad = [
      { ...item, status: 'great' },
      { ...item, name: undefined },
      { ...item, badge_url: 'javascript:alert(1)' },
      null,
    ];
    expect(parsePactBadges({ pacticipants: bad })).toEqual([]);
  });

  it('defaults a missing pact count to 0', () => {
    expect(parsePactBadges({ pacticipants: [{ ...item, pacts: undefined }] })[0].pacts).toBe(0);
  });
});

describe('consumers (PFX-7.5)', () => {
  const consumers = [
    { slug: 'web', name: 'Web', status: 'verified' },
    { slug: 'app', name: 'App', status: 'failing' },
    { slug: 'bad', name: 'Bad', status: 'weird' },
    { slug: 3, name: 'Bad' },
  ];

  it('parses well-formed consumers and drops malformed ones', () => {
    const [parsed] = parsePactBadges({ pacticipants: [{ ...item, consumers, consumer_count: 5 }] });
    expect(parsed.consumers.map((c) => c.slug)).toEqual(['web', 'app']);
    expect(parsed.consumer_count).toBe(5);
  });

  it('tolerates an older API with no consumers', () => {
    const [parsed] = parsePactBadges({ pacticipants: [item] });
    expect(parsed.consumers).toEqual([]);
    expect(parsed.consumer_count).toBe(0);
  });

  it('falls back to the listed length when the count is missing or negative', () => {
    const [parsed] = parsePactBadges({ pacticipants: [{ ...item, consumers, consumer_count: -1 }] });
    expect(parsed.consumer_count).toBe(2);
  });

  it('summarises the consumers', () => {
    expect(consumersSummary({ consumer_count: 0, consumers: [] })).toBeNull();
    expect(consumersSummary({ consumer_count: 1, consumers: [{ slug: 'a', name: 'A', status: 'unknown' }] })).toBe(
      '1 consumer'
    );
    expect(
      consumersSummary({
        consumer_count: 3,
        consumers: [
          { slug: 'a', name: 'A', status: 'verified' },
          { slug: 'b', name: 'B', status: 'verified' },
          { slug: 'c', name: 'C', status: 'failing' },
        ],
      })
    ).toBe('3 consumers · 2 verified · 1 failing');
  });
});
