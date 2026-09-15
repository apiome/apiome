/**
 * Guide editor — policy tab tests (CLX-1.3, #4850; re-pointed by HIVE-5.7, #5310).
 *
 * The contract is unchanged: the Policy heading and its CI toggles, and a Save that PUTs
 * the draft settings with `snapshot: true`. What changed with the redesign is *where the
 * draft lives* — the tab is presentational now and its state is `useGuidePolicy` on the
 * page — so the suite drives the real page and opens the tab, rather than rendering a
 * component with a `guideId` prop it no longer takes. That also means these tests exercise
 * the composition the reader actually gets, including the lazy load.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({
    confirm: jest.fn(() => Promise.resolve(true)),
    alert: jest.fn(),
  }),
}));

import GuideEditorClient from '../src/app/ade/dashboard/style-guides/[guideId]/GuideEditorClient';

const GUIDE_ID = 'guide-custom';

/** The rule catalog the page opens on — the policy tab is one click away from it. */
const RULES_VIEW = {
  guideId: GUIDE_ID,
  guideName: 'Payments Guide',
  source: 'custom' as const,
  rules: [
    {
      ruleId: 'documentation.operation-missing-summary',
      pack: 'openapi',
      category: 'documentation',
      defaultSeverity: 'warning' as const,
      rationale: 'Operations without a summary are hard to scan in generated docs.',
      docsAnchor: 'documentation-operation-missing-summary',
      enabled: true,
      severity: 'warning' as const,
    },
  ],
  count: 1,
  enabledCount: 1,
  docsPage: 'docs/guide/lint-rules.md',
};

const POLICY = {
  guideId: GUIDE_ID,
  axisGates: { quality: { minGrade: 'B' } },
  requiredCoverage: ['quality'],
  ciOutcomes: {
    failOnUnwaivedErrors: true,
    failOnRequiredCoverage: true,
    failOnAxisGates: true,
  },
  breakingPublishPolicy: 'warn',
  requiredApprovals: 0,
  requiredReviewerRole: null as string | null,
};

/** The tenant's roles, for the COL-2.3 required-reviewer-role picker. */
const ROLES = [
  { id: 'r1', slug: 'owner', name: 'Owner', is_builtin: true },
  { id: 'r2', slug: 'release-manager', name: 'Release Manager', is_builtin: false },
];

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

/** Whether the signed-in viewer administers the tenant. */
let isAdmin = true;

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

    if (url.includes('/api/access/permissions/me')) {
      return jsonResponse({ success: true, data: { is_admin: isAdmin, permissions: [] } });
    }
    if (url.includes('/api/access/roles')) {
      return jsonResponse({ success: true, data: ROLES });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/policy-versions`)) {
      return jsonResponse({ success: true, data: VERSIONS });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/policy`) && method === 'PUT') {
      const put = body as {
        axisGates: typeof POLICY.axisGates;
        requiredCoverage: string[];
        ciOutcomes: typeof POLICY.ciOutcomes;
        breakingPublishPolicy: typeof POLICY.breakingPublishPolicy;
        requiredApprovals: number;
        requiredReviewerRole: string | null;
        snapshot: boolean;
      };
      return jsonResponse({
        success: true,
        data: {
          ...POLICY,
          axisGates: put.axisGates,
          requiredCoverage: put.requiredCoverage,
          ciOutcomes: put.ciOutcomes,
          breakingPublishPolicy: put.breakingPublishPolicy,
          requiredApprovals: put.requiredApprovals,
          requiredReviewerRole: put.requiredReviewerRole,
        },
      });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/policy`)) {
      return jsonResponse({ success: true, data: POLICY });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/rules`)) {
      return jsonResponse({ success: true, data: RULES_VIEW });
    }
    return jsonResponse({ success: false, error: 'Unexpected request' });
  });
  // @ts-expect-error - assigning a test double to the global
  global.fetch = fn;
  return fn;
}

beforeEach(() => {
  calls = [];
  isAdmin = true;
  mockFetch();
});

afterEach(() => {
  jest.restoreAllMocks();
});

/** Render the page, open the policy tab and wait for its payload to land. */
async function renderPolicyTab() {
  render(<GuideEditorClient guideId={GUIDE_ID} />);
  await screen.findByText('documentation.operation-missing-summary');
  fireEvent.click(screen.getByTestId('guide-tab-policy'));
  await screen.findByTestId('guide-policy-panel');
}

describe('PolicyTab', () => {
  it('loads nothing until the tab is opened', async () => {
    render(<GuideEditorClient guideId={GUIDE_ID} />);
    await screen.findByText('documentation.operation-missing-summary');

    expect(calls.some((c) => c.url.includes('/policy'))).toBe(false);

    fireEvent.click(screen.getByTestId('guide-tab-policy'));
    await screen.findByTestId('guide-policy-panel');
    expect(calls.some((c) => c.url.includes('/policy'))).toBe(true);
  });

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
    fireEvent.click(screen.getByTestId('guide-policy-save'));

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
      breakingPublishPolicy: 'warn',
      requiredApprovals: 0,
      requiredReviewerRole: null,
      snapshot: true,
    });
  });

  it('renders the breaking-publish guardrail level with its explanation', async () => {
    await renderPolicyTab();

    const select = screen.getByLabelText('Breaking-change publish policy');
    expect(select).toHaveValue('warn');
    expect(
      screen.getByText(/Warn when a publish is breaking without a major-version bump/),
    ).toBeInTheDocument();
  });

  it('saves an escalation to block and explains what it does', async () => {
    await renderPolicyTab();

    fireEvent.change(screen.getByLabelText('Breaking-change publish policy'), {
      target: { value: 'block' },
    });
    expect(
      screen.getByText(/Refuse the publish until the major version is bumped/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('guide-policy-save'));

    await waitFor(() => {
      expect(calls.find((c) => c.method === 'PUT')).toBeDefined();
    });
    const put = calls.find((c) => c.method === 'PUT');
    expect((put!.body as { breakingPublishPolicy: string }).breakingPublishPolicy).toBe('block');
  });

  it('keeps Save disabled until the guardrail level actually changes', async () => {
    await renderPolicyTab();

    const save = screen.getByTestId('guide-policy-save');
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Breaking-change publish policy'), {
      target: { value: 'off' },
    });
    expect(save).not.toBeDisabled();
  });

  it('hides Save when read-only', async () => {
    isAdmin = false;
    await renderPolicyTab();

    expect(screen.queryByTestId('guide-policy-save')).toBeNull();
    expect(screen.getByLabelText('Fail on unwaived errors')).toBeDisabled();
    expect(screen.getByLabelText('Breaking-change publish policy')).toBeDisabled();
    expect(screen.getByLabelText('Required approvals')).toBeDisabled();
  });

  /* --- Approval policy (COL-2.3, #4519) --- */

  it('shows the approval gate off, with the role picker unusable until it is armed', async () => {
    await renderPolicyTab();

    expect(screen.getByLabelText('Required approvals')).toHaveValue(0);
    const role = screen.getByLabelText('Required reviewer role');
    expect(role).toHaveValue('');
    expect(role).toBeDisabled();
    expect(
      screen.getByText(/Zero means no approval gate/),
    ).toBeInTheDocument();
  });

  it('arms the gate, offers the tenant roles, and saves both settings', async () => {
    await renderPolicyTab();

    fireEvent.change(screen.getByLabelText('Required approvals'), {
      target: { value: '2' },
    });
    expect(
      screen.getByText(/Publishing is blocked until the current review round has 2 approval/),
    ).toBeInTheDocument();

    const role = screen.getByLabelText('Required reviewer role');
    expect(role).not.toBeDisabled();
    expect(screen.getByRole('option', { name: 'Release Manager' })).toBeInTheDocument();
    fireEvent.change(role, { target: { value: 'release-manager' } });

    fireEvent.click(screen.getByTestId('guide-policy-save'));

    await waitFor(() => {
      expect(calls.find((c) => c.method === 'PUT')).toBeDefined();
    });
    const put = calls.find((c) => c.method === 'PUT');
    expect(put!.body).toMatchObject({
      requiredApprovals: 2,
      requiredReviewerRole: 'release-manager',
      snapshot: true,
    });
  });

  it('clamps an out-of-range approval count rather than sending it', async () => {
    await renderPolicyTab();

    fireEvent.change(screen.getByLabelText('Required approvals'), {
      target: { value: '99' },
    });
    expect(screen.getByLabelText('Required approvals')).toHaveValue(20);

    fireEvent.change(screen.getByLabelText('Required approvals'), {
      target: { value: '-4' },
    });
    expect(screen.getByLabelText('Required approvals')).toHaveValue(0);
  });

  it('drops the required role when the gate is switched back off', async () => {
    await renderPolicyTab();

    fireEvent.change(screen.getByLabelText('Required approvals'), {
      target: { value: '1' },
    });
    fireEvent.change(screen.getByLabelText('Required reviewer role'), {
      target: { value: 'owner' },
    });
    expect(screen.getByLabelText('Required reviewer role')).toHaveValue('owner');

    fireEvent.change(screen.getByLabelText('Required approvals'), {
      target: { value: '0' },
    });
    expect(screen.getByLabelText('Required reviewer role')).toHaveValue('');
  });

  it('keeps Save disabled until an approval setting actually changes', async () => {
    await renderPolicyTab();

    const save = screen.getByTestId('guide-policy-save');
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Required approvals'), {
      target: { value: '3' },
    });
    expect(save).not.toBeDisabled();
  });

  /** HIVE-5.7's fourth acceptance criterion, on the tab the mockup gives no save bar. */
  it('keeps an unsaved policy edit across a tab switch', async () => {
    await renderPolicyTab();

    fireEvent.change(screen.getByLabelText('Breaking-change publish policy'), {
      target: { value: 'block' },
    });

    fireEvent.click(screen.getByTestId('guide-tab-catalog'));
    fireEvent.click(screen.getByTestId('guide-tab-policy'));

    expect(screen.getByLabelText('Breaking-change publish policy')).toHaveValue('block');
    expect(screen.getByTestId('guide-policy-save')).not.toBeDisabled();
    // Nothing was re-read: the draft is the page's, not the panel's.
    expect(calls.filter((c) => c.url.includes('/policy-versions')).length).toBe(1);
  });
});
