/**
 * Tests for the Browse `changelog.md` upstream URL — PCX-2.1 (#5896).
 */

import { describe, expect, it } from 'vitest';
import { changelogMarkdownUpstreamUrl } from '../markdownRoute';

describe('changelogMarkdownUpstreamUrl', () => {
  it('targets the REST browse changelog.md endpoint', () => {
    expect(changelogMarkdownUpstreamUrl('http://rest:8000/v1/', 'acme', 'pet store', new URLSearchParams())).toBe(
      'http://rest:8000/v1/browse/tenants/acme/projects/pet%20store/changelog.md'
    );
  });

  it('forwards only recognised filters', () => {
    const search = new URLSearchParams('severity=breaking&pathGroup=/info&since=1.0.0&evil=1');
    expect(changelogMarkdownUpstreamUrl('http://x/v1', 'a', 'b', search)).toBe(
      'http://x/v1/browse/tenants/a/projects/b/changelog.md?severity=breaking&pathGroup=%2Finfo&since=1.0.0'
    );
  });

  it('drops an unknown severity', () => {
    expect(changelogMarkdownUpstreamUrl('http://x/v1', 'a', 'b', new URLSearchParams('severity=scary'))).toBe(
      'http://x/v1/browse/tenants/a/projects/b/changelog.md'
    );
  });
});
