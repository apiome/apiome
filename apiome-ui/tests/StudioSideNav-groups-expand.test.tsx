/**
 * Studio sidebar Groups tab: expand/collapse group entries (#98).
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import StudioSideNav from '../src/app/components/ade/studio/StudioSideNav';

jest.mock('../lib/db/helper', () => ({
  getPropertiesForClassesBatch: jest.fn().mockResolvedValue('{}'),
}));

describe('StudioSideNav Groups expand/collapse', () => {
  const groups = [
    {
      id: 'g1',
      name: 'Orders',
      color: '#8b5cf6',
      nodeIds: ['c1', 'c2'],
    },
  ];

  const classes = [
    { id: 'c1', name: 'Order' },
    { id: 'c2', name: 'LineItem' },
  ];

  it('shows group title and node count when collapsed; lists classes when expanded', async () => {
    const user = userEvent.setup();
    render(
      <StudioSideNav
        classes={classes}
        groups={groups}
        selectedProjectId="p1"
        selectedVersionId={null}
        callbacks={{}}
      />
    );

    await user.click(screen.getByRole('tab', { name: 'Groups' }));

    expect(screen.getByText('Orders')).toBeInTheDocument();
    expect(screen.getByText('(2)')).toBeInTheDocument();
    expect(screen.queryByText('Order')).not.toBeInTheDocument();
    expect(screen.queryByText('LineItem')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('group-expand-g1'));

    expect(screen.getByText('Order')).toBeInTheDocument();
    expect(screen.getByText('LineItem')).toBeInTheDocument();
  });

  it('toggles aria-expanded on the expand control', async () => {
    const user = userEvent.setup();
    render(
      <StudioSideNav
        classes={classes}
        groups={groups}
        selectedProjectId="p1"
        selectedVersionId={null}
        callbacks={{}}
      />
    );

    await user.click(screen.getByRole('tab', { name: 'Groups' }));

    const expandBtn = screen.getByRole('button', { name: 'Expand group' });
    expect(expandBtn).toHaveAttribute('aria-expanded', 'false');

    await user.click(expandBtn);
    expect(screen.getByRole('button', { name: 'Collapse group' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('calls onClassSelect when clicking a class under an expanded group', async () => {
    const onClassSelect = jest.fn();
    const user = userEvent.setup();

    render(
      <StudioSideNav
        classes={classes}
        groups={groups}
        selectedProjectId="p1"
        selectedVersionId={null}
        callbacks={{ onClassSelect }}
      />
    );

    await user.click(screen.getByRole('tab', { name: 'Groups' }));
    await user.click(screen.getByTestId('group-expand-g1'));
    await user.click(screen.getByTestId('group-class-g1-c1'));

    expect(onClassSelect).toHaveBeenCalledTimes(1);
    expect(onClassSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'c1', name: 'Order' })
    );
  });
});
