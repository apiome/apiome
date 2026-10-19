'use client';

import * as React from 'react';
import { Plus, Trash2 } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/app/components/ui/Drawer';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Spinner } from '@/app/components/ui/Spinner';

import {
  BINDING_KINDS,
  BINDING_KIND_LABEL,
  BINDING_NAME_LABEL,
  BINDING_NAME_PLACEHOLDER,
  EMPTY_BINDING_DRAFT,
  bindingDraftProblem,
  bindingMetaLine,
  bindingNeedsValue,
  callsLabel,
  runtimeSummaryLine,
  type BindingDraft,
  type BindingKind,
  type ConsumerBinding,
  type ConsumerRuntime,
  type RuntimeOperation,
} from './bindingsModel';
import { operationLabel, type ConsumerSummary } from './consumersModel';

/**
 * A consumer's bindings and its declared-versus-observed traffic — RDG-1.8 (#5765).
 *
 * Two halves, top to bottom:
 *
 * 1. **Bindings** — how the usage index recognises this consumer in traffic. A header, API-key or
 *    JWT-claim value is typed once; the server hashes it before storing it and never shows it
 *    again, so the list shows the name and when it last matched, never the value.
 * 2. **Declared vs observed** — the consumer's contract next to what its bindings show it calls,
 *    over the last 30 days. A **used, undeclared** operation is the edge a breaking-change check
 *    would otherwise miss, so it is listed first and carries **Add to contract**.
 *
 * The drawer reads both when it opens (and after every write) through the callbacks it is given,
 * so it never holds a stale list.
 */

/** Props for {@link ConsumerBindingsDrawer}. */
export interface ConsumerBindingsDrawerProps {
  /** Whether the drawer is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /** The row being inspected; `null` while closed. */
  summary: ConsumerSummary | null;
  /** Read the consumer's live bindings. */
  loadBindings: (consumerSlug: string) => Promise<ConsumerBinding[]>;
  /** Read the consumer's runtime report. */
  loadRuntime: (consumerSlug: string) => Promise<ConsumerRuntime>;
  /** Create a binding; resolves to an error sentence, or `null` on success. */
  onCreate: (consumerSlug: string, draft: BindingDraft) => Promise<string | null>;
  /** Delete a binding; resolves to an error sentence, or `null` on success. */
  onDelete: (consumerSlug: string, binding: ConsumerBinding) => Promise<string | null>;
  /** Add an observed operation to the contract; resolves to an error sentence, or `null`. */
  onAddToContract: (summary: ConsumerSummary, operation: RuntimeOperation) => Promise<string | null>;
  /** The caller holds `consumer_contracts:create`. */
  canCreate: boolean;
  /** The caller holds `consumer_contracts:delete`. */
  canDelete: boolean;
  /** The caller holds `consumer_contracts:edit`. */
  canEdit: boolean;
}

/** What the drawer has read. */
interface DrawerData {
  bindings: ConsumerBinding[];
  runtime: ConsumerRuntime | null;
}

/**
 * One side of the comparison.
 *
 * @param props The heading, the tone, the operations, and the optional row action.
 * @returns The section, or nothing when it is empty and `hideEmpty` is set.
 */
function RuntimeSide({
  heading,
  tone,
  testId,
  operations,
  empty,
  action,
}: {
  heading: string;
  tone: 'ok' | 'warn' | 'neutral';
  testId: string;
  operations: RuntimeOperation[];
  empty: string;
  action?: (operation: RuntimeOperation) => React.ReactNode;
}) {
  return (
    <div className="cns-runtime__side" data-testid={testId}>
      <h4 className="cns-drawer__grouphead">
        {heading}
        <span className="cns-drawer__count">{operations.length}</span>
      </h4>
      {operations.length === 0 ? (
        <p className="cns-drawer__empty">{empty}</p>
      ) : (
        <ul className="cns-runtime__ops">
          {operations.map((operation) => (
            <li className="cns-runtime__op" key={operation.operation_key}>
              <code className="mono cns-runtime__label">{operationLabel(operation)}</code>
              <span className="cns-runtime__meta">
                {operation.calls > 0 ? (
                  <Badge variant={tone}>{callsLabel(operation.calls)}</Badge>
                ) : (
                  <Badge variant="neutral">No calls</Badge>
                )}
                {operation.last_seen_day && <span>last {operation.last_seen_day}</span>}
              </span>
              {action?.(operation)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The bindings and runtime drawer.
 *
 * @param props See {@link ConsumerBindingsDrawerProps}.
 * @returns The drawer.
 */
export default function ConsumerBindingsDrawer({
  open,
  onOpenChange,
  summary,
  loadBindings,
  loadRuntime,
  onCreate,
  onDelete,
  onAddToContract,
  canCreate,
  canDelete,
  canEdit,
}: ConsumerBindingsDrawerProps) {
  const slug = summary?.consumer.slug ?? null;
  const [data, setData] = React.useState<DrawerData>({ bindings: [], runtime: null });
  const [loading, setLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState('');
  const [draft, setDraft] = React.useState<BindingDraft>(EMPTY_BINDING_DRAFT);
  const [formError, setFormError] = React.useState('');
  const [busy, setBusy] = React.useState<string | null>(null);

  const reload = React.useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    setLoadError('');
    try {
      const [bindings, runtime] = await Promise.all([loadBindings(slug), loadRuntime(slug)]);
      setData({ bindings, runtime });
    } catch (error) {
      setLoadError(error instanceof Error && error.message ? error.message : "Couldn't read this consumer's traffic");
    } finally {
      setLoading(false);
    }
  }, [slug, loadBindings, loadRuntime]);

  React.useEffect(() => {
    if (!open || !slug) return;
    setDraft(EMPTY_BINDING_DRAFT);
    setFormError('');
    void reload();
  }, [open, slug, reload]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!slug) return;
    const problem = bindingDraftProblem(draft);
    if (problem) {
      setFormError(problem);
      return;
    }
    setBusy('create');
    const error = await onCreate(slug, draft);
    setBusy(null);
    if (error) {
      setFormError(error);
      return;
    }
    setDraft({ ...EMPTY_BINDING_DRAFT, kind: draft.kind });
    setFormError('');
    await reload();
  };

  const remove = async (binding: ConsumerBinding) => {
    if (!slug) return;
    setBusy(binding.id);
    const error = await onDelete(slug, binding);
    setBusy(null);
    if (error) setLoadError(error);
    else await reload();
  };

  const add = async (operation: RuntimeOperation) => {
    if (!summary) return;
    setBusy(operation.operation_key);
    const error = await onAddToContract(summary, operation);
    setBusy(null);
    if (error) setLoadError(error);
    else await reload();
  };

  const runtime = data.runtime;
  const needsValue = bindingNeedsValue(draft.kind);

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent size="lg" data-testid="consumer-bindings-drawer">
        <DrawerHeader>
          <DrawerTitle>{summary?.consumer.name ?? 'Consumer'} · traffic</DrawerTitle>
          <DrawerDescription>
            How usage traffic is attributed to this consumer, and what it calls next to what it
            declares.
          </DrawerDescription>
        </DrawerHeader>

        <DrawerBody>
          {loadError && <Alert variant="danger">{loadError}</Alert>}

          <section className="cns-drawer__section" data-testid="consumer-bindings">
            <h3 className="cns-drawer__heading">Bindings</h3>
            {loading && data.bindings.length === 0 ? (
              <p className="cns-drawer__empty">
                <Spinner aria-hidden="true" /> Loading…
              </p>
            ) : data.bindings.length === 0 ? (
              <p className="cns-drawer__empty">
                No bindings yet. Until one matches, this consumer&apos;s calls are counted as
                anonymous.
              </p>
            ) : (
              <ul className="cns-bindings__list">
                {data.bindings.map((binding) => (
                  <li className="cns-bindings__item" key={binding.id}>
                    <Badge variant="neutral">{BINDING_KIND_LABEL[binding.kind] ?? binding.kind}</Badge>
                    <span className="cns-bindings__name">
                      <code className="mono">{binding.name}</code>
                      <span className="cns-bindings__meta">{bindingMetaLine(binding)}</span>
                    </span>
                    {canDelete && (
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete binding ${binding.name}`}
                        disabled={busy !== null}
                        onClick={() => void remove(binding)}
                      >
                        <Trash2 aria-hidden="true" />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {canCreate && (
              <form className="cns-bindings__form" onSubmit={submit} data-testid="binding-form" noValidate>
                <div className="cns-form__field">
                  <Label htmlFor="binding-kind">Kind</Label>
                  <select
                    id="binding-kind"
                    className="hive-control cns-bindings__select"
                    value={draft.kind}
                    onChange={(event) =>
                      setDraft({ kind: event.target.value as BindingKind, name: '', value: '' })
                    }
                  >
                    {BINDING_KINDS.map((kind) => (
                      <option key={kind} value={kind}>
                        {BINDING_KIND_LABEL[kind]}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="cns-form__field">
                  <Label htmlFor="binding-name">{BINDING_NAME_LABEL[draft.kind]}</Label>
                  <Input
                    id="binding-name"
                    value={draft.name}
                    placeholder={BINDING_NAME_PLACEHOLDER[draft.kind]}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                  />
                </div>
                {needsValue && (
                  <div className="cns-form__field">
                    <Label htmlFor="binding-value">Value</Label>
                    <Input
                      id="binding-value"
                      type="password"
                      value={draft.value}
                      autoComplete="off"
                      onChange={(event) => setDraft({ ...draft, value: event.target.value })}
                    />
                  </div>
                )}
                <p className="cns-form__hint cns-bindings__hint">
                  {needsValue
                    ? "The value is hashed before it's stored and can't be shown again."
                    : 'Use * and ? as wildcards. Matching ignores case.'}
                </p>
                {formError && <Alert variant="danger">{formError}</Alert>}
                <div className="cns-bindings__actions">
                  <Button type="submit" size="sm" disabled={busy !== null}>
                    {busy === 'create' ? <Spinner aria-hidden="true" /> : <Plus aria-hidden="true" />}
                    Add binding
                  </Button>
                </div>
              </form>
            )}
          </section>

          <section className="cns-drawer__section" data-testid="consumer-runtime">
            <h3 className="cns-drawer__heading">
              Declared vs observed
              {runtime && (
                <span className="cns-runtime__window">
                  {' '}
                  · {runtime.since_day} to {runtime.until_day}
                </span>
              )}
            </h3>
            {runtime && <p className="cns-drawer__summary">{runtimeSummaryLine(runtime.summary)}</p>}
            {runtime && (
              <div className="cns-runtime">
                <RuntimeSide
                  heading="Used, undeclared"
                  tone="warn"
                  testId="runtime-used-undeclared"
                  operations={runtime.used_undeclared}
                  empty="Nothing called outside the contract."
                  action={
                    canEdit
                      ? (operation) => (
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={busy !== null}
                            onClick={() => void add(operation)}
                          >
                            {busy === operation.operation_key && <Spinner aria-hidden="true" />}
                            Add to contract
                          </Button>
                        )
                      : undefined
                  }
                />
                <RuntimeSide
                  heading="Declared and used"
                  tone="ok"
                  testId="runtime-declared-used"
                  operations={runtime.declared_and_used}
                  empty={
                    runtime.contract_state === 'declared'
                      ? 'No declared operation was called in this window.'
                      : 'This consumer has declared nothing yet.'
                  }
                />
                <RuntimeSide
                  heading="Declared, unused"
                  tone="neutral"
                  testId="runtime-declared-unused"
                  operations={runtime.declared_unused}
                  empty="Every declared operation was called."
                />
              </div>
            )}
          </section>
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
