'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  ReactFlow,
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
import { ArrowLeft, GitFork } from 'lucide-react';
import { LoadingState } from '../../../ui/LoadingState';
import { EmptyState } from '../../../ui/EmptyState';
import { Alert } from '../../../ui/Alert';
import {
  buildRelationshipGraphData,
  type ClassWithProperties,
} from '@/app/utils/relationship-graph';
import { applyAutoLayout } from '@/app/utils/canvas-auto-layout';

const NODE_WIDTH = 140;
const NODE_HEIGHT = 40;

export interface ClassesGraphViewProps {
  projectId: string;
}

interface VersionRow {
  id: string;
  version_id: string;
  published: boolean;
}

function pickDefaultVersion(versions: VersionRow[]): VersionRow | null {
  if (versions.length === 0) return null;
  return versions.find((v) => v.published) ?? versions[0];
}

export function ClassesGraphView({ projectId }: ClassesGraphViewProps) {
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [classes, setClasses] = useState<ClassWithProperties[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setIsLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/versions?projectId=${encodeURIComponent(projectId)}`);
        const json = (await res.json()) as { success?: boolean; versions?: VersionRow[]; error?: string };
        if (!res.ok || !json.success) throw new Error(json.error || 'Failed to load versions');
        if (cancelled) return;
        const list = json.versions ?? [];
        setVersions(list);
        setVersionId(pickDefaultVersion(list)?.id ?? null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Failed to load versions');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const loadClasses = useCallback(async (vid: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/classes/version/${vid}/with-properties-tags`);
      const json = (await res.json()) as { success?: boolean; classes?: ClassWithProperties[]; error?: string };
      if (!res.ok || !json.success) throw new Error(json.error || 'Failed to load classes');
      setClasses(json.classes ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load classes');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!versionId) return;
    void loadClasses(versionId);
  }, [versionId, loadClasses]);

  const graphData = useMemo(
    () => (classes.length ? buildRelationshipGraphData(classes) : { nodes: [], edges: [] }),
    [classes]
  );

  const { initialNodes, initialEdges } = useMemo(() => {
    if (graphData.nodes.length === 0) {
      return { initialNodes: [] as Node[], initialEdges: [] as Edge[] };
    }
    const rfNodes: Node[] = graphData.nodes.map((n) => ({
      id: n.id,
      type: 'default',
      position: { x: 0, y: 0 },
      data: { label: n.name },
      measured: { width: NODE_WIDTH, height: NODE_HEIGHT },
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    }));
    const rfEdges: Edge[] = graphData.edges.map((e, i) => ({
      id: `e-${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
    }));
    const laidOut = applyAutoLayout(rfNodes, rfEdges, {
      direction: 'TB',
      nodeSpacingX: 60,
      nodeSpacingY: 80,
      padding: 40,
      minimizeCrossings: true,
    });
    return { initialNodes: laidOut, initialEdges: rfEdges };
  }, [graphData]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Link
            href={`/ade/dashboard/projects/${projectId}?tab=classes`}
            className="text-xs text-gray-500 hover:text-indigo-500 inline-flex items-center gap-1"
          >
            <ArrowLeft className="w-3 h-3" /> Back to class list
          </Link>
          <span className="text-gray-300 dark:text-gray-600">·</span>
          <h2 className="text-lg font-semibold inline-flex items-center gap-2">
            <GitFork className="w-5 h-5 text-indigo-500" /> Relationship graph
          </h2>
        </div>
        {versions.length > 0 ? (
          <select
            value={versionId ?? ''}
            onChange={(e) => setVersionId(e.target.value)}
            className="h-9 px-2 text-sm rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 font-mono"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_id}
                {v.published ? ' · published' : ''}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {error ? <Alert variant="error">{error}</Alert> : null}

      <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden bg-white dark:bg-gray-800">
        {isLoading ? (
          <div className="h-[640px] flex items-center justify-center">
            <LoadingState message="Loading schema…" />
          </div>
        ) : graphData.nodes.length === 0 ? (
          <div className="h-[640px] flex items-center justify-center">
            <EmptyState
              icon={<GitFork className="w-8 h-8" />}
              title="Nothing to graph"
              description="Add classes with $ref properties between them to visualise relationships."
            />
          </div>
        ) : (
          <>
            {graphData.edges.length === 0 ? (
              <div className="px-4 py-2 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200/80 dark:border-amber-800/50 text-sm text-amber-800 dark:text-amber-200">
                This version has {graphData.nodes.length} class
                {graphData.nodes.length !== 1 ? 'es' : ''} but no references ($ref) between
                them.
              </div>
            ) : null}
            <div style={{ height: '720px' }}>
              <ReactFlow
                key={versionId ?? 'graph'}
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable
                fitView
                fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
                className="bg-gray-50 dark:bg-gray-900"
              >
                <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
                <Controls />
                <MiniMap />
              </ReactFlow>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
