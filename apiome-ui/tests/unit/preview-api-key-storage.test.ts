import {
  clearStoredPreviewApiKey,
  getStoredPreviewApiKey,
  previewApiKeyStorageKey,
  setStoredPreviewApiKey,
} from '../../src/app/utils/preview-api-key-storage';

describe('preview-api-key-storage', () => {
  const tenant = 'tenant-uuid-1';

  beforeEach(() => {
    localStorage.clear();
  });

  it('uses a stable storage key per tenant', () => {
    expect(previewApiKeyStorageKey(tenant)).toContain(tenant);
  });

  it('round-trips a trimmed key', () => {
    setStoredPreviewApiKey(tenant, '  sk_test_abc  ');
    expect(getStoredPreviewApiKey(tenant)).toBe('sk_test_abc');
  });

  it('returns null for empty or whitespace-only writes', () => {
    setStoredPreviewApiKey(tenant, '   ');
    expect(getStoredPreviewApiKey(tenant)).toBeNull();
  });

  it('clearStoredPreviewApiKey removes the entry', () => {
    setStoredPreviewApiKey(tenant, 'sk_x');
    clearStoredPreviewApiKey(tenant);
    expect(getStoredPreviewApiKey(tenant)).toBeNull();
  });

  it('getStoredPreviewApiKey returns null when tenant is missing', () => {
    setStoredPreviewApiKey(tenant, 'sk_x');
    expect(getStoredPreviewApiKey(null)).toBeNull();
    expect(getStoredPreviewApiKey(undefined)).toBeNull();
  });
});
