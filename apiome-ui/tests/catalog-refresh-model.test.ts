/**
 * The rules behind a catalog item's Live refresh card and dialog (MFI-31.1, #4398).
 *
 * Pure: the status pill, when Check now is allowed, the next-check line, the dialog's starting
 * values, its client-side checks, and the PUT body — in particular the keep / clear / replace
 * credential contract REST relies on.
 */

import {
  catalogDetailActions,
  refreshCanCheck,
  refreshFormError,
  refreshFormFrom,
  refreshNextCheckText,
  refreshPayload,
  refreshStatusView,
  type CatalogRefresh,
  type RefreshForm,
} from '../src/app/components/ade/catalog/detail';

const BASE: CatalogRefresh = {
  itemId: 'item-1',
  configured: true,
  cadence: 'daily',
  adapter: 'graphql',
  endpoint: 'https://api.example.com/graphql',
  options: {},
  authType: 'none',
  hasCredential: false,
  status: 'unchanged',
  lastCheckedAt: '2026-10-27T10:00:00Z',
  lastSuccessAt: '2026-10-27T10:00:00Z',
  lastFailureAt: null,
  lastError: null,
  lastFingerprint: 'fp',
  consecutiveFailures: 0,
  nextCheckAt: '2026-10-28T10:00:00Z',
  tenantEnabled: true,
  adapters: ['graphql', 'grpc'],
};

const FORM: RefreshForm = {
  adapter: 'graphql',
  endpoint: ' https://api.example.com/graphql ',
  cadence: 'daily',
  secure: false,
  authType: 'keep',
  secret: '',
  headerName: '',
  keepVersions: '50',
};

describe('refreshStatusView', () => {
  it.each([
    [{ status: 'unchanged' }, 'Up to date', 'ok'],
    [{ status: 'changed' }, 'Source changed', 'accent'],
    [{ status: 'failed' }, 'Last check failed', 'danger'],
    [{ status: 'never' }, 'Not checked yet', 'neutral'],
    [{ cadence: 'off' }, 'Off', 'neutral'],
    [{ configured: false }, 'Off', 'neutral'],
    [{ tenantEnabled: false, status: 'failed' }, 'Paused for workspace', 'warn'],
  ] as const)('%j reads %s', (patch, label, tone) => {
    expect(refreshStatusView({ ...BASE, ...patch })).toEqual({ label, tone });
  });
});

describe('refreshCanCheck', () => {
  it('allows a manual or scheduled setting', () => {
    expect(refreshCanCheck({ ...BASE, cadence: 'manual' })).toBe(true);
    expect(refreshCanCheck(BASE)).toBe(true);
  });
  it('refuses when off, unset, or paused for the workspace', () => {
    expect(refreshCanCheck({ ...BASE, cadence: 'off' })).toBe(false);
    expect(refreshCanCheck({ ...BASE, configured: false })).toBe(false);
    expect(refreshCanCheck({ ...BASE, tenantEnabled: false })).toBe(false);
  });
});

describe('refreshNextCheckText', () => {
  it('names off and manual cadences in words', () => {
    expect(refreshNextCheckText({ cadence: 'off', nextCheckAt: null })).toBe('Never — refresh is off');
    expect(refreshNextCheckText({ cadence: 'manual', nextCheckAt: null })).toBe('Only when you check now');
  });
  it('says due now for a scheduled item without a time, and a date otherwise', () => {
    expect(refreshNextCheckText({ cadence: 'daily', nextCheckAt: null })).toBe('Due now');
    expect(refreshNextCheckText(BASE)).toMatch(/2026/);
  });
});

describe('refreshFormFrom', () => {
  it('starts a new setting on the first adapter, daily, no credential', () => {
    expect(refreshFormFrom({ ...BASE, configured: false })).toMatchObject({
      adapter: 'graphql',
      endpoint: '',
      cadence: 'daily',
      authType: 'none',
    });
    expect(refreshFormFrom(null).adapter).toBe('graphql');
  });
  it('starts an existing setting from its values, keeping a stored credential', () => {
    const form = refreshFormFrom({ ...BASE, adapter: 'grpc', endpoint: 'h:443', options: { secure: true }, hasCredential: true });
    expect(form).toMatchObject({ adapter: 'grpc', endpoint: 'h:443', secure: true, authType: 'keep', secret: '' });
  });
  it('starts Keep versions at the stored value, else 50 (MFI-31.5)', () => {
    expect(refreshFormFrom({ ...BASE, keepVersions: 12 }).keepVersions).toBe('12');
    expect(refreshFormFrom({ ...BASE, configured: false }).keepVersions).toBe('50');
  });
});

describe('refreshFormError', () => {
  it('passes a complete form', () => {
    expect(refreshFormError(FORM)).toBeNull();
    expect(refreshFormError({ ...FORM, adapter: 'grpc', endpoint: 'grpc.example.com:443' })).toBeNull();
  });
  it.each([
    [{ endpoint: '  ' }, /Enter the endpoint/],
    [{ endpoint: 'ftp://x' }, /http/],
    [{ authType: 'bearer' }, /credential/],
    [{ authType: 'header', secret: 'v' }, /header name/],
    [{ keepVersions: '0' }, /Keep versions must be a whole number from 1 to 1000/],
    [{ keepVersions: '1001' }, /1 to 1000/],
    [{ keepVersions: '2.5' }, /whole number/],
  ] as const)('%j is refused', (patch, message) => {
    expect(refreshFormError({ ...FORM, ...patch })).toMatch(message);
  });
});

describe('refreshPayload', () => {
  it('omits the credential to keep it, and trims the endpoint', () => {
    expect(refreshPayload(FORM)).toEqual({
      cadence: 'daily',
      adapter: 'graphql',
      endpoint: 'https://api.example.com/graphql',
      options: {},
      keepVersions: 50,
    });
  });
  it('sends null to clear it', () => {
    expect(refreshPayload({ ...FORM, authType: 'none' }).credential).toBeNull();
  });
  it.each([
    ['bearer', { authType: 'bearer', payload: { token: 's' } }],
    ['oauth2', { authType: 'oauth2', payload: { access_token: 's' } }],
    ['header', { authType: 'header', payload: { name: 'X-Key', value: 's' } }],
  ] as const)('sends the %s payload shape REST validates', (authType, credential) => {
    expect(refreshPayload({ ...FORM, authType, secret: 's', headerName: ' X-Key ' }).credential).toEqual(credential);
  });
  it('sends the TLS option for gRPC only', () => {
    expect(refreshPayload({ ...FORM, adapter: 'grpc', secure: true }).options).toEqual({ secure: true });
    expect(refreshPayload({ ...FORM, secure: true }).options).toEqual({});
  });
});

describe('catalogDetailActions.refresh', () => {
  const item = { deleted_at: null, sourceFormat: 'graphql', conversion: null };
  it('is offered with projects:edit on a live item', () => {
    expect(catalogDetailActions(item, (p) => p === 'projects:edit').refresh.shown).toBe(true);
  });
  it('is hidden without it, or once the item is deleted', () => {
    expect(catalogDetailActions(item, () => false).refresh.shown).toBe(false);
    expect(catalogDetailActions({ ...item, deleted_at: '2026-10-01' }).refresh.shown).toBe(false);
  });
});
