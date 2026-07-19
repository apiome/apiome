/**
 * Authoring resume behavior (UXE-1.2).
 */

import {
  clearAuthoringResume,
  readAuthoringResume,
  writeAuthoringResume,
} from '../../lib/authoring/resume';

const TENANT = 'tenant-1';
const ENTRY = {
  surfaceId: 'scribe' as const,
  projectId: 'proj-1',
  versionId: 'ver-1',
  environmentId: 'production' as const,
};

beforeEach(() => {
  window.localStorage.clear();
});

describe('writeAuthoringResume / readAuthoringResume', () => {
  it('round-trips a complete entry', () => {
    writeAuthoringResume(TENANT, ENTRY, 1_700_000_000_000);
    expect(readAuthoringResume(TENANT)).toEqual({ ...ENTRY, updatedAt: 1_700_000_000_000 });
  });

  it('keeps entries separate per tenant, so scope never leaks across them', () => {
    writeAuthoringResume(TENANT, ENTRY, 1);
    writeAuthoringResume('tenant-2', { ...ENTRY, projectId: 'proj-9' }, 2);

    expect(readAuthoringResume(TENANT)?.projectId).toBe('proj-1');
    expect(readAuthoringResume('tenant-2')?.projectId).toBe('proj-9');
  });

  it('returns null without a tenant', () => {
    expect(writeAuthoringResume(null, ENTRY)).toBeNull();
    expect(readAuthoringResume(null)).toBeNull();
  });

  it('returns null when nothing was stored', () => {
    expect(readAuthoringResume(TENANT)).toBeNull();
  });

  it('refuses an incomplete scope, which would resume into an empty picker', () => {
    expect(writeAuthoringResume(TENANT, { ...ENTRY, versionId: '' })).toBeNull();
    expect(readAuthoringResume(TENANT)).toBeNull();
  });

  it('overwrites the previous entry for the same tenant', () => {
    writeAuthoringResume(TENANT, ENTRY, 1);
    writeAuthoringResume(TENANT, { ...ENTRY, surfaceId: 'slate' }, 2);
    expect(readAuthoringResume(TENANT)?.surfaceId).toBe('slate');
  });
});

describe('validation on read', () => {
  /**
   * Seed raw storage for the tenant.
   *
   * @param raw - Payload to store.
   */
  function seed(raw: string) {
    window.localStorage.setItem(`authoring.resume.${TENANT}`, raw);
  }

  it('ignores corrupt JSON rather than throwing', () => {
    seed('{not json');
    expect(readAuthoringResume(TENANT)).toBeNull();
  });

  it('ignores an entry naming a surface this build does not have', () => {
    seed(JSON.stringify({ ...ENTRY, surfaceId: 'retired-surface', updatedAt: 1 }));
    expect(readAuthoringResume(TENANT)).toBeNull();
  });

  it('ignores an entry naming an environment this build does not have', () => {
    seed(JSON.stringify({ ...ENTRY, environmentId: 'canary', updatedAt: 1 }));
    expect(readAuthoringResume(TENANT)).toBeNull();
  });

  it('ignores an entry missing its version', () => {
    seed(JSON.stringify({ ...ENTRY, versionId: undefined, updatedAt: 1 }));
    expect(readAuthoringResume(TENANT)).toBeNull();
  });
});

describe('clearAuthoringResume', () => {
  it('forgets the entry for one tenant only', () => {
    writeAuthoringResume(TENANT, ENTRY, 1);
    writeAuthoringResume('tenant-2', ENTRY, 1);

    clearAuthoringResume(TENANT);

    expect(readAuthoringResume(TENANT)).toBeNull();
    expect(readAuthoringResume('tenant-2')).not.toBeNull();
  });
});
