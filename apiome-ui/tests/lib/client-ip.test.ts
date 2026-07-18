/**
 * Tests for the client-IP resolver used in rate-limit keys (OLO-7.1, #4223).
 *
 * The resolver must handle both header container shapes it meets in production:
 * WHATWG `Headers` (Next.js route handlers) and plain header objects (NextAuth's
 * `authorize(credentials, req)` request shape, where values may be arrays).
 */
import { resolveClientIp } from '@lib/auth/client-ip';

describe('resolveClientIp — Headers instance', () => {
  it('takes the first x-forwarded-for hop', () => {
    const headers = new Headers({ 'x-forwarded-for': '203.0.113.4, 10.0.0.1, 10.0.0.2' });
    expect(resolveClientIp(headers)).toBe('203.0.113.4');
  });

  it('trims whitespace around the first hop', () => {
    const headers = new Headers({ 'x-forwarded-for': '  203.0.113.4 , 10.0.0.1' });
    expect(resolveClientIp(headers)).toBe('203.0.113.4');
  });

  it('falls back to x-real-ip when x-forwarded-for is absent', () => {
    const headers = new Headers({ 'x-real-ip': '198.51.100.7' });
    expect(resolveClientIp(headers)).toBe('198.51.100.7');
  });

  it('prefers x-forwarded-for over x-real-ip', () => {
    const headers = new Headers({
      'x-forwarded-for': '203.0.113.4',
      'x-real-ip': '198.51.100.7',
    });
    expect(resolveClientIp(headers)).toBe('203.0.113.4');
  });

  it("returns 'unknown' when neither header is present", () => {
    expect(resolveClientIp(new Headers())).toBe('unknown');
  });
});

describe('resolveClientIp — plain header object (NextAuth authorize req)', () => {
  it('reads string values', () => {
    expect(resolveClientIp({ 'x-forwarded-for': '203.0.113.4, 10.0.0.1' })).toBe('203.0.113.4');
    expect(resolveClientIp({ 'x-real-ip': '198.51.100.7' })).toBe('198.51.100.7');
  });

  it('reads the first element of array values (Node multi-value headers)', () => {
    expect(resolveClientIp({ 'x-forwarded-for': ['203.0.113.4', '10.0.0.1'] })).toBe('203.0.113.4');
  });

  it("returns 'unknown' for empty objects and empty values", () => {
    expect(resolveClientIp({})).toBe('unknown');
    expect(resolveClientIp({ 'x-forwarded-for': '' })).toBe('unknown');
    expect(resolveClientIp({ 'x-forwarded-for': [] })).toBe('unknown');
    expect(resolveClientIp({ 'x-real-ip': '   ' })).toBe('unknown');
  });
});

describe('resolveClientIp — degenerate inputs', () => {
  it("returns 'unknown' for null/undefined containers", () => {
    expect(resolveClientIp(null)).toBe('unknown');
    expect(resolveClientIp(undefined)).toBe('unknown');
  });

  it("returns 'unknown' when the forwarded chain is only separators", () => {
    expect(resolveClientIp({ 'x-forwarded-for': ' , , ' })).toBe('unknown');
  });
});
