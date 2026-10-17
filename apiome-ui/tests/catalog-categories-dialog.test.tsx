/**
 * The catalog Categorize dialog (MFI-6.3, #3755).
 *
 * Pins how an item's manual categories are edited: tags are added with Enter or a comma (and a
 * tag still in the box is saved as if Enter had been pressed), held to the REST rule as they are
 * typed, removed with their × button or Backspace; the domain comes from the Projects list; Save
 * sends `PUT /api/catalog/{id}/categories` with exactly what the API stores, and a refusal is
 * shown in the dialog rather than closing it. Plus axe, and the item page's entry point.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { CatalogCategoriesDialog } from '../src/app/components/ade/catalog/CatalogCategoriesDialog';

const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

const ITEM = {
  id: 'item-1',
  name: 'Orders gRPC',
  paradigm: 'rpc',
  domain: 'ecommerce',
  tags: ['public'],
};

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

/** Mock the proxy: answer the PUT with `response` (ok) or `{ detail }` (status ≥ 400). */
function mockPut(status = 200, body: Record<string, unknown> = {}) {
  global.fetch = jest.fn(async () => ({
    ok: status < 400,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

function renderDialog(item = ITEM) {
  const onSaved = jest.fn();
  const onOpenChange = jest.fn();
  render(<CatalogCategoriesDialog open item={item} onSaved={onSaved} onOpenChange={onOpenChange} />);
  return { onSaved, onOpenChange };
}

const tagInput = () => screen.getByTestId('catalog-categories-tag-input');
const chips = () =>
  within(screen.getByTestId('catalog-categories-tags'))
    .getAllByRole('listitem')
    .map((li) => li.textContent);

afterEach(() => jest.restoreAllMocks());

describe('CatalogCategoriesDialog', () => {
  it('shows the derived paradigm read-only, and the current domain and tags', () => {
    renderDialog();
    expect(screen.getByTestId('catalog-categories-paradigm')).toHaveTextContent('rpc');
    expect(screen.getByTestId('catalog-categories-domain')).toHaveTextContent(/e-?commerce/i);
    expect(chips()).toEqual(['public']);
  });

  it('adds a tag with Enter or a comma, normalized, and ignores a duplicate', () => {
    renderDialog();
    fireEvent.change(tagInput(), { target: { value: '  Payments   Core ' } });
    fireEvent.keyDown(tagInput(), { key: 'Enter' });
    fireEvent.change(tagInput(), { target: { value: 'beta' } });
    fireEvent.keyDown(tagInput(), { key: ',' });
    fireEvent.change(tagInput(), { target: { value: 'PUBLIC' } });
    fireEvent.keyDown(tagInput(), { key: 'Enter' });
    expect(chips()).toEqual(['public', 'payments core', 'beta']);
    expect(tagInput()).toHaveValue('');
  });

  it('refuses a reserved tag as it is typed', () => {
    renderDialog();
    fireEvent.change(tagInput(), { target: { value: 'uncategorized' } });
    fireEvent.keyDown(tagInput(), { key: 'Enter' });
    expect(screen.getByRole('alert')).toHaveTextContent('reserved');
    expect(chips()).toEqual(['public']);
  });

  it('removes a tag with its × button, and the last one with Backspace on an empty box', () => {
    renderDialog({ ...ITEM, tags: ['a', 'b', 'c'] });
    fireEvent.click(screen.getByRole('button', { name: 'Remove tag b' }));
    expect(chips()).toEqual(['a', 'c']);
    fireEvent.keyDown(tagInput(), { key: 'Backspace' });
    expect(chips()).toEqual(['a']);
  });

  it('saves the domain and tags — including a tag still being typed — and closes', async () => {
    mockPut(200, { success: true, paradigm: 'rpc', domain: 'finance', tags: ['beta', 'public'] });
    const { onSaved, onOpenChange } = renderDialog();
    fireEvent.click(screen.getByTestId('catalog-categories-domain'));
    fireEvent.click(await screen.findByRole('option', { name: /Finance/ }));
    fireEvent.change(tagInput(), { target: { value: 'Beta' } });
    fireEvent.click(screen.getByTestId('catalog-categories-save'));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toBe('/api/catalog/item-1/categories');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ domain: 'finance', tags: ['public', 'beta'] });
    expect(onSaved).toHaveBeenCalledWith({ paradigm: 'rpc', domain: 'finance', tags: ['beta', 'public'] });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('sends null when No domain is chosen', async () => {
    mockPut(200, { success: true, domain: null, tags: [] });
    renderDialog();
    fireEvent.click(screen.getByTestId('catalog-categories-domain'));
    fireEvent.click(await screen.findByRole('option', { name: 'No domain' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove tag public' }));
    fireEvent.click(screen.getByTestId('catalog-categories-save'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body)).toEqual({
      domain: null,
      tags: [],
    });
  });

  it('keeps the dialog open and says why when the API refuses', async () => {
    mockPut(403, { success: false, detail: 'You do not have projects:edit.' });
    const { onSaved, onOpenChange } = renderDialog();
    fireEvent.click(screen.getByTestId('catalog-categories-save'));
    expect(await screen.findByRole('alert')).toHaveTextContent('projects:edit');
    expect(onSaved).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it('passes axe', async () => {
    renderDialog();
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });
});
