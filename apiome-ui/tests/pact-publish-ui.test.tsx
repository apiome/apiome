/**
 * @jest-environment jsdom
 */
/** Publish pacts from the Pact import dialog — PFX-5.8 (#6952): the dialog's broker section. */

import { jest } from '@jest/globals';
import * as React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import PactImportDialog from '../src/app/components/ade/consumers/PactImportDialog';

const PACT = JSON.stringify({ consumer: { name: 'billing-service' }, interactions: [] });

describe('dialog', () => {
  const outcome = { operationCount: 1, fieldCount: 2, revision: 3, unresolved: [] };
  const setup = (onImport: jest.Mock) => {
    render(<PactImportDialog open onOpenChange={() => {}} defaultProvider="orders-api" onImport={onImport as never} />);
    fireEvent.change(screen.getByLabelText('Pact document'), { target: { value: PACT } });
  };

  it('imports to the registry only by default', async () => {
    const onImport = jest.fn(async () => ({ outcome }));
    setup(onImport);
    expect(screen.queryByTestId('pact-publish-fields')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(onImport).toHaveBeenCalledWith(PACT, '', undefined));
  });

  it('asks for the broker details, validates them, and passes them on', async () => {
    const onImport = jest.fn(async () => ({
      outcome: { ...outcome, broker: { notices: ['Pact published'] } },
    }));
    setup(onImport);
    fireEvent.click(screen.getByLabelText('Also publish to the Pact Broker'));
    expect((screen.getByLabelText('Provider') as HTMLInputElement).value).toBe('orders-api');
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    expect(await screen.findByText(/consumer version/i, { selector: '[role="alert"], .alert, div' })).toBeTruthy();
    expect(onImport).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Consumer version'), { target: { value: '9f3c2a1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() =>
      expect(onImport).toHaveBeenCalledWith(PACT, '', {
        consumerName: 'billing-service',
        draft: expect.objectContaining({ providerName: 'orders-api', version: '9f3c2a1' }),
      }),
    );
    expect(await screen.findByText('Pact published')).toBeTruthy();
  });

  it('reports a broker failure beside the stored revision', async () => {
    const onImport = jest.fn(async () => ({ outcome: { ...outcome, broker: { error: 'Conflict' } } }));
    setup(onImport);
    fireEvent.click(screen.getByLabelText('Also publish to the Pact Broker'));
    fireEvent.change(screen.getByLabelText('Consumer version'), { target: { value: 'v1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    expect(await screen.findByText(/not published to the Pact Broker: Conflict/)).toBeTruthy();
    expect(screen.getByText(/Revision 3 stored/)).toBeTruthy();
  });

  it('opens the Publish page pre-filled, handing the pact over (PFX-8.3)', () => {
    const onImport = jest.fn(async () => ({ outcome }));
    setup(onImport);
    fireEvent.click(screen.getByLabelText('Also publish to the Pact Broker'));
    fireEvent.change(screen.getByLabelText('Consumer version'), { target: { value: '9f3c2a1' } });
    fireEvent.change(screen.getByLabelText('Tags (optional)'), { target: { value: 'dev, rc' } });
    const link = screen.getByTestId('pact-publish-page-link');
    expect(link).toHaveAttribute('href', '/ade/dashboard/pacts/publish?source=paste&version=9f3c2a1&tag=dev&tag=rc');
    link.addEventListener('click', (event) => event.preventDefault());
    fireEvent.click(link);
    expect(JSON.parse(window.sessionStorage.getItem('apiome.pactPublish.handoff') ?? '{}')).toEqual({ pact: PACT });
  });
});
