/**
 * The Arazzo workflow viewer's read model and step graph (COA-1.3, #7039).
 *
 * - `parseArazzoWorkflows` maps the REST payload defensively (malformed parts degrade, never throw);
 * - the helpers phrase actions, sources, targets and resolution failures;
 * - `buildStepGraph` follows the Arazzo routing rules (default next step, goto, end, retry,
 *   called workflows, reusable actions, conditional fall-through);
 * - `layoutStepGraph` places it deterministically.
 */

import {
  describeArazzoAction,
  formatArazzoValue,
  inputsReference,
  operationOwnerHref,
  parseArazzoAction,
  parseArazzoOperationDetail,
  parseArazzoWorkflows,
  sourceStatusTone,
  stepResolutionText,
  stepTargetLabel,
  workflowInputFields,
  type ArazzoWorkflowView,
} from '../src/app/components/ade/workflows/arazzoWorkflowModel';
import {
  END_NODE_ID,
  FAILED_NODE_ID,
  START_NODE_ID,
  STEP_GRAPH_COLUMN,
  buildStepGraph,
  describeStepGraph,
  fitStepLabel,
  layoutStepGraph,
  stepNodeId,
} from '../src/app/components/ade/workflows/arazzoStepGraphModel';
import { OPERATION_RESPONSE, WORKFLOWS_RESPONSE } from './helpers/arazzo-workflows-fixture';

const view = parseArazzoWorkflows(WORKFLOWS_RESPONSE);
const checkout = view.workflows[0];

/** A bare workflow with the given steps, for routing cases the fixture does not cover. */
function workflowOf(steps: Partial<ArazzoWorkflowView['steps'][number]>[]): ArazzoWorkflowView {
  return {
    workflowId: 'w',
    summary: null,
    description: null,
    inputs: {},
    outputs: {},
    sources: [],
    steps: steps.map((over, index) => ({
      stepId: `s${index}`,
      orderIndex: index,
      description: null,
      targetKind: 'operation',
      targetWorkflowId: null,
      operationRef: null,
      operationId: 'op',
      resolutionStatus: 'unresolved',
      resolutionReason: 'unknown-operation',
      operation: null,
      sourceNames: [],
      parameters: [],
      requestBody: null,
      successCriteria: [],
      onSuccess: [],
      onFailure: [],
      outputs: {},
      dependsOn: [],
      ...over,
    })),
  };
}

describe('parseArazzoWorkflows', () => {
  it('maps the payload to camelCase, keeping order and resolved operations', () => {
    expect(view.versionId).toBe(WORKFLOWS_RESPONSE.version_id);
    expect(view.workflows.map((w) => w.workflowId)).toEqual(['checkout', 'send-receipt']);
    expect(checkout.steps.map((s) => s.stepId)).toEqual(['load-cart', 'pay', 'notify']);
    expect(checkout.steps[0].operation).toMatchObject({ method: 'GET', path: '/carts/{cartId}', projectPublishable: true });
    expect(checkout.steps[0].onSuccess[0]).toMatchObject({ type: 'goto', stepId: 'pay', name: 'to-pay' });
    expect(checkout.steps[1].operation).toBeNull();
    expect(checkout.steps[2]).toMatchObject({ targetKind: 'workflow', targetWorkflowId: 'send-receipt' });
    expect(checkout.sources.map((s) => [s.name, s.status])).toEqual([
      ['shop', 'resolved'],
      ['payments', 'missing'],
    ]);
  });

  it('degrades malformed input instead of throwing', () => {
    expect(parseArazzoWorkflows(null)).toEqual({ versionId: null, projectId: null, sources: [], workflows: [] });
    const odd = parseArazzoWorkflows({
      workflows: [
        { summary: 'no id' },
        {
          workflow_id: 'ok',
          sources: [{ url: 'nameless' }, { name: 'x', status: 'weird' }],
          steps: [{ order_index: 1, step_id: 'b' }, { step_id: 'a', order_index: 0, operation: { method: 'GET' } }],
        },
      ],
    });
    expect(odd.workflows).toHaveLength(1);
    expect(odd.workflows[0].sources).toEqual([expect.objectContaining({ name: 'x', status: 'unknown' })]);
    expect(odd.workflows[0].steps.map((s) => s.stepId)).toEqual(['a', 'b']);
    // An operation missing its route is not an operation.
    expect(odd.workflows[0].steps[0].operation).toBeNull();
    expect(odd.workflows[0].steps[0].targetKind).toBe('none');
  });

  it('reads the operation drawer payload', () => {
    const detail = parseArazzoOperationDetail(OPERATION_RESPONSE)!;
    expect(detail.parameters).toEqual([{ name: 'cartId', in: 'path', description: 'The cart to read.' }]);
    expect(detail.responses.map((r) => r.statusCode)).toEqual(['200', '404']);
    expect(parseArazzoOperationDetail({ method: 'GET' })).toBeNull();
  });
});

describe('the helpers', () => {
  it('phrases each action type', () => {
    expect(describeArazzoAction(parseArazzoAction({ type: 'end' }))).toBe('End the workflow');
    expect(describeArazzoAction(parseArazzoAction({ type: 'goto', stepId: 'pay' }))).toBe('Go to step pay');
    expect(describeArazzoAction(parseArazzoAction({ type: 'goto', workflowId: 'w2' }))).toBe('Go to workflow w2');
    expect(describeArazzoAction(parseArazzoAction({ type: 'retry', retryLimit: 3, retryAfter: 1 }))).toBe(
      'Retry up to 3 times, 1 s apart'
    );
    expect(describeArazzoAction(parseArazzoAction({ type: 'retry', retryLimit: 1, stepId: 'a' }))).toBe(
      'Retry from step a up to 1 time'
    );
    expect(describeArazzoAction(parseArazzoAction({ reference: '$components.failureActions.x' }))).toBe(
      'Reusable action $components.failureActions.x'
    );
    expect(describeArazzoAction(parseArazzoAction({ type: 'end', criteria: [{ condition: 'x' }] }))).toBe(
      'End the workflow (when its criteria match)'
    );
    expect(describeArazzoAction(parseArazzoAction({ type: 'jump' }))).toBe('Unrecognised action');
  });

  it('gives each source status a tone and says why a step has no operation', () => {
    expect(sourceStatusTone('resolved')).toBe('ok');
    expect(sourceStatusTone('missing')).toBe('danger');
    expect(sourceStatusTone('unknown')).toBe('neutral');
    expect(stepResolutionText(checkout.steps[0])).toBeNull();
    expect(stepResolutionText(checkout.steps[1])).toBe('No imported operation matches this reference.');
    expect(stepResolutionText({ ...checkout.steps[0], operation: null })).toMatch(/deleted since the import/);
    expect(stepResolutionText({ ...checkout.steps[1], resolutionReason: 'brand-new' })).toMatch(/not imported/);
  });

  it('labels a step by what it calls', () => {
    expect(stepTargetLabel(checkout.steps[0])).toBe('GET /carts/{cartId}');
    expect(stepTargetLabel(checkout.steps[1])).toBe('$sourceDescriptions.payments.url#/paths/~1charges/post');
    expect(stepTargetLabel(checkout.steps[2])).toBe('Calls workflow send-receipt');
  });

  it('reads inputs from the schema, or reports its reference', () => {
    expect(workflowInputFields(checkout.inputs)).toEqual([
      { name: 'cartId', type: 'string', required: true, description: null },
      { name: 'coupon', type: 'string', required: false, description: null },
    ]);
    const receipt = view.workflows[1];
    expect(workflowInputFields(receipt.inputs)).toEqual([]);
    expect(inputsReference(receipt.inputs)).toBe('#/components/inputs/receipt');
  });

  it('formats values and links an operation to its owner', () => {
    expect(formatArazzoValue('$inputs.x')).toBe('$inputs.x');
    expect(formatArazzoValue(null)).toBe('—');
    expect(formatArazzoValue({ a: 1 })).toBe('{"a":1}');
    const op = checkout.steps[0].operation!;
    expect(operationOwnerHref(op)).toBe(`/ade/dashboard/versions?projectId=${op.projectId}`);
    expect(operationOwnerHref({ ...op, projectPublishable: false })).toBe(`/ade/dashboard/catalog/${op.projectId}`);
  });
});

describe('buildStepGraph', () => {
  const graph = buildStepGraph(checkout);
  const edge = (source: string, target: string) =>
    graph.edges.filter((e) => e.source === source && e.target === target);

  it('draws start, the steps in order, End, Failed and the called workflow', () => {
    expect(graph.nodes.map((n) => [n.id, n.column, n.row])).toEqual([
      [START_NODE_ID, 0, 0],
      [stepNodeId('load-cart'), 1, 0],
      [stepNodeId('pay'), 2, 0],
      [stepNodeId('notify'), 3, 0],
      [END_NODE_ID, 4, 0],
      [FAILED_NODE_ID, 4, 1],
    ]);
    // `notify` *calls* send-receipt; that is its target line, not an edge.
    expect(graph.nodes.find((n) => n.stepId === 'notify')!.detail).toBe('Calls workflow send-receipt');
  });

  it('follows explicit actions and replaces the defaults they override', () => {
    // load-cart: onSuccess goto pay (no implicit next — the action replaces it), onFailure end → Failed.
    expect(edge(stepNodeId('load-cart'), stepNodeId('pay')).map((e) => [e.kind, e.label])).toEqual([['success', 'to-pay']]);
    expect(edge(stepNodeId('load-cart'), FAILED_NODE_ID).map((e) => e.label)).toEqual(['give-up']);
    // pay: no onSuccess → next; a self-retry is a badge, not an edge, so no default failure edge either.
    expect(edge(stepNodeId('pay'), stepNodeId('notify')).map((e) => e.kind)).toEqual(['next']);
    expect(edge(stepNodeId('pay'), FAILED_NODE_ID)).toEqual([]);
    expect(graph.nodes.find((n) => n.stepId === 'pay')!.retryLabel).toBe('retry ×3');
    expect(graph.nodes.find((n) => n.stepId === 'pay')!.unresolved).toBe(true);
    // notify: last step → done; no onFailure → fails.
    expect(edge(stepNodeId('notify'), END_NODE_ID).map((e) => e.label)).toEqual(['done']);
    expect(edge(stepNodeId('notify'), FAILED_NODE_ID).map((e) => e.label)).toEqual(['fails']);
  });

  it('routes neighbours straight, jumps under the row and external targets up', () => {
    const goto = buildStepGraph(
      workflowOf([
        { onSuccess: [parseArazzoAction({ name: 'skip', type: 'goto', stepId: 's2' })] },
        {},
        { onFailure: [parseArazzoAction({ name: 'back', type: 'goto', stepId: 's0' })] },
        {
          onSuccess: [
            parseArazzoAction({ name: 'other', type: 'goto', workflowId: 'w2' }),
            parseArazzoAction({ reference: '$components.successActions.done' }),
          ],
        },
      ])
    );
    const route = (label: string) => goto.edges.find((e) => e.label === label)!.route;
    expect(route('start')).toBe('straight');
    expect(route('skip')).toBe('under');
    expect(route('back')).toBe('under');
    expect(route('other')).toBe('up');
    expect(route('done')).toBe('up');
    const above = goto.nodes.filter((n) => n.row === -1);
    expect(above.map((n) => n.kind)).toEqual(['workflow', 'reference']);
    // Two external targets from the same step get their own columns.
    expect(new Set(above.map((n) => n.column)).size).toBe(2);
  });

  it('keeps the default path when every action is conditional', () => {
    const conditional = buildStepGraph(
      workflowOf([
        {
          onSuccess: [parseArazzoAction({ name: 'maybe-end', type: 'end', criteria: [{ condition: '$statusCode == 204' }] })],
          onFailure: [parseArazzoAction({ name: 'maybe-retry', type: 'retry', stepId: 's1', criteria: [{ condition: 'x' }] })],
        },
        {},
      ])
    );
    const fromS0 = conditional.edges.filter((e) => e.source === stepNodeId('s0')).map((e) => [e.kind, e.target]);
    expect(fromS0).toEqual(
      expect.arrayContaining([
        ['next', stepNodeId('s1')],
        ['success', END_NODE_ID],
        ['failure', FAILED_NODE_ID],
        ['retry', stepNodeId('s1')],
      ])
    );
  });

  it('points a goto to an unknown step at a labelled reference node', () => {
    const broken = buildStepGraph(workflowOf([{ onSuccess: [parseArazzoAction({ type: 'goto', stepId: 'ghost' })] }]));
    expect(broken.nodes.find((n) => n.kind === 'reference')!.label).toBe('Unknown step ghost');
  });

  it('draws a stepless workflow as Start → End', () => {
    const empty = buildStepGraph(workflowOf([]));
    expect(empty.nodes.map((n) => n.id)).toEqual([START_NODE_ID, END_NODE_ID]);
    expect(empty.edges.map((e) => [e.source, e.target])).toEqual([[START_NODE_ID, END_NODE_ID]]);
  });

  it('describes the routing in words', () => {
    expect(describeStepGraph(graph)).toContain('load-cart → pay (to-pay)');
    expect(describeStepGraph(graph)).toContain('notify → Failed (fails)');
  });
});

describe('layoutStepGraph', () => {
  it('places nodes deterministically and sizes the drawing to them', () => {
    const layout = layoutStepGraph(buildStepGraph(checkout));
    expect(layoutStepGraph(buildStepGraph(checkout))).toEqual(layout);
    const box = (id: string) => layout.nodes.find((n) => n.id === id)!;
    expect(box(stepNodeId('pay')).x - box(stepNodeId('load-cart')).x).toBe(STEP_GRAPH_COLUMN);
    expect(box(FAILED_NODE_ID).y).toBeGreaterThan(box(END_NODE_ID).y);
    for (const node of layout.nodes) {
      expect(node.x).toBeGreaterThanOrEqual(0);
      expect(node.y).toBeGreaterThanOrEqual(0);
      expect(node.x + node.width).toBeLessThanOrEqual(layout.width);
      expect(node.y + node.height).toBeLessThanOrEqual(layout.height);
    }
    const straight = layout.edges.find((e) => e.route === 'straight')!;
    expect(straight.d).toMatch(/^M [\d.]+ [\d.]+ L [\d.]+ [\d.]+$/);
    const curved = layout.edges.find((e) => e.route === 'down')!;
    expect(curved.d).toMatch(/ C /);
  });

  it('cuts long labels with an ellipsis', () => {
    expect(fitStepLabel('short')).toBe('short');
    expect(fitStepLabel('a'.repeat(40), 10)).toBe(`${'a'.repeat(9)}…`);
  });
});
