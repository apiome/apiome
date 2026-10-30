/**
 * The **Postman Collection** import card's panel (MFI-32.7, #4409): it converts through the REST
 * Postman import adapter and continues into the import wizard with the OpenAPI it returns; with
 * `FEATURE_LEGACY_POSTMAN_IMPORT` on it falls back to the retired in-browser converter.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { afterEach, describe, expect, jest, test } from '@jest/globals';

const convertPostmanWithAdapter = jest.fn<(...args: unknown[]) => Promise<unknown>>();
const legacyConvert = jest.fn<(...args: unknown[]) => unknown>();
const flags = { FEATURE_LEGACY_POSTMAN_IMPORT: false };

jest.mock('@/app/utils/postman-import-adapter', () => ({
  convertPostmanWithAdapter: (...args: unknown[]) => convertPostmanWithAdapter(...args),
}));
jest.mock('@/app/utils/postman-to-openapi', () => ({
  convertPostmanJsonToOpenAPIString: (...args: unknown[]) => legacyConvert(...args),
}));
jest.mock('@lib/feature-flags', () => ({
  get FEATURE_LEGACY_POSTMAN_IMPORT() {
    return flags.FEATURE_LEGACY_POSTMAN_IMPORT;
  },
}));

import { PostmanImportPanel } from '@/app/components/ade/dashboard/PostmanImportPanel';

const COLLECTION = JSON.stringify({ info: { name: 'Shop API' }, item: [] });
const OPENAPI = { openapi: '3.1.0', info: { title: 'Shop API', version: '1.0.0' }, paths: { '/orders': {} } };

/** Render the panel, paste the collection and press Convert. */
function convert(onSpecificationFetched = jest.fn()) {
  render(<PostmanImportPanel onSpecificationFetched={onSpecificationFetched} />);
  fireEvent.change(screen.getByPlaceholderText(/Paste Postman Collection/), { target: { value: COLLECTION } });
  fireEvent.change(screen.getByPlaceholderText('e.g. https://api.example.com'), {
    target: { value: 'https://api.example.com' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Convert to OpenAPI/ }));
  return onSpecificationFetched;
}

afterEach(() => {
  convertPostmanWithAdapter.mockReset();
  legacyConvert.mockReset();
  flags.FEATURE_LEGACY_POSTMAN_IMPORT = false;
});

describe('PostmanImportPanel', () => {
  test('converts through the adapter and hands the OpenAPI to the wizard', async () => {
    convertPostmanWithAdapter.mockResolvedValue({ success: true, document: OPENAPI, warnings: [] });
    const onFetched = convert();

    await waitFor(() => expect(onFetched).toHaveBeenCalledTimes(1));
    expect(convertPostmanWithAdapter).toHaveBeenCalledWith(COLLECTION, {
      baseUrl: 'https://api.example.com',
      filename: 'postman-collection.json',
    });
    const [content, filename] = onFetched.mock.calls[0] as [string, string];
    expect(JSON.parse(content)).toEqual(OPENAPI);
    expect(filename).toBe('postman-collection-openapi.json');
    expect(screen.getByText('Converted to OpenAPI 3.1')).toBeInTheDocument();
    expect(legacyConvert).not.toHaveBeenCalled();
  });

  test('lists the adapter’s warnings', async () => {
    convertPostmanWithAdapter.mockResolvedValue({
      success: true,
      document: OPENAPI,
      warnings: ['Pre-request and test scripts are run by Postman; they are not modelled. (Create order)'],
    });
    convert();
    expect(
      await screen.findByText('Pre-request and test scripts are run by Postman; they are not modelled. (Create order)')
    ).toBeInTheDocument();
  });

  test('shows the adapter’s error and does not continue', async () => {
    convertPostmanWithAdapter.mockResolvedValue({ success: false, error: 'Not a Postman collection', warnings: [] });
    const onFetched = convert();
    expect(await screen.findByText('Not a Postman collection')).toBeInTheDocument();
    expect(screen.getByText('Conversion failed')).toBeInTheDocument();
    expect(onFetched).not.toHaveBeenCalled();
  });

  test('uses the in-browser converter when FEATURE_LEGACY_POSTMAN_IMPORT is on', async () => {
    flags.FEATURE_LEGACY_POSTMAN_IMPORT = true;
    legacyConvert.mockReturnValue({ success: true, document: OPENAPI, warnings: [] });
    const onFetched = convert();
    await waitFor(() => expect(onFetched).toHaveBeenCalledTimes(1));
    expect(legacyConvert).toHaveBeenCalledWith(COLLECTION, { baseUrl: 'https://api.example.com' });
    expect(convertPostmanWithAdapter).not.toHaveBeenCalled();
  });
});
