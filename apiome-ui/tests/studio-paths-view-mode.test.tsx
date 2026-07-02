/**
 * Paths editor Canvas / Code session preference (#2640 P-01).
 */

import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { StudioProvider, useStudio, PATHS_VIEW_MODE_STORAGE_KEY } from '../src/app/ade/studio/StudioContext';

function PathsModeProbe() {
  const { pathsViewMode, setPathsViewMode } = useStudio();
  return (
    <div>
      <span data-testid="paths-mode">{pathsViewMode}</span>
      <button type="button" onClick={() => setPathsViewMode('code')}>
        use-code
      </button>
      <button type="button" onClick={() => setPathsViewMode('canvas')}>
        use-canvas
      </button>
    </div>
  );
}

describe('StudioContext pathsViewMode', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('persists setPathsViewMode to sessionStorage', () => {
    render(
      <StudioProvider>
        <PathsModeProbe />
      </StudioProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'use-code' }));
    expect(sessionStorage.getItem(PATHS_VIEW_MODE_STORAGE_KEY)).toBe('code');

    fireEvent.click(screen.getByRole('button', { name: 'use-canvas' }));
    expect(sessionStorage.getItem(PATHS_VIEW_MODE_STORAGE_KEY)).toBe('canvas');
  });

  it('restores paths view mode from sessionStorage after mount', async () => {
    sessionStorage.setItem(PATHS_VIEW_MODE_STORAGE_KEY, 'code');

    render(
      <StudioProvider>
        <PathsModeProbe />
      </StudioProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('paths-mode')).toHaveTextContent('code');
    });
  });
});
