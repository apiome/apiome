/**
 * Tests for the mock-server URL helpers — SIM-2.3 (#4444).
 *
 * Pins the framework-free logic behind the "Mock available" surfacing: base-URL composition
 * (mirroring REST `_mock_base_url`: `{mockHost}/{tenant}/{project}/{version}`), the curl
 * one-liner, and the OpenAPI sample-path picker's preference order and fallbacks.
 */

import { describe, expect, it } from 'vitest';
import { buildMockBaseUrl, mockCurlCommand, sampleMockPath } from '../mockUrl';

describe('buildMockBaseUrl', () => {
  it('composes {mockHost}/{tenant}/{project}/{version}', () => {
    expect(buildMockBaseUrl('http://localhost:8775', 'acme', 'petstore', '1.0.0')).toBe(
      'http://localhost:8775/acme/petstore/1.0.0'
    );
    expect(buildMockBaseUrl('https://mock.example.com', 'acme', 'petstore', '2.1')).toBe(
      'https://mock.example.com/acme/petstore/2.1'
    );
  });

  it('trims trailing slashes off the host so separators never double', () => {
    expect(buildMockBaseUrl('https://mock.example.com/', 'acme', 'petstore', '1.0.0')).toBe(
      'https://mock.example.com/acme/petstore/1.0.0'
    );
    expect(buildMockBaseUrl('https://mock.example.com///', 'acme', 'petstore', '1.0.0')).toBe(
      'https://mock.example.com/acme/petstore/1.0.0'
    );
  });

  it('returns null when any part is missing', () => {
    expect(buildMockBaseUrl('', 'acme', 'petstore', '1.0.0')).toBeNull();
    expect(buildMockBaseUrl('/', 'acme', 'petstore', '1.0.0')).toBeNull();
    expect(buildMockBaseUrl('http://localhost:8775', '', 'petstore', '1.0.0')).toBeNull();
    expect(buildMockBaseUrl('http://localhost:8775', 'acme', '', '1.0.0')).toBeNull();
    expect(buildMockBaseUrl('http://localhost:8775', 'acme', 'petstore', '')).toBeNull();
  });
});

describe('mockCurlCommand', () => {
  const BASE = 'https://mock.example.com/acme/petstore/1.0.0';

  it('defaults to the base URL root', () => {
    expect(mockCurlCommand(BASE)).toBe(`curl ${BASE}/`);
  });

  it('appends the sample path', () => {
    expect(mockCurlCommand(BASE, '/pets')).toBe(`curl ${BASE}/pets`);
  });

  it('normalizes a missing leading slash and a trailing base slash', () => {
    expect(mockCurlCommand(BASE, 'pets')).toBe(`curl ${BASE}/pets`);
    expect(mockCurlCommand(`${BASE}/`, '/pets')).toBe(`curl ${BASE}/pets`);
  });
});

describe('sampleMockPath', () => {
  it('prefers the first parameterless GET path in document order', () => {
    const spec = {
      openapi: '3.0.0',
      paths: {
        '/pets/{petId}': { get: {} },
        '/pets': { get: {}, post: {} },
        '/owners': { get: {} },
      },
    };
    expect(sampleMockPath(spec)).toBe('/pets');
  });

  it('falls back to a parameterized GET path when no parameterless one exists', () => {
    const spec = { paths: { '/pets/{petId}': { get: {} }, '/orders': { post: {} } } };
    expect(sampleMockPath(spec)).toBe('/pets/{petId}');
  });

  it('falls back to the first path with any operation when there is no GET', () => {
    const spec = { paths: { '/pets': { post: {} }, '/orders': { delete: {} } } };
    expect(sampleMockPath(spec)).toBe('/pets');
  });

  it('adds a leading slash to a non-conforming path key', () => {
    const spec = { paths: { pets: { get: {} } } };
    expect(sampleMockPath(spec)).toBe('/pets');
  });

  it('returns / for empty, path-less, operation-less, or non-object specs', () => {
    expect(sampleMockPath(null)).toBe('/');
    expect(sampleMockPath(undefined)).toBe('/');
    expect(sampleMockPath('nope')).toBe('/');
    expect(sampleMockPath({})).toBe('/');
    expect(sampleMockPath({ paths: {} })).toBe('/');
    expect(sampleMockPath({ paths: { '/pets': { description: 'no ops' } } })).toBe('/');
    expect(sampleMockPath({ paths: { '/pets': 'not-an-object' } })).toBe('/');
  });
});
