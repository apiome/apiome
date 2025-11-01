'use client';

import { useCallback, useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import {
  ReactFlow,
  useNodesState,
  useEdgesState,
  addEdge,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Connection,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { getProjectsForTenant, getVersionsForProject } from '../../../../lib/db/helper';

interface Project {
  id: string;
  name: string;
  slug: string;
}

interface Version {
  id: string;
  version_id: string;
  description: string;
}

const Studio = () => {
  const { data: session } = useSession();
  const [projects, setProjects] = useState<Project[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [selectedVersionId, setSelectedVersionId] = useState<string>('');
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const currentTenantId = (session?.user as any)?.current_tenant_id;

  // Load projects on mount
  useEffect(() => {
    if (currentTenantId) {
      loadProjects();
    }
  }, [currentTenantId]);

  // Load versions when project is selected
  useEffect(() => {
    if (selectedProjectId) {
      loadVersions(selectedProjectId);
    } else {
      setVersions([]);
      setSelectedVersionId('');
    }
  }, [selectedProjectId]);

  // Clear canvas when version changes
  useEffect(() => {
    if (selectedProjectId && selectedVersionId) {
      // Clear existing nodes and edges
      setNodes([]);
      setEdges([]);

      // Here we would load classes for the selected project/version
      // This will be implemented later when class data structure is ready
      console.log('Loading canvas for project:', selectedProjectId, 'version:', selectedVersionId);
    }
  }, [selectedProjectId, selectedVersionId, setNodes, setEdges]);

  const loadProjects = async () => {
    if (!currentTenantId) return;

    setIsLoadingProjects(true);
    try {
      const result = await getProjectsForTenant(currentTenantId);
      const projectsData = JSON.parse(result);
      setProjects(projectsData);
    } catch (error) {
      console.error('Failed to load projects:', error);
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const loadVersions = async (projectId: string) => {
    setIsLoadingVersions(true);
    try {
      const result = await getVersionsForProject(projectId);
      const versionsData = JSON.parse(result);
      setVersions(versionsData);

      // Auto-select the first version if available
      if (versionsData.length > 0) {
        setSelectedVersionId(versionsData[0].id);
      }
    } catch (error) {
      console.error('Failed to load versions:', error);
    } finally {
      setIsLoadingVersions(false);
    }
  };

  const handleProjectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedProjectId(e.target.value);
    setSelectedVersionId(''); // Reset version when project changes
  };

  const handleVersionChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedVersionId(e.target.value);
  };

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  const onNodeClick = useCallback((event: React.MouseEvent, node: any) => {
    console.log('Clicked node:', node);
  }, []);

  const onEdgeClick = useCallback((event: React.MouseEvent, edge: Edge) => {
    console.log('Clicked edge:', edge);
  }, []);

  const selectedProject = projects.find(p => p.id === selectedProjectId);
  const selectedVersion = versions.find(v => v.id === selectedVersionId);

  return (
    <div className="flex flex-col h-full">
      {/* Header with Project and Version Selectors */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-2">
        <div className="flex items-center gap-3">
          {/* Project Selector */}
          <div className="flex items-center gap-1.5">
            <select
              value={selectedProjectId}
              onChange={handleProjectChange}
              disabled={isLoadingProjects || !currentTenantId}
              className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-transparent min-w-[180px]"
            >
              <option value="">Select project...</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>

          {/* Version Selector */}
          <div className="flex items-center gap-1.5">
            <select
              value={selectedVersionId}
              onChange={handleVersionChange}
              disabled={isLoadingVersions || !selectedProjectId || versions.length === 0}
              className="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-transparent min-w-[180px]"
            >
              <option value="">Select version...</option>
              {versions.map((version) => (
                <option key={version.id} value={version.id}>
                  {version.version_id} - {version.description}
                </option>
              ))}
            </select>
          </div>

          {/* Context Display */}
          {selectedProject && selectedVersion && (
            <div className="ml-auto flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
              <span className="font-medium">{selectedProject.name}</span>
              <span>/</span>
              <span className="font-mono">{selectedVersion.version_id}</span>
            </div>
          )}
        </div>
      </div>

      {/* Canvas Area */}
      <div className="flex-1 bg-white dark:bg-gray-900">
        {!selectedProjectId || !selectedVersionId ? (
          // Empty state when no project/version selected
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <svg
                className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
              <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                No Project Selected
              </h3>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                Select a project and version to view the class diagram
              </p>
            </div>
          </div>
        ) : (
          // React Flow Canvas
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            fitView
            attributionPosition="bottom-left"
            className="dark:bg-gray-900"
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={12}
              size={1}
              className="dark:bg-gray-900"
              color="currentColor"
              style={{
                color: 'rgb(156, 163, 175)',
                opacity: 0.5
              }}
            />
            <Controls className="dark:bg-gray-800 dark:border-gray-700" />
            <MiniMap
              nodeStrokeColor={(node) => {
                if (node.type === 'input') return '#3b82f6';
                if (node.type === 'output') return '#ec4899';
                return '#6b7280';
              }}
              nodeColor={(node) => {
                if (node.type === 'input') return '#dbeafe';
                if (node.type === 'output') return '#fce7f3';
                return '#f3f4f6';
              }}
              className="dark:bg-gray-800 dark:border-gray-700"
              maskColor="rgb(0, 0, 0, 0.1)"
            />
          </ReactFlow>
        )}
      </div>
    </div>
  );
};

export default Studio;
