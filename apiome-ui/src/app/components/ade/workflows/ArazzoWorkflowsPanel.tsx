'use client';

/**
 * The **Workflows** tab (COA-1.3, #7039).
 *
 * Reads an Arazzo document's persisted workflows — for a catalog item through
 * `/api/workflows/catalog/{itemId}`, for a project revision through
 * `/api/workflows/versions/{versionId}` — and shows them as flows rather than as a file:
 *
 * - a list of the workflows, each with its source-description status;
 * - for the selected workflow, its inputs and outputs, its steps in order (each naming the
 *   operation it calls) and a step graph of the success/failure routing;
 * - a step drawer, opened from a step row or a graph node, that opens the operation the step
 *   calls.
 *
 * The read is lazy: nothing is fetched until the tab is first shown (`active`), and it is not
 * re-fetched on every return to the tab. Loading, empty and error states replace the content
 * so a slow or failed read never blanks the surrounding page.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GitBranch, Workflow } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import ArazzoStepDrawer from './ArazzoStepDrawer';
import ArazzoStepGraph from './ArazzoStepGraph';
import {
  SOURCE_STATUS_LABEL,
  formatArazzoValue,
  inputsReference,
  parseArazzoWorkflows,
  sourceStatusTone,
  stepTargetLabel,
  workflowInputFields,
  type ArazzoSourceView,
  type ArazzoWorkflowView,
  type ArazzoWorkflowsView,
} from './arazzoWorkflowModel';

export interface ArazzoWorkflowsPanelProps {
  /** The `/api/workflows/...` URL to read, or `null` when there is nothing to read yet. */
  endpoint: string | null;
  /** True while the tab is shown; the first `true` triggers the read. */
  active: boolean;
  /** Told the workflow count once the read succeeds (for a tab count chip). */
  onLoaded?: (count: number) => void;
}

/** The status badges for a workflow's sources. */
function SourceStatusList({ sources }: { sources: ArazzoSourceView[] }) {
  if (sources.length === 0) {
    return <p className="awf-muted">This workflow declares no source descriptions.</p>;
  }
  return (
    <ul className="awf-sources" aria-label="Source descriptions">
      {sources.map((source) => (
        <li key={source.name} className="awf-sources__item" data-testid={`awf-source-${source.name}`}>
          <span className="mono awf-sources__name">{source.name}</span>
          <Badge variant={sourceStatusTone(source.status)} data-status-kind={source.status}>
            {SOURCE_STATUS_LABEL[source.status]}
          </Badge>
          {source.status === 'resolved' && source.tier ? (
            <span className="awf-muted">from {source.tier}</span>
          ) : null}
          {source.status === 'missing' && source.reason ? (
            <span className="awf-muted mono" title={source.detail ?? undefined}>
              {source.reason}
            </span>
          ) : null}
          {source.url ? <span className="awf-muted mono awf-sources__url">{source.url}</span> : null}
        </li>
      ))}
    </ul>
  );
}

/** The workflow's inputs (from its JSON Schema) and outputs (name → runtime expression). */
function InputsOutputs({ workflow }: { workflow: ArazzoWorkflowView }) {
  const fields = workflowInputFields(workflow.inputs);
  const reference = inputsReference(workflow.inputs);
  const outputs = Object.entries(workflow.outputs);
  return (
    <div className="awf-io">
      <section aria-labelledby={`awf-inputs-${workflow.workflowId}`}>
        <h4 id={`awf-inputs-${workflow.workflowId}`} className="awf-subheading">
          Inputs
        </h4>
        {fields.length > 0 ? (
          <table className="awf-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Required</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr key={field.name}>
                  <td className="mono">{field.name}</td>
                  <td className="mono">{field.type ?? '—'}</td>
                  <td>{field.required ? 'Yes' : 'No'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : reference ? (
          <p className="awf-muted">
            Defined by <span className="mono">{reference}</span>
          </p>
        ) : (
          <p className="awf-muted">No inputs.</p>
        )}
      </section>
      <section aria-labelledby={`awf-outputs-${workflow.workflowId}`}>
        <h4 id={`awf-outputs-${workflow.workflowId}`} className="awf-subheading">
          Outputs
        </h4>
        {outputs.length > 0 ? (
          <table className="awf-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Value</th>
              </tr>
            </thead>
            <tbody>
              {outputs.map(([name, value]) => (
                <tr key={name}>
                  <td className="mono">{name}</td>
                  <td className="mono">{formatArazzoValue(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="awf-muted">No outputs.</p>
        )}
      </section>
    </div>
  );
}

/**
 * The Workflows tab body.
 *
 * @param props See {@link ArazzoWorkflowsPanelProps}.
 * @returns The workflow list, the selected workflow's steps and graph, and the step drawer.
 */
export default function ArazzoWorkflowsPanel({ endpoint, active, onLoaded }: ArazzoWorkflowsPanelProps) {
  const [data, setData] = useState<ArazzoWorkflowsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [openStepId, setOpenStepId] = useState<string | null>(null);
  // The endpoint the tab has read, so returning to the tab does not read it again.
  const requestedRef = useRef<string | null>(null);
  // Incremented per read; a response for an older read (the endpoint changed meanwhile) is dropped.
  const tokenRef = useRef(0);

  /**
   * Read the workflows from `url`.
   *
   * @param url The `/api/workflows/...` endpoint.
   */
  const load = useCallback(
    async (url: string) => {
      const token = ++tokenRef.current;
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(url);
        const body = await response.json().catch(() => ({}));
        if (token !== tokenRef.current) return;
        if (!response.ok || body?.success === false) {
          setError(typeof body?.error === 'string' ? body.error : 'The workflows could not be loaded.');
          return;
        }
        const parsed = parseArazzoWorkflows(body?.workflows);
        setData(parsed);
        setSelectedWorkflowId((current) =>
          current && parsed.workflows.some((w) => w.workflowId === current)
            ? current
            : (parsed.workflows[0]?.workflowId ?? null)
        );
        onLoaded?.(parsed.workflows.length);
      } catch (caught) {
        if (token === tokenRef.current) {
          setError(caught instanceof Error ? caught.message : 'The workflows could not be loaded.');
        }
      } finally {
        if (token === tokenRef.current) setLoading(false);
      }
    },
    [onLoaded]
  );

  useEffect(() => {
    if (!active || !endpoint || requestedRef.current === endpoint) return;
    requestedRef.current = endpoint;
    void load(endpoint);
  }, [active, endpoint, load]);

  const workflow = useMemo(
    () => data?.workflows.find((w) => w.workflowId === selectedWorkflowId) ?? null,
    [data, selectedWorkflowId]
  );
  const openStep = useMemo(
    () => workflow?.steps.find((step) => step.stepId === openStepId) ?? null,
    [workflow, openStepId]
  );

  const openWorkflow = useCallback(
    (workflowId: string) => {
      setOpenStepId(null);
      if (data?.workflows.some((w) => w.workflowId === workflowId)) setSelectedWorkflowId(workflowId);
    },
    [data]
  );
  const closeStep = useCallback(() => setOpenStepId(null), []);

  if (!endpoint) {
    return <EmptyState icon={<Workflow />} title="No revision to read" description="Import a revision to see its workflows." />;
  }
  if (loading && !data) return <LoadingState message="Loading workflows…" />;
  if (error) {
    return (
      <ErrorState
        title="Couldn't load the workflows."
        description={error}
        onRetry={() => void load(endpoint)}
      />
    );
  }
  if (!data) return null;
  if (data.workflows.length === 0) {
    return (
      <EmptyState
        icon={<Workflow />}
        title="No workflows"
        description="This revision holds no Arazzo workflows. Import an Arazzo document to see one."
        data-testid="awf-empty"
      />
    );
  }

  return (
    <div className="awf" data-testid="awf-panel">
      <nav className="awf-list" aria-label="Workflows">
        <h3 className="awf-heading">
          Workflows <span className="awf-count tabular-nums">{data.workflows.length}</span>
        </h3>
        <ul>
          {data.workflows.map((entry) => {
            const missing = entry.sources.filter((source) => source.status === 'missing').length;
            const selected = entry.workflowId === selectedWorkflowId;
            return (
              <li key={entry.workflowId}>
                <button
                  type="button"
                  className="awf-list__item"
                  aria-current={selected ? 'true' : undefined}
                  data-testid={`awf-workflow-${entry.workflowId}`}
                  onClick={() => openWorkflow(entry.workflowId)}
                >
                  <span className="mono awf-list__id">{entry.workflowId}</span>
                  {entry.summary ? <span className="awf-list__summary">{entry.summary}</span> : null}
                  <span className="awf-list__meta">
                    {entry.steps.length} step{entry.steps.length === 1 ? '' : 's'}
                    {missing > 0 ? (
                      <Badge variant="danger">
                        {missing} source{missing === 1 ? '' : 's'} missing
                      </Badge>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {workflow ? (
        <section className="awf-detail" aria-labelledby="awf-detail-title" data-testid="awf-detail">
          <header className="awf-detail__head">
            <h3 id="awf-detail-title" className="awf-detail__title mono">
              <GitBranch aria-hidden className="awf-detail__icon" />
              {workflow.workflowId}
            </h3>
            {workflow.summary ? <p className="awf-detail__summary">{workflow.summary}</p> : null}
            {workflow.description ? <p className="awf-muted">{workflow.description}</p> : null}
          </header>

          <section aria-labelledby="awf-sources-title">
            <h4 id="awf-sources-title" className="awf-subheading">
              Source descriptions
            </h4>
            <SourceStatusList sources={workflow.sources} />
          </section>

          <InputsOutputs workflow={workflow} />

          <section aria-labelledby="awf-steps-title">
            <h4 id="awf-steps-title" className="awf-subheading">
              Steps
            </h4>
            {workflow.steps.length === 0 ? (
              <p className="awf-muted">This workflow has no steps.</p>
            ) : (
              <ol className="awf-steps">
                {workflow.steps.map((step, index) => {
                  const unresolved = step.targetKind === 'operation' && !step.operation;
                  return (
                    <li key={step.stepId}>
                      <button
                        type="button"
                        className="awf-steps__item"
                        data-testid={`awf-step-${step.stepId}`}
                        onClick={() => setOpenStepId(step.stepId)}
                      >
                        <span className="awf-steps__index tabular-nums" aria-hidden>
                          {index + 1}
                        </span>
                        <span className="awf-steps__body">
                          <span className="mono awf-steps__id">{step.stepId}</span>
                          <span className="mono awf-steps__target">{stepTargetLabel(step)}</span>
                          {step.description ? <span className="awf-muted">{step.description}</span> : null}
                        </span>
                        {unresolved ? <Badge variant="warn">Not resolved</Badge> : null}
                        {step.targetKind === 'workflow' ? <Badge variant="accent">Workflow</Badge> : null}
                      </button>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>

          <section aria-labelledby="awf-graph-heading">
            <h4 id="awf-graph-heading" className="awf-subheading">
              Step graph
            </h4>
            <ArazzoStepGraph workflow={workflow} onOpenStep={setOpenStepId} onOpenWorkflow={openWorkflow} />
          </section>
        </section>
      ) : null}

      <ArazzoStepDrawer
        step={openStep}
        workflowId={workflow?.workflowId ?? ''}
        onClose={closeStep}
        onOpenWorkflow={openWorkflow}
      />
    </div>
  );
}
