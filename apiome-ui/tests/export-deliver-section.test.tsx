/**
 * The Review step's Deliver section — MFX-46.3 (#4381).
 *
 * The acceptance criteria:
 *
 *  1. **An export lands as a git PR from the Studio with the PR link shown** — a git delivery's attempt
 *     renders its pull request as a link that opens the PR.
 *  2. **Each channel shows its result artifact** — the git pull request (or commit), the webhook
 *     receiver's answer and the digest of what was sent, the object-storage objects and manifest, and the
 *     schema registry's subjects with their version and schema id.
 *  3. **Absent profiles → helpful empty state** — before and after the job, and for the registry.
 *
 * Plus: Download is always the first destination; no credential reaches the page.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe, toHaveNoViolations } from 'jest-axe';

import { ExportJobDeliveryPanel } from '@/app/components/ade/export-studio/delivery/ExportJobDeliveryPanel';
import { resultLines, type DeliveryProfile } from '@/app/components/ade/export-studio/delivery/deliveryProfilesModel';
import {
  EMPTY_REGISTRY_DRAFT,
  registryDraftProblem,
  registryFormatFor,
  registryPushBody,
  subjectStatus,
  subjectWhere,
  type RegistryPushSource,
} from '@/app/components/ade/export-studio/delivery/registryPushModel';

expect.extend(toHaveNoViolations);

const GIT_PROFILE: DeliveryProfile = {
  id: 'p1',
  name: 'specs-repo',
  description: null,
  channel: 'git',
  destination: { repositoryId: 'repo1', targetPath: 'specs', baseBranch: '', mode: 'pr' },
  credentialRef: { kind: 'repository', id: 'repo1' },
} as unknown as DeliveryProfile;

const GIT_ATTEMPT = {
  channel: 'git', runId: 'r1', jobId: 'job-1', status: 'opened', outcome: 'delivered', profileId: 'p1',
  profileName: 'specs-repo', destination: 'acme/specs', attemptCount: 1, errorCode: null, errorMessage: null,
  startedAt: '2026-11-05T10:00:00Z',
  result: {
    mode: 'pr', pullRequestUrl: 'https://github.com/acme/specs/pull/7', pullRequestNumber: 7,
    branch: 'apiome/export-orders-openapi-3.1', commitSha: '0123456789abcdef0123', objectUrls: [],
  },
};
const WEBHOOK_ATTEMPT = {
  ...GIT_ATTEMPT, channel: 'webhook', runId: 'r2', status: 'delivered', profileName: 'ci',
  destination: 'https://ci.example.com/h?…',
  result: { httpStatus: 202, payloadSha256: 'abcdef0123456789abcdef', objectUrls: [] },
};
const STORAGE_ATTEMPT = {
  ...GIT_ATTEMPT, channel: 'object_storage', runId: 'r3', status: 'delivered', profileName: 'lake',
  destination: 'specs/orders',
  result: {
    objectUrls: ['https://minio.example.com/specs/orders/openapi.json', 's3://specs/orders/openapi.yaml'],
    objectCount: 5, manifestUrl: 'https://minio.example.com/specs/orders/manifests/abc.json',
  },
};

const AVRO: RegistryPushSource = { format: 'avro', artifact: 'proj-1', version: 'rev-1', options: { namespace: 'acme' } };

let calls: { url: string; init?: RequestInit }[] = [];

function mockFetch(options: {
  profiles?: DeliveryProfile[];
  deliveries?: unknown[];
  connectors?: unknown[];
  pushFails?: boolean;
} = {}) {
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const json = (body: unknown, status = 200) =>
      ({ ok: status < 400, status, json: async () => body }) as unknown as Response;
    const path = String(url);
    if (path === '/api/export/delivery-profiles') {
      return json({ success: true, data: { profiles: options.profiles ?? [GIT_PROFILE] } });
    }
    if (path.endsWith('/deliveries')) {
      return json({ success: true, data: { deliveries: options.deliveries ?? [GIT_ATTEMPT] } });
    }
    if (path === '/api/connectors') {
      return json({
        connectors: options.connectors ?? [
          { id: 'c1', kind: 'schema-registry', name: 'confluent-prod', baseUrl: 'https://registry.example.com' },
          { id: 'c2', kind: 'kong-admin', name: 'gateway' },
        ],
      });
    }
    if (path === '/api/export/registry-push') {
      if (options.pushFails) return json({ success: false, error: 'imports:edit is required' }, 403);
      const body = JSON.parse(String(init?.body));
      return json({
        success: true,
        data: {
          registry_url: 'https://registry.example.com', dry_run: body.dry_run,
          summary: { registered: 1, incompatible: 1 },
          subjects: [
            { subject: 'acme.Order-value', file: 'acme/Order.avsc', status: body.dry_run ? 'would_register' : 'registered',
              schema_id: 41, version: 3, messages: [] },
            { subject: 'acme.Customer-value', file: 'acme/Customer.avsc', status: 'incompatible', schema_id: null,
              version: null, messages: ['READER_FIELD_MISSING_DEFAULT_VALUE email'] },
          ],
        },
      });
    }
    return json({ success: false, error: `unmocked ${path}` }, 500);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  calls = [];
});

const panel = (props: Partial<React.ComponentProps<typeof ExportJobDeliveryPanel>> = {}) =>
  render(
    <ExportJobDeliveryPanel
      jobId="job-1"
      selected={[]}
      onSelectedChange={() => undefined}
      expected={1}
      manageHref="/ade/dashboard/export/studio?tab=delivery"
      downloadHint="“Download orders.json” or “Download .zip”"
      {...props}
    />,
  );

// ---------------------------------------------------------------------------
// The result lines (pure)
// ---------------------------------------------------------------------------

describe('resultLines', () => {
  it('shows a git delivery’s pull request as a link, and its commit', () => {
    expect(resultLines('git', GIT_ATTEMPT.result)).toEqual([
      { label: 'Pull request #7', value: 'https://github.com/acme/specs/pull/7', href: 'https://github.com/acme/specs/pull/7' },
      { label: 'Commit', value: '0123456789ab on apiome/export-orders-openapi-3.1', href: null },
    ]);
  });

  it('shows a webhook’s receipt', () => {
    expect(resultLines('webhook', WEBHOOK_ATTEMPT.result)).toEqual([
      { label: 'Receiver answered', value: 'HTTP 202', href: null },
      { label: 'Body sent', value: 'sha256:abcdef0123456789…', href: null },
    ]);
  });

  it('lists the objects written, links only what a browser opens, and counts the rest', () => {
    expect(resultLines('object_storage', STORAGE_ATTEMPT.result)).toEqual([
      { label: 'Object', value: 'https://minio.example.com/specs/orders/openapi.json', href: 'https://minio.example.com/specs/orders/openapi.json' },
      { label: 'Object', value: 's3://specs/orders/openapi.yaml', href: null },
      { label: 'Object', value: 'and 3 more', href: null },
      { label: 'Manifest', value: 'https://minio.example.com/specs/orders/manifests/abc.json', href: 'https://minio.example.com/specs/orders/manifests/abc.json' },
    ]);
  });

  it('shows nothing before a delivery produced something', () => {
    expect(resultLines('git', null)).toEqual([]);
    expect(resultLines('git', { mode: 'pr' })).toEqual([]);
    expect(resultLines('webhook', {})).toEqual([]);
  });

  it('never links a javascript: or other non-web URL', () => {
    expect(resultLines('git', { pullRequestUrl: 'javascript:alert(1)' })[0].href).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The registry model (pure)
// ---------------------------------------------------------------------------

describe('registry model', () => {
  it('offers the registry for Avro, JSON Schema and Protobuf targets only', () => {
    expect(registryFormatFor('avro')).toBe('avro');
    expect(registryFormatFor('json-schema')).toBe('json-schema');
    expect(registryFormatFor('protobuf', 'proto3')).toBe('protobuf');
    expect(registryFormatFor('grpc', 'proto3')).toBe('protobuf');
    expect(registryFormatFor('openapi-3.1', 'openapi-3.1')).toBeNull();
    expect(registryFormatFor(null)).toBeNull();
  });

  it('needs a connector, and a topic for the topic strategies', () => {
    expect(registryDraftProblem(EMPTY_REGISTRY_DRAFT)).toBe('Choose a schema registry connector.');
    const chosen = { ...EMPTY_REGISTRY_DRAFT, connectorId: 'c1' };
    expect(registryDraftProblem(chosen)).toBeNull();
    expect(registryDraftProblem({ ...chosen, subjectNaming: 'topic_name' })).toMatch(/topic/);
    expect(registryDraftProblem({ ...chosen, subjectNaming: 'topic_name', topic: ' orders ' })).toBeNull();
  });

  it('builds the push body', () => {
    expect(registryPushBody(AVRO, { ...EMPTY_REGISTRY_DRAFT, connectorId: 'c1' })).toEqual({
      format: 'avro', artifact: 'proj-1', version: 'rev-1', connector_id: 'c1', subject_naming: 'record_name',
      subject_role: 'value', dry_run: false, options: { namespace: 'acme' },
    });
    const body = registryPushBody({ ...AVRO, options: {} }, {
      ...EMPTY_REGISTRY_DRAFT, connectorId: 'c1', subjectNaming: 'topic_record_name', topic: ' orders ', subjectRole: 'key',
      dryRun: true,
    });
    expect(body).toMatchObject({ topic: 'orders', subject_role: 'key', dry_run: true });
    expect(body).not.toHaveProperty('options');
  });

  it('says each subject’s status and where it now lives', () => {
    expect(subjectStatus('registered')).toEqual({ label: 'Registered', tone: 'ok' });
    expect(subjectStatus('incompatible').tone).toBe('warn');
    expect(subjectStatus('failed').tone).toBe('danger');
    expect(subjectWhere({ subject: 's', file: 'f', status: 'registered', version: 3, schema_id: 41 })).toBe('version 3 · id 41');
    expect(subjectWhere({ subject: 's', file: 'f', status: 'incompatible' })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The Deliver section
// ---------------------------------------------------------------------------

describe('Deliver section', () => {
  it('always offers Download first, naming the step’s own buttons', async () => {
    mockFetch();
    panel();
    const download = await screen.findByTestId('download-destination');
    expect(download).toHaveTextContent('Download');
    expect(download).toHaveTextContent('Default');
    expect(screen.getByTestId('download-destination-hint')).toHaveTextContent('“Download orders.json” or “Download .zip”');
  });

  it('shows the git pull request a delivery opened, as a link', async () => {
    mockFetch();
    panel();
    const attempt = await screen.findByTestId('delivery-attempt');
    const link = within(attempt).getByRole('link', { name: 'https://github.com/acme/specs/pull/7' });
    expect(link).toHaveAttribute('href', 'https://github.com/acme/specs/pull/7');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(within(attempt).getByTestId('delivery-result')).toHaveTextContent('Pull request #7');
  });

  it('shows each channel’s result', async () => {
    mockFetch({ deliveries: [GIT_ATTEMPT, WEBHOOK_ATTEMPT, STORAGE_ATTEMPT] });
    panel({ expected: 3 });
    const attempts = await screen.findAllByTestId('delivery-attempt');
    expect(attempts).toHaveLength(3);
    expect(attempts[1]).toHaveTextContent('Receiver answered HTTP 202');
    expect(attempts[2]).toHaveTextContent('and 3 more');
    expect(within(attempts[2]).getByRole('link', { name: /manifests\/abc\.json/ })).toBeInTheDocument();
    expect(within(attempts[2]).queryByRole('link', { name: 's3://specs/orders/openapi.yaml' })).not.toBeInTheDocument();
  });

  it('points at the Delivery tab when there are no profiles — before and after the job', async () => {
    mockFetch({ profiles: [], deliveries: [] });
    const { unmount } = panel({ jobId: null, expected: 0 });
    expect(await screen.findByTestId('delivery-empty')).toHaveTextContent('No delivery profiles yet');
    expect(within(screen.getByTestId('delivery-empty')).getByRole('link', { name: 'Delivery' })).toHaveAttribute(
      'href',
      '/ade/dashboard/export/studio?tab=delivery',
    );
    unmount();
    panel({ expected: 0 });
    expect(await screen.findByTestId('delivery-empty')).toHaveTextContent('a git repository (as a pull request or a commit), a webhook or a bucket');
    expect(screen.queryByRole('button', { name: 'Deliver now' })).not.toBeInTheDocument();
  });

  it('offers no registry for a target a schema registry cannot hold', async () => {
    mockFetch();
    panel({ registry: null });
    await screen.findByTestId('delivery-attempt');
    expect(screen.queryByTestId('registry-destination')).not.toBeInTheDocument();
    expect(calls.some((c) => c.url === '/api/connectors')).toBe(false);
  });

  it('pushes an Avro export to a schema registry and lists each subject with its version and id', async () => {
    mockFetch();
    panel({ registry: AVRO });
    const registry = await screen.findByTestId('registry-destination');
    // The only schema-registry connector is chosen; other connector kinds are not offered.
    expect(within(registry).getByTestId('registry-connector')).toHaveValue('c1');
    expect(within(within(registry).getByTestId('registry-connector')).queryByText('gateway')).not.toBeInTheDocument();
    fireEvent.click(within(registry).getByTestId('registry-push'));
    const result = await within(registry).findByTestId('registry-result');
    const push = calls.find((c) => c.url === '/api/export/registry-push')!;
    expect(JSON.parse(String(push.init!.body))).toMatchObject({ format: 'avro', artifact: 'proj-1', connector_id: 'c1', dry_run: false });
    const subjects = within(result).getAllByTestId('registry-subject');
    expect(subjects[0]).toHaveTextContent('Registered');
    expect(subjects[0]).toHaveTextContent('acme.Order-value');
    expect(subjects[0]).toHaveTextContent('version 3 · id 41');
    expect(subjects[1]).toHaveTextContent('Incompatible');
    expect(subjects[1]).toHaveTextContent('READER_FIELD_MISSING_DEFAULT_VALUE');
    expect(result).toHaveTextContent('Pushed to https://registry.example.com');
  });

  it('dry-runs, and needs a topic for a topic strategy', async () => {
    mockFetch();
    panel({ registry: AVRO });
    const registry = await screen.findByTestId('registry-destination');
    fireEvent.change(within(registry).getByTestId('registry-naming'), { target: { value: 'topic_name' } });
    expect(within(registry).getByTestId('registry-push')).toBeDisabled();
    expect(within(registry).getByTestId('registry-push')).toHaveAttribute('title', 'Enter the Kafka topic the subjects are named after.');
    fireEvent.change(within(registry).getByTestId('registry-topic'), { target: { value: 'orders' } });
    fireEvent.click(within(registry).getByTestId('registry-dry-run'));
    expect(within(registry).getByTestId('registry-push')).toHaveTextContent('Check against registry');
    fireEvent.click(within(registry).getByTestId('registry-push'));
    expect(await within(registry).findByTestId('registry-result')).toHaveTextContent('Checked against');
    const push = calls.find((c) => c.url === '/api/export/registry-push')!;
    expect(JSON.parse(String(push.init!.body))).toMatchObject({ subject_naming: 'topic_name', topic: 'orders', dry_run: true });
  });

  it('says where to add a schema registry when the workspace has none', async () => {
    mockFetch({ connectors: [] });
    panel({ registry: AVRO, connectorsHref: '/ade/dashboard/connectors' });
    const empty = await screen.findByTestId('registry-empty');
    expect(within(empty).getByRole('link', { name: 'Connectors' })).toHaveAttribute('href', '/ade/dashboard/connectors');
  });

  it('shows a refused push as an alert', async () => {
    mockFetch({ pushFails: true });
    panel({ registry: AVRO });
    const registry = await screen.findByTestId('registry-destination');
    fireEvent.click(within(registry).getByTestId('registry-push'));
    await waitFor(() => expect(within(registry).getByRole('alert')).toHaveTextContent('imports:edit is required'));
  });

  it('is axe-clean with results and the registry', async () => {
    mockFetch({ deliveries: [GIT_ATTEMPT, WEBHOOK_ATTEMPT, STORAGE_ATTEMPT] });
    const { container } = panel({ registry: AVRO, expected: 3 });
    await screen.findAllByTestId('delivery-attempt');
    await screen.findByTestId('registry-destination');
    expect(await axe(container)).toHaveNoViolations();
  });
});

/**
 * The docs fixture (`apiome-docs/screens.json`: `export-studio-deliver`): the Deliver section of a finished
 * job — a git pull request, a webhook receipt, objects in a bucket, and an Avro push to a schema registry.
 * Written into `e2e/fixtures/hive-export-studio/` when `EXPORT_STUDIO_FIXTURE_DUMP=1`.
 */
describe('the docs fixtures', () => {
  it('writes the Deliver section with every channel’s result', async () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const fs = require('node:fs') as typeof import('node:fs');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const path = require('node:path') as typeof import('node:path');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { liveMarkup } = require('./helpers/a11y-fixture-dump') as typeof import('./helpers/a11y-fixture-dump');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { Page, PageBody } = require('@/app/components/shell/pageChrome');
    mockFetch({ deliveries: [GIT_ATTEMPT, WEBHOOK_ATTEMPT, STORAGE_ATTEMPT] });
    const { container } = render(
      <Page>
        <PageBody>
          <ExportJobDeliveryPanel jobId="job-1" selected={[]} onSelectedChange={() => undefined} expected={3}
            manageHref="/ade/dashboard/export/studio?tab=delivery"
            downloadHint="“Download orders.avsc” or “Download .zip”" registry={AVRO} />
        </PageBody>
      </Page>,
    );
    await screen.findAllByTestId('delivery-attempt');
    const registry = await screen.findByTestId('registry-destination');
    fireEvent.click(within(registry).getByTestId('registry-push'));
    await within(registry).findByTestId('registry-result');
    const html = liveMarkup(container.querySelector('.page') as HTMLElement);
    expect(html.length).toBeGreaterThan(0);
    if (process.env.EXPORT_STUDIO_FIXTURE_DUMP !== '1') return;
    const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-export-studio');
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, 'deliver.html'), `${html}\n`);
  });
});
