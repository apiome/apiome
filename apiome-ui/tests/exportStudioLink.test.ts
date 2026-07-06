/**
 * exportStudioHref — the Export Studio deep-link contract (MFX-41.1, #4348).
 *
 * The ExportDialog escalation and the Studio route agree on the query string built here: a
 * required `artifact`, plus the optional `version`, `label`, and pre-selected `target`.
 */

import { EXPORT_STUDIO_PATH, exportStudioHref } from '../src/app/components/ade/dashboard/export/exportStudioLink';

describe('exportStudioHref', () => {
  it('builds a bare artifact-only link', () => {
    expect(exportStudioHref({ artifact: 'proj-1' })).toBe(`${EXPORT_STUDIO_PATH}?artifact=proj-1`);
  });

  it('includes version, label, and target when provided', () => {
    const href = exportStudioHref({
      artifact: 'proj-1',
      version: 'rev-9',
      label: 'Pet Store API',
      target: 'proto',
    });
    const params = new URLSearchParams(href.split('?')[1]);
    expect(href.startsWith(`${EXPORT_STUDIO_PATH}?`)).toBe(true);
    expect(params.get('artifact')).toBe('proj-1');
    expect(params.get('version')).toBe('rev-9');
    expect(params.get('label')).toBe('Pet Store API');
    expect(params.get('target')).toBe('proto');
  });

  it('omits empty and null optional fields', () => {
    const href = exportStudioHref({ artifact: 'proj-1', version: null, label: '', target: undefined });
    expect(href).toBe(`${EXPORT_STUDIO_PATH}?artifact=proj-1`);
  });
});
