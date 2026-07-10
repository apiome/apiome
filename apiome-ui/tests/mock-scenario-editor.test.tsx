/**
 * Render/interaction tests for the mock scenario override editor (#4454, SIM-4.2).
 *
 * Acceptance criteria under test:
 * - Opening the editor loads persisted definitions from the scenarios proxy route.
 * - Saving round-trips the canonical payload through `PUT /api/versions/{id}/mock/scenarios`.
 * - Client-side JSON/field errors block the save and are listed inline.
 * - Server-side validation failures (REST 422) are listed inline.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { MockScenarioEditor } from '../src/app/components/ade/dashboard/MockScenarioEditor';
import { toast } from 'sonner';

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

const STORED_SCENARIOS = {
  'quota-exceeded': {
    description: 'Throttled.',
    operations: {
      'GET /pets': {
        responses: [
          { status: 429, headers: { 'Retry-After': '60' }, body: { error: 'quota' } },
        ],
      },
    },
  },
};

const baseProps = {
  versionRecordId: 'rev-1',
  projectId: 'proj-1',
  versionLabel: '1.0.0',
  open: true,
  onOpenChange: jest.fn(),
};

const renderEditor = (overrides: Partial<React.ComponentProps<typeof MockScenarioEditor>> = {}) =>
  render(<MockScenarioEditor {...baseProps} {...overrides} />);

/** Mock the GET load; subsequent calls fall through to `putResponse` when given. */
const mockFetch = (
  scenarios: unknown,
  putResponse?: { ok: boolean; json: unknown }
) => {
  (global.fetch as jest.Mock).mockImplementation(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      return {
        ok: putResponse?.ok ?? true,
        json: async () => putResponse?.json ?? { success: true, scenarios: {} },
      };
    }
    return { ok: true, json: async () => ({ success: true, scenarios }) };
  });
};

let consoleErrorSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  (global as { fetch: unknown }).fetch = jest.fn();
  consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  consoleErrorSpy.mockRestore();
});

describe('MockScenarioEditor — loading', () => {
  it('loads persisted scenarios through the proxy route when opened', async () => {
    mockFetch(STORED_SCENARIOS);
    renderEditor();

    await waitFor(() =>
      expect(screen.getByLabelText('Scenario 1 name')).toHaveValue('quota-exceeded')
    );
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/versions/rev-1/mock/scenarios?projectId=proj-1'
    );
    expect(screen.getByLabelText('Scenario 1 description')).toHaveValue('Throttled.');
    expect(screen.getByLabelText('Scenario 1 operation 1 key')).toHaveValue('GET /pets');
    expect(screen.getByLabelText('Scenario 1 operation 1 response 1 status')).toHaveValue('429');
  });

  it('shows an error toast when loading fails', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      json: async () => ({ success: false, error: 'Version not found' }),
    });
    renderEditor();

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Version not found'));
  });

  it('does not fetch while closed', () => {
    renderEditor({ open: false });
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

describe('MockScenarioEditor — saving', () => {
  it('round-trips the canonical payload through the PUT proxy route', async () => {
    mockFetch(STORED_SCENARIOS, { ok: true, json: { success: true, scenarios: STORED_SCENARIOS } });
    const onOpenChange = jest.fn();
    renderEditor({ onOpenChange });

    await waitFor(() =>
      expect(screen.getByLabelText('Scenario 1 name')).toHaveValue('quota-exceeded')
    );
    fireEvent.click(screen.getByTestId('mock-scenario-save'));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Scenarios saved for v1.0.0.'));
    const putCall = (global.fetch as jest.Mock).mock.calls.find(
      ([, init]) => init?.method === 'PUT'
    );
    expect(putCall).toBeDefined();
    expect(putCall![0]).toBe('/api/versions/rev-1/mock/scenarios');
    const body = JSON.parse(putCall![1].body as string);
    expect(body.projectId).toBe('proj-1');
    expect(body.scenarios['quota-exceeded'].operations['GET /pets'].responses[0]).toEqual({
      status: 429,
      headers: { 'Retry-After': '60' },
      body: { error: 'quota' },
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('supports authoring a new scenario with a sequence', async () => {
    mockFetch({}, { ok: true, json: { success: true, scenarios: {} } });
    renderEditor();

    await waitFor(() => expect(screen.getByTestId('mock-scenario-add')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('mock-scenario-add'));
    fireEvent.change(screen.getByLabelText('Scenario 1 name'), {
      target: { value: 'flaky-then-ok' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Add operation override/ }));
    fireEvent.change(screen.getByLabelText('Scenario 1 operation 1 key'), {
      target: { value: 'GET /pets' },
    });
    fireEvent.change(screen.getByLabelText('Scenario 1 operation 1 response 1 status'), {
      target: { value: '503' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Add sequence step/ }));
    fireEvent.change(screen.getByLabelText('Scenario 1 operation 1 response 2 status'), {
      target: { value: '200' },
    });
    fireEvent.click(screen.getByTestId('mock-scenario-save'));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const putCall = (global.fetch as jest.Mock).mock.calls.find(
      ([, init]) => init?.method === 'PUT'
    );
    const body = JSON.parse(putCall![1].body as string);
    expect(body.scenarios['flaky-then-ok'].operations['GET /pets'].responses).toEqual([
      { status: 503 },
      { status: 200 },
    ]);
  });

  it('blocks the save and lists client-side errors for invalid JSON bodies', async () => {
    mockFetch(STORED_SCENARIOS);
    renderEditor();

    await waitFor(() =>
      expect(screen.getByLabelText('Scenario 1 name')).toHaveValue('quota-exceeded')
    );
    fireEvent.change(screen.getByLabelText('Scenario 1 operation 1 response 1 body'), {
      target: { value: '{not json' },
    });
    fireEvent.click(screen.getByTestId('mock-scenario-save'));

    await waitFor(() => expect(screen.getByTestId('mock-scenario-errors')).toBeInTheDocument());
    expect(screen.getByText(/body must be valid JSON/)).toBeInTheDocument();
    const putCall = (global.fetch as jest.Mock).mock.calls.find(
      ([, init]) => init?.method === 'PUT'
    );
    expect(putCall).toBeUndefined();
  });

  it('lists REST validation errors returned by the PUT route', async () => {
    mockFetch(STORED_SCENARIOS, {
      ok: false,
      json: {
        success: false,
        error: 'Scenario definitions failed validation.',
        errors: ["Scenario 'quota-exceeded', operation 'GET /pets': no operation GET /pets exists in this version's spec."],
      },
    });
    renderEditor();

    await waitFor(() =>
      expect(screen.getByLabelText('Scenario 1 name')).toHaveValue('quota-exceeded')
    );
    fireEvent.click(screen.getByTestId('mock-scenario-save'));

    await waitFor(() => expect(screen.getByTestId('mock-scenario-errors')).toBeInTheDocument());
    expect(screen.getByText(/no operation GET \/pets exists/)).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
  });
});
