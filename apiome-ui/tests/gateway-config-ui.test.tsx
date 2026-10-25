/**
 * Gateway configs as entities — CDG-5.3 (#5981).
 *
 * * **Rules**: the proxy forwards only the list and one read; served APIs link to their catalog item
 *   or Project; why push-back is not offered.
 * * **Gateway config page**: the APIs served, auth and rate-limit posture, redacted-credential count,
 *   the declared loss and the owner; **Push back** on a Kong config opens the export on the `kong`
 *   target's fidelity report (or the Studio's Verify step once it is released); an AWS config pushes
 *   back to `aws-apigateway` (FMT-7.7); a connector with no gateway format explains why not; the
 *   Graph tab draws the edges; axe passes.
 * * **Connector Environments tab**: one row per gateway config, linked.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `gateway-config-entity` and
 * `export-studio-gateway`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockPush = jest.fn();
let mockReleased = false;

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/connectors/environments/kong-konnect-prod',
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u-1', current_tenant_id: 't-1' } } }),
}));

// The real gate, with Export studio switched per test and the owner and Graph tab's features
// (teams, dependency graph) previewed unless a test clears `mockPreview`.
let mockPreview = 'teams,dependency-graph';
jest.mock('@lib/feature-release', () => {
  const actual = jest.requireActual('@lib/feature-release');
  return {
    ...actual,
    isFeatureReleased: (id: string) => (id === 'export-studio' ? mockReleased : actual.isFeatureReleased(id, mockPreview)),
  };
});

import GatewayConfigClient from '../src/app/ade/dashboard/connectors/environments/[slug]/GatewayConfigClient';
import { ConnectorEnvironments } from '../src/app/components/ade/gatewayConfigs/ConnectorEnvironments';
import ExportDialog from '../src/app/components/ade/dashboard/export/ExportDialog';
import {
  gatewayConfigProxyPath,
  pushBackUnavailable,
  servedApiHref,
  type GatewayConfig,
} from '../lib/gateway-configs';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const CONNECTOR = '44444444-4444-4444-8444-444444444444';

const KONG: GatewayConfig = {
  id: 'g-prod',
  slug: 'kong-konnect-prod',
  name: 'Kong Konnect · prod',
  connector: { id: CONNECTOR, name: 'Kong Konnect', kind: 'kong-konnect' },
  environment: 'prod',
  flavor: 'kong-konnect',
  apiCount: 2,
  posture: {
    auth: [{ scheme: 'apiKey', via: 'key-auth' }, { scheme: 'oauth2', via: 'openid-connect' }],
    rateLimits: [{ name: 'rate-limiting', kind: 'rate-limiting' }],
    policies: ['cors', 'prometheus'],
    credentialRedactions: 3,
  },
  declaredLosses: [
    {
      construct: 'request-response-schemas',
      reason:
        'Gateway configs carry no request/response schemas — they say where a request goes, not what it carries. Its APIs are operations only.',
    },
  ],
  pushBack: { target: 'kong', reason: null },
  owner: { team: { id: 't-1', slug: 'platform', name: 'Platform' }, status: 'confirmed', source: 'gateway_tag' },
  apis: [
    {
      itemId: 'i-1', name: 'orders', remoteId: 'svc-orders', status: 'imported', hosts: ['api.acme.io'],
      basePath: '/orders', projectId: 'p-orders', projectName: 'Orders (Kong)', publishable: false, lastSeenAt: null,
    },
    {
      itemId: 'i-2', name: 'payments', remoteId: 'svc-payments', status: 'discovered', hosts: ['api.acme.io'],
      basePath: '/payments', projectId: null, projectName: null, publishable: null, lastSeenAt: null,
    },
  ],
  lastSyncedAt: '2026-06-15T09:00:00Z',
  updatedAt: '2026-06-15T09:00:00Z',
};

const AWS: GatewayConfig = {
  ...KONG,
  id: 'g-aws',
  slug: 'aws-prod',
  name: 'AWS · prod',
  connector: { id: CONNECTOR, name: 'AWS', kind: 'aws-apigateway' },
  flavor: 'aws-apigateway',
  pushBack: { target: 'aws-apigateway', reason: null },
};

/** A config whose connector has no gateway format to push back to. */
const PLAIN: GatewayConfig = {
  ...KONG,
  id: 'g-plain',
  slug: 'plain-prod',
  name: 'Plain · prod',
  connector: { id: CONNECTOR, name: 'Plain', kind: 'url' },
  flavor: 'url',
  pushBack: { target: null, reason: 'unsupported' },
};

/** A Kong export target and its dry-run fidelity, for the push-back dialog. */
const KONG_TARGETS = {
  artifact: 'p-orders',
  version: null,
  version_record_id: 'rev-1',
  version_label: '3.0.0',
  targets: [
    {
      descriptor: {
        key: 'kong', format: 'kong', label: 'Kong Declarative Config', description: 'Emit a Kong decK file.',
        icon: 'network', paradigm: 'rest', multi_file: false, needs_toolchain: false, available: true,
        unavailable_reason: null,
      },
      capability_profile: { operations: true },
      options_schema: { properties: {}, type: 'object' },
      default_options: {},
      fidelity: { tier: 'lossy', preserved_percent: 71, total: 24, preserved: 17, dropped: 5, approximated: 2, synthesized: 0 },
    },
  ],
};

const KONG_PREVIEW = {
  target: KONG_TARGETS.targets[0].descriptor,
  summary: KONG_TARGETS.targets[0].fidelity,
  report: {
    items: [
      { construct: 'GET /orders/{id}', kind: 'ok', severity: 'info', message: 'Becomes a route on the orders service.', target_mapping: null },
      { construct: 'Order', kind: 'drop', severity: 'warn', message: 'Gateway configs carry no request/response schemas.', target_mapping: null },
      { construct: 'GET /orders?status', kind: 'approx', severity: 'warn', message: 'Query matching is not expressible on a Kong route.', target_mapping: 'query → route path only' },
    ],
    kind_counts: { drop: 1, approx: 1, synth: 0, ok: 1 },
    severity_counts: { info: 1, warn: 2, critical: 0 },
  },
  advisory: {
    show: true, severity: 'warn', requires_ack: false, target_format: 'Kong Declarative Config',
    dropped: 5, approximated: 2, synthesized: 0, affected: 7, headline: 'This export loses fidelity',
    message: 'Exporting to Kong Declarative Config may lose some fidelity: 7 constructs affected.',
  },
};

let calls: string[] = [];

const res = (body: unknown, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, json: async () => body, headers: { get: () => null } }) as unknown as Response;

beforeEach(() => {
  calls = [];
  mockPush.mockReset();
  mockReleased = false;
  mockPreview = 'teams,dependency-graph';
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(url);
    if (url.startsWith('/api/gateway-configs?connector=')) return res({ gatewayConfigs: [KONG, AWS] });
    if (url === '/api/gateway-configs/aws-prod') return res(AWS);
    if (url === '/api/gateway-configs/plain-prod') return res(PLAIN);
    if (url.startsWith('/api/gateway-configs/')) return res(KONG);
    if (url === '/api/teams') return res({ teams: [{ id: 't-1', slug: 'platform', name: 'Platform' }] });
    if (url.endsWith('/facts')) {
      return res({
        kind: 'gateway_config', id: 'g-prod', name: 'prod', score: null,
        facts: [
          { key: 'owner.present', label: 'Owner present', status: 'met', value: true, detail: null, evidence: [] },
          { key: 'refresh.fresh', label: 'Refreshed within twice its cadence', status: 'met', value: true,
            detail: 'Kong Konnect last refreshed 2026-06-15 03:00 UTC (cadence 1 h).', evidence: [] },
        ],
      });
    }
    if (url.startsWith('/api/graph/edges')) return res({ edges: [], total: 0, truncated: false, limit: 500, offset: 0 });
    if (url.includes('/api/export/targets')) return res({ success: true, ...KONG_TARGETS });
    if (url.includes('/api/export/preflight')) return res({ success: true, targets: [] });
    if (url.includes('/api/export/preview') && init?.method === 'POST') {
      return res({ success: true, artifact: 'p-orders', version: null, version_record_id: 'rev-1', version_label: '3.0.0', fidelity: KONG_PREVIEW });
    }
    return res({}, 404);
  }) as unknown as typeof fetch;
});

describe('the rules', () => {
  it('forwards only the list and one read', () => {
    expect(gatewayConfigProxyPath([])).toBe('gateway-configs');
    expect(gatewayConfigProxyPath(['kong-konnect-prod'])).toBe('gateway-configs/kong-konnect-prod');
    expect(gatewayConfigProxyPath(['../x'])).toBeNull();
    expect(gatewayConfigProxyPath(['a', 'b'])).toBeNull();
  });

  it('links served APIs and explains a missing push-back', () => {
    expect(servedApiHref(KONG.apis[0])).toBe('/ade/dashboard/catalog/p-orders');
    expect(servedApiHref({ ...KONG.apis[0], publishable: true })).toBe('/ade/dashboard/versions?projectId=p-orders');
    expect(servedApiHref(KONG.apis[1])).toBeNull();
    expect(pushBackUnavailable(KONG.pushBack)).toBeNull();
    expect(pushBackUnavailable(AWS.pushBack)).toBeNull();
    expect(pushBackUnavailable(PLAIN.pushBack)).toMatch(/no gateway format/);
  });
});

describe('the gateway config page', () => {
  async function renderPage(slug = 'kong-konnect-prod') {
    const view = render(<GatewayConfigClient slug={slug} />);
    await screen.findByTestId('gateway-config-detail');
    return view;
  }

  it('shows the APIs served, the posture, the declared loss and the owner', async () => {
    await renderPage();
    const apis = screen.getByTestId('gateway-config-apis');
    expect(within(apis).getByRole('link', { name: 'Orders (Kong)' })).toHaveAttribute('href', '/ade/dashboard/catalog/p-orders');
    expect(within(apis).getByText('Not imported')).toBeInTheDocument();
    const posture = screen.getByTestId('gateway-config-posture');
    expect(posture).toHaveTextContent('apiKey · key-auth');
    expect(posture).toHaveTextContent('rate-limiting');
    expect(posture).toHaveTextContent('cors, prometheus');
    expect(posture).toHaveTextContent('3 credentials were redacted');
    expect(screen.getByTestId('gateway-config-loss')).toHaveTextContent('carry no request/response schemas');
    expect(screen.getByTestId('entity-owner-cell')).toHaveTextContent('Platform');
  });

  it('pushes a Kong API back through the fidelity report before export', async () => {
    await renderPage();
    expect(screen.getByTestId('gateway-config-push-back-i-2')).toBeDisabled(); // not imported
    fireEvent.click(screen.getByTestId('gateway-config-push-back-i-1'));
    await waitFor(() => expect(screen.getByTestId('export-preserved-percent')).toHaveTextContent('71%'));
    expect(calls.some((url) => url.includes('/api/export/targets?artifact=p-orders'))).toBe(true);
  });

  it('opens the Studio on Verify once the Studio is released', async () => {
    mockReleased = true;
    await renderPage();
    fireEvent.click(screen.getByTestId('gateway-config-push-back-i-1'));
    const query = new URLSearchParams(String(mockPush.mock.calls[0][0]).split('?')[1]);
    expect(query.get('artifact')).toBe('p-orders');
    expect(query.get('target')).toBe('kong');
    expect(query.get('from')).toBe('gateway-config');
    expect(query.get('step')).toBe('verify');
  });

  it('offers push back on an AWS config (FMT-7.7)', async () => {
    await renderPage('aws-prod');
    expect(screen.queryByTestId('gateway-config-push-back-unavailable')).toBeNull();
    expect(screen.getByTestId('gateway-config-push-back-i-1')).not.toBeDisabled();
  });

  it('explains why a connector with no gateway format cannot push back', async () => {
    await renderPage('plain-prod');
    expect(screen.getByTestId('gateway-config-push-back-unavailable')).toHaveTextContent('no gateway format');
    expect(screen.getByTestId('gateway-config-push-back-i-1')).toBeDisabled();
  });

  it('draws the deployed APIs on the Graph tab', async () => {
    await renderPage();
    fireEvent.mouseDown(screen.getByTestId('gateway-config-tab-graph'));
    fireEvent.click(screen.getByTestId('gateway-config-tab-graph'));
    await waitFor(() => expect(calls.some((url) => url.startsWith('/api/graph/edges/gateway_config/g-prod'))).toBe(true));
  });

  it('leaves out the owner and the Graph tab while teams and the dependency graph are held back', async () => {
    mockPreview = '';
    await renderPage();
    expect(screen.queryByTestId('entity-owner')).not.toBeInTheDocument();
    expect(screen.queryByTestId('gateway-config-tab-graph')).not.toBeInTheDocument();
    expect(screen.getByTestId('gateway-config-apis')).toBeInTheDocument();
  });

  it('passes axe and dumps the docs fixture as the released build shows it', async () => {
    mockPreview = '';
    const { container } = await renderPage();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('gateway-config-entity', liveMarkup((document.querySelector('.page') ?? container.firstElementChild)!));
  });
});

describe('the push-back fidelity report', () => {
  it('opens on the gateway target and dumps the docs fixture', async () => {
    render(
      <ExportDialog
        open
        onClose={jest.fn()}
        artifact="p-orders"
        artifactLabel="Orders (Kong)"
        studioOrigin="gateway-config"
        initialTarget="kong"
      />,
    );
    await waitFor(() => expect(screen.getByTestId('export-preserved-percent')).toHaveTextContent('71%'));
    await waitFor(() => expect(screen.getByTestId('export-advisory')).toBeInTheDocument());
    const dialog = document.querySelector('[role="dialog"]')!;
    writeA11yFixture('export-studio-gateway', liveMarkup(dialog));
  });
});

describe('the connector Environments tab', () => {
  it('lists one linked row per gateway config', async () => {
    render(<ConnectorEnvironments connectorId={CONNECTOR} active />);
    const row = await screen.findByTestId('connector-environment-kong-konnect-prod');
    expect(within(row).getByRole('link', { name: 'prod' })).toHaveAttribute(
      'href',
      '/ade/dashboard/connectors/environments/kong-konnect-prod',
    );
    expect(row).toHaveTextContent('apiKey, oauth2');
    expect(calls[0]).toBe(`/api/gateway-configs?connector=${CONNECTOR}`);
  });

  it('reads nothing until the tab is shown', () => {
    render(<ConnectorEnvironments connectorId={CONNECTOR} active={false} />);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
