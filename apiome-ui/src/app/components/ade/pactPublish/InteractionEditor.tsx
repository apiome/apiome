'use client';

/**
 * **Write interactions** — the interaction editor on the Publish page (PFX-8.5, #7302), built to
 * `docs/mockups/contracts/publish-pact.html` (`src-build`):
 *
 * * The pair: consumer and provider. Leaving the provider field reads the provider's spec, state
 *   catalogue and mock scenarios (`/api/pact/publish/provider-spec`).
 * * On the left, the interactions — one Tab stop; ↑ ↓ Home End move and select (a listbox). New
 *   interactions take the kind chosen beside **Add interaction**: HTTP, message, GraphQL or gRPC.
 * * On the right, the selected one: description, provider states with parameters (suggested from
 *   the catalogue and the mock's scenarios), the request — its path matched against the spec,
 *   flagged and never blocked when it is not there — and the response, with **Fill from the spec**
 *   and the body fields as matcher chips.
 *
 * The page turns the draft into a Pact v4 document (`buildPact`) and publishes it as any other.
 */

import * as React from 'react';
import { AlertTriangle, CircleCheck, CircleX, Plus, Trash2, WandSparkles } from 'lucide-react';
import { Badge, Button, Input, Label, MethodChip, Segmented, SegmentedItem, Textarea } from '@/app/components/ui';
import {
  GRPC_NOTE,
  INTERACTION_KINDS,
  KIND_LABELS,
  MAX_INTERACTIONS,
  fillFromSpec,
  listLabel,
  newInteraction,
  specFlag,
  type DraftProblems,
  type EditorDraft,
  type InteractionDraft,
  type InteractionKind,
  type SpecFlag,
} from '@lib/pact-interaction-editor';
import type { ProviderSpec } from '@lib/pact-provider-spec';
import { BodyField, KeyValueRows, MatcherRows, StateRows } from './InteractionFields';

/** The methods the request offers. */
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];

/** Where the provider's spec stands. */
export type SpecState =
  | { status: 'idle' }
  | { status: 'loading'; provider: string }
  | { status: 'ready'; spec: ProviderSpec }
  | { status: 'error'; provider: string; error: string };

/** Props for {@link InteractionEditor}. */
export interface InteractionEditorProps {
  draft: EditorDraft;
  onChange: (draft: EditorDraft) => void;
  /** What stops the draft from being a pact. */
  problems: DraftProblems;
  spec: SpecState;
  /** Read the spec of the provider as typed. */
  onLoadSpec: (provider: string) => void;
  /** Makes a new interaction's id. */
  nextId: () => string;
  /** What reading a pact into the editor could not hold, each with its reason. */
  importNotes: string[];
}

/**
 * The editor.
 *
 * @param props - See {@link InteractionEditorProps}.
 * @returns The editor.
 */
export function InteractionEditor({ draft, onChange, problems, spec, onLoadSpec, nextId, importNotes }: InteractionEditorProps) {
  const [selectedId, setSelectedId] = React.useState<string | null>(draft.interactions[0]?.id ?? null);
  const [kind, setKind] = React.useState<InteractionKind>('http');
  const [fillNote, setFillNote] = React.useState<{ id: string; text: string; tone: 'ok' | 'warn' } | null>(null);
  const listRef = React.useRef<HTMLUListElement>(null);

  const selected = draft.interactions.find((ix) => ix.id === selectedId) ?? draft.interactions[0] ?? null;
  const operations = spec.status === 'ready' && spec.spec.revision ? spec.spec.operations : null;
  const revision = spec.status === 'ready' ? (spec.spec.revision?.label ?? null) : null;
  const suggestions = spec.status === 'ready' ? spec.spec.states : [];

  const update = (id: string, patch: Partial<InteractionDraft>) =>
    onChange({ ...draft, interactions: draft.interactions.map((ix) => (ix.id === id ? { ...ix, ...patch } : ix)) });

  const add = () => {
    if (draft.interactions.length >= MAX_INTERACTIONS) return;
    const ix = newInteraction(nextId(), kind);
    onChange({ ...draft, interactions: [...draft.interactions, ix] });
    setSelectedId(ix.id);
  };

  const remove = (id: string) => {
    const index = draft.interactions.findIndex((ix) => ix.id === id);
    const rest = draft.interactions.filter((ix) => ix.id !== id);
    onChange({ ...draft, interactions: rest });
    setSelectedId(rest[Math.min(index, rest.length - 1)]?.id ?? null);
  };

  /** ↑ ↓ Home End move through the list and select. */
  const onListKey = (event: React.KeyboardEvent<HTMLUListElement>) => {
    const ids = draft.interactions.map((ix) => ix.id);
    if (!ids.length || !selected) return;
    const at = ids.indexOf(selected.id);
    const to = { ArrowDown: Math.min(at + 1, ids.length - 1), ArrowUp: Math.max(at - 1, 0), Home: 0, End: ids.length - 1 }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    setSelectedId(ids[to]);
    listRef.current?.querySelector<HTMLElement>(`[data-ix-id="${ids[to]}"]`)?.focus();
  };

  const fill = (ix: InteractionDraft, flag: SpecFlag) => {
    if (flag.state !== 'match') return;
    const answer = fillFromSpec(ix, flag.operation);
    if ('error' in answer) return setFillNote({ id: ix.id, text: answer.error, tone: 'warn' });
    update(ix.id, answer.patch);
    setFillNote({ id: ix.id, text: answer.note, tone: answer.note.includes('review') ? 'warn' : 'ok' });
  };

  const provider = draft.provider.trim();
  return (
    <div className="ppub-editor" data-testid="ppub-editor">
      <div className="ppub-grid">
        <div className="ppub-field">
          <Label htmlFor="ppub-write-consumer">Consumer</Label>
          <Input
            id="ppub-write-consumer"
            value={draft.consumer}
            maxLength={255}
            placeholder="Orders UI"
            onChange={(event) => onChange({ ...draft, consumer: event.target.value })}
          />
        </div>
        <div className="ppub-field">
          <Label htmlFor="ppub-write-provider">Provider</Label>
          <Input
            id="ppub-write-provider"
            value={draft.provider}
            maxLength={255}
            placeholder="Billing Service"
            aria-describedby="ppub-write-spec"
            onChange={(event) => onChange({ ...draft, provider: event.target.value })}
            onBlur={() => provider && onLoadSpec(provider)}
          />
        </div>
      </div>
      <SpecLine spec={spec} provider={provider} onLoad={() => provider && onLoadSpec(provider)} />
      {importNotes.length ? (
        <details className="ppub-more" data-testid="ppub-import-notes" open>
          <summary>{importNotes.length === 1 ? 'One part of the pasted pact is not in the editor' : `${importNotes.length} parts of the pasted pact are not in the editor`}</summary>
          <ul className="ppub-editor__notes">
            {importNotes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </details>
      ) : null}
      {problems.pair.length && draft.interactions.length ? (
        <p className="ppub-hint ppub-hint--danger" data-testid="ppub-pair-problems">
          {problems.pair.join(' ')}
        </p>
      ) : null}

      <div className="ppub-editor__split">
        <div className="ppub-editor__list">
          <div className="ppub-editor__list-head">
            <span className="ppub-caps" id="ppub-ix-heading">
              Interactions
            </span>
            <Button type="button" variant="ghost" size="sm" aria-label={`Add ${KIND_LABELS[kind]} interaction`} onClick={add} disabled={draft.interactions.length >= MAX_INTERACTIONS} data-testid="ppub-add-interaction">
              <Plus aria-hidden />
            </Button>
          </div>
          <Segmented size="sm" value={kind} onValueChange={(value) => setKind(value as InteractionKind)} aria-label="Kind of new interactions" className="ppub-editor__kinds">
            {INTERACTION_KINDS.map((k) => (
              <SegmentedItem key={k} value={k}>
                {KIND_LABELS[k]}
              </SegmentedItem>
            ))}
          </Segmented>
          {draft.interactions.length ? (
            <ul ref={listRef} role="listbox" aria-labelledby="ppub-ix-heading" className="ppub-editor__items" onKeyDown={onListKey} data-testid="ppub-ix-list">
              {draft.interactions.map((ix) => {
                const label = listLabel(ix);
                const active = ix.id === selected?.id;
                const invalid = Boolean(problems.interactions[ix.id]);
                const flagged = specFlag(ix, operations, revision).state === 'not-in-spec';
                return (
                  <li
                    key={ix.id}
                    role="option"
                    aria-selected={active}
                    tabIndex={active ? 0 : -1}
                    data-ix-id={ix.id}
                    className={`ppub-editor__item${active ? ' is-active' : ''}`}
                    onClick={() => setSelectedId(ix.id)}
                  >
                    {ix.kind === 'http' ? <MethodChip method={label.badge} block={false} /> : <Badge variant="neutral">{label.badge}</Badge>}
                    <span className="ppub-editor__item-title">{label.title}</span>
                    {invalid ? (
                      <>
                        <CircleX aria-hidden className="ppub-ix__glyph ppub-ix__glyph--danger" />
                        <span className="sr-only">, cannot be published yet</span>
                      </>
                    ) : flagged ? (
                      <>
                        <AlertTriangle aria-hidden className="ppub-ix__glyph ppub-ix__glyph--warn" />
                        <span className="sr-only">, not in the spec</span>
                      </>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="ppub-hint ppub-editor__empty">No interactions yet. Choose a kind and press + to add the first.</p>
          )}
        </div>
        <div className="ppub-editor__detail">
          {selected ? (
            <InteractionDetail
              key={selected.id}
              ix={selected}
              index={draft.interactions.indexOf(selected)}
              problems={problems.interactions[selected.id] ?? []}
              flag={specFlag(selected, operations, revision)}
              revision={revision}
              suggestions={suggestions}
              fillNote={fillNote?.id === selected.id ? fillNote : null}
              onChange={(patch) => update(selected.id, patch)}
              onFill={(flag) => fill(selected, flag)}
              onRemove={() => remove(selected.id)}
            />
          ) : (
            <p className="ppub-hint">Add an interaction: what the consumer sends and the answer it needs.</p>
          )}
        </div>
      </div>
    </div>
  );
}

/** Props for {@link SpecLine}. */
interface SpecLineProps {
  spec: SpecState;
  provider: string;
  onLoad: () => void;
}

/**
 * Which spec paths are checked against, or why none is.
 *
 * @param props - See {@link SpecLineProps}.
 * @returns The line.
 */
function SpecLine({ spec, provider, onLoad }: SpecLineProps) {
  let text: string;
  let problems: string[] = [];
  if (spec.status === 'loading') text = `Reading ${spec.provider}’s spec…`;
  else if (spec.status === 'error') text = spec.error;
  else if (spec.status === 'ready') {
    const s = spec.spec;
    const states = s.states.length ? ` · ${s.states.length} provider state${s.states.length === 1 ? '' : 's'} suggested` : '';
    text = s.revision
      ? `Paths are checked against ${s.provider}’s spec, revision ${s.revision.label} (${s.operations.length} operations)${states}.`
      : `${s.provider}’s paths are not checked${states}.`;
    problems = s.problems;
  } else text = provider ? 'Leave the provider field to read its spec.' : 'Name the provider to check paths against its spec and get provider-state suggestions.';
  return (
    <div className="ppub-editor__spec" id="ppub-write-spec" role="status" data-testid="ppub-spec-line">
      <p className={`ppub-hint${spec.status === 'error' ? ' ppub-hint--danger' : ''}`}>
        {text}
        {problems.length ? ` ${problems.join(' ')}` : ''}
      </p>
      {provider && spec.status !== 'loading' ? (
        <Button type="button" variant="link" size="sm" onClick={onLoad}>
          {spec.status === 'idle' ? 'Read the spec' : 'Read it again'}
        </Button>
      ) : null}
    </div>
  );
}

/** Props for {@link InteractionDetail}. */
interface InteractionDetailProps {
  ix: InteractionDraft;
  index: number;
  problems: string[];
  flag: SpecFlag;
  revision: string | null;
  suggestions: ProviderSpec['states'];
  fillNote: { text: string; tone: 'ok' | 'warn' } | null;
  onChange: (patch: Partial<InteractionDraft>) => void;
  onFill: (flag: SpecFlag) => void;
  onRemove: () => void;
}

/**
 * The selected interaction.
 *
 * @param props - See {@link InteractionDetailProps}.
 * @returns The form.
 */
function InteractionDetail({ ix, index, problems, flag, revision, suggestions, fillNote, onChange, onFill, onRemove }: InteractionDetailProps) {
  const id = `ppub-ix-${ix.id}`;
  const http = ix.kind === 'http' || ix.kind === 'graphql';
  const extras = ix.query.length + ix.requestHeaders.length + ix.requestMatchers.length + (ix.requestBody.text.trim() ? 1 : 0);
  return (
    <div className="ppub-editor__form" data-testid="ppub-ix-detail">
      <div className="ppub-editor__form-head">
        <Badge variant="neutral">{KIND_LABELS[ix.kind]}</Badge>
        <span className="ppub-hint">Interaction {index + 1}</span>
        <Button type="button" variant="ghost" size="sm" onClick={onRemove} className="ppub-editor__remove">
          <Trash2 aria-hidden />
          Remove interaction
        </Button>
      </div>
      {problems.length ? (
        <ul className="ppub-editor__problems" aria-label="What stops this interaction from being published" data-testid="ppub-ix-problems">
          {problems.map((problem, i) => (
            <li key={i}>{problem}</li>
          ))}
        </ul>
      ) : null}
      <div className="ppub-field">
        <Label htmlFor={`${id}-description`}>Description</Label>
        <Input id={`${id}-description`} value={ix.description} placeholder="get invoice 42" onChange={(event) => onChange({ description: event.target.value })} />
      </div>
      <div className="ppub-field">
        <span className="ppub-field__label">
          Provider state <span className="ppub-hint">(what must be true first)</span>
        </span>
        <StateRows idPrefix={id} states={ix.states} suggestions={suggestions} onChange={(states) => onChange({ states })} />
        <p className="ppub-hint">Suggestions come from the provider’s state catalogue and the mock’s scenarios.</p>
      </div>

      {ix.kind === 'message' ? (
        <section className="ppub-editor__section" aria-labelledby={`${id}-message`}>
          <h3 className="ppub-caps" id={`${id}-message`}>
            Message
          </h3>
          <BodyField idPrefix={`${id}-contents`} label="Contents" body={ix.responseBody} onChange={(responseBody) => onChange({ responseBody })} />
          <span className="ppub-field__label">Metadata</span>
          <KeyValueRows idPrefix={`${id}-metadata`} noun="Metadata" rows={ix.metadata} onChange={(metadata) => onChange({ metadata })} />
          <span className="ppub-field__label">Fields the consumer relies on</span>
          <MatcherRows
            idPrefix={`${id}-contents`}
            side="message"
            matchers={ix.responseMatchers}
            onChange={(responseMatchers, responseBody) => onChange({ responseMatchers, ...(responseBody ? { responseBody } : {}) })}
            body={ix.responseBody}
          />
        </section>
      ) : null}

      {ix.kind === 'grpc' ? (
        <section className="ppub-editor__section" aria-labelledby={`${id}-call`}>
          <h3 className="ppub-caps" id={`${id}-call`}>
            Call
          </h3>
          <div className="ppub-field">
            <Label htmlFor={`${id}-service`}>Service and method</Label>
            <Input id={`${id}-service`} className="ppx__mono" value={ix.service} placeholder="billing.Invoices/GetInvoice" onChange={(event) => onChange({ service: event.target.value })} />
          </div>
          <BodyField idPrefix={`${id}-grpc-request`} label="Request message" body={ix.requestBody} onChange={(requestBody) => onChange({ requestBody })} rows={4} />
          <BodyField idPrefix={`${id}-grpc-reply`} label="Reply" body={ix.responseBody} onChange={(responseBody) => onChange({ responseBody })} />
          <span className="ppub-field__label">Fields the consumer relies on</span>
          <MatcherRows
            idPrefix={`${id}-reply`}
            side="reply"
            matchers={ix.responseMatchers}
            onChange={(responseMatchers, responseBody) => onChange({ responseMatchers, ...(responseBody ? { responseBody } : {}) })}
            body={ix.responseBody}
          />
          {ix.requestMatchers.length ? (
            <>
              <span className="ppub-field__label">Request fields</span>
              <MatcherRows idPrefix={`${id}-grpc-req`} side="request" matchers={ix.requestMatchers} onChange={(requestMatchers) => onChange({ requestMatchers })} />
            </>
          ) : null}
          <p className="ppub-hint" data-testid="ppub-grpc-note">
            {GRPC_NOTE}
          </p>
        </section>
      ) : null}

      {http ? (
        <section className="ppub-editor__section" aria-labelledby={`${id}-request`}>
          <h3 className="ppub-caps" id={`${id}-request`}>
            Request
          </h3>
          <div className="ppub-editor__line">
            <select
              className="ppub-select ppub-editor__method"
              aria-label="Method"
              value={ix.method}
              disabled={ix.kind === 'graphql'}
              onChange={(event) => onChange({ method: event.target.value })}
            >
              {(METHODS.includes(ix.method) ? METHODS : [ix.method, ...METHODS]).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <Input className="ppx__mono" aria-label="Path" value={ix.path} placeholder="/invoices/42" onChange={(event) => onChange({ path: event.target.value })} />
          </div>
          <FlagLine flag={flag} revision={revision} />
          {ix.kind === 'graphql' ? (
            <>
              <div className="ppub-field">
                <Label htmlFor={`${id}-gql`}>Operation</Label>
                <Textarea
                  id={`${id}-gql`}
                  className="ppx__mono ppub-editor__code"
                  rows={5}
                  spellCheck={false}
                  value={ix.graphqlQuery}
                  placeholder="query Invoice($id: ID!) { invoice(id: $id) { id amount } }"
                  onChange={(event) => onChange({ graphqlQuery: event.target.value })}
                />
              </div>
              <div className="ppub-grid">
                <div className="ppub-field">
                  <Label htmlFor={`${id}-gql-vars`}>Variables (JSON, optional)</Label>
                  <Textarea id={`${id}-gql-vars`} className="ppx__mono" rows={3} value={ix.graphqlVariables} onChange={(event) => onChange({ graphqlVariables: event.target.value })} />
                </div>
                <div className="ppub-field">
                  <Label htmlFor={`${id}-gql-op`}>Operation name (optional)</Label>
                  <Input id={`${id}-gql-op`} className="ppx__mono" value={ix.operationName} onChange={(event) => onChange({ operationName: event.target.value })} />
                </div>
              </div>
            </>
          ) : null}
          <details className="ppub-more" open={extras > 0 ? true : undefined}>
            <summary>{ix.kind === 'graphql' ? 'Headers' : 'Headers, query and body'}{extras ? ` (${extras})` : ''}</summary>
            <div className="ppub-more__body">
              <span className="ppub-field__label">Headers</span>
              <KeyValueRows idPrefix={`${id}-req-headers`} noun="Header" rows={ix.requestHeaders} onChange={(requestHeaders) => onChange({ requestHeaders })} />
              {ix.kind === 'http' ? (
                <>
                  <span className="ppub-field__label">Query</span>
                  <KeyValueRows idPrefix={`${id}-query`} noun="Query parameter" rows={ix.query} onChange={(query) => onChange({ query })} />
                  <BodyField idPrefix={`${id}-req`} label="Request body" body={ix.requestBody} onChange={(requestBody) => onChange({ requestBody })} rows={4} />
                  <span className="ppub-field__label">Request fields</span>
                  <MatcherRows
                    idPrefix={`${id}-req`}
                    side="request"
                    matchers={ix.requestMatchers}
                    onChange={(requestMatchers, requestBody) => onChange({ requestMatchers, ...(requestBody ? { requestBody } : {}) })}
                    body={ix.requestBody}
                  />
                </>
              ) : null}
            </div>
          </details>
        </section>
      ) : null}

      {http ? (
        <section className="ppub-editor__section" aria-labelledby={`${id}-response`}>
          <div className="ppub-editor__section-head">
            <h3 className="ppub-caps" id={`${id}-response`}>
              Response
            </h3>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onFill(flag)}
              disabled={flag.state !== 'match'}
              title={flag.state === 'match' ? undefined : 'Available when the path is in the provider’s spec'}
              data-testid="ppub-fill-from-spec"
            >
              <WandSparkles aria-hidden />
              Fill from the spec
            </Button>
          </div>
          {fillNote ? (
            <p className={`ppub-hint${fillNote.tone === 'warn' ? ' ppub-editor__warn' : ''}`} role="status" data-testid="ppub-fill-note">
              {fillNote.text}
            </p>
          ) : null}
          <div className="ppub-editor__line">
            <Label htmlFor={`${id}-status`}>Status</Label>
            <Input id={`${id}-status`} className="ppx__mono ppub-editor__status" inputMode="numeric" value={ix.status} onChange={(event) => onChange({ status: event.target.value })} />
          </div>
          <span className="ppub-field__label">Headers</span>
          <KeyValueRows idPrefix={`${id}-res-headers`} noun="Response header" rows={ix.responseHeaders} onChange={(responseHeaders) => onChange({ responseHeaders })} />
          <BodyField idPrefix={`${id}-res`} label="Response body" body={ix.responseBody} onChange={(responseBody) => onChange({ responseBody })} />
          <span className="ppub-field__label">Fields the consumer relies on</span>
          <MatcherRows
            idPrefix={`${id}-res`}
            side="response"
            matchers={ix.responseMatchers}
            onChange={(responseMatchers, responseBody) => onChange({ responseMatchers, ...(responseBody ? { responseBody } : {}) })}
            body={ix.responseBody}
          />
        </section>
      ) : null}
    </div>
  );
}

/**
 * The spec's word on the request: matched, flagged, or not checked.
 *
 * @param props - The flag and the revision.
 * @returns The line.
 */
function FlagLine({ flag, revision }: { flag: SpecFlag; revision: string | null }) {
  if (flag.state === 'match') {
    return (
      <p className="ppub-hint ppub-editor__flag" data-testid="ppub-spec-flag" data-state="match">
        <CircleCheck aria-hidden className="ppub-ix__glyph ppub-ix__glyph--ok" />
        Matches <span className="ppx__mono">{flag.operation.method} {flag.operation.path}</span>
        {revision ? ` in revision ${revision}` : ''}.
      </p>
    );
  }
  return (
    <p className={`ppub-hint ppub-editor__flag${flag.state === 'not-in-spec' ? ' ppub-editor__warn' : ''}`} data-testid="ppub-spec-flag" data-state={flag.state}>
      {flag.state === 'not-in-spec' ? <AlertTriangle aria-hidden className="ppub-ix__glyph ppub-ix__glyph--warn" /> : null}
      {flag.message}
    </p>
  );
}
