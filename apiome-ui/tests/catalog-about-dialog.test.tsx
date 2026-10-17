/**
 * "How the catalog works" (HIVE-11.6, #5602).
 *
 * The dialog replaced the Catalog page's standing non-publishable banner and its Supported
 * import formats card. These tests pin that it carries the explainer's three points, and that
 * its formats list follows the import-source registry (FMT-1.2, #5413) the way the gallery did:
 * a format is importable because `GET /api/import/sources` reports its adapter, an adapter whose
 * toolchain is missing is not counted as importable here, and the shipped list is the fallback
 * when the registry is unreachable.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import {
  CATALOG_ABOUT_PILL_LIMIT,
  CatalogAboutDialog,
  SUPPORTED_FORMATS_GUIDE_HREF,
  catalogFormatCountsLine,
} from '../src/app/components/ade/catalog/CatalogAboutDialog';

/** One descriptor as `GET /api/import/sources` reports it. */
function source(key: string, available = true, unavailable_reason: string | null = null) {
  return {
    key,
    label: key,
    description: `The ${key} adapter.`,
    icon: 'file-code',
    paradigm: 'rest',
    input_kinds: ['file', 'url', 'paste'],
    supports_live_discovery: false,
    formats: [key],
    file_extensions: [`.${key}`],
    available,
    unavailable_reason,
  };
}

/** Serve a fixture registry payload for `/api/import/sources`; everything else fails closed. */
function mockRegistry(sources: ReturnType<typeof source>[] | null) {
  return jest.fn((input: unknown) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/import/sources')) {
      if (sources === null) {
        return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, sources }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
}

/** Render the dialog open and wait for the registry read it makes while open. */
async function renderDialog(onOpenChange: (open: boolean) => void = () => undefined) {
  render(<CatalogAboutDialog open onOpenChange={onOpenChange} />);
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything())
  );
  return screen.getByRole('dialog', { name: 'How the catalog works' });
}

/** The counts line beside the formats heading. */
const counts = () => screen.getByTestId('catalog-about-counts');

afterEach(() => {
  jest.restoreAllMocks();
});

describe('catalogFormatCountsLine', () => {
  it('always states the importable count and drops the zeros after it', () => {
    expect(
      catalogFormatCountsLine({
        importable: 44,
        unavailable: 0,
        recognized: 4,
      })
    ).toBe('44 importable · 4 recognized');
    expect(catalogFormatCountsLine({ importable: 0, unavailable: 0, recognized: 0 })).toBe(
      '0 importable'
    );
    expect(catalogFormatCountsLine({ importable: 3, unavailable: 1, recognized: 2 })).toBe(
      '3 importable · 1 unavailable here · 2 recognized'
    );
  });
});

describe('CatalogAboutDialog carries the explainer', () => {
  it('states the three points', async () => {
    global.fetch = mockRegistry([source('grpc')]) as unknown as typeof fetch;
    const dialog = await renderDialog();
    expect(within(dialog).getByText('Catalog items are stored as-is')).toBeInTheDocument();
    expect(
      within(dialog).getByText('They are not publishable until converted')
    ).toBeInTheDocument();
    expect(within(dialog).getByText('OpenAPI and Swagger go to Projects')).toBeInTheDocument();
    expect(within(dialog).getByText('Convert to OpenAPI')).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Projects' })).toHaveAttribute(
      'href',
      '/ade/dashboard/projects'
    );
  });

  it('links the Supported formats guide in a new tab, and says so', async () => {
    global.fetch = mockRegistry([source('grpc')]) as unknown as typeof fetch;
    const dialog = await renderDialog();
    const guide = within(dialog).getByRole('link', {
      name: /Supported formats guide/,
    });
    expect(guide).toHaveAttribute('href', SUPPORTED_FORMATS_GUIDE_HREF);
    expect(SUPPORTED_FORMATS_GUIDE_HREF).toMatch(/bring-in\/supported-formats$/);
    expect(guide).toHaveAttribute('target', '_blank');
    expect(guide).toHaveAccessibleName(/opens in new tab/);
  });

  it('closes from Got it', async () => {
    const user = userEvent.setup();
    const onOpenChange = jest.fn();
    global.fetch = mockRegistry([source('grpc')]) as unknown as typeof fetch;
    const dialog = await renderDialog(onOpenChange);
    await user.click(within(dialog).getByRole('button', { name: 'Got it' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('reads the registry only while it is open', () => {
    global.fetch = mockRegistry([source('grpc')]) as unknown as typeof fetch;
    render(<CatalogAboutDialog open={false} onOpenChange={() => undefined} />);
    expect(global.fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('CatalogAboutDialog reads the registry', () => {
  it('lists a format as importable because the registry reports its adapter', async () => {
    global.fetch = mockRegistry([source('grpc'), source('graphql')]) as unknown as typeof fetch;
    await renderDialog();
    // Two entries — `gRPC` and `Protobuf` — import under the one `grpc` adapter, plus GraphQL.
    await waitFor(() => expect(counts()).toHaveTextContent(/^3 importable/));
    const pills = screen.getByTestId('catalog-about-formats');
    expect(within(pills).getByText('GraphQL')).toBeInTheDocument();
    expect(within(pills).getByText('gRPC')).toBeInTheDocument();
    // Everything the registry does not report is recognized, not importable.
    expect(counts()).toHaveTextContent(/recognized$/);
  });

  it('counts only what this deployment can actually run', async () => {
    global.fetch = mockRegistry([
      source('grpc', false, 'Requires the buf toolchain, which is not available in this runtime.'),
      source('graphql'),
    ]) as unknown as typeof fetch;
    await renderDialog();
    await waitFor(() => expect(counts()).toHaveTextContent(/^1 importable · 2 unavailable here/));
    expect(within(screen.getByTestId('catalog-about-formats')).queryByText('gRPC')).toBeNull();
  });

  it('draws a capped row of pills and counts the rest as "+n more"', async () => {
    const everything = [
      'grpc',
      'graphql',
      'asyncapi',
      'thrift',
      'connectrpc',
      'flatbuffers',
      'capnproto',
      'wit',
      'wsdl',
      'raml',
      'wadl',
      'discovery',
      'openrpc',
      'avro',
      'xmlrpc',
      'xsd',
      'postman',
    ].map((key) => source(key));
    global.fetch = mockRegistry(everything) as unknown as typeof fetch;
    await renderDialog();

    await waitFor(() => expect(screen.getByTestId('catalog-about-more')).toBeInTheDocument());
    const total = Number(/^(\d+) importable/.exec(counts().textContent ?? '')?.[1]);
    const pills = within(screen.getByTestId('catalog-about-formats')).getAllByTestId('format-pill');
    expect(pills).toHaveLength(CATALOG_ABOUT_PILL_LIMIT);
    expect(screen.getByTestId('catalog-about-more')).toHaveTextContent(
      `+${total - CATALOG_ABOUT_PILL_LIMIT} more`
    );
  });

  it('falls back to the shipped list when the registry is unreachable', async () => {
    // A blank list would be worse than a slightly stale one.
    global.fetch = mockRegistry(null) as unknown as typeof fetch;
    await renderDialog();
    expect(
      within(screen.getByTestId('catalog-about-formats')).getAllByTestId('format-pill').length
    ).toBeGreaterThan(0);
  });
});
