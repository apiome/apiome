/**
 * The Import to catalog → Projects hand-off rules (COA-4.3b, #7127).
 *
 * `projectsHandoffFor` decides which catalog sources can be handed to the Projects importer and
 * what they carry; `projectsIntakeSourceFor` picks the Projects intake they land in; and
 * `catalogImportFooterFor` swaps the detect step's disabled Continue for **Continue in Projects**.
 */

import {
  CONTINUE_IN_PROJECTS_LABEL,
  catalogImportFooterFor,
  projectsHandoffFor,
  projectsIntakeSourceFor,
} from '../src/app/components/ade/import';

const OPENAPI_YAML = 'openapi: 3.1.0\ninfo:\n  title: Pets\n  version: 1.0.0\npaths: {}\n';
const OPENAPI_JSON = '{"openapi":"3.1.0","info":{"title":"Pets","version":"1.0.0"},"paths":{}}';

describe('projectsHandoffFor', () => {
  it('hands a pasted YAML source over under a .yaml name', () => {
    expect(
      projectsHandoffFor({
        destination: 'project',
        method: 'paste',
        text: OPENAPI_YAML,
        label: 'Pasted source',
        format: 'openapi-3.1',
      }),
    ).toEqual({
      text: OPENAPI_YAML,
      filename: 'openapi-spec.yaml',
      method: 'paste',
      url: null,
      format: 'openapi-3.1',
    });
  });

  it('names a pasted JSON source .json', () => {
    const payload = projectsHandoffFor({
      destination: 'project',
      method: 'paste',
      text: `  ${OPENAPI_JSON}`,
      label: 'Pasted source',
      format: null,
    });
    expect(payload?.filename).toBe('openapi-spec.json');
  });

  it('keeps an uploaded file’s own name', () => {
    const payload = projectsHandoffFor({
      destination: 'project',
      method: 'file',
      text: OPENAPI_YAML,
      label: 'petstore.yaml',
      format: 'openapi-3.0',
    });
    expect(payload).toEqual(
      expect.objectContaining({ method: 'file', filename: 'petstore.yaml', url: null }),
    );
  });

  it('carries a URL and names the source after its last path segment', () => {
    const payload = projectsHandoffFor({
      destination: 'project',
      method: 'url',
      text: OPENAPI_JSON,
      label: 'https://specs.example.com/v2/pets%20api.json?raw=1',
      format: 'openapi-3.1',
    });
    expect(payload).toEqual(
      expect.objectContaining({
        method: 'url',
        filename: 'pets api.json',
        url: 'https://specs.example.com/v2/pets%20api.json?raw=1',
      }),
    );
  });

  it('falls back to a paste-style name for a URL with no path', () => {
    const payload = projectsHandoffFor({
      destination: 'project',
      method: 'url',
      text: OPENAPI_JSON,
      label: 'https://specs.example.com/',
      format: null,
    });
    expect(payload?.filename).toBe('openapi-spec.json');
  });

  it.each(['catalog', 'json-schema-choice', 'not-importable'])(
    'offers nothing for a source routed to %s',
    (destination) => {
      expect(
        projectsHandoffFor({ destination, method: 'paste', text: OPENAPI_YAML, label: 'x', format: null }),
      ).toBeNull();
    },
  );

  it.each(['git', 'compass'])('offers nothing for a %s intake', (method) => {
    expect(
      projectsHandoffFor({ destination: 'project', method, text: OPENAPI_YAML, label: 'x', format: null }),
    ).toBeNull();
  });

  it('offers nothing for an archive, which has no single text document', () => {
    expect(
      projectsHandoffFor({ destination: 'project', method: 'file', text: '', label: 'specs.zip', format: null }),
    ).toBeNull();
  });
});

describe('projectsIntakeSourceFor', () => {
  it('lands a paste in Clipboard, a file in File and a URL in URL', () => {
    expect(projectsIntakeSourceFor('paste')).toBe('clipboard');
    expect(projectsIntakeSourceFor('file')).toBe('file');
    expect(projectsIntakeSourceFor('url')).toBe('url');
  });
});

describe('catalogImportFooterFor on the detect step', () => {
  const base = {
    step: 'detect' as const,
    storing: false,
    done: false,
    canContinueFromDetect: false,
    adapterUnavailable: false,
    destination: 'project' as const,
    canStoreCatalog: false,
  };

  it('offers Continue in Projects when the source can be handed off', () => {
    expect(catalogImportFooterFor({ ...base, handsOffToProjects: true }).primary).toEqual({
      label: CONTINUE_IN_PROJECTS_LABEL,
      disabled: false,
    });
  });

  it('keeps Continue drawn and disabled when it cannot', () => {
    expect(catalogImportFooterFor({ ...base, handsOffToProjects: false }).primary).toEqual({
      label: 'Continue',
      disabled: true,
    });
  });

  it('ignores the flag on a catalog route', () => {
    expect(
      catalogImportFooterFor({
        ...base,
        destination: 'catalog',
        canContinueFromDetect: true,
        handsOffToProjects: true,
      }).primary,
    ).toEqual({ label: 'Continue', disabled: false });
  });
});
