'use client';

/**
 * The pieces of the **Webhooks** pages (PFX-5.6, #6950): the webhook and delivery tables, the
 * delivery log with its **Status** filter and **Load more**, the editor dialog (create, edit and
 * **Test** before saving), a test run's outcome and the delete confirmation.
 *
 * Tables are real `<table>`s with captions and column headers; every control is a native input,
 * select, checkbox or button, so the pages are read and driven from the keyboard like the other
 * Contracts pages.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw, Send } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, CommandBlock, EmptyState, LoadingState } from '@/app/components/ui';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/app/components/ui/AlertDialog';
import { formatWhen, shortVersion } from '@lib/pact-pacticipants';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { webhookCommandAction } from '@lib/pact-webhook-command';
import {
  DELIVERY_STATUSES,
  EVENT_OPTIONS,
  REDACTED,
  WEBHOOK_METHODS,
  deliveryRoute,
  deliveryStatus,
  emptyWebhookForm,
  eventLabel,
  formFromWebhook,
  scopeLabel,
  targetLabel,
  triggerTypeLabel,
  webhookBodyFromForm,
  webhookFormProblem,
  webhookRoute,
  type DeliveryStatus,
  type ExecutionResult,
  type WebhookDelivery,
  type WebhookDocument,
  type WebhookForm,
} from '@lib/pact-webhooks';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { fetchDeliveries } from './webhooksApi';

/**
 * A delivery's status as a badge.
 *
 * @param props - The status.
 * @returns The badge.
 */
export function DeliveryStatusBadge({ status }: { status: string }) {
  const shown = deliveryStatus(status);
  return (
    <Badge variant={shown.variant} data-testid="pwx-status">
      {shown.label}
    </Badge>
  );
}

/**
 * Every webhook of the workspace: what it is for, what it fires on, where it sends, whether it is
 * on, and its newest delivery.
 *
 * @param props - The webhooks and the newest firing of each.
 * @returns The table.
 */
export function WebhooksTable({
  webhooks,
  latest,
}: {
  webhooks: WebhookDocument[];
  latest: Record<string, WebhookDelivery>;
}) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="pwx-webhooks-table">
        <caption className="sr-only">Contract webhooks</caption>
        <thead>
          <tr>
            <th scope="col">Webhook</th>
            <th scope="col">For</th>
            <th scope="col">Events</th>
            <th scope="col">Sends to</th>
            <th scope="col">State</th>
            <th scope="col">Last delivery</th>
          </tr>
        </thead>
        <tbody>
          {webhooks.map((webhook) => {
            const last = latest[webhook.uuid];
            return (
              <tr key={webhook.uuid} data-testid={`pwx-webhook-${webhook.uuid}`}>
                <th scope="row">
                  <Link className="ppx__link" href={webhookRoute(webhook.uuid)}>
                    {webhook.description}
                  </Link>
                </th>
                <td>{scopeLabel(webhook)}</td>
                <td>
                  <ul className="ppx__plain-list">
                    {webhook.events.map((event) => (
                      <li key={event.name}>{eventLabel(event.name)}</li>
                    ))}
                  </ul>
                </td>
                <td className="ppx__mono">{targetLabel(webhook)}</td>
                <td>
                  <span className="ppx__chips">
                    <Badge variant={webhook.enabled ? 'ok' : 'neutral'}>{webhook.enabled ? 'Enabled' : 'Disabled'}</Badge>
                    {webhook.signed ? <Badge variant="neutral">Signed</Badge> : null}
                  </span>
                </td>
                <td>
                  {last ? (
                    <span className="ppx__chips">
                      <DeliveryStatusBadge status={last.status} />
                      <Link className="ppx__link ppx__when" href={deliveryRoute(last.id)}>
                        {formatWhen(last.triggeredAt)}
                      </Link>
                    </span>
                  ) : (
                    <span className="ppx__muted">Never fired</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Firings, newest first.
 *
 * @param props - The firings; `showWebhook` adds the webhook column (the workspace's log).
 * @returns The table.
 */
export function DeliveriesTable({
  deliveries,
  showWebhook,
}: {
  deliveries: WebhookDelivery[];
  showWebhook: boolean;
}) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="pwx-deliveries-table">
        <caption className="sr-only">Webhook deliveries, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Triggered</th>
            <th scope="col">Status</th>
            <th scope="col">Event</th>
            <th scope="col">Pact</th>
            {showWebhook ? <th scope="col">Webhook</th> : null}
            <th scope="col">Attempts</th>
            <th scope="col">Trigger</th>
          </tr>
        </thead>
        <tbody>
          {deliveries.map((delivery) => (
            <tr key={delivery.id} data-testid={`pwx-delivery-${delivery.id}`}>
              <th scope="row" className="ppx__when">
                <Link className="ppx__link" href={deliveryRoute(delivery.id)}>
                  {formatWhen(delivery.triggeredAt)}
                </Link>
              </th>
              <td>
                <DeliveryStatusBadge status={delivery.status} />
              </td>
              <td>{eventLabel(delivery.eventName)}</td>
              <td>
                {delivery.consumer.name} → {delivery.provider.name}
                {delivery.consumerVersionNumber ? (
                  <span className="ppx__muted ppx__mono" title={delivery.consumerVersionNumber}>
                    {' '}
                    · {shortVersion(delivery.consumerVersionNumber)}
                  </span>
                ) : null}
              </td>
              {showWebhook ? (
                <td>
                  <Link className="ppx__link" href={webhookRoute(delivery.webhookId)}>
                    {delivery.name}
                  </Link>
                </td>
              ) : null}
              <td>
                {delivery.attemptsMade}
                {delivery.attemptsRemaining > 0 ? (
                  <span className="ppx__muted"> ({delivery.attemptsRemaining} left)</span>
                ) : null}
              </td>
              <td>{triggerTypeLabel(delivery.triggerType)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The loaded firings and where the next page starts. */
interface LogState {
  rows: WebhookDelivery[];
  nextCursor: string | null;
}

/**
 * A delivery log: the workspace's (no `webhook`) or one webhook's, with a **Status** filter,
 * **Refresh** and **Load more**. It reads its own pages; `reloadKey` changing reads again (after a
 * redelivery or a test).
 *
 * @param props - The webhook to narrow to, the panel's heading and the reload key.
 * @returns The panel.
 */
export function DeliveryLog({
  webhook,
  title,
  reloadKey = 0,
}: {
  webhook: string | null;
  title: string;
  reloadKey?: number;
}) {
  const [status, setStatus] = React.useState<DeliveryStatus | ''>('');
  const [log, setLog] = React.useState<LogState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [moreError, setMoreError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLog(null);
    setError(null);
    setMoreError(null);
    try {
      const page = await fetchDeliveries({ webhook, status: status || null });
      setLog({ rows: page.deliveries, nextCursor: page.nextCursor });
    } catch (caught) {
      setError(describeFailure(caught, 'Could not load the deliveries'));
    }
  }, [status, webhook]);

  React.useEffect(() => {
    void load();
  }, [load, reloadKey]);

  const loadMore = async () => {
    if (!log?.nextCursor) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await fetchDeliveries({ webhook, status: status || null, cursor: log.nextCursor });
      setLog({ rows: [...log.rows, ...page.deliveries], nextCursor: page.nextCursor });
    } catch (caught) {
      setMoreError(describeFailure(caught, 'Could not load more deliveries'));
    } finally {
      setLoadingMore(false);
    }
  };

  const headingId = webhook ? 'pwx-log-title-webhook' : 'pwx-log-title';
  return (
    <section className="ppx__panel" aria-labelledby={headingId} data-testid="pwx-log">
      <div className="ppx__panel-head">
        <h2 id={headingId} className="ppx__title">
          {title}
        </h2>
        <span className="ppx__actions">
          <label className="ppx__field">
            <span className="ppx__field-label">Status</span>
            <select
              className="ppx__select"
              value={status}
              onChange={(event) => setStatus(event.target.value as DeliveryStatus | '')}
              data-testid="pwx-status-filter"
            >
              <option value="">All statuses</option>
              {DELIVERY_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {deliveryStatus(value).label}
                </option>
              ))}
            </select>
          </label>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        </span>
      </div>
      {error ? (
        <EmptyState
          variant="compact"
          tone="danger"
          titleAs="h3"
          title="The deliveries could not be read"
          description={error}
          action={
            <Button variant="soft" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Try again
            </Button>
          }
        />
      ) : log === null ? (
        <LoadingState message="Reading the deliveries…" minHeightClassName="min-h-[6rem]" />
      ) : log.rows.length === 0 ? (
        <EmptyState
          variant="compact"
          titleAs="h3"
          title={status ? `No ${deliveryStatus(status).label.toLowerCase()} deliveries` : 'No deliveries yet'}
          description={
            status
              ? 'Choose another status, or All statuses.'
              : 'A webhook fires when one of its events happens to a pact. Use Test to send one now.'
          }
        />
      ) : (
        <>
          <DeliveriesTable deliveries={log.rows} showWebhook={webhook === null} />
          {moreError ? (
            <p className="ppx__error" role="alert">
              {moreError}
            </p>
          ) : null}
          {log.nextCursor ? (
            <div className="ppx__more">
              <Button
                variant="outline"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                data-testid="pwx-deliveries-more"
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

/** A value of a test run as text: JSON pretty-printed, text as it is. */
function shown(value: unknown): string {
  if (value === undefined || value === null || value === '') return '';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

/**
 * What a test run sent and what came back (secrets redacted by REST).
 *
 * @param props - The run.
 * @returns The outcome.
 */
export function TestOutcome({ result }: { result: ExecutionResult }) {
  return (
    <div className="pwx-test-outcome" data-testid="pwx-test-outcome" role="status">
      <p className="ppx__chips">
        <Badge variant={result.success ? 'ok' : 'danger'}>{result.success ? 'Test succeeded' : 'Test failed'}</Badge>
        {result.response ? <span className="ppx__mono">HTTP {result.response.status}</span> : null}
        {result.error ? <span className="ppx__error">{result.error.message}</span> : null}
      </p>
      {result.request.url ? (
        <p className="ppx__meta">
          Sent to <span className="ppx__mono">{result.request.url}</span>
        </p>
      ) : null}
      {result.response && shown(result.response.body) ? (
        <pre className="ppx__snippet pwx-pre" tabIndex={0} aria-label="Response body">
          {shown(result.response.body)}
        </pre>
      ) : null}
      <pre className="ppx__snippet pwx-pre" tabIndex={0} aria-label="Test log">
        {result.logs}
      </pre>
    </div>
  );
}

/** A secret input that shows the stored value is kept until something is typed. */
function SecretField({
  id,
  label,
  value,
  onChange,
  placeholder,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled: boolean;
}) {
  const stored = value === REDACTED;
  const noteId = `${id}-note`;
  return (
    <div className="pmx-field">
      <label className="ppx__field-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="pmx-input"
        type="password"
        autoComplete="off"
        value={stored ? '' : value}
        placeholder={stored ? 'Stored — type to replace' : placeholder}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={stored ? noteId : undefined}
        disabled={disabled}
      />
      {stored ? (
        <span id={noteId} className="ppx__muted pwx-secret-note">
          The stored value is kept.{' '}
          <button type="button" className="pwx-text-button" onClick={() => onChange('')} disabled={disabled}>
            Remove it
          </button>
        </span>
      ) : null}
    </div>
  );
}

/**
 * **The same, from anywhere** under the editor (PFX-8.2, #7299): what the form holds as
 * `apiome pact create-webhook`, Pact CLI, a pipeline step and REST — redrawn on every keystroke,
 * with every secret as a `$WEBHOOK_…` variable. Editing a saved webhook has no command, so the
 * block then shows the REST `PUT` and says why.
 *
 * @param props - The editor's form, and the saved webhook's id when editing one.
 * @returns The block.
 */
export function WebhookCommandBlock({ form, webhookId }: { form: WebhookForm; webhookId: string | null }) {
  const action = webhookCommandAction(form, { tenant: '', webhookId });
  return (
    <CommandBlock
      className="pwx-command-block"
      surfaces={pactCommandSurfaces(action)}
      unsupported={unsupportedLines(action)}
      footnote="Replace {tenant} with your workspace’s handle in the REST path."
      data-testid="pwx-command-block"
    />
  );
}

/**
 * The editor: a new webhook (`webhook` null) or an existing one. **Save** creates or replaces it.
 * With `onTest`, **Test** sends what the form holds once without saving it — offered for a new
 * webhook only: an unsaved request cannot use a stored secret, so an existing webhook is tested
 * from its page, as saved.
 *
 * @param props - The webhook to edit, what saving (and testing) does, and how to close.
 * @returns The dialog.
 */
export function WebhookEditor({
  webhook,
  onSave,
  onTest,
  onClose,
}: {
  webhook: WebhookDocument | null;
  onSave: (body: Record<string, unknown>) => Promise<void>;
  onTest?: (body: Record<string, unknown>) => Promise<ExecutionResult>;
  onClose: () => void;
}) {
  const [form, setForm] = React.useState<WebhookForm>(() => (webhook ? formFromWebhook(webhook) : emptyWebhookForm()));
  const [busy, setBusy] = React.useState<'save' | 'test' | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [tested, setTested] = React.useState<ExecutionResult | null>(null);
  const problem = webhookFormProblem(form);
  const set = <K extends keyof WebhookForm>(key: K, value: WebhookForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const toggleEvent = (name: string, on: boolean) =>
    set('events', on ? [...form.events, name] : form.events.filter((event) => event !== name));
  const disabled = busy !== null;

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (problem || disabled) return;
    setBusy('save');
    setError(null);
    try {
      await onSave(webhookBodyFromForm(form));
    } catch (caught) {
      setError(describeFailure(caught, 'The webhook could not be saved.'));
      setBusy(null);
    }
  };

  const test = async () => {
    if (problem || disabled || !onTest) return;
    setBusy('test');
    setError(null);
    setTested(null);
    try {
      setTested(await onTest(webhookBodyFromForm(form)));
    } catch (caught) {
      setError(describeFailure(caught, 'The webhook could not be tested.'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !disabled && onClose()}>
      <DialogContent data-testid="pwx-editor" size="lg">
        <DialogHeader>
          <DialogTitle>{webhook ? 'Edit webhook' : 'New webhook'}</DialogTitle>
          <DialogDescription>
            Send an HTTP request, or start a GitHub Actions workflow, when something happens to a pact.
            {' '}
            <code>{'${pactbroker.…}'}</code> parameters are filled in when it fires.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void save(event)}>
          <DialogBody>
            <div className="pwx-form">
              <label className="pmx-field" htmlFor="pwx-description">
                <span className="ppx__field-label">Description (optional)</span>
                <input
                  id="pwx-description"
                  className="pmx-input"
                  value={form.description}
                  onChange={(event) => set('description', event.target.value)}
                  placeholder="Verify Ledger API when a pact changes"
                  maxLength={1000}
                  disabled={disabled}
                />
              </label>
              <div className="pwx-form__row">
                <label className="pmx-field" htmlFor="pwx-consumer">
                  <span className="ppx__field-label">Consumer (optional)</span>
                  <input
                    id="pwx-consumer"
                    className="pmx-input"
                    value={form.consumer}
                    onChange={(event) => set('consumer', event.target.value)}
                    placeholder="Any consumer"
                    disabled={disabled}
                  />
                </label>
                <label className="pmx-field" htmlFor="pwx-provider">
                  <span className="ppx__field-label">Provider (optional)</span>
                  <input
                    id="pwx-provider"
                    className="pmx-input"
                    value={form.provider}
                    onChange={(event) => set('provider', event.target.value)}
                    placeholder="Any provider"
                    disabled={disabled}
                  />
                </label>
              </div>
              <fieldset className="pmx-radios pwx-events" data-testid="pwx-events">
                <legend>Events</legend>
                {EVENT_OPTIONS.map((option) => (
                  <label key={option.name} className="pmx-check" title={option.description}>
                    <input
                      type="checkbox"
                      checked={form.events.includes(option.name)}
                      onChange={(event) => toggleEvent(option.name, event.target.checked)}
                      disabled={disabled}
                    />
                    {option.label}
                  </label>
                ))}
              </fieldset>
              <fieldset className="pmx-radios">
                <legend>Sends to</legend>
                <label className="pmx-check">
                  <input
                    type="radio"
                    name="pwx-kind"
                    checked={form.kind === 'http'}
                    onChange={() => set('kind', 'http')}
                    disabled={disabled}
                  />
                  An HTTP endpoint
                </label>
                <label className="pmx-check">
                  <input
                    type="radio"
                    name="pwx-kind"
                    checked={form.kind === 'github'}
                    onChange={() => set('kind', 'github')}
                    disabled={disabled}
                  />
                  A GitHub Actions workflow (repository_dispatch)
                </label>
              </fieldset>
              {form.kind === 'http' ? (
                <>
                  <div className="pwx-form__row pwx-form__row--url">
                    <label className="pmx-field" htmlFor="pwx-method">
                      <span className="ppx__field-label">Method</span>
                      <select
                        id="pwx-method"
                        className="pmx-input"
                        value={form.method}
                        onChange={(event) => set('method', event.target.value)}
                        disabled={disabled}
                      >
                        {WEBHOOK_METHODS.map((method) => (
                          <option key={method} value={method}>
                            {method}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="pmx-field" htmlFor="pwx-url">
                      <span className="ppx__field-label">URL</span>
                      <input
                        id="pwx-url"
                        className="pmx-input"
                        value={form.url}
                        onChange={(event) => set('url', event.target.value)}
                        placeholder="https://ci.example.com/hooks/verify-pact"
                        disabled={disabled}
                      />
                    </label>
                  </div>
                  <label className="pmx-field" htmlFor="pwx-headers">
                    <span className="ppx__field-label">Headers — one “Name: value” per line</span>
                    <textarea
                      id="pwx-headers"
                      className="pmx-input pwx-textarea"
                      value={form.headers}
                      onChange={(event) => set('headers', event.target.value)}
                      rows={3}
                      spellCheck={false}
                      disabled={disabled}
                    />
                    <span className="ppx__muted">
                      Authorization, tokens, API keys and cookies are stored sealed and read back as {REDACTED}; leave{' '}
                      {REDACTED} to keep the stored value.
                    </span>
                  </label>
                  <label className="pmx-field" htmlFor="pwx-body">
                    <span className="ppx__field-label">Body — JSON is sent as JSON, anything else as text</span>
                    <textarea
                      id="pwx-body"
                      className="pmx-input pwx-textarea"
                      value={form.body}
                      onChange={(event) => set('body', event.target.value)}
                      rows={5}
                      spellCheck={false}
                      disabled={disabled}
                    />
                  </label>
                  <div className="pwx-form__row">
                    <label className="pmx-field" htmlFor="pwx-username">
                      <span className="ppx__field-label">Basic auth username (optional)</span>
                      <input
                        id="pwx-username"
                        className="pmx-input"
                        value={form.username}
                        onChange={(event) => set('username', event.target.value)}
                        autoComplete="off"
                        disabled={disabled}
                      />
                    </label>
                    <SecretField
                      id="pwx-password"
                      label="Password (optional)"
                      value={form.password}
                      onChange={(value) => set('password', value)}
                      disabled={disabled}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="pwx-form__row">
                    <label className="pmx-field" htmlFor="pwx-repository">
                      <span className="ppx__field-label">Repository</span>
                      <input
                        id="pwx-repository"
                        className="pmx-input"
                        value={form.repository}
                        onChange={(event) => set('repository', event.target.value)}
                        placeholder="acme/ledger-api"
                        disabled={disabled}
                      />
                    </label>
                    <label className="pmx-field" htmlFor="pwx-event-type">
                      <span className="ppx__field-label">Event type (optional)</span>
                      <input
                        id="pwx-event-type"
                        className="pmx-input"
                        value={form.eventType}
                        onChange={(event) => set('eventType', event.target.value)}
                        placeholder="${pactbroker.eventName}"
                        disabled={disabled}
                      />
                    </label>
                  </div>
                  <div className="pwx-form__row">
                    <SecretField
                      id="pwx-token"
                      label="GitHub token"
                      value={form.token}
                      onChange={(value) => set('token', value)}
                      placeholder="A token with contents: write"
                      disabled={disabled}
                    />
                    <label className="pmx-field" htmlFor="pwx-api-url">
                      <span className="ppx__field-label">GitHub Enterprise API URL (optional)</span>
                      <input
                        id="pwx-api-url"
                        className="pmx-input"
                        value={form.apiUrl}
                        onChange={(event) => set('apiUrl', event.target.value)}
                        placeholder="https://api.github.com"
                        disabled={disabled}
                      />
                    </label>
                  </div>
                </>
              )}
              <SecretField
                id="pwx-signing"
                label="Signing secret (optional, 16 characters or more)"
                value={form.signingSecret}
                onChange={(value) => set('signingSecret', value)}
                placeholder="Signs each delivery with X-Apiome-Signature"
                disabled={disabled}
              />
              <label className="pmx-check">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(event) => set('enabled', event.target.checked)}
                  disabled={disabled}
                />
                Enabled — fire on its events
              </label>
            </div>
            {problem ? (
              <p className="ppx__muted" data-testid="pwx-editor-problem">
                {problem}
              </p>
            ) : null}
            {error ? (
              <p className="ppx__error" role="alert" data-testid="pwx-editor-error">
                {error}
              </p>
            ) : null}
            {tested ? <TestOutcome result={tested} /> : null}
            <WebhookCommandBlock form={form} webhookId={webhook?.uuid ?? null} />
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={disabled}>
              Cancel
            </Button>
            {onTest ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => void test()}
                disabled={Boolean(problem) || disabled}
                data-testid="pwx-editor-test"
              >
                <Send aria-hidden />
                {busy === 'test' ? 'Testing…' : 'Test'}
              </Button>
            ) : null}
            <Button type="submit" disabled={Boolean(problem) || disabled} data-testid="pwx-editor-save">
              {busy === 'save' ? 'Saving…' : webhook ? 'Save changes' : 'Create webhook'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Confirm deleting a webhook.
 *
 * @param props - The webhook (or `null` when closed), what deleting does and how to close.
 * @returns The confirmation.
 */
export function DeleteWebhookDialog({
  webhook,
  onDelete,
  onClose,
}: {
  webhook: WebhookDocument | null;
  onDelete: (webhook: WebhookDocument) => void;
  onClose: () => void;
}) {
  return (
    <AlertDialog open={webhook !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent data-testid="pwx-delete-confirm">
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {webhook?.description ?? 'webhook'}?</AlertDialogTitle>
          <AlertDialogDescription>
            It stops firing at once. Its queued deliveries, its delivery log and their execution logs are deleted
            with it.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="danger"
            onClick={() => webhook && onDelete(webhook)}
            data-testid="pwx-delete-confirm-action"
          >
            Delete webhook
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
