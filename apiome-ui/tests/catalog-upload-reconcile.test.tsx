/**
 * Reconcile one-shot file uploads on a catalog item (RAR-6.2, #3539).
 *
 * Pins: the model's wording (age, status pill, banner title, the replayed settings and the
 * re-upload outcome) and the file → request body encoding; the stale banner shows only for a stale
 * upload and offers **Re-upload…** only to an editor; the **Uploaded file** card shows the file,
 * age, threshold and the settings a re-upload replays (or says defaults for a pre-capture upload)
 * and draws nothing for an item that is not an upload; the dialog posts the file as base64 with its
 * name, reports the answer and shows a refusal instead of closing. Plus axe on the card, the banner
 * and the dialog.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { CatalogItemUploadCard } from '../src/app/components/ade/catalog/detail/CatalogItemUploadCard';
import { CatalogReuploadDialog } from '../src/app/components/ade/catalog/detail/CatalogReuploadDialog';
import { CatalogStaleUploadBanner } from '../src/app/components/ade/catalog/detail/CatalogStaleUploadBanner';
import {
  bytesToBase64,
  replaySummary,
  replayedSettings,
  reuploadResultText,
  staleUploadTitle,
  uploadAgeText,
  uploadStatusView,
  type CatalogReuploadResult,
  type CatalogUpload,
} from '../src/app/components/ade/catalog/detail/catalogUploadModel';
import { catalogDetailActions } from '../src/app/components/ade/catalog/detail/catalogItemView';

const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

const ITEM = { id: 'item-1', name: 'Orders events' };

const STALE: CatalogUpload = {
  itemId: 'item-1',
  eligible: true,
  stale: true,
  staleAfterDays: 90,
  uploadedAt: '2026-06-01T09:30:00Z',
  ageDays: 151,
  versionId: 'ver-1',
  versionLabel: '1.0.0',
  sourceLabel: 'orders.asyncapi.yaml',
  spec: {
    specSchemaVersion: 1,
    sourceKind: 'asyncapi-2',
    options: {
      apply_naming_convention: true,
      class_naming_convention: 'camelCase',
      selected_schemas: ['OrderPlaced', 'OrderShipped'],
      auto_layout: false,
    },
  },
};

const RECENT: CatalogUpload = { ...STALE, stale: false, ageDays: 3 };
const NOT_AN_UPLOAD: CatalogUpload = { ...STALE, eligible: false, stale: false, spec: null };

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
  Element.prototype.hasPointerCapture = jest.fn(() => false);
  if (!File.prototype.arrayBuffer) {
    // jsdom's File has no arrayBuffer(); read it the way a browser would.
    File.prototype.arrayBuffer = function arrayBuffer(this: File) {
      return new Promise<ArrayBuffer>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as ArrayBuffer);
        reader.readAsArrayBuffer(this);
      });
    };
  }
});

afterEach(() => jest.restoreAllMocks());

// ---------------------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------------------

describe('catalogUploadModel', () => {
  it('words the age', () => {
    expect(uploadAgeText(null)).toBe('at an unknown time');
    expect(uploadAgeText(0)).toBe('today');
    expect(uploadAgeText(1)).toBe('1 day ago');
    expect(uploadAgeText(151)).toBe('151 days ago');
  });

  it('pills a stale upload as a warning and a recent one as ok', () => {
    expect(uploadStatusView(STALE)).toEqual({ label: 'May be stale', tone: 'warn' });
    expect(uploadStatusView(RECENT)).toEqual({ label: 'Recent', tone: 'ok' });
  });

  it('names the file and its age in the banner title', () => {
    expect(staleUploadTitle(STALE)).toBe('orders.asyncapi.yaml was uploaded 151 days ago');
    expect(staleUploadTitle({ ...STALE, sourceLabel: null })).toBe('This file was uploaded 151 days ago');
  });

  it('lists the settings that were set, known ones first, unset ones left out', () => {
    const spec = { ...STALE.spec!, options: { ...STALE.spec!.options, zz_custom: 'x', har_hosts: [] } };
    expect(replayedSettings(spec)).toEqual([
      { label: 'Schemas', value: 'OrderPlaced, OrderShipped' },
      { label: 'Apply naming convention', value: 'Yes' },
      { label: 'Class names', value: 'camelCase' },
      { label: 'zz_custom', value: 'x' },
    ]);
    expect(replayedSettings(null)).toEqual([]);
  });

  it('summarises what a re-upload replays', () => {
    expect(replaySummary(STALE)).toBe('The new file is imported with the 3 settings the first upload used.');
    expect(replaySummary({ ...STALE, spec: { ...STALE.spec!, options: {} } })).toMatch(/the defaults/);
    expect(replaySummary({ ...STALE, spec: null })).toMatch(/before Apiome kept import settings/);
  });

  it('words the re-upload outcome', () => {
    const changed = { status: 'changed', versionLabel: '2026-10-30T12:00Z' } as CatalogReuploadResult;
    expect(reuploadResultText(changed)).toBe('Added version 2026-10-30T12:00Z.');
    expect(reuploadResultText({ ...changed, status: 'unchanged' })).toMatch(/nothing changed/);
  });

  it('encodes bytes as standard base64', () => {
    expect(bytesToBase64(new TextEncoder().encode('asyncapi: 2.6.0\n'))).toBe('YXN5bmNhcGk6IDIuNi4wCg==');
    expect(bytesToBase64(new Uint8Array([0xff, 0xfe, 0x00]))).toBe('//4A');
  });

  it('offers re-upload only to a role that may import and edit, on a live item', () => {
    const item = { deleted_at: null, sourceFormat: 'asyncapi-2', conversion: null };
    expect(catalogDetailActions(item).reupload.shown).toBe(true);
    expect(catalogDetailActions(item, (grant) => grant !== 'imports:create').reupload.shown).toBe(false);
    expect(catalogDetailActions(item, (grant) => grant !== 'projects:edit').reupload.shown).toBe(false);
    expect(catalogDetailActions({ ...item, deleted_at: '2026-10-01' }).reupload.shown).toBe(false);
  });
});

// ---------------------------------------------------------------------------------------
// Banner
// ---------------------------------------------------------------------------------------

describe('CatalogStaleUploadBanner', () => {
  it('draws nothing while loading, for a recent upload or for a non-upload', () => {
    for (const upload of [null, RECENT, NOT_AN_UPLOAD]) {
      const { container, unmount } = render(
        <CatalogStaleUploadBanner upload={upload} canReupload onReupload={jest.fn()} onOpenDetails={jest.fn()} />,
      );
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it('flags a stale upload and offers re-upload and the details', async () => {
    const onReupload = jest.fn();
    const onOpenDetails = jest.fn();
    const { container } = render(
      <CatalogStaleUploadBanner upload={STALE} canReupload onReupload={onReupload} onOpenDetails={onOpenDetails} />,
    );
    expect(screen.getByTestId('catalog-stale-upload-banner')).toHaveTextContent(
      'orders.asyncapi.yaml was uploaded 151 days ago',
    );
    fireEvent.click(screen.getByTestId('catalog-stale-upload-reupload'));
    fireEvent.click(screen.getByTestId('catalog-stale-upload-details'));
    expect(onReupload).toHaveBeenCalledTimes(1);
    expect(onOpenDetails).toHaveBeenCalledTimes(1);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('shows a viewer the hint without the re-upload button', () => {
    render(<CatalogStaleUploadBanner upload={STALE} canReupload={false} onReupload={jest.fn()} onOpenDetails={jest.fn()} />);
    expect(screen.getByTestId('catalog-stale-upload-banner')).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-stale-upload-reupload')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------------------

describe('CatalogItemUploadCard', () => {
  const card = (props: Partial<React.ComponentProps<typeof CatalogItemUploadCard>> = {}) =>
    render(
      <CatalogItemUploadCard
        upload={STALE}
        error={null}
        canReupload
        onReupload={jest.fn()}
        lastResult={null}
        {...props}
      />,
    );

  it('draws nothing while loading or for an item that is not an upload', () => {
    expect(card({ upload: null }).container).toBeEmptyDOMElement();
    expect(card({ upload: NOT_AN_UPLOAD }).container).toBeEmptyDOMElement();
  });

  it('shows the file, its age, the threshold and the replayed settings', async () => {
    const { container } = card();
    expect(screen.getByTestId('catalog-detail-upload-status')).toHaveTextContent('May be stale');
    const facts = screen.getByTestId('catalog-detail-upload-facts');
    expect(facts).toHaveTextContent('orders.asyncapi.yaml');
    expect(facts).toHaveTextContent('151 days ago');
    expect(screen.getByTestId('catalog-detail-upload-threshold')).toHaveTextContent('90 days');
    const settings = screen.getByTestId('catalog-detail-upload-settings');
    expect(settings).toHaveTextContent('Class names: camelCase');
    expect(settings).toHaveTextContent('Schemas: OrderPlaced, OrderShipped');
    expect(settings).not.toHaveTextContent('Auto layout');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('says a pre-capture upload re-uploads with the defaults', () => {
    card({ upload: { ...RECENT, spec: null } });
    expect(screen.getByTestId('catalog-detail-upload-status')).toHaveTextContent('Recent');
    expect(screen.getByTestId('catalog-detail-upload-settings')).toHaveTextContent('Default settings');
  });

  it('offers re-upload to an editor only, and shows the last outcome', () => {
    const onReupload = jest.fn();
    const { unmount } = card({ onReupload, lastResult: 'Added version 2026-10-30T12:00Z.' });
    fireEvent.click(screen.getByTestId('catalog-detail-upload-reupload'));
    expect(onReupload).toHaveBeenCalled();
    expect(screen.getByTestId('catalog-detail-upload-result')).toHaveTextContent('Added version 2026-10-30T12:00Z.');
    unmount();
    card({ canReupload: false });
    expect(screen.queryByTestId('catalog-detail-upload-reupload')).not.toBeInTheDocument();
  });

  it('shows a load error', () => {
    card({ upload: null, error: 'The upload details could not be loaded.' });
    expect(screen.getByRole('alert')).toHaveTextContent('could not be loaded');
  });
});

// ---------------------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------------------

type Answer = { status?: number; body: unknown };

/** Mock the BFF's re-upload route; every call is recorded. */
function mockReupload(answer: Answer) {
  const calls: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      method: init?.method ?? 'GET',
      url: String(input),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    const status = answer.status ?? 200;
    return { ok: status < 400, status, json: async () => answer.body } as Response;
  }) as unknown as typeof fetch;
  return calls;
}

function pickFile(text: string, name = 'orders.asyncapi.yaml') {
  const file = new File([text], name, { type: 'application/yaml' });
  fireEvent.change(screen.getByTestId('catalog-reupload-file'), { target: { files: [file] } });
}

describe('CatalogReuploadDialog', () => {
  const dialog = (props: Partial<React.ComponentProps<typeof CatalogReuploadDialog>> = {}) =>
    render(
      <CatalogReuploadDialog
        open
        item={ITEM}
        upload={STALE}
        onOpenChange={jest.fn()}
        onReuploaded={jest.fn()}
        {...props}
      />,
    );

  it('lists the settings it replays and waits for a file', async () => {
    dialog();
    const replay = screen.getByTestId('catalog-reupload-replay');
    expect(replay).toHaveTextContent('3 settings the first upload used');
    expect(replay).toHaveTextContent('camelCase');
    expect(screen.getByTestId('catalog-reupload-submit')).toBeDisabled();
    expect(await axe(screen.getByTestId('catalog-reupload-dialog'), AXE_OPTIONS)).toHaveNoViolations();
  });

  it('posts the file as base64 with its name and hands back the answer', async () => {
    const result: CatalogReuploadResult = {
      status: 'changed',
      specReplayed: true,
      versionId: 'ver-2',
      versionLabel: '2026-10-30T12:00Z',
      upload: { ...STALE, stale: false, ageDays: 0 },
    };
    const calls = mockReupload({ body: result });
    const onReuploaded = jest.fn();
    const onOpenChange = jest.fn();
    dialog({ onReuploaded, onOpenChange });

    pickFile('asyncapi: 2.6.0\n');
    fireEvent.click(screen.getByTestId('catalog-reupload-submit'));

    await waitFor(() => expect(onReuploaded).toHaveBeenCalledWith(result));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(calls).toEqual([
      {
        method: 'POST',
        url: '/api/catalog/item-1/reupload',
        body: {
          filename: 'orders.asyncapi.yaml',
          documentBase64: 'YXN5bmNhcGk6IDIuNi4wCg==',
          contentType: 'application/yaml',
        },
      },
    ]);
  });

  it('shows a refusal and stays open', async () => {
    mockReupload({ status: 409, body: { success: false, error: 'The import quality policy blocks this file.' } });
    const onOpenChange = jest.fn();
    const onReuploaded = jest.fn();
    dialog({ onOpenChange, onReuploaded });

    pickFile('asyncapi: 2.6.0\n');
    fireEvent.click(screen.getByTestId('catalog-reupload-submit'));

    expect(await screen.findByTestId('catalog-reupload-error')).toHaveTextContent('quality policy');
    expect(onReuploaded).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
