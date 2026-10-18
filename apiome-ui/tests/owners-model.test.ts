/**
 * The ownership model — CDG-2.4 (#5963): owner parsing, the `team` parameter rule every BFF route
 * applies, and the team page's helpers.
 */

import { describe, expect, test } from '@jest/globals';
import {
  groupOwnedByKind,
  ownedEntityHref,
  ownerDescription,
  ownerSourceLabel,
  parseEntityOwner,
  sanitizeTeamParam,
  teamLinks,
  withTeamParam,
  type OwnedEntity,
} from '../lib/owners';

describe('parseEntityOwner', () => {
  test('reads the envelope shape', () => {
    expect(
      parseEntityOwner({ team: { id: 't', slug: 'payments', name: 'Payments' }, status: 'suggested', source: 'codeowners' })
    ).toEqual({ team: { id: 't', slug: 'payments', name: 'Payments' }, status: 'suggested', source: 'codeowners' });
  });

  test.each([null, undefined, 'payments', {}, { team: { slug: 'x' } }, { team: { slug: 'x', name: 'X' }, status: 'maybe' }])(
    'refuses %p',
    (value) => {
      expect(parseEntityOwner(value)).toBeNull();
    }
  );
});

describe('describing an owner', () => {
  test('says who owns it, or who is suggested and why', () => {
    const team = { id: 't', slug: 'payments', name: 'Payments' };
    expect(ownerDescription(null)).toBe('No owner');
    expect(ownerDescription({ team, status: 'confirmed', source: 'manual' })).toBe('Owned by Payments');
    expect(ownerDescription({ team, status: 'suggested', source: 'gateway_tag' })).toBe(
      'Suggested owner: Payments (Gateway tag)'
    );
    expect(ownerSourceLabel('spec_extension')).toBe('Spec');
    expect(ownerSourceLabel('something-new')).toBe('something-new');
  });
});

describe('the team parameter', () => {
  test('forwards only a slug', () => {
    expect(sanitizeTeamParam(' Payments ')).toBe('payments');
    for (const bad of [null, '', 'pay ments', '../owners', '-payments', 'a'.repeat(129)]) {
      expect(sanitizeTeamParam(bad)).toBeNull();
    }
  });

  test('sets or clears it on a query being built', () => {
    expect(withTeamParam(new URLSearchParams('a=1'), 'payments').toString()).toBe('a=1&team=payments');
    expect(withTeamParam(new URLSearchParams('team=old'), null).toString()).toBe('');
    expect(withTeamParam(new URLSearchParams(), 'not a slug').toString()).toBe('');
  });
});

describe('team page helpers', () => {
  const owned: OwnedEntity[] = [
    { kind: 'connector', id: 'n', name: 'Kong', source: 'manual' },
    { kind: 'project', id: 'p', name: 'API', source: 'manual' },
    { kind: 'consumer', id: 'c', name: 'Checkout', source: 'manual' },
  ];

  test('groups owned entities in kind order', () => {
    expect(groupOwnedByKind(owned).map(([kind]) => kind)).toEqual(['project', 'consumer', 'connector']);
  });

  test('links each kind to its page, and a consumer nowhere', () => {
    expect(owned.map(ownedEntityHref)).toEqual([
      '/ade/dashboard/connectors/n',
      '/ade/dashboard/versions?projectId=p',
      null,
    ]);
    expect(ownedEntityHref({ kind: 'mcp_endpoint', id: 'm 1' })).toBe('/ade/dashboard/mcp/m%201');
  });

  test('lists the links a team has, in a fixed order', () => {
    expect(teamLinks({ docs_url: 'https://d', contact_email: 'a@b.c', chat_url: null })).toEqual([
      ['Contact', 'mailto:a@b.c'],
      ['Docs', 'https://d'],
    ]);
  });
});
