/**
 * Component tests for the MCP endpoint Test tab (V2-MCP-22.4 / V2-MCP-24.5, #3690 / #3701):
 * the form invokes a tool and renders its result / latency / isError, the destructive confirm
 * gate holds the call back until it is ticked, and a missing credential is surfaced.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { beforeEach, describe, expect, it, jest } from '@jest/globals';

import McpToolTestPanel from '../src/app/ade/dashboard/mcp/[endpointId]/McpToolTestPanel';
import type { McpCapabilityItem } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

const ENDPOINT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

function tool(overrides: Partial<McpCapabilityItem>): McpCapabilityItem {
  return {
    item_type: 'tool',
    name: 'payments.search',
    title: 'Search payments',
    description: 'Find payments.',
    uri: null,
    uri_template: null,
    input_schema: {
      type: 'object',
      required: ['customer'],
      properties: { customer: { type: 'string', title: 'Customer' }, limit: { type: 'integer' } },
    },
    output_schema: null,
    annotations: { readOnlyHint: true },
    ordinal: 0,
    lifecycle: null,
    ...overrides,
  };
}

const SEARCH = tool({});
const REFUND = tool({
  name: 'payments.refund',
  title: 'Refund a payment',
  input_schema: { type: 'object', properties: {} },
  annotations: { destructiveHint: true },
  ordinal: 1,
});

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, statusText: ok ? 'OK' : 'Error', json: async () => body } as Response;
}

const RESULT = {
  success: true,
  itemName: 'payments.search',
  method: 'tools/call',
  target: 'payments.search',
  completed: true,
  isError: false,
  content: [{ type: 'text', text: '2 payments found' }],
  structuredContent: null,
  latencyMs: 142,
  error: null,
  invocationId: 'inv-1',
};

let posts: Array<{ url: string; body: Record<string, unknown> }> = [];

function routeFetch({ authType = 'bearer', testResponse = () => jsonResponse(RESULT) } = {}) {
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/credentials')) {
      return jsonResponse({ success: true, credential: { auth_type: authType, configured: authType !== 'none' } });
    }
    if (url.endsWith('/test') && init?.method === 'POST') {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      return testResponse();
    }
    throw new Error(`unexpected fetch: ${url}`);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  posts = [];
  routeFetch();
});

describe('McpToolTestPanel', () => {
  it('invokes the picked tool and renders result, latency and isError', async () => {
    render(<McpToolTestPanel endpointId={ENDPOINT_ID} items={[SEARCH, REFUND]} />);

    await userEvent.type(screen.getByTestId('mcp-test-arg-customer'), 'cus_42');
    await userEvent.type(screen.getByTestId('mcp-test-arg-limit'), '5');
    await userEvent.click(screen.getByTestId('mcp-test-run'));

    await waitFor(() => expect(screen.getByTestId('mcp-test-result')).toBeInTheDocument());
    expect(posts).toEqual([
      {
        url: `/api/mcp/endpoints/${ENDPOINT_ID}/test`,
        body: {
          item_type: 'tool',
          item_name: 'payments.search',
          arguments: { customer: 'cus_42', limit: 5 },
          confirm: false,
        },
      },
    ]);
    expect(screen.getByTestId('mcp-test-summary')).toHaveTextContent('142 ms · isError: false');
    expect(screen.getByTestId('mcp-test-outcome')).toHaveTextContent('Succeeded');
    expect(screen.getByTestId('mcp-test-content')).toHaveTextContent('2 payments found');
  });

  it('blocks the call while a required argument is blank', async () => {
    render(<McpToolTestPanel endpointId={ENDPOINT_ID} items={[SEARCH]} />);
    await userEvent.click(screen.getByTestId('mcp-test-run'));
    expect(await screen.findByText('Customer is required.')).toBeInTheDocument();
    expect(posts).toHaveLength(0);
  });

  it('enforces the destructive confirm before sending confirm: true', async () => {
    render(<McpToolTestPanel endpointId={ENDPOINT_ID} items={[REFUND]} />);

    expect(screen.getByTestId('mcp-test-confirm')).toHaveTextContent('flagged destructive');
    expect(screen.getByTestId('mcp-test-no-args')).toBeInTheDocument();
    const run = screen.getByTestId('mcp-test-run');
    expect(run).toBeDisabled();

    await userEvent.click(screen.getByTestId('mcp-test-confirm-box'));
    expect(run).toBeEnabled();
    await userEvent.click(run);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].body).toMatchObject({ item_name: 'payments.refund', confirm: true, arguments: {} });
  });

  it('renders a tool error and a failed call distinctly', async () => {
    routeFetch({
      testResponse: () =>
        jsonResponse({ ...RESULT, completed: false, content: [], error: { code: 'timeout', message: 'no answer' } }),
    });
    render(<McpToolTestPanel endpointId={ENDPOINT_ID} items={[SEARCH]} />);
    await userEvent.type(screen.getByTestId('mcp-test-arg-customer'), 'x');
    await userEvent.click(screen.getByTestId('mcp-test-run'));

    expect(await screen.findByTestId('mcp-test-error')).toHaveTextContent('no answer');
    expect(screen.getByTestId('mcp-test-outcome')).toHaveTextContent('Call failed');
  });

  it('shows the server refusal when the request is rejected', async () => {
    routeFetch({
      testResponse: () => jsonResponse({ success: false, error: "'customer' is a required property" }, false, 422),
    });
    render(<McpToolTestPanel endpointId={ENDPOINT_ID} items={[SEARCH]} />);
    await userEvent.type(screen.getByTestId('mcp-test-arg-customer'), 'x');
    await userEvent.click(screen.getByTestId('mcp-test-run'));
    expect(await screen.findByTestId('mcp-test-request-error')).toHaveTextContent('required property');
  });

  it('surfaces a missing credential', async () => {
    routeFetch({ authType: 'none' });
    render(<McpToolTestPanel endpointId={ENDPOINT_ID} items={[SEARCH]} />);
    expect(await screen.findByTestId('mcp-test-no-credential')).toHaveTextContent('No stored credential');
  });

  it('does not warn when a credential is stored', async () => {
    render(<McpToolTestPanel endpointId={ENDPOINT_ID} items={[SEARCH]} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(screen.queryByTestId('mcp-test-no-credential')).not.toBeInTheDocument();
  });

  it('draws empty states for an undiscovered or tool-less surface', () => {
    const { rerender } = render(<McpToolTestPanel endpointId={ENDPOINT_ID} items={null} />);
    expect(screen.getByTestId('mcp-test-undiscovered')).toBeInTheDocument();
    rerender(<McpToolTestPanel endpointId={ENDPOINT_ID} items={[{ ...SEARCH, item_type: 'prompt' }]} />);
    expect(screen.getByTestId('mcp-test-no-tools')).toBeInTheDocument();
  });
});
