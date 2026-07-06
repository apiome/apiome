/**
 * Render tests for the bundle file tabs strip (MFX-43.2, #4362).
 *
 * The strip must render one tab per open file (basename + finding badge), mark the active tab, and
 * call back on activate/close. It renders nothing when no file is open.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { BundleFileTabs } from '../src/app/components/ade/dashboard/export/BundleFileTabs';
import { countFindingsByFile } from '../src/app/components/ade/dashboard/export/exportBundle';

const counts = countFindingsByFile([{ file: 'com/example/User.avsc' }], []);

describe('BundleFileTabs (MFX-43.2)', () => {
  it('renders a tab per open file with its basename', () => {
    render(
      <BundleFileTabs
        openPaths={['petstore.proto', 'com/example/User.avsc']}
        activePath="petstore.proto"
        countsByPath={counts}
        onActivate={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    expect(screen.getByTestId('bundle-file-tabs')).toBeInTheDocument();
    expect(screen.getByTestId('bundle-tab-petstore.proto')).toHaveAttribute('data-active', 'true');
    // The nested path shows only its basename.
    expect(screen.getByTestId('bundle-tab-activate-com/example/User.avsc')).toHaveTextContent('User.avsc');
    // The finding-bearing tab badges its count.
    expect(screen.getByTestId('bundle-tab-badge-com/example/User.avsc')).toHaveTextContent('1');
  });

  it('activates and closes tabs', () => {
    const onActivate = jest.fn();
    const onClose = jest.fn();
    render(
      <BundleFileTabs
        openPaths={['petstore.proto', 'com/example/User.avsc']}
        activePath="petstore.proto"
        countsByPath={counts}
        onActivate={onActivate}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId('bundle-tab-activate-com/example/User.avsc'));
    expect(onActivate).toHaveBeenCalledWith('com/example/User.avsc');

    fireEvent.click(screen.getByTestId('bundle-tab-close-petstore.proto'));
    expect(onClose).toHaveBeenCalledWith('petstore.proto');
  });

  it('renders nothing when no file is open', () => {
    const { container } = render(
      <BundleFileTabs
        openPaths={[]}
        activePath={null}
        countsByPath={counts}
        onActivate={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
