/**
 * Tests for the embeddable status-badge helpers — MCAT-19.3 (#4652).
 *
 * Pins the framework-free logic behind the "Status badge" snippet: origin derivation (stripping
 * the `/v1` suffix), badge image URL composition with default-omitting query params, the detail-page
 * link target, and the Markdown / HTML / URL snippet formats.
 */

import { describe, expect, it } from 'vitest';
import {
  BADGE_METRICS,
  BADGE_THEMES,
  badgeAltText,
  badgeImageUrl,
  badgeLinkUrl,
  badgeOrigin,
  badgeSnippet,
} from '../badge';

const REST_BASE = 'https://api.example.com/v1';

describe('badgeOrigin', () => {
  it('strips the trailing /v1 and any trailing slash', () => {
    expect(badgeOrigin('https://api.example.com/v1')).toBe('https://api.example.com');
    expect(badgeOrigin('https://api.example.com/v1/')).toBe('https://api.example.com');
    expect(badgeOrigin('http://localhost:8000/v1')).toBe('http://localhost:8000');
  });

  it('leaves an origin without /v1 untouched (bar trailing slash)', () => {
    expect(badgeOrigin('https://api.example.com/')).toBe('https://api.example.com');
  });
});

describe('badgeImageUrl', () => {
  it('composes the root /mcp/badge path with defaults omitted', () => {
    expect(badgeImageUrl(REST_BASE, 'acme', 'weather')).toBe(
      'https://api.example.com/mcp/badge/acme/weather.svg'
    );
  });

  it('emits only non-default metric/theme query params', () => {
    expect(badgeImageUrl(REST_BASE, 'acme', 'weather', 'health')).toBe(
      'https://api.example.com/mcp/badge/acme/weather.svg?metric=health'
    );
    expect(badgeImageUrl(REST_BASE, 'acme', 'weather', 'version', 'dark')).toBe(
      'https://api.example.com/mcp/badge/acme/weather.svg?metric=version&theme=dark'
    );
    expect(badgeImageUrl(REST_BASE, 'acme', 'weather', 'grade', 'dark')).toBe(
      'https://api.example.com/mcp/badge/acme/weather.svg?theme=dark'
    );
  });

  it('encodes slugs', () => {
    expect(badgeImageUrl(REST_BASE, 'ac me', 'a/b')).toContain('/mcp/badge/ac%20me/a%2Fb.svg');
  });
});

describe('badgeLinkUrl', () => {
  it('points at the endpoint public detail page', () => {
    expect(badgeLinkUrl('https://catalog.example.com/', 'acme', 'weather')).toBe(
      'https://catalog.example.com/mcp/acme/weather'
    );
  });
});

describe('badgeSnippet', () => {
  const image = 'https://api.example.com/mcp/badge/acme/weather.svg';
  const link = 'https://catalog.example.com/mcp/acme/weather';
  const alt = badgeAltText('Weather', 'grade');

  it('wraps the image in a link for markdown and html', () => {
    expect(badgeSnippet('markdown', image, link, alt)).toBe(
      `[![${alt}](${image})](${link})`
    );
    expect(badgeSnippet('html', image, link, alt)).toBe(
      `<a href="${link}"><img src="${image}" alt="${alt}" /></a>`
    );
  });

  it('returns the bare image url for the url format', () => {
    expect(badgeSnippet('url', image, link, alt)).toBe(image);
  });
});

describe('vocabularies', () => {
  it('exposes the metric and theme lists', () => {
    expect(BADGE_METRICS).toEqual(['grade', 'health', 'version']);
    expect(BADGE_THEMES).toEqual(['light', 'dark']);
  });
});
