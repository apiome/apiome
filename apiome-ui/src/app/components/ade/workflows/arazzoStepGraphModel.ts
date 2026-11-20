/**
 * Arazzo step graph — nodes, edges and geometry (COA-1.3, #7039).
 *
 * Turns one workflow into the graph the **Workflows** tab draws. The routing follows the Arazzo
 * specification:
 *
 * - **Success.** A step with no `onSuccess` continues to the next step; the last step ends the
 *   workflow. Each `onSuccess` action draws its own edge: `end` to *End*, `goto` to the named
 *   step or workflow. When every action is conditional (`criteria`), the default path is drawn
 *   too, because a step whose criteria do not match still falls through to the next step.
 * - **Failure.** A step with no `onFailure` fails the workflow. Each `onFailure` action draws
 *   an edge: `end` to *Failed*, `goto` to its target, and a `retry` that names a step or
 *   workflow draws an edge there. A plain `retry` (the same step again) is not an edge — it is
 *   a badge on the step, since a self-loop reads poorly and says less than "retry ×3".
 * - **Reusable actions** (`$components.successActions.x`) cannot be followed without the
 *   components block, so they point at a labelled reference node.
 *
 * Layout is deterministic, like the dependency graph's SVG drawing, so a workflow always draws
 * the same way (and the docs screenshot fixture is stable): the start node, the steps in source
 * order and *End* along one row; *Failed* below it; called workflows and reusable-action
 * references above it. Edges between neighbouring steps run straight; any other jump leaves from
 * a step's lower edge and arcs under the row instead of running through it.
 *
 * Pure: no React — `ArazzoStepGraph.tsx` draws what {@link layoutStepGraph} returns.
 */

import type { ArazzoAction, ArazzoStepView, ArazzoWorkflowView } from './arazzoWorkflowModel';
import { stepTargetLabel } from './arazzoWorkflowModel';

/** The kinds of node the step graph draws. */
export type StepGraphNodeKind = 'start' | 'step' | 'end' | 'failed' | 'workflow' | 'reference';

/** The kinds of edge, each with its own stroke class. */
export type StepGraphEdgeKind = 'next' | 'success' | 'failure' | 'retry';

/** How an edge is routed between its two nodes. */
export type StepGraphRoute = 'straight' | 'under' | 'down' | 'up';

/** One node, placed on the grid. */
export interface StepGraphNode {
  id: string;
  kind: StepGraphNodeKind;
  label: string;
  /** The second line: a step's target, a reference's kind. */
  detail: string | null;
  /** The step this node draws, for a `step` node (activating it opens the step). */
  stepId: string | null;
  /** The called workflow, for a `workflow` node (activating it selects that workflow). */
  workflowId: string | null;
  /** `retry ×3` when the step retries itself on failure. */
  retryLabel: string | null;
  /** True when the step's operation did not resolve. */
  unresolved: boolean;
  /** Grid column: 0 is Start, steps are 1…n, End is n + 1. */
  column: number;
  /** Grid row: −1 external targets, 0 the main row, 1 Failed. */
  row: number;
}

/** One edge. */
export interface StepGraphEdge {
  id: string;
  source: string;
  target: string;
  kind: StepGraphEdgeKind;
  /** The action name, or the default path's label. */
  label: string;
  route: StepGraphRoute;
}

/** The graph for one workflow. */
export interface StepGraph {
  nodes: StepGraphNode[];
  edges: StepGraphEdge[];
}

/** A node with its box in SVG user units. */
export interface StepGraphNodeBox extends StepGraphNode {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** An edge with its path and label anchor in SVG user units. */
export interface StepGraphEdgePath extends StepGraphEdge {
  /** The SVG path `d`. */
  d: string;
  labelX: number;
  labelY: number;
}

/** A graph ready to draw. */
export interface StepGraphLayout {
  width: number;
  height: number;
  nodes: StepGraphNodeBox[];
  edges: StepGraphEdgePath[];
}

/** Horizontal distance between neighbouring grid columns. */
export const STEP_GRAPH_COLUMN = 250;
/** Vertical distance between grid rows. */
export const STEP_GRAPH_ROW = 140;
/** A step / external node's box. */
export const STEP_NODE_WIDTH = 196;
export const STEP_NODE_HEIGHT = 56;
/** A terminal (Start / End / Failed) node's box. */
export const TERMINAL_NODE_WIDTH = 96;
export const TERMINAL_NODE_HEIGHT = 36;
/** Margin around the drawing. */
const PADDING = 24;
/** Longest label drawn in full; longer ones are cut with an ellipsis (the full text is the title). */
export const STEP_LABEL_MAX = 26;

export const START_NODE_ID = 'start';
export const END_NODE_ID = 'end';
export const FAILED_NODE_ID = 'failed';

/** The node id a step draws as. */
export function stepNodeId(stepId: string): string {
  return `step:${stepId}`;
}

/** The node id a called workflow draws as. */
function workflowNodeId(workflowId: string): string {
  return `workflow:${workflowId}`;
}

/** The node id a reusable-action reference draws as. */
function referenceNodeId(reference: string): string {
  return `reference:${reference}`;
}

/** `retry ×N` for a step that retries itself, or `null`. */
function selfRetryLabel(step: ArazzoStepView): string | null {
  const retry = step.onFailure.find((action) => action.type === 'retry' && !action.stepId && !action.workflowId);
  if (!retry) return null;
  return retry.retryLimit !== null ? `retry ×${retry.retryLimit}` : 'retry';
}

/**
 * The label an action's edge carries: its `name`, else the reused action's own name (the last
 * segment of `$components.successActions.done`), else its type.
 */
function actionLabel(action: ArazzoAction): string {
  if (action.name) return action.name;
  if (action.reference) return action.reference.split('.').pop() || action.reference;
  return action.type;
}

/** True when every action in a non-empty list applies only under its criteria. */
function allConditional(actions: ArazzoAction[]): boolean {
  return actions.length > 0 && actions.every((action) => action.conditional);
}

/**
 * Build the graph for one workflow.
 *
 * @param workflow The workflow view.
 * @returns Nodes (placed on the grid) and edges. A workflow with no steps is just Start → End.
 */
export function buildStepGraph(workflow: ArazzoWorkflowView): StepGraph {
  const steps = workflow.steps;
  const columnOf = new Map<string, number>();
  steps.forEach((step, index) => columnOf.set(stepNodeId(step.stepId), index + 1));
  const endColumn = steps.length + 1;
  columnOf.set(START_NODE_ID, 0);
  columnOf.set(END_NODE_ID, endColumn);

  const node = (id: string, kind: StepGraphNodeKind, label: string, column: number, row: number): StepGraphNode => ({
    id,
    kind,
    label,
    detail: null,
    stepId: null,
    workflowId: null,
    retryLabel: null,
    unresolved: false,
    column,
    row,
  });

  const nodes: StepGraphNode[] = [node(START_NODE_ID, 'start', 'Start', 0, 0)];
  steps.forEach((step, index) => {
    nodes.push({
      ...node(stepNodeId(step.stepId), 'step', step.stepId, index + 1, 0),
      detail: stepTargetLabel(step),
      stepId: step.stepId,
      retryLabel: selfRetryLabel(step),
      unresolved: step.targetKind === 'operation' && !step.operation,
    });
  });
  nodes.push(node(END_NODE_ID, 'end', 'End', endColumn, 0));

  const external = new Map<string, StepGraphNode>();
  const edges: StepGraphEdge[] = [];
  const edgeIds = new Set<string>();

  /** Add (once) the node above the row that an external target draws as. */
  const externalNode = (id: string, kind: 'workflow' | 'reference', label: string, column: number): string => {
    if (!external.has(id)) {
      const base = node(id, kind, label, column, -1);
      external.set(
        id,
        kind === 'workflow' ? { ...base, workflowId: label, detail: 'Workflow' } : { ...base, detail: 'Not followed' }
      );
    }
    return id;
  };

  /** Add an edge, choosing its route from where the two ends sit. */
  const addEdge = (source: string, target: string, kind: StepGraphEdgeKind, label: string) => {
    const id = `${kind}:${source}->${target}:${label}`;
    if (edgeIds.has(id)) return;
    edgeIds.add(id);
    let route: StepGraphRoute;
    if (target === FAILED_NODE_ID) route = 'down';
    else if (external.has(target)) route = 'up';
    else route = columnOf.get(target) === (columnOf.get(source) ?? 0) + 1 ? 'straight' : 'under';
    edges.push({ id, source, target, kind, label, route });
  };

  /** Resolve an action's target to a node id, adding an external node when needed. */
  const actionTarget = (action: ArazzoAction, terminal: string, column: number): string | null => {
    if (action.type === 'end') return terminal;
    if (action.type === 'reference' && action.reference) {
      return externalNode(referenceNodeId(action.reference), 'reference', action.reference, column);
    }
    if (action.stepId) {
      const id = stepNodeId(action.stepId);
      return columnOf.has(id)
        ? id
        : externalNode(referenceNodeId(`step ${action.stepId}`), 'reference', `Unknown step ${action.stepId}`, column);
    }
    if (action.workflowId) return externalNode(workflowNodeId(action.workflowId), 'workflow', action.workflowId, column);
    return null;
  };

  let failedUsed = false;
  addEdge(START_NODE_ID, steps.length > 0 ? stepNodeId(steps[0].stepId) : END_NODE_ID, 'next', 'start');

  steps.forEach((step, index) => {
    const source = stepNodeId(step.stepId);
    const column = index + 1;
    const next = index + 1 < steps.length ? stepNodeId(steps[index + 1].stepId) : END_NODE_ID;

    if (step.onSuccess.length === 0 || allConditional(step.onSuccess)) {
      addEdge(source, next, 'next', next === END_NODE_ID ? 'done' : 'next');
    }
    for (const action of step.onSuccess) {
      const target = actionTarget(action, END_NODE_ID, column);
      if (target) addEdge(source, target, 'success', actionLabel(action));
    }

    if (step.onFailure.length === 0 || allConditional(step.onFailure)) {
      failedUsed = true;
      addEdge(source, FAILED_NODE_ID, 'failure', 'fails');
    }
    for (const action of step.onFailure) {
      if (action.type === 'retry' && !action.stepId && !action.workflowId) continue; // the badge
      const target = actionTarget(action, FAILED_NODE_ID, column);
      if (!target) continue;
      if (target === FAILED_NODE_ID) failedUsed = true;
      addEdge(source, target, action.type === 'retry' ? 'retry' : 'failure', actionLabel(action));
    }
  });

  if (failedUsed) nodes.push(node(FAILED_NODE_ID, 'failed', 'Failed', endColumn, 1));
  // Two external targets introduced from the same step would share a column; nudge them apart.
  const usedColumns = new Set<number>();
  for (const extra of external.values()) {
    let column = extra.column;
    while (usedColumns.has(column)) column += 1;
    usedColumns.add(column);
    nodes.push({ ...extra, column });
  }
  return { nodes, edges };
}

/** True for the three pill-shaped terminals. */
function isTerminal(kind: StepGraphNodeKind): boolean {
  return kind === 'start' || kind === 'end' || kind === 'failed';
}

/**
 * Place the graph in SVG user units.
 *
 * @param graph The graph from {@link buildStepGraph}.
 * @returns Node boxes, edge paths with label anchors, and the drawing's size. Rows that hold no
 *   node take no space, so a workflow with no external target draws no empty band above it.
 */
export function layoutStepGraph(graph: StepGraph): StepGraphLayout {
  const minRow = Math.min(0, ...graph.nodes.map((node) => node.row));
  const maxRow = Math.max(0, ...graph.nodes.map((node) => node.row));
  const maxColumn = Math.max(0, ...graph.nodes.map((node) => node.column));

  const boxes = graph.nodes.map<StepGraphNodeBox>((node) => {
    const terminal = isTerminal(node.kind);
    const width = terminal ? TERMINAL_NODE_WIDTH : STEP_NODE_WIDTH;
    const height = terminal ? TERMINAL_NODE_HEIGHT : STEP_NODE_HEIGHT;
    const centreX = PADDING + STEP_NODE_WIDTH / 2 + node.column * STEP_GRAPH_COLUMN;
    const centreY = PADDING + STEP_NODE_HEIGHT / 2 + (node.row - minRow) * STEP_GRAPH_ROW;
    return { ...node, width, height, x: centreX - width / 2, y: centreY - height / 2 };
  });
  const byId = new Map(boxes.map((box) => [box.id, box]));

  const edges = graph.edges.flatMap<StepGraphEdgePath>((edge) => {
    const from = byId.get(edge.source);
    const to = byId.get(edge.target);
    if (!from || !to) return [];
    const fromCx = from.x + from.width / 2;
    const toCx = to.x + to.width / 2;
    if (edge.route === 'straight') {
      const y = from.y + from.height / 2;
      const x1 = from.x + from.width;
      const x2 = to.x;
      return [{ ...edge, d: `M ${x1} ${y} L ${x2} ${y}`, labelX: (x1 + x2) / 2, labelY: y }];
    }
    // The three curved routes are cubic Béziers; a label sits at the curve's midpoint (t = ½).
    let p0: [number, number];
    let p1: [number, number];
    let p2: [number, number];
    let p3: [number, number];
    if (edge.route === 'under') {
      const span = Math.abs(to.column - from.column);
      const depth = Math.min(34 + 14 * span, STEP_GRAPH_ROW - STEP_NODE_HEIGHT);
      const y1 = from.y + from.height;
      const y2 = to.y + to.height;
      const bottom = Math.max(y1, y2) + depth;
      p0 = [fromCx, y1];
      p1 = [fromCx, bottom];
      p2 = [toCx, bottom];
      p3 = [toCx, y2];
    } else if (edge.route === 'down') {
      const y1 = from.y + from.height;
      const y2 = to.y;
      const mid = (y1 + y2) / 2;
      p0 = [fromCx, y1];
      p1 = [fromCx, mid];
      p2 = [toCx, mid];
      p3 = [toCx, y2];
    } else {
      const y1 = from.y;
      const y2 = to.y + to.height;
      const mid = (y1 + y2) / 2;
      p0 = [fromCx, y1];
      p1 = [fromCx, mid];
      p2 = [toCx, mid];
      p3 = [toCx, y2];
    }
    const labelX = (p0[0] + 3 * p1[0] + 3 * p2[0] + p3[0]) / 8;
    const labelY = (p0[1] + 3 * p1[1] + 3 * p2[1] + p3[1]) / 8;
    return [{ ...edge, d: `M ${p0[0]} ${p0[1]} C ${p1[0]} ${p1[1]}, ${p2[0]} ${p2[1]}, ${p3[0]} ${p3[1]}`, labelX, labelY }];
  });

  return {
    width: PADDING * 2 + STEP_NODE_WIDTH + maxColumn * STEP_GRAPH_COLUMN,
    height: PADDING * 2 + STEP_NODE_HEIGHT + (maxRow - minRow) * STEP_GRAPH_ROW + (maxRow === 0 ? STEP_GRAPH_ROW - STEP_NODE_HEIGHT : 0),
    nodes: boxes,
    edges,
  };
}

/**
 * Cut a label to fit its node.
 *
 * @param text The full label.
 * @param max Longest length drawn in full.
 * @returns The label, or its first `max − 1` characters and an ellipsis.
 */
export function fitStepLabel(text: string, max: number = STEP_LABEL_MAX): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

/**
 * A text rendering of the graph for screen readers.
 *
 * @param graph The step graph.
 * @returns One sentence per edge, e.g. `find-pet → find-coupons (next)`, in edge order.
 */
export function describeStepGraph(graph: StepGraph): string[] {
  const labelOf = new Map(graph.nodes.map((node) => [node.id, node.label]));
  return graph.edges.map(
    (edge) => `${labelOf.get(edge.source) ?? edge.source} → ${labelOf.get(edge.target) ?? edge.target} (${edge.label})`
  );
}
