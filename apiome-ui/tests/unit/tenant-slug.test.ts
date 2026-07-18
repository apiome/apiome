/**
 * Tenant slug helper tests (OLO-4.1, #4205).
 *
 * `generateTenantSlug`/`validateTenantSlug` are the single shape contract for
 * tenant slugs, shared by OAuth self-signup and the first-tenant onboarding
 * wizard — the wizard previews the exact slug the server action will create.
 */
import { generateTenantSlug, validateTenantSlug } from '../../lib/auth/tenant-slug';

describe('generateTenantSlug', () => {
  it('lowercases and dash-joins a plain name', () => {
    expect(generateTenantSlug('Acme Corp')).toBe('acme-corp');
  });

  it('strips punctuation and collapses separator runs', () => {
    expect(generateTenantSlug('Acme, Inc.')).toBe('acme-inc');
    expect(generateTenantSlug('a  __  b')).toBe('a-b');
  });

  it('trims leading and trailing dashes', () => {
    expect(generateTenantSlug('--Acme--')).toBe('acme');
  });

  it('returns an empty string when nothing usable remains', () => {
    expect(generateTenantSlug('!!!')).toBe('');
    expect(generateTenantSlug('   ')).toBe('');
  });
});

describe('validateTenantSlug', () => {
  it('accepts lowercase letters, numbers, and dashes', () => {
    expect(validateTenantSlug('acme-inc-2')).toBeNull();
  });

  it('rejects empty or whitespace-only slugs', () => {
    expect(validateTenantSlug('')).toMatch(/required/i);
    expect(validateTenantSlug('   ')).toMatch(/required/i);
  });

  it('rejects one-character slugs', () => {
    expect(validateTenantSlug('a')).toMatch(/at least 2/i);
  });

  it('rejects disallowed characters', () => {
    expect(validateTenantSlug('acme inc')).toMatch(/lowercase letters, numbers, and dashes/i);
    expect(validateTenantSlug('acme_inc')).toMatch(/lowercase letters, numbers, and dashes/i);
  });

  it('normalizes case before checking', () => {
    expect(validateTenantSlug('ACME-INC')).toBeNull();
  });
});
