/**
 * Guide editor — policy tab tests (CLX-1.3, #4850)
 *
 * Renders PolicyTab against mocked `global.fetch` returning the documented
 * `{ success, data }` proxy shapes and asserts the Policy heading, CI toggles,
 * and that Save PUTs draft settings with `snapshot: true`.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import PolicyTab from '../src/app/ade/dashboard/style-guides/[guideId]/PolicyTab';

const GUIDE_ID = 'guide-custom';

const POLICY = {
  guideId: GUIDE_ID,
  axisGates: { quality: { minGrade: 'B' } },
  requiredCoverage: ['quality'],
  ciOutcomes: {
    failOnUnwaivedErrors: true,
    failOnRequiredCoverage: true,
    failOnAxisGates: true,
  },
};

const VERSIONS = {
  versions: [
    {
      id: 'pv1',
      guideId: GUIDE_ID,
      versionNumber: 1,
      contentFingerprint: 'abcdef1234567890',
      axisGates: { quality: { minGrade: 'B' } },
      requiredCoverage: ['quality'],
      ciOutcomes: POLICY.ciOutcomes,
      actorLabel: 'admin@example.com',
      createdAt: '2026-01-15T12:00:00Z',
    },
  ],
  count: 1,
};

let calls: { url: string; method: string; body: unknown }[] = [];

function jsonResponse(payload: unknown) {
  return Promise.resolve({
    status: 200,
    json: () => Promise.resolve(payload),
  } as Response);
}

function mockFetch() {
  const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';
    const body = init?.body ? JSON.parse(init.body as string) : null;
    calls.push({ url, method, body });

    if (url.includes(`/api/style-guides/${GUIDE_ID}/policy-versions`)) {
      return jsonResponse({ success: true, data: VERSIONS });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/policy`) && method === 'PUT') {
      const put = body as {
        axisGates: typeof POLICY.axisGates;
        requiredCoverage: string[];
        ciOutcomes: typeof POLICY.ciOutcomes;
        snapshot: boolean;
      };
      return jsonResponse({
        success: true,
        data: {
          ...POLICY,
          axisGates: put.axisGates,
          requiredCoverage: put.requiredCoverage,
          ciOutcomes: put.ciOutcomes,
        },
      });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/policy`)) {
      return jsonResponse({ success: true, data: POLICY });
    }
    return jsonResponse({ success: false, error: 'Unexpected request' });
  });
  // @ts-expect-error - assigning a test double to the global
  global.fetch = fn;
  return fn;
}

beforeEach(() => {
  calls = [];
  mockFetch();
});

afterEach(() => {
  jest.restoreAllMocks();
});

/** Render PolicyTab and wait for the policy payload to land. */
async function renderPolicyTab(readOnly = false) {
  render(<PolicyTab guideId={GUIDE_ID} readOnly={readOnly} />);
  await screen.findByText('Policy');
}

describe('PolicyTab', () => {
  it('renders the Policy heading and CI outcome toggles', async () => {
    await renderPolicyTab();

    expect(screen.getByRole('heading', { name: 'Policy' })).toBeInTheDocument();
    expect(screen.getByLabelText('Fail on unwaived errors')).toBeChecked();
    expect(screen.getByLabelText('Fail on required coverage')).toBeChecked();
    expect(screen.getByLabelText('Fail on axis gates')).toBeChecked();
    expect(screen.getByLabelText('Quality minimum grade')).toHaveValue('B');
    expect(screen.getByLabelText('Require quality coverage')).toBeChecked();
    expect(screen.getByText('v1')).toBeInTheDocument();
  });

  it('saves policy settings via PUT with snapshot: true', async () => {
    await renderPolicyTab();

    fireEvent.click(screen.getByLabelText('Fail on axis gates'));
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT');
      expect(put).toBeDefined();
    });

    const put = calls.find((c) => c.method === 'PUT');
    expect(put!.url).toContain(`/api/style-guides/${GUIDE_ID}/policy`);
    expect(put!.body).toEqual({
      axisGates: { quality: { minGrade: 'B' } },
      requiredCoverage: ['quality'],
      ciOutcomes: {
        failOnUnwaivedErrors: true,
        failOnRequiredCoverage: true,
        failOnAxisGates: false,
      },
      snapshot: true,
    });
  });

  it('hides Save when read-only', async () => {
    await renderPolicyTab(true);

    expect(screen.queryByText('Save')).toBeNull();
    expect(screen.getByLabelText('Fail on unwaived errors')).toBeDisabled();
  });
});
