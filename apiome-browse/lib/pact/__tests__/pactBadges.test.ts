/** Tests for the pact badge helpers — PFX-1.10 (#6923). */

import { describe, expect, it } from 'vitest';
import { pactBadgesUrl, parsePactBadges } from '../pactBadges';

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
