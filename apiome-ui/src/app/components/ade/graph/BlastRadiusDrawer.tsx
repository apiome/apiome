'use client';

/**
 * The **Blast radius** drawer (CDG-3.4, #5969): runs the CDG-3.3 query for a picked operation or
 * schema of a project or catalog item and lists who is affected — direct, then transitive, each
 * with its owner team and how it is reached — and the evidence the change invalidates, with links.
 *
 * An empty answer says so in words ("Nothing depends on this change"), because REST checked the
 * evidence rather than skipped it. A truncated answer says how much it shows.
 */

import * as React from 'react';
import Link from 'next/link';
import { Radar } from 'lucide-react';
import {
  Badge,
  Button,
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
  ErrorState,
  Input,
  Label,
  LoadingState,
} from '@/app/components/ui';
import {
  BLAST_RADIUS_MAX_NODES,
  EDGE_KIND_LABELS,
  EVIDENCE_LABELS,
  EVIDENCE_SECTIONS,
  GRAPH_PROVENANCES,
  NODE_KIND_LABELS,
  PROVENANCE_LABELS,
  evidenceItem,
  graphNodeHref,
  nodeDisplayName,
  operationPointer,
  schemaPointer,
  truncationNotice,
  type AffectedEntity,
  type BlastRadiusAnswer,
  type GraphNodeKind,
  type GraphProvenance,
} from '@lib/graph';
import { GraphOwnerBadge } from './GraphOwnerBadge';
import { runBlastRadius } from './graphApi';

export interface BlastRadiusDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The project or catalog item that changes. */
  entity: { kind: GraphNodeKind; id: string; name: string };
}

type ChangeMode = 'operation' | 'schema' | 'whole';

/** The change as a list of pointers, or the reason it can't be one. */
export function changePointers(mode: ChangeMode, value: string): { pointers: string[] } | { error: string } {
  if (mode === 'whole') return { pointers: [] };
  const pointer = mode === 'operation' ? operationPointer(value) : schemaPointer(value);
  if (!pointer) {
    return {
      error: mode === 'operation' ? 'Type an operation as METHOD /path, e.g. GET /pets/{id}.' : 'Type a schema name, e.g. Pet.',
    };
  }
  return { pointers: [pointer] };
}

function AffectedList({ title, entities, testId }: { title: string; entities: AffectedEntity[]; testId: string }) {
  return (
    <section className="dg-blast__section" aria-labelledby={`${testId}-title`} data-testid={testId}>
      <h3 id={`${testId}-title`} className="dg-blast__heading">
        {title} <span className="dg-group__count">{entities.length}</span>
      </h3>
      {entities.length === 0 ? (
        <p className="dg-blast__none">None.</p>
      ) : (
        <ul className="dg-edges">
          {entities.map((entity) => (
            <li key={entity.id} className="dg-edge" data-testid={`blast-entity-${entity.id}`}>
              <span className="dg-edge__kind">{NODE_KIND_LABELS[entity.kind]}</span>
              <Link href={graphNodeHref(entity.kind, entity.id)} className="dg-edge__name">
                {nodeDisplayName(entity.kind, entity.id, entity)}
              </Link>
              <span className="dg-edge__via">
                {EDGE_KIND_LABELS[entity.edge_kind].out.toLowerCase()} · depth {entity.depth}
              </span>
              <Badge variant="neutral" data-provenance={entity.provenance}>
                {PROVENANCE_LABELS[entity.provenance]}
              </Badge>
              <GraphOwnerBadge owner={entity.owner} testId={`blast-owner-${entity.id}`} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function BlastRadiusDrawer({ open, onOpenChange, entity }: BlastRadiusDrawerProps) {
  const [mode, setMode] = React.useState<ChangeMode>('operation');
  const [value, setValue] = React.useState('');
  const [depth, setDepth] = React.useState(3);
  const [provenance, setProvenance] = React.useState<GraphProvenance[]>([...GRAPH_PROVENANCES]);
  const [state, setState] = React.useState<{ status: 'idle' | 'running' | 'done' | 'error'; error?: string }>({
    status: 'idle',
  });
  const [answer, setAnswer] = React.useState<BlastRadiusAnswer | null>(null);
  const [inputError, setInputError] = React.useState<string | null>(null);
  const valueId = React.useId();

  const run = async (event: React.FormEvent) => {
    event.preventDefault();
    const change = changePointers(mode, value);
    if ('error' in change) {
      setInputError(change.error);
      return;
    }
    if (provenance.length === 0) {
      setInputError('Pick at least one kind of edge to follow.');
      return;
    }
    setInputError(null);
    setState({ status: 'running' });
    try {
      setAnswer(
        await runBlastRadius({ entity: { kind: entity.kind, id: entity.id }, pointers: change.pointers, depth, provenance })
      );
      setState({ status: 'done' });
    } catch (caught) {
      setState({ status: 'error', error: caught instanceof Error ? caught.message : String(caught) });
    }
  };

  const toggleProvenance = (value: GraphProvenance) =>
    setProvenance((current) => (current.includes(value) ? current.filter((p) => p !== value) : [...current, value]));

  const affectedCount = answer ? answer.direct.length + answer.transitive.length : 0;
  const notice = answer
    ? truncationNotice(answer.node_count, answer.total_found > answer.node_count ? answer.total_found : null, answer.truncated, {
        atLeast: answer.node_count >= BLAST_RADIUS_MAX_NODES,
      })
    : null;
  const evidenceTotal = answer
    ? EVIDENCE_SECTIONS.reduce((sum, key) => sum + (answer.invalidated_evidence[key]?.length ?? 0), 0)
    : 0;

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent size="lg" data-testid="blast-radius-drawer">
        <DrawerHeader>
          <DrawerTitle className="dg-blast__title">
            <Radar aria-hidden />
            Blast radius
          </DrawerTitle>
          <DrawerDescription>What a change to {entity.name} affects, and the evidence it invalidates.</DrawerDescription>
        </DrawerHeader>
        <DrawerBody className="dg-blast">
          <form className="dg-blast__form" onSubmit={run} aria-label="The change">
            <fieldset className="dg-blast__modes">
              <legend className="dg-blast__legend">What changes</legend>
              {(
                [
                  ['operation', 'An operation'],
                  ['schema', 'A schema'],
                  ['whole', 'The whole API'],
                ] as const
              ).map(([key, text]) => (
                <label key={key} className="dg-blast__mode">
                  <input
                    type="radio"
                    name="blast-mode"
                    value={key}
                    checked={mode === key}
                    onChange={() => setMode(key)}
                  />
                  {text}
                </label>
              ))}
            </fieldset>
            {mode !== 'whole' ? (
              <div className="dg-blast__field">
                <Label htmlFor={valueId}>{mode === 'operation' ? 'Operation' : 'Schema name'}</Label>
                <Input
                  id={valueId}
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  placeholder={mode === 'operation' ? 'GET /pets/{id}' : 'Pet'}
                  aria-invalid={inputError ? true : undefined}
                  aria-describedby={inputError ? `${valueId}-error` : undefined}
                  data-testid="blast-radius-value"
                />
              </div>
            ) : null}
            <div className="dg-blast__options">
              <label className="dg-blast__depth">
                Depth
                <select value={depth} onChange={(event) => setDepth(Number(event.target.value))} data-testid="blast-radius-depth">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset className="dg-blast__provenance">
                <legend className="dg-blast__legend">Follow</legend>
                {GRAPH_PROVENANCES.map((p) => (
                  <label key={p} className="dg-blast__mode">
                    <input type="checkbox" checked={provenance.includes(p)} onChange={() => toggleProvenance(p)} />
                    {PROVENANCE_LABELS[p]}
                  </label>
                ))}
              </fieldset>
            </div>
            {inputError ? (
              <p id={`${valueId}-error`} className="dg-blast__error" role="alert">
                {inputError}
              </p>
            ) : null}
            <Button type="submit" disabled={state.status === 'running'} data-testid="blast-radius-run">
              Show the blast radius
            </Button>
          </form>

          {state.status === 'running' ? <LoadingState message="Working out the blast radius" /> : null}
          {state.status === 'error' ? <ErrorState title="The blast radius could not be worked out" description={state.error} /> : null}
          {state.status === 'done' && answer ? (
            <div className="dg-blast__answer" data-testid="blast-radius-answer">
              <p className="dg-blast__summary" role="status">
                {affectedCount === 0 && evidenceTotal === 0 && answer.evidence_checked
                  ? 'Nothing depends on this change, and no evidence is invalidated.'
                  : `${affectedCount} affected · ${evidenceTotal} pieces of evidence invalidated`}
                {answer.version?.label ? ` · version ${answer.version.label}` : ''}
              </p>
              {notice ? (
                <p className="dg-notice" data-testid="blast-radius-truncated">
                  {notice}
                </p>
              ) : null}
              {answer.warnings.map((warning) => (
                <p key={warning} className="dg-notice">
                  {warning}
                </p>
              ))}
              <AffectedList title="Direct" entities={answer.direct} testId="blast-radius-direct" />
              <AffectedList title="Transitive" entities={answer.transitive} testId="blast-radius-transitive" />
              <section className="dg-blast__section" aria-labelledby="blast-evidence-title" data-testid="blast-radius-evidence">
                <h3 id="blast-evidence-title" className="dg-blast__heading">
                  Invalidated evidence
                </h3>
                <dl className="dg-evidence">
                  {EVIDENCE_SECTIONS.map((section) => {
                    const rows = answer.invalidated_evidence[section] ?? [];
                    return (
                      <div key={section} className="dg-evidence__row" data-testid={`blast-evidence-${section}`}>
                        <dt className="dg-evidence__label">
                          {EVIDENCE_LABELS[section]} <span className="dg-group__count">{rows.length}</span>
                        </dt>
                        <dd className="dg-evidence__items">
                          {rows.length === 0 ? (
                            <span className="dg-blast__none">None.</span>
                          ) : (
                            <ul>
                              {rows.map((row) => {
                                const item = evidenceItem(section, row, entity.id);
                                return (
                                  <li key={item.key} className="dg-evidence__item">
                                    {item.href ? <Link href={item.href}>{item.title}</Link> : <span>{item.title}</span>}
                                    {item.detail ? <span className="dg-evidence__detail">{item.detail}</span> : null}
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </section>
            </div>
          ) : null}
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
