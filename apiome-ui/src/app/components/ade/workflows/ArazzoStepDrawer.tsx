'use client';

/**
 * Arazzo step drawer (COA-1.3, #7039).
 *
 * Opened from a step row or a step node in the **Workflows** tab. It shows the step — what it
 * calls, its parameters, success criteria, `onSuccess` / `onFailure` actions and outputs — and,
 * when the step's reference resolved to an imported operation, opens that operation: method,
 * route, summary, parameters and declared responses, read from
 * `GET /api/workflows/operations/{pathOperationId}`, with a link to the project or catalog item
 * that holds it.
 *
 * A step whose reference did not resolve says why instead of offering a link that would lead
 * nowhere; a step that calls another workflow offers to show that workflow.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerOpenFullPageLink,
  DrawerTitle,
  DrawerClose,
} from '@/app/components/ui/Drawer';
import { ErrorBanner } from '@/app/components/ui/ErrorState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { MethodChip } from '@/app/components/ui/MethodChip';
import {
  describeArazzoAction,
  formatArazzoValue,
  operationOwnerHref,
  parseArazzoOperationDetail,
  stepResolutionText,
  type ArazzoAction,
  type ArazzoOperationDetail,
  type ArazzoStepView,
} from './arazzoWorkflowModel';

export interface ArazzoStepDrawerProps {
  /** The step to show, or `null` when the drawer is closed. */
  step: ArazzoStepView | null;
  /** The workflow the step belongs to, for the sub-line. */
  workflowId: string;
  /** Close the drawer. */
  onClose: () => void;
  /** Show another workflow (a step that calls one). */
  onOpenWorkflow: (workflowId: string) => void;
}

/** A titled section of the drawer, omitted when it has nothing to say. */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="awf-drawer__section">
      <h3 className="awf-drawer__heading">{title}</h3>
      {children}
    </section>
  );
}

/** One step parameter as `name (in) = value`. */
function parameterLine(raw: unknown): string {
  if (!raw || typeof raw !== 'object') return formatArazzoValue(raw);
  const parameter = raw as Record<string, unknown>;
  if (typeof parameter.reference === 'string') return `Reusable parameter ${parameter.reference}`;
  const where = typeof parameter.in === 'string' ? ` (${parameter.in})` : '';
  return `${formatArazzoValue(parameter.name)}${where} = ${formatArazzoValue(parameter.value)}`;
}

/** One success criterion as its condition (and type, when not a plain condition). */
function criterionLine(raw: unknown): string {
  if (!raw || typeof raw !== 'object') return formatArazzoValue(raw);
  const criterion = raw as Record<string, unknown>;
  const type = typeof criterion.type === 'string' && criterion.type !== 'simple' ? ` [${criterion.type}]` : '';
  const context = typeof criterion.context === 'string' ? ` on ${criterion.context}` : '';
  return `${formatArazzoValue(criterion.condition)}${context}${type}`;
}

/** The list of actions, or the default behaviour when there are none. */
function ActionList({ actions, fallback }: { actions: ArazzoAction[]; fallback: string }) {
  if (actions.length === 0) return <p className="awf-drawer__muted">{fallback}</p>;
  return (
    <ul className="awf-drawer__list">
      {actions.map((action, index) => (
        <li key={`${action.name ?? action.type}-${index}`}>
          {action.name ? <span className="mono awf-drawer__name">{action.name}</span> : null}
          {describeArazzoAction(action)}
        </li>
      ))}
    </ul>
  );
}

/**
 * The resolved operation, fetched when the drawer opens on a resolved step.
 *
 * @param props The operation id to read.
 * @returns The operation section, its loading state, or an inline error.
 */
function OperationSection({ pathOperationId }: { pathOperationId: string }) {
  const [detail, setDetail] = useState<ArazzoOperationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Incremented per read; a response for an older operation is dropped.
  const tokenRef = useRef(0);

  /** Read the operation (on open, and again from the error banner's retry). */
  const load = useCallback(async () => {
    const token = ++tokenRef.current;
    setLoading(true);
    setError(null);
    setDetail(null);
    try {
      const response = await fetch(`/api/workflows/operations/${encodeURIComponent(pathOperationId)}`);
      const body = await response.json().catch(() => ({}));
      if (token !== tokenRef.current) return;
      if (!response.ok || body?.success === false) {
        setError(typeof body?.error === 'string' ? body.error : 'The operation could not be loaded.');
        return;
      }
      const parsed = parseArazzoOperationDetail(body?.operation);
      if (parsed) setDetail(parsed);
      else setError('The operation could not be read.');
    } catch (caught) {
      if (token === tokenRef.current) {
        setError(caught instanceof Error ? caught.message : 'The operation could not be loaded.');
      }
    } finally {
      if (token === tokenRef.current) setLoading(false);
    }
  }, [pathOperationId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingState message="Loading the operation…" />;
  if (error || !detail) {
    return (
      <ErrorBanner
        title="Couldn't load the operation."
        description={error ?? 'The operation could not be loaded.'}
        onRetry={() => void load()}
      />
    );
  }
  return (
    <div className="awf-drawer__operation" data-testid="awf-drawer-operation">
      <p className="awf-drawer__route">
        <MethodChip method={detail.method} />
        <span className="mono">{detail.path}</span>
      </p>
      {detail.summary ? <p className="awf-drawer__summary">{detail.summary}</p> : null}
      {detail.description ? <p className="awf-drawer__muted">{detail.description}</p> : null}
      <dl className="awf-drawer__facts">
        {detail.operationId ? (
          <>
            <dt>Operation ID</dt>
            <dd className="mono">{detail.operationId}</dd>
          </>
        ) : null}
        <dt>{detail.projectPublishable ? 'Project' : 'Catalog item'}</dt>
        <dd>
          {detail.projectName ?? detail.projectId}
          {detail.versionLabel ? <span className="awf-drawer__muted"> · {detail.versionLabel}</span> : null}
        </dd>
      </dl>
      <h4 className="awf-drawer__subheading">Parameters</h4>
      {detail.parameters.length === 0 ? (
        <p className="awf-drawer__muted">No parameters.</p>
      ) : (
        <ul className="awf-drawer__list">
          {detail.parameters.map((parameter) => (
            <li key={`${parameter.in}-${parameter.name}`}>
              <span className="mono awf-drawer__name">{parameter.name}</span>
              {parameter.in ? <Badge variant="neutral">{parameter.in}</Badge> : null}
              {parameter.description ? <span className="awf-drawer__muted"> {parameter.description}</span> : null}
            </li>
          ))}
        </ul>
      )}
      <h4 className="awf-drawer__subheading">Responses</h4>
      {detail.responses.length === 0 ? (
        <p className="awf-drawer__muted">No responses declared.</p>
      ) : (
        <ul className="awf-drawer__list">
          {detail.responses.map((response) => (
            <li key={response.statusCode}>
              <span className="mono awf-drawer__name">{response.statusCode}</span>
              {response.description ?? ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The step drawer.
 *
 * @param props See {@link ArazzoStepDrawerProps}.
 * @returns The right side-sheet, open while `step` is set.
 */
export default function ArazzoStepDrawer({ step, workflowId, onClose, onOpenWorkflow }: ArazzoStepDrawerProps) {
  const unresolvedText = step ? stepResolutionText(step) : null;
  return (
    <Drawer open={step !== null} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      {step ? (
        <DrawerContent size="lg" data-testid="awf-step-drawer">
          <DrawerHeader>
            <DrawerTitle className="mono">{step.stepId}</DrawerTitle>
            <DrawerDescription>
              Step {step.orderIndex + 1} of workflow <span className="mono">{workflowId}</span>
            </DrawerDescription>
          </DrawerHeader>
          <DrawerBody className="awf-drawer">
            {step.description ? <p className="awf-drawer__summary">{step.description}</p> : null}

            <Section title={step.targetKind === 'workflow' ? 'Calls workflow' : 'Operation'}>
              {step.targetKind === 'workflow' && step.targetWorkflowId ? (
                <Button type="button" variant="secondary" size="sm" onClick={() => onOpenWorkflow(step.targetWorkflowId!)}>
                  Show workflow <span className="mono">{step.targetWorkflowId}</span>
                </Button>
              ) : step.operation ? (
                <OperationSection pathOperationId={step.operation.pathOperationId} />
              ) : (
                <>
                  <p className="awf-drawer__muted" data-testid="awf-drawer-unresolved">
                    {unresolvedText}
                  </p>
                  {step.operationId || step.operationRef ? (
                    <p className="mono awf-drawer__ref">{step.operationId ?? step.operationRef}</p>
                  ) : null}
                </>
              )}
              {step.sourceNames.length > 0 ? (
                <p className="awf-drawer__muted">
                  Source: <span className="mono">{step.sourceNames.join(', ')}</span>
                </p>
              ) : null}
            </Section>

            {step.parameters.length > 0 ? (
              <Section title="Step parameters">
                <ul className="awf-drawer__list mono">
                  {step.parameters.map((parameter, index) => (
                    <li key={index}>{parameterLine(parameter)}</li>
                  ))}
                </ul>
              </Section>
            ) : null}

            {step.requestBody ? (
              <Section title="Request body">
                <pre className="awf-drawer__code mono">{JSON.stringify(step.requestBody, null, 2)}</pre>
              </Section>
            ) : null}

            <Section title="Success criteria">
              {step.successCriteria.length === 0 ? (
                <p className="awf-drawer__muted">None — any response counts as success.</p>
              ) : (
                <ul className="awf-drawer__list mono">
                  {step.successCriteria.map((criterion, index) => (
                    <li key={index}>{criterionLine(criterion)}</li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="On success">
              <ActionList actions={step.onSuccess} fallback="Continues to the next step." />
            </Section>
            <Section title="On failure">
              <ActionList actions={step.onFailure} fallback="The workflow fails." />
            </Section>

            {Object.keys(step.outputs).length > 0 ? (
              <Section title="Outputs">
                <dl className="awf-drawer__facts">
                  {Object.entries(step.outputs).map(([name, value]) => (
                    <React.Fragment key={name}>
                      <dt className="mono">{name}</dt>
                      <dd className="mono">{formatArazzoValue(value)}</dd>
                    </React.Fragment>
                  ))}
                </dl>
              </Section>
            ) : null}
          </DrawerBody>
          <DrawerFooter>
            {step.operation ? (
              <DrawerOpenFullPageLink href={operationOwnerHref(step.operation)}>
                {step.operation.projectPublishable ? 'Open project' : 'Open catalog item'}
              </DrawerOpenFullPageLink>
            ) : null}
            <DrawerClose asChild>
              <Button variant="outline">Close</Button>
            </DrawerClose>
          </DrawerFooter>
        </DrawerContent>
      ) : null}
    </Drawer>
  );
}
