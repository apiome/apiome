/**
 * Export delivery profiles — the pure half (MFX-38.4, #4331).
 *
 * The bodies a draft becomes for `POST` and `PATCH` (one channel block, a webhook secret only when
 * typed, a destination only when it changed), the client-side mirror of the REST rules, the one-line
 * destination, and the outcome tones.
 */

import {
  createBody,
  deliveryEventCount,
  destinationSummary,
  draftFromProfile,
  emptyDraft,
  needsWebhookUrl,
  outcomeTone,
  updateBody,
  validateDraft,
  type DeliveryProfile,
} from '../src/app/components/ade/export-studio/delivery/deliveryProfilesModel';

const SECRET = 'a-long-enough-signing-secret';

function profile(partial: Partial<DeliveryProfile>): DeliveryProfile {
  return {
    id: 'p1',
    name: 'lake',
    description: null,
    channel: 'object_storage',
    destination: { credentialId: 'c1', bucket: 'data-lake', prefix: 'exports', partitioning: ['artifact'] },
    credentialRef: { kind: 'storage_credential', id: 'c1' },
    ...partial,
  };
}

describe('createBody', () => {
  it('sends the chosen channel block only', () => {
    const draft = emptyDraft('git');
    draft.name = ' repo ';
    draft.git = { repositoryId: 'r1', targetPath: 'specs', baseBranch: '', mode: 'commit' };
    draft.webhook.url = 'https://ignored.example.com';
    expect(createBody(draft)).toEqual({
      name: 'repo',
      channel: 'git',
      git: { repositoryId: 'r1', targetPath: 'specs', mode: 'commit' },
    });
  });

  it('carries a webhook secret and a description when given', () => {
    const draft = emptyDraft('webhook');
    draft.name = 'ci';
    draft.description = 'CI hook';
    draft.webhook = { url: 'https://ci.example.com/h', secret: SECRET, artifact: 'fetch' };
    expect(createBody(draft)).toEqual({
      name: 'ci',
      description: 'CI hook',
      channel: 'webhook',
      webhook: { url: 'https://ci.example.com/h', artifact: 'fetch', secret: SECRET },
    });
  });
});

describe('updateBody', () => {
  it('leaves the destination out when only the name changed', () => {
    const original = draftFromProfile(profile({}));
    const draft = { ...original, name: 'lake-2' };
    expect(updateBody(draft, original)).toEqual({ name: 'lake-2', description: '' });
  });

  it('sends the whole destination when a field of it changed', () => {
    const original = draftFromProfile(profile({}));
    const draft = { ...original, objectStorage: { ...original.objectStorage, bucket: 'other' } };
    expect(updateBody(draft, original).objectStorage).toEqual({
      credentialId: 'c1', bucket: 'other', prefix: 'exports', partitioning: ['artifact'],
    });
  });

  it('sends a webhook destination when a new secret was typed, and needs the URL then', () => {
    const stored = profile({ channel: 'webhook', destination: { url: 'https://h.example.com/p?…', artifact: 'auto' } });
    const original = draftFromProfile(stored);
    expect(original.webhook.url).toBe('');
    const draft = { ...original, webhook: { ...original.webhook, secret: SECRET } };
    expect(updateBody(draft, original).webhook).toEqual({ url: '', artifact: 'auto', secret: SECRET });
    expect(needsWebhookUrl(draft, original)).toBe(true);
    expect(validateDraft(draft, false, original)).toContain('Re-enter the receiver URL to change the destination.');
    expect(validateDraft({ ...original, name: 'renamed' }, false, original)).toEqual([]);
  });
});

describe('validateDraft', () => {
  it('lists every problem of a blank draft for each channel', () => {
    expect(validateDraft(emptyDraft('git'), true)).toEqual(['Name the profile.', 'Choose a repository.']);
    expect(validateDraft(emptyDraft('webhook'), true)).toEqual([
      'Name the profile.', 'Enter the receiver URL (https://…).', 'Enter the signing secret.',
    ]);
    expect(validateDraft(emptyDraft('object_storage'), true)).toEqual([
      'Name the profile.', 'Choose a storage credential.',
      'The bucket must be 3–63 lowercase letters, digits, "." and "-".',
    ]);
  });

  it('checks the secret length and path escapes', () => {
    const draft = emptyDraft('webhook');
    draft.name = 'ci';
    draft.webhook = { url: 'https://ci.example.com', secret: 'short', artifact: 'auto' };
    expect(validateDraft(draft, true)).toEqual(['The secret must be 16–512 characters.']);
    const git = emptyDraft('git');
    git.name = 'r';
    git.git.repositoryId = 'r1';
    git.git.targetPath = 'a/../b';
    expect(validateDraft(git, true)).toEqual(['The path cannot contain "..".']);
  });
});

describe('destinationSummary and outcomes', () => {
  it('summarises each channel', () => {
    expect(destinationSummary(profile({}))).toBe('data-lake/exports');
    expect(destinationSummary(profile({ channel: 'git', destination: { repositoryId: 'r1', targetPath: '', mode: 'pr' } }),
      { r1: 'acme/specs' })).toBe('acme/specs → / (pull request)');
    expect(destinationSummary(profile({ channel: 'webhook', destination: { url: 'https://h.example.com' } })))
      .toBe('https://h.example.com');
  });

  it('tones and counts delivery outcomes', () => {
    expect(outcomeTone('delivered')).toBe('ok');
    expect(outcomeTone('failed')).toBe('danger');
    expect(outcomeTone('in_progress')).toBe('neutral');
    expect(deliveryEventCount([{ code: 'EXPORT_COMPLETED' }, { code: 'EXPORT_DELIVERED' }, { code: 'EXPORT_DELIVERY_FAILED' }]))
      .toBe(2);
    expect(deliveryEventCount(null)).toBe(0);
  });

  it('round-trips a stored git profile into a draft', () => {
    const draft = draftFromProfile(profile({
      channel: 'git', destination: { repositoryId: 'r1', targetPath: 'specs', baseBranch: 'main', mode: 'commit' },
    }));
    expect(draft.git).toEqual({ repositoryId: 'r1', targetPath: 'specs', baseBranch: 'main', mode: 'commit' });
  });
});
