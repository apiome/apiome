/**
 * What's New dialog: viewport-centered overlay (#2531).
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

jest.mock('rehype-raw', () => ({
  __esModule: true,
  default: () => () => {},
}));

import WhatsNewDialog from '../src/app/components/ade/WhatsNewDialog';

describe('WhatsNewDialog', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    (global.fetch as jest.Mock).mockResolvedValue({
      text: () => Promise.resolve('# Test\n\nHello.'),
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders the backdrop as a direct child of document.body (viewport-fixed centering)', async () => {
    render(<WhatsNewDialog isOpen onClose={jest.fn()} />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /what's new/i })).toBeInTheDocument();
    });

    const backdrop = screen
      .getByRole('heading', { name: /what's new/i })
      .closest('.fixed.inset-0');

    expect(backdrop).toBeTruthy();
    expect(backdrop?.parentElement).toBe(document.body);
  });

  it('renders nothing when closed', () => {
    const { container } = render(<WhatsNewDialog isOpen={false} onClose={jest.fn()} />);

    expect(container.firstChild).toBeNull();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
