/**
 * exportStudioHref — the Export Studio deep-link contract (MFX-41.1, #4348).
 *
 * The ExportDialog escalation and the Studio route agree on the query string built here: a
 * required `artifact`, plus the optional `version`, `label`, and pre-selected `target`.
 */

import {
  EXPORT_STUDIO_PATH,
  exportStudioHref,
  parseExportStudioOptions,
  resolveStudioBack,
} from '../src/app/components/ade/dashboard/export/exportStudioLink';

describe('exportStudioHref', () => {
  it('builds a bare artifact-only link', () => {
    expect(exportStudioHref({ artifact: 'proj-1' })).toBe(`${EXPORT_STUDIO_PATH}?artifact=proj-1`);
  });

  it('includes version, label, target, origin, and sourceFormat when provided', () => {
    const href = exportStudioHref({
      artifact: 'proj-1',
      version: 'rev-9',
      label: 'Pet Store API',
      target: 'proto',
      origin: 'catalog',
      sourceFormat: 'graphql',
    });
    const params = new URLSearchParams(href.split('?')[1]);
    expect(href.startsWith(`${EXPORT_STUDIO_PATH}?`)).toBe(true);
    expect(params.get('artifact')).toBe('proj-1');
    expect(params.get('version')).toBe('rev-9');
    expect(params.get('label')).toBe('Pet Store API');
    expect(params.get('target')).toBe('proto');
    expect(params.get('from')).toBe('catalog');
    expect(params.get('sourceFormat')).toBe('graphql');
  });

  it('omits empty and null optional fields', () => {
    const href = exportStudioHref({
      artifact: 'proj-1',
      version: null,
      label: '',
      target: undefined,
      origin: null,
      sourceFormat: '',
      options: null,
    });
    expect(href).toBe(`${EXPORT_STUDIO_PATH}?artifact=proj-1`);
  });

  it('encodes non-empty option overrides as JSON and round-trips them (MFX-41.3)', () => {
    const options = { package: 'com.example', emit_services: false };
    const href = exportStudioHref({ artifact: 'proj-1', target: 'proto', options });
    const params = new URLSearchParams(href.split('?')[1]);
    expect(params.get('target')).toBe('proto');
    expect(JSON.parse(params.get('options') ?? '{}')).toEqual(options);
    expect(parseExportStudioOptions(params.get('options'))).toEqual(options);
  });

  it('omits the options param for an empty override map', () => {
    const href = exportStudioHref({ artifact: 'proj-1', target: 'proto', options: {} });
    expect(new URLSearchParams(href.split('?')[1]).has('options')).toBe(false);
  });
});

describe('parseExportStudioOptions', () => {
  it('parses a JSON object of overrides', () => {
    expect(parseExportStudioOptions('{"package":"com.example"}')).toEqual({ package: 'com.example' });
  });

  it('returns null for missing, malformed, or non-object values', () => {
    expect(parseExportStudioOptions(null)).toBeNull();
    expect(parseExportStudioOptions('')).toBeNull();
    expect(parseExportStudioOptions('not json')).toBeNull();
    expect(parseExportStudioOptions('[1,2,3]')).toBeNull();
    expect(parseExportStudioOptions('"a string"')).toBeNull();
    expect(parseExportStudioOptions('42')).toBeNull();
  });
});

describe('resolveStudioBack', () => {
  it('returns the Catalog screen for a catalog origin', () => {
    expect(resolveStudioBack('catalog')).toEqual({ href: '/ade/dashboard/catalog', label: 'Catalog' });
  });

  it('returns the Versions screen for a versions origin', () => {
    expect(resolveStudioBack('versions')).toEqual({ href: '/ade/dashboard/versions', label: 'Versions' });
  });

  it('falls back to Versions for a missing or unknown origin', () => {
    expect(resolveStudioBack(null)).toEqual({ href: '/ade/dashboard/versions', label: 'Versions' });
    expect(resolveStudioBack('mars')).toEqual({ href: '/ade/dashboard/versions', label: 'Versions' });
  });
});
