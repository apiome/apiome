/**
 * CatalogImportDialog — an OpenAPI source carries on into the Projects importer (COA-4.3b, #7127).
 *
 * Import to catalog routes OpenAPI/Swagger to Projects. With `onOpenApiToProjects` wired, the
 * detect step's primary reads **Continue in Projects** and hands the source (text, name, method,
 * URL, detected format) over in one click — for a paste, an uploaded file and a fetched URL alike.
 * A repository selection has no single document, so it keeps the disabled Continue and the
 * **Open Projects** link (#7060).
 *
 * The docs screenshot `catalog-import-routing-projects` mounts the dump this suite writes when
 * `IMPORT_WIZARD_FIXTURE_DUMP=1` is set:
 *
 *     IMPORT_WIZARD_FIXTURE_DUMP=1 npx jest tests/CatalogImportDialogProjectsHandoff.test.tsx -t fixture
 */

import * as fs from 'fs';
import * as path from 'path';

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';

const OPENAPI_YAML = 'openapi: 3.1.0\ninfo:\n  title: Pets\n  version: 1.0.0\npaths: {}\n';
const REMOTE_URL = 'https://specs.example.com/pets.yaml';

const OPENAPI_DETECTION = {
  matched: true,
  detected: { format: 'openapi-3.1', confidence: 0.99, reason: '`openapi: 3.1.0` marker', importable: true },
};

/** Registry, detector, the remote document and the git reader; anything else fails closed. */
function mockFetch(): jest.Mock {
  return jest.fn((input: unknown) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/import/sources')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, sources: [] }) });
    }
    if (url.includes('/api/import/detect')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(OPENAPI_DETECTION) });
    }
    if (url === REMOTE_URL) {
      return Promise.resolve({ ok: true, text: () => Promise.resolve(OPENAPI_YAML) });
    }
    if (url.includes('/api/catalog/import/git')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            success: true,
            filename: 'repo.zip',
            document_base64: 'UEsDBA==',
            archive_root: 'openapi.yaml',
            git_source: {
              provider: 'github',
              repo_url: 'https://github.com/o/r',
              ref: 'main',
              commit_sha: 'abcdef1234567',
              path: '',
            },
            members: ['openapi.yaml'],
            skipped: [],
            detection: OPENAPI_DETECTION,
          }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
}

/** A `File` whose `text()` resolves in jsdom. */
function fileOf(name: string, content: string): File {
  const file = new File([content], name);
  Object.defineProperty(file, 'text', { value: () => Promise.resolve(content) });
  return file;
}

/** Mount the dialog with a hand-off handler and wait for the registry. */
async function renderDialog() {
  const onClose = jest.fn();
  const onOpenApiToProjects = jest.fn();
  render(<CatalogImportDialog open onClose={onClose} onOpenApiToProjects={onOpenApiToProjects} />);
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
  );
  return { onClose, onOpenApiToProjects };
}

async function waitForDetect() {
  await waitFor(() => expect(screen.getByText(/Routing decision → Projects/i)).toBeInTheDocument());
}

describe('CatalogImportDialog — OpenAPI hand-off to Projects (#7127)', () => {
  beforeEach(() => {
    global.fetch = mockFetch() as unknown as typeof fetch;
  });
  afterEach(() => jest.restoreAllMocks());

  it('hands a pasted OpenAPI document to Projects in one click', async () => {
    const { onClose, onOpenApiToProjects } = await renderDialog();
    fireEvent.click(screen.getByTestId('catalog-import-source-paste'));
    fireEvent.change(screen.getByLabelText('Source content'), { target: { value: OPENAPI_YAML } });
    fireEvent.click(screen.getByRole('button', { name: /detect pasted source/i }));
    await waitForDetect();

    // The routing card explains the hand-off instead of the dead-end link.
    expect(screen.getByTestId('catalog-import-routing-handoff')).toHaveTextContent(
      'Continue in Projects opens the Projects importer with this source loaded',
    );
    expect(screen.queryByTestId('catalog-import-routing-projects')).not.toBeInTheDocument();

    const primary = screen.getByRole('button', { name: 'Continue in Projects' });
    expect(primary).toBeEnabled();
    fireEvent.click(primary);

    expect(onOpenApiToProjects).toHaveBeenCalledTimes(1);
    expect(onOpenApiToProjects).toHaveBeenCalledWith({
      text: OPENAPI_YAML.trim(),
      filename: 'openapi-spec.yaml',
      method: 'paste',
      url: null,
      format: 'openapi-3.1',
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('hands an uploaded file over under its own name', async () => {
    const { onOpenApiToProjects } = await renderDialog();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [fileOf('petstore.yaml', OPENAPI_YAML)] });
    fireEvent.change(input);
    await waitForDetect();

    fireEvent.click(screen.getByRole('button', { name: 'Continue in Projects' }));
    expect(onOpenApiToProjects).toHaveBeenCalledWith(
      expect.objectContaining({ text: OPENAPI_YAML, filename: 'petstore.yaml', method: 'file', url: null }),
    );
  });

  it('hands a fetched URL over with the URL it came from', async () => {
    const { onOpenApiToProjects } = await renderDialog();
    fireEvent.click(screen.getByTestId('catalog-import-source-url'));
    fireEvent.change(screen.getByLabelText('Document URL'), { target: { value: REMOTE_URL } });
    fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));
    await waitForDetect();

    fireEvent.click(screen.getByRole('button', { name: 'Continue in Projects' }));
    expect(onOpenApiToProjects).toHaveBeenCalledWith(
      expect.objectContaining({
        text: OPENAPI_YAML,
        filename: 'pets.yaml',
        method: 'url',
        url: REMOTE_URL,
        format: 'openapi-3.1',
      }),
    );
  });

  it('keeps the Open Projects link and a disabled Continue for a repository selection', async () => {
    const { onOpenApiToProjects } = await renderDialog();
    fireEvent.click(screen.getByTestId('catalog-import-source-git'));
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'https://github.com/o/r' } });
    fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));
    await waitForDetect();

    expect(screen.getByTestId('catalog-import-routing-projects')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Continue in Projects' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
    expect(onOpenApiToProjects).not.toHaveBeenCalled();
  });

  it('keeps the link when no hand-off handler is wired', async () => {
    render(<CatalogImportDialog open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    fireEvent.click(screen.getByTestId('catalog-import-source-paste'));
    fireEvent.change(screen.getByLabelText('Source content'), { target: { value: OPENAPI_YAML } });
    fireEvent.click(screen.getByRole('button', { name: /detect pasted source/i }));
    await waitForDetect();

    expect(screen.getByTestId('catalog-import-routing-projects')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });
});

describe('the docs fixture', () => {
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-import-wizard');

  beforeEach(() => {
    global.fetch = mockFetch() as unknown as typeof fetch;
  });
  afterEach(() => jest.restoreAllMocks());

  it('renders the Projects routing step (and writes the fixture on request)', async () => {
    await renderDialog();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [fileOf('petstore.yaml', OPENAPI_YAML)] });
    fireEvent.change(input);
    await waitForDetect();

    // Monaco never finishes loading in jsdom, so the dump would freeze on "Loading...". Draw the
    // viewer's own offline `<pre>` fallback (same class) in its place so the screenshot shows the
    // source the way a reader sees it.
    const editor = screen.getByTestId('catalog-import-preview-editor');
    const pre = document.createElement('pre');
    pre.className = 'xstd-code-fallback';
    pre.textContent = OPENAPI_YAML;
    editor.replaceChildren(pre);

    const html = (document.querySelector('.imp-wizard') as HTMLElement).outerHTML;
    expect(html).toContain('catalog-import-routing-handoff');
    if (process.env.IMPORT_WIZARD_FIXTURE_DUMP !== '1') return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, 'catalog-routing-projects.html'), html);
  });
});
