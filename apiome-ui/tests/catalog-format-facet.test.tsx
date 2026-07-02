/**
 * Render/interaction tests for the Catalog format facet (MFI-28.4, #4120).
 *
 * The facet is a controlled multi-select dropdown that filters the catalog by format. These cover
 * the disabled empty state, opening the menu, toggling options on/off (reported to the parent),
 * the active-count badge, clearing the selection, and closing on Escape.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { CatalogFormatFacet } from '../src/app/components/ade/dashboard/catalog/CatalogFormatFacet';

const OPTIONS = [
  { id: 'grpc', label: 'gRPC' },
  { id: 'graphql', label: 'GraphQL' },
  { id: 'asyncapi', label: 'AsyncAPI' },
];

describe('CatalogFormatFacet', () => {
  it('disables the trigger and does not open when there are no formats', () => {
    render(<CatalogFormatFacet options={[]} selected={[]} onChange={() => {}} />);
    const trigger = screen.getByTestId('catalog-format-facet');
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByTestId('catalog-format-facet-menu')).not.toBeInTheDocument();
  });

  it('opens the menu and lists every available format', () => {
    render(<CatalogFormatFacet options={OPTIONS} selected={[]} onChange={() => {}} />);
    fireEvent.click(screen.getByTestId('catalog-format-facet'));
    expect(screen.getByTestId('catalog-format-facet-menu')).toBeInTheDocument();
    for (const opt of OPTIONS) {
      expect(screen.getByTestId(`catalog-format-option-${opt.id}`)).toHaveTextContent(opt.label);
    }
  });

  it('adds an unselected format to the selection when clicked', () => {
    const onChange = jest.fn();
    render(<CatalogFormatFacet options={OPTIONS} selected={['grpc']} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('catalog-format-facet'));
    fireEvent.click(screen.getByTestId('catalog-format-option-graphql'));
    expect(onChange).toHaveBeenCalledWith(['grpc', 'graphql']);
  });

  it('removes an already-selected format when clicked again', () => {
    const onChange = jest.fn();
    render(<CatalogFormatFacet options={OPTIONS} selected={['grpc', 'graphql']} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('catalog-format-facet'));
    fireEvent.click(screen.getByTestId('catalog-format-option-grpc'));
    expect(onChange).toHaveBeenCalledWith(['graphql']);
  });

  it('shows the active-count badge and marks selected options', () => {
    render(<CatalogFormatFacet options={OPTIONS} selected={['grpc', 'asyncapi']} onChange={() => {}} />);
    expect(screen.getByTestId('catalog-format-facet')).toHaveTextContent('2');
    fireEvent.click(screen.getByTestId('catalog-format-facet'));
    expect(screen.getByTestId('catalog-format-option-grpc')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('catalog-format-option-graphql')).toHaveAttribute('aria-selected', 'false');
  });

  it('clears the whole selection via the Clear button', () => {
    const onChange = jest.fn();
    render(<CatalogFormatFacet options={OPTIONS} selected={['grpc']} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('catalog-format-facet'));
    fireEvent.click(screen.getByTestId('catalog-format-clear'));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('offers no Clear button when nothing is selected', () => {
    render(<CatalogFormatFacet options={OPTIONS} selected={[]} onChange={() => {}} />);
    fireEvent.click(screen.getByTestId('catalog-format-facet'));
    expect(screen.queryByTestId('catalog-format-clear')).not.toBeInTheDocument();
  });

  it('closes the menu on Escape', () => {
    render(<CatalogFormatFacet options={OPTIONS} selected={[]} onChange={() => {}} />);
    fireEvent.click(screen.getByTestId('catalog-format-facet'));
    expect(screen.getByTestId('catalog-format-facet-menu')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('catalog-format-facet-menu')).not.toBeInTheDocument();
  });
});
