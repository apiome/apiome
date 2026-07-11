/**
 * Guide editor — custom rules tab tests (GOV-2.3, #4435)
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('monaco-yaml', () => ({
  configureMonacoYaml: jest.fn(),
}));

jest.mock('@monaco-editor/react', () => {
  const React = require('react');
  return {
    __esModule: true,
    default: ({
      value,
      onChange,
      onMount,
    }: {
      value?: string;
      onChange?: (v: string) => void;
      onMount?: (ed: unknown, monaco: unknown) => void;
    }) => {
      React.useEffect(() => {
        const monaco = {
          editor: {
            createModel: (text: string, _lang: string, uri: { toString: () => string }) => ({
              getValue: () => text,
              uri,
              dispose: jest.fn(),
            }),
            setModelMarkers: jest.fn(),
            Uri: { parse: (s: string) => ({ toString: () => s }) },
          },
          Uri: { parse: (s: string) => ({ toString: () => s }) },
        };
        const ed = {
          getModel: () => ({
            getValue: () => value ?? '',
            uri: { toString: () => 'test' },
            dispose: jest.fn(),
          }),
          setModel: jest.fn(),
        };
        onMount?.(ed, monaco);
      }, [onMount, value]);
      return (
        <textarea
          aria-label="Custom rules YAML"
          value={value}
          onChange={(e) => onChange?.(e.target.value)}
        />
      );
    },
  };
});

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
      docsAnchor: 'x',
      enabled: true,
      severity: 'warning' as const,
    },
  ],
  count: 1,
  enabledCount: 1,
  docsPage: 'docs/guide/lint-rules.md',
};

const CUSTOM_RULES_VIEW = {
  guideId: GUIDE_ID,
  guideName: 'Payments Guide',
  source: 'custom' as const,
  yaml: 'rules: {}\n',
  ruleCount: 0,
};

const PROJECT_ID = 'project-1';
const VERSION_ID = 'version-1';

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve({
    status,
    json: () => Promise.resolve(payload),
  } as Response);
}

beforeEach(() => {
  const fetchMock = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';

    if (url.includes('/api/access/permissions/me')) {
      return jsonResponse({ success: true, data: { is_admin: true, permissions: [] } });
    }
    if (url.includes('/api/projects')) {
      return jsonResponse({
        success: true,
        projects: [{ id: PROJECT_ID, name: 'Payments API' }],
      });
    }
    if (url.includes('/api/versions?')) {
      return jsonResponse({
        success: true,
        versions: [{ id: VERSION_ID, version_id: 'v1', name: 'Initial' }],
      });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/custom-rules/preview`) && method === 'POST') {
      return jsonResponse({
        success: true,
        data: {
          projectId: PROJECT_ID,
          versionRecordId: VERSION_ID,
          versionId: 'v1',
          count: 1,
          findings: [
            {
              id: 'f1',
              path: 'servers.0.url',
              category: 'custom',
              rule: 'servers-use-https',
              severity: 'error',
              message: 'must use https',
            },
          ],
          ruleErrors: {},
        },
      });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/custom-rules`) && method === 'PUT') {
      const body = JSON.parse(init?.body as string);
      if (body.yaml.includes('broken-match')) {
        return jsonResponse(
          {
            success: false,
            error: {
              message: "'match' is not a valid regular expression",
              pointer: 'rules.bad.then.functionOptions.match',
            },
          },
          422,
        );
      }
      return jsonResponse({ success: true, data: { ...CUSTOM_RULES_VIEW, yaml: body.yaml } });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/custom-rules`)) {
      return jsonResponse({ success: true, data: CUSTOM_RULES_VIEW });
    }
    if (url.includes(`/api/style-guides/${GUIDE_ID}/rules`)) {
      return jsonResponse({ success: true, data: RULES_VIEW });
    }
    return jsonResponse({ success: false, error: 'Unexpected request' });
  });
  // @ts-expect-error test double
  global.fetch = fetchMock;
});

afterEach(() => {
  jest.restoreAllMocks();
});

async function openCustomRulesTab() {
  render(<GuideEditorClient guideId={GUIDE_ID} />);
  await screen.findByText('Rule catalog');
  fireEvent.click(screen.getByRole('tab', { name: 'Custom rules' }));
  await screen.findByLabelText('Custom rules YAML');
}

describe('GuideEditorClient — custom rules tab', () => {
  it('renders the YAML editor and test-against controls', async () => {
    await openCustomRulesTab();
    expect(screen.getByText('Test against…')).toBeInTheDocument();
    expect(screen.getByLabelText('Preview project')).toBeInTheDocument();
    expect(screen.getByLabelText('Preview version')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument();
  });

  it('lists preview violations after Run', async () => {
    await openCustomRulesTab();
    await waitFor(() =>
      expect(screen.getByLabelText('Preview version')).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await waitFor(() => expect(screen.getByText('servers-use-https')).toBeInTheDocument());
    expect(screen.getByText(/must use https/)).toBeInTheDocument();
  });

  it('blocks save on invalid YAML and surfaces the server message', async () => {
    await openCustomRulesTab();
    fireEvent.change(screen.getByLabelText('Custom rules YAML'), {
      target: {
        value: `rules:
  bad:
    description: x
    given: $.info
    then:
      function: pattern
      functionOptions:
        match: broken-match
`,
      },
    });
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() =>
      expect(screen.getByText(/not a valid regular expression/)).toBeInTheDocument(),
    );
  });
});
