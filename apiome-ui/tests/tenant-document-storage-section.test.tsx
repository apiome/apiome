/**
 * The tenant drawer's **Document storage** section — COA-5.15 (#7092).
 *
 * Reads where documents are kept, switches to the workspace's own bucket (validating, testing and
 * saving in turn), adds a storage credential without showing its secret again, follows a move
 * while it runs, deletes old copies only after the confirm, and is read-only for
 * non-administrators and on an install that does not offer tenant buckets.
 */

import React from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import TenantDocumentStorageSection from '../src/app/components/ade/tenants/TenantDocumentStorageSection';
import {
  draftBody,
  draftFromStore,
  isDraftDirty,
  movePercent,
  moveSummary,
  validateDraft,
  type TenantDocumentStore,
} from '../lib/tenant-document-store';
import { settingsBody } from '../src/app/api/tenant-document-store/body';
import { restErrorMessage } from '../lib/rest-error-message';

const IDLE_MOVE = {
  state: 'idle' as const, target: null, total: 0, moved: 0, failed: 0, error: null, startedAt: null, finishedAt: null,
};

const PLATFORM: TenantDocumentStore = {
  allowed: true,
  mode: 'platform',
  credentialId: null,
  credentialName: null,
  bucket: null,
  prefix: 'apiome',
  region: '',
  endpointUrl: '',
  addressingStyle: 'auto',
  sse: '',
  kmsKeyId: '',
  health: { available: true, unavailableSince: null, error: null },
  move: IDLE_MOVE,
  cleanupPending: false,
};

const ON_BUCKET: TenantDocumentStore = {
  ...PLATFORM,
  mode: 'tenant',
  credentialId: 'cred-1',
  credentialName: 'documents',
  bucket: 'acme-documents',
  move: { ...IDLE_MOVE, state: 'completed', target: 'tenant', total: 3, moved: 3 },
  cleanupPending: true,
};

const SECRET = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY';

let store: TenantDocumentStore = PLATFORM;
let calls: Array<{ url: string; method: string; body: any }> = [];
let probe: unknown = { ok: true, bucket: 'acme-documents', error: null, steps: [] };
let putError: string | null = null;

beforeEach(() => {
  window.localStorage.clear();
  store = PLATFORM;
  calls = [];
  probe = { ok: true, bucket: 'acme-documents', error: null, steps: [] };
  putError = null;
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const reply = (data: unknown, status = 200) =>
      ({ ok: status < 400, status, json: async () => data }) as Response;
    if (url === '/api/tenant-document-store' && method === 'PUT') {
      if (putError) return reply({ success: false, error: putError }, 400);
      store =
        body.mode === 'tenant'
          ? { ...ON_BUCKET, bucket: body.bucket, credentialId: body.credentialId, sse: body.sse, kmsKeyId: body.kmsKeyId,
              move: { ...IDLE_MOVE, state: 'running', target: 'tenant', total: 3, moved: 1 }, cleanupPending: false }
          : { ...ON_BUCKET, mode: 'platform', move: { ...IDLE_MOVE, state: 'completed', target: 'platform', total: 3, moved: 3 } };
      return reply(store);
    }
    if (url === '/api/tenant-document-store') return reply(store);
    if (url === '/api/tenant-document-store/test') return reply(probe);
    if (url === '/api/tenant-document-store/cleanup') {
      store = { ...store, cleanupPending: false };
      return reply({ checked: 3, deleted: 3 });
    }
    if (url === '/api/export/storage-credentials' && method === 'POST') {
      return reply({ success: true, data: { id: 'cred-new', name: body.name, accessKeyHint: 'WXYZ', region: body.region } });
    }
    if (url === '/api/export/storage-credentials') {
      return reply({ success: true, data: { credentials: [{ id: 'cred-1', name: 'documents', accessKeyHint: 'ABCD', region: 'us-east-1' }] } });
    }
    return reply({ error: 'not found' }, 404);
  }) as unknown as typeof fetch;
});

afterEach(() => {
  jest.useRealTimers();
});

/** Render the section and wait for the settings to load. */
const renderSection = async (isAdmin = true) => {
  const onDirtyChange = jest.fn();
  const view = render(<TenantDocumentStorageSection isAdmin={isAdmin} onDirtyChange={onDirtyChange} />);
  await screen.findByRole('heading', { name: 'Document storage' });
  await waitFor(() => expect(screen.queryByText('Loading document storage…')).not.toBeInTheDocument());
  return { ...view, onDirtyChange };
};

const sent = (url: string, method: string) => calls.filter((call) => call.url === url && call.method === method);

describe('TenantDocumentStorageSection', () => {
  it('shows platform storage by default, with nothing to save', async () => {
    const { container } = await renderSection();
    expect(screen.getByRole('radio', { name: /Platform storage/ })).toBeChecked();
    expect(screen.queryByTestId('tenant-storage-form')).not.toBeInTheDocument();
    expect(screen.getByTestId('tenant-storage-save')).toBeDisabled();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('validates, tests and saves a bucket, then follows the move', async () => {
    const user = userEvent.setup();
    const { onDirtyChange, container } = await renderSection();

    await user.click(screen.getByRole('radio', { name: /Your own bucket/ }));
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
    // Nothing can be sent until the bucket and the credential are given.
    expect(screen.getByTestId('tenant-storage-save')).toBeDisabled();
    expect(screen.getByTestId('tenant-storage-test')).toBeDisabled();

    await user.type(screen.getByLabelText('Bucket'), 'Bad_Name');
    expect(screen.getByText('Use 3 to 63 lower-case letters, digits, dots or hyphens.')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Bucket'));
    await user.type(screen.getByLabelText('Bucket'), 'acme-documents');
    await user.selectOptions(await screen.findByLabelText('Storage credential'), 'cred-1');
    await user.selectOptions(screen.getByLabelText('Encryption'), 'kms');
    await user.type(screen.getByLabelText('KMS key ID'), 'alias/docs');
    expect(await axe(container)).toHaveNoViolations();

    await user.click(screen.getByTestId('tenant-storage-test'));
    expect(await screen.findByTestId('tenant-storage-test-result')).toHaveTextContent('The bucket passed');
    // The unsaved values are what is tested.
    expect(sent('/api/tenant-document-store/test', 'POST')[0].body).toMatchObject({
      mode: 'tenant', bucket: 'acme-documents', credentialId: 'cred-1', sse: 'kms', kmsKeyId: 'alias/docs',
    });

    const save = screen.getByTestId('tenant-storage-save');
    expect(save).toHaveTextContent('Save and move documents');
    await user.click(save);
    const move = await screen.findByTestId('tenant-storage-move');
    expect(within(move).getByRole('progressbar', { name: 'Documents moved' })).toHaveAttribute('aria-valuenow', '33');
    expect(move).toHaveTextContent('Moving documents to your bucket: 1 of 3 done.');
    expect(sent('/api/tenant-document-store', 'PUT')[0].body).toEqual({
      mode: 'tenant', credentialId: 'cred-1', bucket: 'acme-documents', prefix: 'apiome', region: '',
      endpointUrl: '', addressingStyle: 'auto', sse: 'kms', kmsKeyId: 'alias/docs',
    });
    // While the move runs the form is locked and there is no cleanup yet.
    expect(screen.getByTestId('tenant-storage-save')).toBeDisabled();
    expect(screen.queryByTestId('tenant-storage-cleanup')).not.toBeInTheDocument();
  });

  it('keeps polling until a running move finishes', async () => {
    jest.useFakeTimers();
    store = { ...ON_BUCKET, cleanupPending: false, move: { ...IDLE_MOVE, state: 'running', target: 'tenant', total: 3, moved: 1 } };
    render(<TenantDocumentStorageSection isAdmin />);
    expect(await screen.findByTestId('tenant-storage-move')).toHaveTextContent('1 of 3 done');

    store = ON_BUCKET;
    await act(async () => {
      jest.advanceTimersByTime(3100);
    });
    await waitFor(() => expect(screen.getByTestId('tenant-storage-move')).toHaveTextContent('Moved 3 documents to your bucket.'));
    expect(screen.getByTestId('tenant-storage-cleanup')).toBeInTheDocument();
    const reads = sent('/api/tenant-document-store', 'GET').length;
    await act(async () => {
      jest.advanceTimersByTime(10000);
    });
    // The move is over: no more polling.
    expect(sent('/api/tenant-document-store', 'GET')).toHaveLength(reads);
  });

  it('locks where the bucket is while documents are in it', async () => {
    store = ON_BUCKET;
    await renderSection();
    expect(screen.getByLabelText('Bucket')).toBeDisabled();
    expect(screen.getByLabelText('Folder')).toBeDisabled();
    expect(screen.getByLabelText('Endpoint URL')).toBeDisabled();
    expect(screen.getByLabelText('Region')).toBeEnabled();
    expect(screen.getByTestId('tenant-storage-location-locked')).toHaveTextContent('move back to platform storage');
  });

  it('deletes old copies only after the confirm', async () => {
    const user = userEvent.setup();
    store = ON_BUCKET;
    await renderSection();
    expect(screen.getByTestId('tenant-storage-cleanup')).toHaveTextContent('still have a copy in platform storage');

    await user.click(screen.getByTestId('tenant-storage-cleanup-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('This cannot be undone.');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(sent('/api/tenant-document-store/cleanup', 'POST')).toHaveLength(0);

    await user.click(screen.getByTestId('tenant-storage-cleanup-open'));
    await user.click(await screen.findByTestId('tenant-storage-cleanup-confirm-action'));
    expect(await screen.findByTestId('tenant-storage-cleaned')).toHaveTextContent('Deleted 3 old copies.');
    expect(sent('/api/tenant-document-store/cleanup', 'POST')[0].body).toEqual({ confirm: true });
    await waitFor(() => expect(screen.queryByTestId('tenant-storage-cleanup')).not.toBeInTheDocument());
  });

  it('adds a credential, selects it and never shows the secret again', async () => {
    const user = userEvent.setup();
    await renderSection();
    await user.click(screen.getByRole('radio', { name: /Your own bucket/ }));
    await user.click(screen.getByTestId('tenant-storage-add-credential'));

    const form = screen.getByTestId('tenant-storage-credential-form');
    expect(screen.getByTestId('tenant-credential-store')).toBeDisabled();
    await user.type(within(form).getByLabelText('Name'), 'documents-bucket');
    await user.type(within(form).getByLabelText('Access key ID'), 'AKIAIOSFODNN7EXAMPLE');
    const secret = within(form).getByLabelText('Secret access key');
    expect(secret).toHaveAttribute('type', 'password');
    await user.type(secret, SECRET);
    await user.click(screen.getByTestId('tenant-credential-store'));

    await waitFor(() => expect(screen.queryByTestId('tenant-storage-credential-form')).not.toBeInTheDocument());
    expect(screen.getByLabelText('Storage credential')).toHaveValue('cred-new');
    expect(screen.getByRole('option', { name: 'documents-bucket (…WXYZ)' })).toBeInTheDocument();
    expect(sent('/api/export/storage-credentials', 'POST')[0].body).toMatchObject({
      name: 'documents-bucket', accessKeyId: 'AKIAIOSFODNN7EXAMPLE', secretAccessKey: SECRET, region: 'us-east-1',
    });
    // The secret is gone from the page, and reopening the form starts empty.
    expect(document.body.innerHTML).not.toContain(SECRET);
    await user.click(screen.getByTestId('tenant-storage-add-credential'));
    expect(screen.getByLabelText('Secret access key')).toHaveValue('');
  });

  it('shows a failed test step by step, and what REST refused on save', async () => {
    const user = userEvent.setup();
    probe = {
      ok: false, bucket: 'acme-documents', error: null,
      steps: [
        { name: 'write', ok: false, skipped: false, durationMs: 12, error: "Apiome could not write to bucket 'acme-documents' (AccessDenied)." },
        { name: 'read', ok: false, skipped: true, durationMs: 0, error: null },
        { name: 'delete', ok: false, skipped: true, durationMs: 0, error: null },
      ],
    };
    putError = 'The bucket did not pass the write, read and delete test, so nothing was changed.';
    await renderSection();
    await user.click(screen.getByRole('radio', { name: /Your own bucket/ }));
    await user.type(screen.getByLabelText('Bucket'), 'acme-documents');
    await user.selectOptions(await screen.findByLabelText('Storage credential'), 'cred-1');

    await user.click(screen.getByTestId('tenant-storage-test'));
    const steps = await screen.findByTestId('tenant-storage-test-steps');
    expect(steps).toHaveTextContent('Write a test object');
    expect(steps).toHaveTextContent('AccessDenied');
    expect(within(steps).getAllByText('Not run')).toHaveLength(2);

    await user.click(screen.getByTestId('tenant-storage-save'));
    expect(await screen.findByRole('alert')).toHaveTextContent('nothing was changed');
    expect(screen.queryByTestId('tenant-storage-move')).not.toBeInTheDocument();
  });

  it('says so when the bucket is not answering', async () => {
    store = {
      ...ON_BUCKET,
      health: { available: false, unavailableSince: '2026-11-21T08:00:00Z', error: "Apiome could not read from bucket 'acme-documents' (InvalidAccessKeyId)." },
    };
    await renderSection();
    const alert = screen.getByTestId('tenant-storage-unavailable');
    expect(alert).toHaveTextContent('Your bucket is not answering.');
    expect(alert).toHaveTextContent('InvalidAccessKeyId');
  });

  it('is read-only for a non-administrator', async () => {
    store = ON_BUCKET;
    await renderSection(false);
    expect(screen.getByText('Only administrators can change document storage.')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Platform storage/ })).toBeDisabled();
    expect(screen.queryByTestId('tenant-storage-save')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tenant-storage-cleanup-open')).not.toBeInTheDocument();
  });

  it('explains an install that does not offer tenant buckets', async () => {
    store = { ...PLATFORM, allowed: false };
    await renderSection();
    expect(screen.getByTestId('tenant-storage-not-offered')).toHaveTextContent('not turned on for this installation');
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });

  it('keeps showing a bucket in use after the install stops offering it, without letting it change', async () => {
    store = { ...ON_BUCKET, allowed: false };
    await renderSection();
    expect(screen.getByTestId('tenant-storage-frozen')).toBeInTheDocument();
    expect(screen.getByLabelText('Bucket')).toHaveValue('acme-documents');
    expect(screen.queryByTestId('tenant-storage-save')).not.toBeInTheDocument();
  });
});

describe('the document storage model', () => {
  it('knows when a draft changed and what it needs', () => {
    const draft = draftFromStore(PLATFORM);
    expect(isDraftDirty(draft, PLATFORM)).toBe(false);
    expect(validateDraft(draft)).toEqual({});
    const own = { ...draft, mode: 'tenant' as const };
    expect(isDraftDirty(own, PLATFORM)).toBe(true);
    expect(Object.keys(validateDraft(own))).toEqual(['credentialId', 'bucket']);
    expect(validateDraft({ ...own, credentialId: 'c', bucket: 'ok-bucket', kmsKeyId: 'k' })).toEqual({
      kmsKeyId: 'A KMS key is only used with SSE-KMS.',
    });
    expect(validateDraft({ ...own, credentialId: 'c', bucket: 'ok-bucket', endpointUrl: 'minio:9000' })).toHaveProperty('endpointUrl');
  });

  it('sends only the mode when going back to platform storage', () => {
    expect(draftBody({ ...draftFromStore(ON_BUCKET), mode: 'platform' })).toEqual({ mode: 'platform' });
    expect(draftBody({ ...draftFromStore(ON_BUCKET), sse: 's3', kmsKeyId: 'stale' })).toMatchObject({ sse: 's3', kmsKeyId: '' });
  });

  it('describes a move', () => {
    expect(movePercent({ ...IDLE_MOVE, state: 'running', total: 0 })).toBe(0);
    expect(movePercent({ ...IDLE_MOVE, state: 'completed', total: 0 })).toBe(100);
    expect(movePercent({ ...IDLE_MOVE, state: 'running', total: 8, moved: 3, failed: 1 })).toBe(50);
    expect(moveSummary(IDLE_MOVE)).toBeNull();
    expect(moveSummary({ ...IDLE_MOVE, state: 'completed', target: 'platform', moved: 0 })).toBe('Nothing needed moving to platform storage.');
    expect(moveSummary({ ...IDLE_MOVE, state: 'failed', target: 'tenant', moved: 4, failed: 1 })).toBe(
      'Moved 4 documents to your bucket; 1 document could not be moved and is still read from where it was.'
    );
  });
});

describe('the proxies', () => {
  it('forward only the settings fields, and nothing without a mode', () => {
    expect(settingsBody({ bucket: 'x' })).toBeNull();
    expect(settingsBody(null)).toBeNull();
    expect(
      settingsBody({ mode: 'tenant', bucket: 'b', credentialId: 'c', sse: 'aes', addressingStyle: 'path', secretAccessKey: SECRET, extra: 1 })
    ).toEqual({ mode: 'tenant', bucket: 'b', credentialId: 'c', addressingStyle: 'path' });
  });

  it('read a field-by-field refusal out of a REST error', () => {
    expect(restErrorMessage({ detail: { code: 'tenant-document-store-invalid', errors: ['bucket: is required to use your own bucket.'] } }))
      .toBe('bucket: is required to use your own bucket.');
  });
});
