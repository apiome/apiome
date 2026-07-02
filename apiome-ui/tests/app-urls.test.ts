import { BROWSE_APP_URL, normalizePublicAppUrl } from '../lib/app-urls';

describe('app-urls', () => {
  describe('normalizePublicAppUrl', () => {
    it('adds a trailing slash', () => {
      expect(normalizePublicAppUrl('https://browse.example.com')).toBe('https://browse.example.com/');
    });

    it('removes duplicate trailing slashes', () => {
      expect(normalizePublicAppUrl('http://localhost:3002///')).toBe('http://localhost:3002/');
    });

    it('falls back to production default when empty', () => {
      expect(normalizePublicAppUrl('   ')).toBe('https://browse.apiome.app/');
    });
  });

  it('exports a browse URL with trailing slash', () => {
    expect(BROWSE_APP_URL.endsWith('/')).toBe(true);
    expect(BROWSE_APP_URL.length).toBeGreaterThan(1);
  });
});
