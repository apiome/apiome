/**
 * The Workflows tab — COA-1.3 (#7039).
 *
 * - **Lazy read**: nothing is fetched until the tab is active, and returning to it does not read
 *   again; the workflow count is reported once loaded.
 * - **States**: no revision, no workflows, and a failed read with a working retry.
 * - **The selected workflow**: source-description status beside it, inputs (from the schema or
 *   its `$ref`) and outputs, the steps in order with what each calls, and the step graph.
 * - **Opening a step** (list row or graph node, mouse or keyboard) opens the drawer; a resolved
 *   step opens its operation (route, parameters, responses, owner link); an unresolved step says
 *   why; a step that calls a workflow switches to it.
 * - **axe** passes on the tab and on the drawer.
 *
 * The docs-screenshot fixtures are written from the whole catalog item page, by
 * `catalog-detail-workflows-tab.test.tsx`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import ArazzoWorkflowsPanel from '../src/app/components/ade/workflows/ArazzoWorkflowsPanel';
import { ITEM_ID, OPERATION_RESPONSE, OP_GET_CART, WORKFLOWS_RESPONSE } from './helpers/arazzo-workflows-fixture';

const ENDPOINT = `/api/workflows/catalog/${ITEM_ID}`;

/** A JSON fetch response. */
function res(body: unknown, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: async () => body } as Response);
}

/** Route the two reads the tab makes. */
function mockFetch(overrides: { workflows?: () => Promise<Response>; operation?: () => Promise<Response> } = {}) {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith('/api/workflows/operations/')) {
      return overrides.operation ? overrides.operation() : res({ success: true, operation: OPERATION_RESPONSE });
    }
    return overrides.workflows ? overrides.workflows() : res({ success: true, workflows: WORKFLOWS_RESPONSE });
  }) as unknown as typeof fetch;
}

async function renderPanel(props: Partial<React.ComponentProps<typeof ArazzoWorkflowsPanel>> = {}) {
  const utils = render(<ArazzoWorkflowsPanel endpoint={ENDPOINT} active {...props} />);
  await screen.findByTestId('awf-panel');
  return utils;
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe('loading', () => {
  it('reads only once the tab is shown, reports the count, and does not re-read on return', async () => {
    mockFetch();
    const onLoaded = jest.fn();
    const { rerender } = render(<ArazzoWorkflowsPanel endpoint={ENDPOINT} active={false} onLoaded={onLoaded} />);
    expect(global.fetch).not.toHaveBeenCalled();

    rerender(<ArazzoWorkflowsPanel endpoint={ENDPOINT} active onLoaded={onLoaded} />);
    await screen.findByTestId('awf-panel');
    expect(global.fetch).toHaveBeenCalledWith(ENDPOINT);
    expect(onLoaded).toHaveBeenCalledWith(2);

    rerender(<ArazzoWorkflowsPanel endpoint={ENDPOINT} active={false} onLoaded={onLoaded} />);
    rerender(<ArazzoWorkflowsPanel endpoint={ENDPOINT} active onLoaded={onLoaded} />);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('says so when there is no revision to read', () => {
    mockFetch();
    render(<ArazzoWorkflowsPanel endpoint={null} active />);
    expect(screen.getByText('No revision to read')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('says so when the revision holds no workflows', async () => {
    mockFetch({ workflows: () => res({ success: true, workflows: { ...WORKFLOWS_RESPONSE, workflows: [] } }) });
    render(<ArazzoWorkflowsPanel endpoint={ENDPOINT} active />);
    expect(await screen.findByText('No workflows')).toBeInTheDocument();
  });

  it('shows a failed read and retries it', async () => {
    let calls = 0;
    mockFetch({
      workflows: () => {
        calls += 1;
        return calls === 1
          ? res({ success: false, error: 'Catalog item not found' }, 404)
          : res({ success: true, workflows: WORKFLOWS_RESPONSE });
      },
    });
    render(<ArazzoWorkflowsPanel endpoint={ENDPOINT} active />);
    expect(await screen.findByText("Couldn't load the workflows.")).toBeInTheDocument();
    expect(screen.getByText('Catalog item not found')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /try again|retry/i }));
    expect(await screen.findByTestId('awf-panel')).toBeInTheDocument();
    expect(calls).toBe(2);
  });
});

describe('the selected workflow', () => {
  it('lists the workflows with their steps and missing sources, and opens the first', async () => {
    mockFetch();
    await renderPanel();
    const list = screen.getByRole('navigation', { name: 'Workflows' });
    const checkout = within(list).getByTestId('awf-workflow-checkout');
    expect(checkout).toHaveAttribute('aria-current', 'true');
    expect(checkout).toHaveTextContent('3 steps');
    expect(checkout).toHaveTextContent('1 source missing');
    expect(within(list).getByTestId('awf-workflow-send-receipt')).toHaveTextContent('1 step');
    expect(screen.getByRole('heading', { name: 'checkout' })).toBeInTheDocument();
  });

  it('shows source status, inputs, outputs and the steps in order', async () => {
    mockFetch();
    await renderPanel();
    expect(screen.getByTestId('awf-source-shop')).toHaveTextContent('Resolved');
    expect(screen.getByTestId('awf-source-shop')).toHaveTextContent('from fileset');
    expect(screen.getByTestId('awf-source-payments')).toHaveTextContent('Missing');
    expect(screen.getByTestId('awf-source-payments')).toHaveTextContent('resolution-disabled');

    const inputs = screen.getByRole('region', { name: 'Inputs' });
    expect(within(inputs).getByRole('row', { name: /cartId string Yes/ })).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Outputs' })).getByText('$steps.pay.outputs.receipt')).toBeInTheDocument();

    const steps = within(screen.getByRole('region', { name: 'Steps' })).getAllByRole('button');
    expect(steps.map((b) => b.getAttribute('data-testid'))).toEqual(['awf-step-load-cart', 'awf-step-pay', 'awf-step-notify']);
    expect(steps[0]).toHaveTextContent('GET /carts/{cartId}');
    expect(steps[1]).toHaveTextContent('Not resolved');
    expect(steps[2]).toHaveTextContent('Calls workflow send-receipt');
  });

  it('draws the step graph with a node per step and the routing in words', async () => {
    mockFetch();
    await renderPanel();
    const graph = screen.getByTestId('awf-step-graph');
    expect(within(graph).getByRole('group', { name: /Step graph for workflow checkout: 3 steps/ })).toBeInTheDocument();
    expect(within(graph).getByTestId('awf-graph-node-pay')).toHaveTextContent('retry ×3');
    expect(within(graph).getByTestId('awf-graph-node-failed')).toBeInTheDocument();
    expect(within(graph).getByText('load-cart → pay (to-pay)')).toBeInTheDocument();
  });

  it('switches workflow from the list and shows a $ref input schema', async () => {
    mockFetch();
    await renderPanel();
    fireEvent.click(screen.getByTestId('awf-workflow-send-receipt'));
    expect(screen.getByRole('heading', { name: 'send-receipt' })).toBeInTheDocument();
    expect(screen.getByText('#/components/inputs/receipt')).toBeInTheDocument();
  });
});

describe('opening a step', () => {
  it('opens the resolved operation from a step row', async () => {
    mockFetch();
    await renderPanel();
    fireEvent.click(screen.getByTestId('awf-step-load-cart'));
    const drawer = await screen.findByTestId('awf-step-drawer');
    const operation = await within(drawer).findByTestId('awf-drawer-operation');
    expect(global.fetch).toHaveBeenCalledWith(`/api/workflows/operations/${OP_GET_CART}`);
    expect(operation).toHaveTextContent('/carts/{cartId}');
    expect(operation).toHaveTextContent('Get a cart');
    expect(operation).toHaveTextContent('cartId');
    expect(operation).toHaveTextContent('404');
    expect(within(drawer).getByText('Go to step pay')).toBeInTheDocument();
    expect(within(drawer).getByText('$statusCode == 200')).toBeInTheDocument();
    expect(within(drawer).getByText('cartId (path) = $inputs.cartId')).toBeInTheDocument();
    expect(within(drawer).getByRole('link', { name: /Open project/ })).toHaveAttribute(
      'href',
      `/ade/dashboard/versions?projectId=${OPERATION_RESPONSE.project_id}`
    );
  });

  it('opens a step from its graph node with the keyboard', async () => {
    mockFetch();
    await renderPanel();
    const node = screen.getByTestId('awf-graph-node-pay');
    expect(node).toHaveAttribute('role', 'button');
    expect(node).toHaveAttribute('tabindex', '0');
    fireEvent.keyDown(node, { key: 'Enter' });
    const drawer = await screen.findByTestId('awf-step-drawer');
    expect(within(drawer).getByTestId('awf-drawer-unresolved')).toHaveTextContent(
      'No imported operation matches this reference.'
    );
    expect(within(drawer).getByText('Retry up to 3 times, 1 s apart')).toBeInTheDocument();
    // An unresolved step offers no link that would lead nowhere, and reads no operation.
    expect(within(drawer).queryByRole('link')).not.toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('switches to the workflow a step calls', async () => {
    mockFetch();
    await renderPanel();
    fireEvent.click(screen.getByTestId('awf-step-notify'));
    const drawer = await screen.findByTestId('awf-step-drawer');
    fireEvent.click(within(drawer).getByRole('button', { name: /Show workflow send-receipt/ }));
    await waitFor(() => expect(screen.queryByTestId('awf-step-drawer')).not.toBeInTheDocument());
    expect(screen.getByRole('heading', { name: 'send-receipt' })).toBeInTheDocument();
  });

  it('says so when the operation cannot be read, and retries', async () => {
    let calls = 0;
    mockFetch({
      operation: () => {
        calls += 1;
        return calls === 1 ? res({ success: false, error: 'Operation not found' }, 404) : res({ success: true, operation: OPERATION_RESPONSE });
      },
    });
    await renderPanel();
    fireEvent.click(screen.getByTestId('awf-step-load-cart'));
    const drawer = await screen.findByTestId('awf-step-drawer');
    expect(await within(drawer).findByText('Operation not found')).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole('button', { name: /try again|retry/i }));
    expect(await within(drawer).findByTestId('awf-drawer-operation')).toBeInTheDocument();
  });
});

describe('accessibility', () => {
  it('passes axe on the tab', async () => {
    mockFetch();
    const { container } = await renderPanel();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('passes axe with the step drawer open', async () => {
    mockFetch();
    await renderPanel();
    await act(async () => {
      fireEvent.click(screen.getByTestId('awf-step-load-cart'));
    });
    const drawer = await screen.findByTestId('awf-step-drawer');
    await within(drawer).findByTestId('awf-drawer-operation');
    expect(await axe(document.body)).toHaveNoViolations();
  });
});
