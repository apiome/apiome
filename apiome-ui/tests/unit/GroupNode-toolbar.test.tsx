/**
 * Group canvas node: floating edit toolbar (#859).
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ReactFlowProvider } from '@xyflow/react';

import GroupNode, { type GroupNodeData } from '../../src/app/components/ade/studio/GroupNode';
import { StudioProvider } from '../../src/app/ade/studio/StudioContext';

jest.mock('../../src/app/components/ade/studio/GroupBulkEditDialog', () => ({
  __esModule: true,
  default: () => null,
}));

// Radix UI popovers use ResizeObserver internally; provide a no-op stub for jsdom.
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

const baseData: GroupNodeData = {
  id: 'g1',
  name: 'Alpha Group',
  color: 'indigo',
  nodeIds: ['n1'],
};

function renderGroup(overrides?: Partial<GroupNodeData>, selected = false) {
  const data = { ...baseData, ...overrides };
  return render(
    <StudioProvider>
      <ReactFlowProvider>
        <GroupNode
          id="g1"
          type="groupNode"
          data={data as unknown as Record<string, unknown>}
          selected={selected}
        />
      </ReactFlowProvider>
    </StudioProvider>
  );
}

describe('GroupNode floating toolbar', () => {
  it('does not show style controls when the frame is not hovered or selected', () => {
    renderGroup(undefined, false);
    expect(screen.queryByTitle('Style settings')).not.toBeInTheDocument();
  });

  it('shows style controls when hovering the group surface', () => {
    renderGroup(undefined, false);
    const surface = screen.getByTestId('group-node-surface');
    fireEvent.mouseEnter(surface);
    expect(screen.getByTitle('Style settings')).toBeInTheDocument();
    expect(screen.getByTitle('Change color')).toBeInTheDocument();
  });

  it('shows style controls when selected even without hover', () => {
    renderGroup(undefined, true);
    expect(screen.getByTitle('Style settings')).toBeInTheDocument();
  });

  it('hides toolbar in read-only mode', () => {
    renderGroup({ isReadOnly: true }, true);
    expect(screen.queryByTitle('Style settings')).not.toBeInTheDocument();
  });

  it('toolbar buttons have accessible aria-labels', () => {
    renderGroup(undefined, true);
    expect(screen.getByRole('button', { name: 'Style settings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Change color' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rename group' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete group' })).toBeInTheDocument();
  });

  it('toolbar stays visible after mouseLeave while the settings popover is open', () => {
    renderGroup(undefined, false);
    const surface = screen.getByTestId('group-node-surface');

    // Hover the surface to reveal the toolbar
    fireEvent.mouseEnter(surface);
    expect(screen.getByTitle('Style settings')).toBeInTheDocument();

    // Open the "Style settings" popover
    fireEvent.click(screen.getByTitle('Style settings'));

    // Simulate the cursor leaving the group surface (e.g., moving into the popover portal)
    fireEvent.mouseLeave(surface);

    // Toolbar must remain because the popover is still open
    expect(screen.getByTitle('Style settings')).toBeInTheDocument();
  });
});
