/**
 * Arazzo workflow viewer — the read model (COA-1.3, #7039).
 *
 * The **Workflows** tab (catalog item detail and the project Versions page) reads
 * `GET /v1/workflows/{tenant}/versions/{versionId}` or `…/catalog/{itemId}` through the
 * `/api/workflows/*` proxies. This module turns that snake_case payload into the camelCase view
 * the components render, defensively: anything malformed degrades to an empty value rather than
 * throwing, so one odd workflow never blanks the tab.
 *
 * It also holds the small, pure helpers the components share — how an Arazzo action reads as
 * text, which tone a source status takes, what a step's target is, where its operation's owner
 * lives — so they are unit-tested here instead of inside JSX.
 */

import type { BadgeTone } from '@/app/components/ui/Badge';

/** Where the import found a `sourceDescriptions` entry, or `unknown` for an older revision. */
export type ArazzoSourceStatus = 'resolved' | 'missing' | 'unknown';

/** One declared source description and whether the import resolved it. */
export interface ArazzoSourceView {
  name: string;
  url: string | null;
  type: string | null;
  status: ArazzoSourceStatus;
  /** `fileset`, `catalog` or `remote` when resolved. */
  tier: string | null;
  /** Stable reason code when missing (`not-in-fileset`, `resolution-disabled`, …). */
  reason: string | null;
  detail: string | null;
}

/** The internal operation a step resolved to. */
export interface ArazzoStepOperation {
  pathOperationId: string;
  method: string;
  path: string;
  pathId: string;
  summary: string | null;
  description: string | null;
  operationId: string | null;
  versionId: string;
  versionLabel: string | null;
  projectId: string;
  projectName: string | null;
  /** True for a Project (Versions page), false for a catalog item. */
  projectPublishable: boolean;
}

/** One Arazzo success/failure action, kept verbatim plus the fields the viewer reads. */
export interface ArazzoAction {
  name: string | null;
  /** `goto`, `end`, `retry`, or `reference` for a `$components` reusable action. */
  type: 'goto' | 'end' | 'retry' | 'reference' | 'unknown';
  stepId: string | null;
  workflowId: string | null;
  /** The `$components.successActions.x` / `failureActions.x` reference, when reused. */
  reference: string | null;
  retryAfter: number | null;
  retryLimit: number | null;
  /** True when the action only applies under its `criteria`. */
  conditional: boolean;
}

/** What a step calls. */
export type ArazzoTargetKind = 'operation' | 'workflow' | 'none';

/** One step, in source order. */
export interface ArazzoStepView {
  stepId: string;
  orderIndex: number;
  description: string | null;
  targetKind: ArazzoTargetKind;
  targetWorkflowId: string | null;
  operationRef: string | null;
  operationId: string | null;
  /** `resolved` | `unresolved` | `not_applicable` | `parse_error`. */
  resolutionStatus: string;
  resolutionReason: string | null;
  operation: ArazzoStepOperation | null;
  sourceNames: string[];
  parameters: unknown[];
  requestBody: unknown;
  successCriteria: unknown[];
  onSuccess: ArazzoAction[];
  onFailure: ArazzoAction[];
  outputs: Record<string, unknown>;
  dependsOn: unknown[];
}

/** One workflow input, read from the `inputs` JSON Schema's top-level properties. */
export interface ArazzoInputField {
  name: string;
  type: string | null;
  required: boolean;
  description: string | null;
}

/** One workflow. */
export interface ArazzoWorkflowView {
  workflowId: string;
  summary: string | null;
  description: string | null;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  sources: ArazzoSourceView[];
  steps: ArazzoStepView[];
}

/** The whole tab's payload. */
export interface ArazzoWorkflowsView {
  versionId: string | null;
  projectId: string | null;
  sources: ArazzoSourceView[];
  workflows: ArazzoWorkflowView[];
}

/** The operation drawer's payload: the summary plus parameters and responses. */
export interface ArazzoOperationDetail extends ArazzoStepOperation {
  parameters: { name: string; in: string | null; description: string | null }[];
  responses: { statusCode: string; description: string | null }[];
}

type Raw = Record<string, unknown>;

/** `value` when it is a plain object, else `{}`. */
function obj(value: unknown): Raw {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Raw) : {};
}

/** `value` when it is an array, else `[]`. */
function arr(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** `value` when it is a non-empty string, else `null`. */
function str(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

/** `value` when it is a finite number, else `null`. */
function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * Read one Arazzo success/failure action.
 *
 * @param raw The action object as stored (`{name, type, stepId?, workflowId?, criteria?, …}`), or
 *   a reusable `{reference: "$components.successActions.x"}`.
 * @returns The action view; an unrecognised `type` is `unknown`.
 */
export function parseArazzoAction(raw: unknown): ArazzoAction {
  const action = obj(raw);
  const reference = str(action.reference);
  const declared = str(action.type);
  const type: ArazzoAction['type'] = reference
    ? 'reference'
    : declared === 'goto' || declared === 'end' || declared === 'retry'
      ? declared
      : 'unknown';
  return {
    name: str(action.name),
    type,
    stepId: str(action.stepId),
    workflowId: str(action.workflowId),
    reference,
    retryAfter: num(action.retryAfter),
    retryLimit: num(action.retryLimit),
    conditional: arr(action.criteria).length > 0,
  };
}

/** Read one source view; `null` when it has no name. */
function parseSource(raw: unknown): ArazzoSourceView | null {
  const source = obj(raw);
  const name = str(source.name);
  if (!name) return null;
  const status = source.status === 'resolved' || source.status === 'missing' ? source.status : 'unknown';
  return {
    name,
    url: str(source.url),
    type: str(source.type),
    status,
    tier: str(source.tier),
    reason: str(source.reason),
    detail: str(source.detail),
  };
}

/** Read a list of sources, dropping nameless entries. */
function parseSources(raw: unknown): ArazzoSourceView[] {
  return arr(raw)
    .map(parseSource)
    .filter((source): source is ArazzoSourceView => source !== null);
}

/** Read an operation summary; `null` when it lacks the fields needed to show it. */
function parseOperation(raw: unknown): ArazzoStepOperation | null {
  const op = obj(raw);
  const pathOperationId = str(op.path_operation_id);
  const method = str(op.method);
  const path = str(op.path);
  const projectId = str(op.project_id);
  const versionId = str(op.version_id);
  if (!pathOperationId || !method || !path || !projectId || !versionId) return null;
  return {
    pathOperationId,
    method,
    path,
    pathId: str(op.path_id) ?? '',
    summary: str(op.summary),
    description: str(op.description),
    operationId: str(op.operation_id),
    versionId,
    versionLabel: str(op.version_label),
    projectId,
    projectName: str(op.project_name),
    projectPublishable: op.project_publishable === true,
  };
}

/** Read one step. */
function parseStep(raw: unknown, index: number): ArazzoStepView {
  const step = obj(raw);
  const kind = step.target_kind === 'operation' || step.target_kind === 'workflow' ? step.target_kind : 'none';
  return {
    stepId: str(step.step_id) ?? `step${index}`,
    orderIndex: num(step.order_index) ?? index,
    description: str(step.description),
    targetKind: kind,
    targetWorkflowId: str(step.target_workflow_id),
    operationRef: str(step.operation_ref),
    operationId: str(step.operation_id),
    resolutionStatus: str(step.resolution_status) ?? 'unresolved',
    resolutionReason: str(step.resolution_reason),
    operation: parseOperation(step.operation),
    sourceNames: arr(step.source_names).filter((name): name is string => typeof name === 'string'),
    parameters: arr(step.parameters),
    requestBody: step.request_body ?? null,
    successCriteria: arr(step.success_criteria),
    onSuccess: arr(step.on_success).map(parseArazzoAction),
    onFailure: arr(step.on_failure).map(parseArazzoAction),
    outputs: obj(step.outputs),
    dependsOn: arr(step.depends_on),
  };
}

/**
 * Read the `/api/workflows/*` payload.
 *
 * @param raw The REST `ArazzoWorkflowsResponse` JSON.
 * @returns The camelCase view; workflows without a `workflow_id` are dropped and steps are
 *   sorted by `orderIndex`.
 */
export function parseArazzoWorkflows(raw: unknown): ArazzoWorkflowsView {
  const body = obj(raw);
  const workflows: ArazzoWorkflowView[] = [];
  for (const entry of arr(body.workflows)) {
    const workflow = obj(entry);
    const workflowId = str(workflow.workflow_id);
    if (!workflowId) continue;
    workflows.push({
      workflowId,
      summary: str(workflow.summary),
      description: str(workflow.description),
      inputs: obj(workflow.inputs),
      outputs: obj(workflow.outputs),
      sources: parseSources(workflow.sources),
      steps: arr(workflow.steps)
        .map(parseStep)
        .sort((a, b) => a.orderIndex - b.orderIndex),
    });
  }
  return {
    versionId: str(body.version_id),
    projectId: str(body.project_id),
    sources: parseSources(body.sources),
    workflows,
  };
}

/**
 * Read the `/api/workflows/operations/{id}` payload.
 *
 * @param raw The REST `ArazzoOperationDetailOut` JSON.
 * @returns The detail, or `null` when the payload is not an operation.
 */
export function parseArazzoOperationDetail(raw: unknown): ArazzoOperationDetail | null {
  const summary = parseOperation(raw);
  if (!summary) return null;
  const body = obj(raw);
  return {
    ...summary,
    parameters: arr(body.parameters).flatMap((entry) => {
      const parameter = obj(entry);
      const name = str(parameter.name);
      return name ? [{ name, in: str(parameter.in_location), description: str(parameter.description) }] : [];
    }),
    responses: arr(body.responses).flatMap((entry) => {
      const response = obj(entry);
      const statusCode = str(response.status_code);
      return statusCode ? [{ statusCode, description: str(response.description) }] : [];
    }),
  };
}

/**
 * List a workflow's inputs from its JSON Schema.
 *
 * @param inputs The workflow `inputs` schema.
 * @returns One field per top-level `properties` entry, in declaration order; empty when the
 *   schema has no properties (for example a bare `$ref`, which {@link inputsReference} reports).
 */
export function workflowInputFields(inputs: Record<string, unknown>): ArazzoInputField[] {
  const properties = obj(inputs.properties);
  const required = new Set(arr(inputs.required).filter((name): name is string => typeof name === 'string'));
  return Object.entries(properties).map(([name, schema]) => {
    const field = obj(schema);
    const type = Array.isArray(field.type) ? field.type.join(' | ') : str(field.type) ?? str(field.$ref);
    return { name, type, required: required.has(name), description: str(field.description) };
  });
}

/**
 * The `$ref` a workflow's inputs point at, when the schema is only a reference.
 *
 * @param inputs The workflow `inputs` schema.
 * @returns The reference string (`#/components/inputs/x`), or `null`.
 */
export function inputsReference(inputs: Record<string, unknown>): string | null {
  return str(inputs.$ref);
}

/**
 * Render a runtime expression or literal for display.
 *
 * @param value A stored value — usually a runtime expression string such as
 *   `$response.body#/id`, sometimes a literal or an object.
 * @returns A single-line string.
 */
export function formatArazzoValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * Describe an action as a short phrase.
 *
 * @param action The parsed action.
 * @returns e.g. `Go to step pay`, `End the workflow`, `Retry up to 3 times, 1 s apart`.
 */
export function describeArazzoAction(action: ArazzoAction): string {
  const when = action.conditional ? ' (when its criteria match)' : '';
  switch (action.type) {
    case 'end':
      return `End the workflow${when}`;
    case 'goto':
      if (action.stepId) return `Go to step ${action.stepId}${when}`;
      if (action.workflowId) return `Go to workflow ${action.workflowId}${when}`;
      return `Go to an unnamed target${when}`;
    case 'retry': {
      const limit = action.retryLimit !== null ? ` up to ${action.retryLimit} time${action.retryLimit === 1 ? '' : 's'}` : '';
      const after = action.retryAfter !== null ? `, ${action.retryAfter} s apart` : '';
      const then = action.stepId ? ` from step ${action.stepId}` : action.workflowId ? ` via workflow ${action.workflowId}` : '';
      return `Retry${then}${limit}${after}${when}`;
    }
    case 'reference':
      return `Reusable action ${action.reference}${when}`;
    default:
      return `Unrecognised action${when}`;
  }
}

/**
 * The badge tone a source status takes.
 *
 * @param status The source status.
 * @returns `ok` resolved, `danger` missing, `neutral` unknown.
 */
export function sourceStatusTone(status: ArazzoSourceStatus): BadgeTone {
  if (status === 'resolved') return 'ok';
  if (status === 'missing') return 'danger';
  return 'neutral';
}

/** The words a source status reads as. */
export const SOURCE_STATUS_LABEL: Readonly<Record<ArazzoSourceStatus, string>> = {
  resolved: 'Resolved',
  missing: 'Missing',
  unknown: 'Not recorded',
};

/** What each stored resolution reason means, for the step drawer. */
const RESOLUTION_REASON_TEXT: Readonly<Record<string, string>> = {
  'no-operation-target': 'The step names no operation.',
  'unknown-operation': 'No imported operation matches this reference.',
  'ambiguous-operation': 'More than one imported operation matches this reference.',
  'unparsable-ref': 'The reference could not be read.',
  'malformed-step': 'The step could not be read when it was imported.',
  'calls-workflow': 'The step calls another workflow.',
};

/**
 * Explain why a step has no operation to open.
 *
 * @param step The step.
 * @returns A sentence, or `null` when the step resolved.
 */
export function stepResolutionText(step: ArazzoStepView): string | null {
  if (step.resolutionStatus === 'resolved') {
    return step.operation ? null : 'The operation this step called has been deleted since the import.';
  }
  if (step.resolutionReason && RESOLUTION_REASON_TEXT[step.resolutionReason]) {
    return RESOLUTION_REASON_TEXT[step.resolutionReason];
  }
  return 'This step’s operation was not imported with the workflow.';
}

/**
 * The one-line target a step list row shows under the step id.
 *
 * @param step The step.
 * @returns `GET /pets/{id}`, `Calls workflow x`, the raw `operationId` / `operationRef`, or
 *   `No target`.
 */
export function stepTargetLabel(step: ArazzoStepView): string {
  if (step.targetKind === 'workflow') return `Calls workflow ${step.targetWorkflowId ?? '—'}`;
  if (step.operation) return `${step.operation.method.toUpperCase()} ${step.operation.path}`;
  return step.operationId ?? step.operationRef ?? 'No target';
}

/**
 * Where the operation's project or catalog item opens in the app.
 *
 * @param operation The resolved operation.
 * @returns The Versions page for a Project, the catalog detail page for a catalog item.
 */
export function operationOwnerHref(operation: ArazzoStepOperation): string {
  const id = encodeURIComponent(operation.projectId);
  return operation.projectPublishable
    ? `/ade/dashboard/versions?projectId=${id}`
    : `/ade/dashboard/catalog/${id}`;
}
