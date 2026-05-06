/**
 * Add Property / Edit Property — **Analyze** opens AI property suggestions (#276).
 */

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: function MockMonaco() {
    return null;
  },
}));

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PropertyDialog from '../../src/app/components/ade/studio/PropertyDialog';

(global as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

describe('PropertyDialog Analyze (#276)', () => {
  it('calls onOpenAiPropertySuggestions when Analyze is clicked', async () => {
    const user = userEvent.setup();
    const onOpenAiPropertySuggestions = jest.fn();

    render(
      <PropertyDialog
        open
        onClose={jest.fn()}
        mode="add"
        property={null}
        onSubmit={jest.fn().mockResolvedValue(undefined)}
        onOpenAiPropertySuggestions={onOpenAiPropertySuggestions}
      />,
    );

    await user.click(screen.getByTestId('property-dialog-analyze-ai-properties'));
    expect(onOpenAiPropertySuggestions).toHaveBeenCalledTimes(1);
  });

  it('does not render Analyze when onOpenAiPropertySuggestions is omitted', () => {
    render(
      <PropertyDialog
        open
        onClose={jest.fn()}
        mode="edit"
        property={{
          id: 'p1',
          name: 'email',
          type: 'string',
        }}
        onSubmit={jest.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.queryByTestId('property-dialog-analyze-ai-properties')).not.toBeInTheDocument();
  });
});
