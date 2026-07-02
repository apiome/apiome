'use client';

import * as React from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMigration, type MigrationRule } from '../MigrationContext';
import MigrationClassNode, { type MigrationClassNodeData } from './MigrationClassNode';
import MigrationRuleNode from './MigrationRuleNode';
import MigrationRuleEdge from './MigrationRuleEdge';
import MigrationRuleDialog from './MigrationRuleDialog';
import { openRuleDialogRef } from '../openRuleDialogRef';
import {
  FROM_NODE_X,
  TO_NODE_X,
  NODE_Y,
  RULE_NODE_X,
  ruleNodeYForPropertyIndex,
} from '../migrationCanvasLayout';

function extractProperties(schema: Record<string, unknown>): Array<{ name: string; type?: string }> {
  const props = schema?.properties;
  if (typeof props !== 'object' || props === null) return [];
  return Object.entries(props).map(([name, def]) => {
    const d = def as Record<string, unknown> | undefined;
    const type = typeof d?.type === 'string' ? d.type : undefined;
    return { name, type };
  });
}

type MigrationNodeData = MigrationClassNodeData;

type RuleDialogState =
  | null
  | { edgeId: string; sourceProp: string; targetProp: string };

function MigrationCanvasInner() {
  const {
    selectedProjectId,
    fromVersionId,
    toVersionId,
    fromTables,
    toTables,
    selectedClassName,
    migrationRules,
    setMigrationRules,
    incrementRuleCountsVersion,
  } = useMigration();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [ruleDialogState, setRuleDialogState] = React.useState<RuleDialogState>(null);
  const openRuleDialog = React.useCallback(
    (edgeId: string, sourceProp: string, targetProp: string) => {
      setRuleDialogState({ edgeId, sourceProp, targetProp });
    },
    []
  );
  openRuleDialogRef.current = openRuleDialog;

  const fromRow = React.useMemo(
    () => (selectedClassName ? fromTables.find((r) => r.class_name === selectedClassName) : null),
    [selectedClassName, fromTables]
  );
  const toRow = React.useMemo(
    () => (selectedClassName ? toTables.find((r) => r.class_name === selectedClassName) : null),
    [selectedClassName, toTables]
  );
  const fromProps = React.useMemo(
    () => extractProperties(fromRow?.schema ?? {}),
    [fromRow?.schema]
  );
  const toProps = React.useMemo(
    () => extractProperties(toRow?.schema ?? {}),
    [toRow?.schema]
  );

  const nodeTypes = React.useMemo(
    () => ({ migrationClass: MigrationClassNode, migrationRule: MigrationRuleNode }),
    []
  );
  const edgeTypes = React.useMemo(() => ({ migrationRule: MigrationRuleEdge }), []);

  const onNodeClick = React.useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.type === 'migrationRule' && node.data) {
        const d = node.data as { ruleKey?: string; sourceProp?: string; outputProperties?: string[] };
        const { ruleKey, sourceProp, outputProperties } = d;
        if (ruleKey != null && sourceProp != null) {
          openRuleDialog(ruleKey, sourceProp, outputProperties?.[0] ?? sourceProp);
        }
      }
    },
    [openRuleDialog]
  );

  React.useEffect(() => {
    if (!selectedClassName) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const fromSchema = fromRow?.schema ?? {};
    const toSchema = toRow?.schema ?? {};
    const fromPropsForEdges = extractProperties(fromSchema);
    const toPropsForEdges = extractProperties(toSchema);

    const fromNode: Node = {
      id: 'migration-from',
      type: 'migrationClass',
      position: { x: FROM_NODE_X, y: NODE_Y },
      data: {
        className: selectedClassName,
        properties: fromPropsForEdges,
        side: 'from',
      } as Record<string, unknown>,
      draggable: false,
      selectable: false,
    };
    const toNode: Node = {
      id: 'migration-to',
      type: 'migrationClass',
      position: { x: TO_NODE_X, y: NODE_Y },
      data: {
        className: selectedClassName,
        properties: toPropsForEdges,
        side: 'to',
      } as Record<string, unknown>,
      draggable: false,
      selectable: false,
    };
    const toPropNames = new Set(toPropsForEdges.map((p) => p.name));
    const allNodes: Node[] = [fromNode, toNode];
    const propertyEdges: Edge[] = [];

    for (let i = 0; i < fromPropsForEdges.length; i++) {
      const fromProp = fromPropsForEdges[i];
      const ruleKey = `migration-edge-prop-${fromProp.name}`;
      const rule = migrationRules[ruleKey];

      if (rule && rule.outputProperties.length > 0) {
        const validOutputs = rule.outputProperties.filter((out) => toPropNames.has(out));
        if (validOutputs.length === 0) continue;
        const ruleNodeId = `migration-rule-${fromProp.name}`;
        const ruleNodeY = ruleNodeYForPropertyIndex(i);
        allNodes.push({
          id: ruleNodeId,
          type: 'migrationRule',
          position: { x: RULE_NODE_X, y: ruleNodeY },
          data: {
            ruleKey,
            ruleName: rule.name ?? 'Rule',
            sourceProp: fromProp.name,
            outputProperties: validOutputs,
          } as Record<string, unknown>,
          draggable: false,
          selectable: false,
        });
        propertyEdges.push({
          id: `edge-from-${fromProp.name}-to-rule-${fromProp.name}`,
          source: 'migration-from',
          target: ruleNodeId,
          sourceHandle: `prop-${fromProp.name}`,
          targetHandle: 'input',
          type: 'migrationRule',
          zIndex: 0,
          data: { isConnector: true },
        });
        for (const targetProp of validOutputs) {
          propertyEdges.push({
            id: `edge-rule-${fromProp.name}-to-${targetProp}`,
            source: ruleNodeId,
            target: 'migration-to',
            sourceHandle: `out-${targetProp}`,
            targetHandle: `prop-${targetProp}`,
            type: 'migrationRule',
            zIndex: 0,
            data: { isConnector: true },
          });
        }
      } else if (toPropNames.has(fromProp.name)) {
        const passthroughKey = `migration-edge-prop-${fromProp.name}`;
        propertyEdges.push({
          id: passthroughKey,
          source: 'migration-from',
          target: 'migration-to',
          sourceHandle: `prop-${fromProp.name}`,
          targetHandle: `prop-${fromProp.name}`,
          type: 'migrationRule',
          zIndex: 0,
          data: {
            ruleName: null,
            ruleKey: passthroughKey,
            isConnector: false,
            onAddRule: () => {
              openRuleDialogRef.current?.(passthroughKey, fromProp.name, fromProp.name);
            },
          },
        });
      }
    }

    setNodes(allNodes);
    setEdges(propertyEdges);
  }, [selectedClassName, fromRow?.schema, toRow?.schema, migrationRules, setNodes, setEdges]);

  const handleSaveRule = React.useCallback(
    (rule: MigrationRule) => {
      if (!ruleDialogState) return;
      const nextRules = { ...migrationRules, [ruleDialogState.edgeId]: rule };
      setMigrationRules((prev) => ({ ...prev, [ruleDialogState.edgeId]: rule }));
      if (selectedProjectId && fromVersionId && toVersionId && selectedClassName) {
        fetch('/api/migration-plans', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            projectId: selectedProjectId,
            fromVersionId,
            toVersionId,
            className: selectedClassName,
            rules: nextRules,
          }),
        })
          .then((res) => {
            if (res.ok) incrementRuleCountsVersion();
          })
          .catch((err) => console.error('Failed to persist migration plan:', err));
      }
    },
    [
      ruleDialogState,
      migrationRules,
      setMigrationRules,
      selectedProjectId,
      fromVersionId,
      toVersionId,
      selectedClassName,
      incrementRuleCountsVersion,
    ]
  );

  return (
    <div className="w-full h-full min-h-0">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={{ type: 'migrationRule' }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
        className="bg-gray-50 dark:bg-gray-900"
      >
        <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
        <Controls />
        <MiniMap />
      </ReactFlow>
      {ruleDialogState && (
        <MigrationRuleDialog
          open={!!ruleDialogState}
          onOpenChange={(open) => !open && setRuleDialogState(null)}
          edgeId={ruleDialogState.edgeId}
          defaultSourceProp={ruleDialogState.sourceProp}
          defaultTargetProp={ruleDialogState.targetProp}
          fromProperties={fromProps}
          toProperties={toProps}
          initialRule={migrationRules[ruleDialogState.edgeId] ?? null}
          onSave={handleSaveRule}
        />
      )}
    </div>
  );
}

export default function MigrationCanvas() {
  return (
    <ReactFlowProvider>
      <MigrationCanvasInner />
    </ReactFlowProvider>
  );
}
