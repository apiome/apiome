'use client';

import React, { useState } from 'react';
import { useStudio } from '../StudioContext';
import PathsSidebar from './components/PathsSidebar';
import PathsCanvasView from './components/PathsCanvasView';
import OperationPropertiesPanel from './components/OperationPropertiesPanel';
import ParameterPropertiesPanel from './components/ParameterPropertiesPanel';

export default function PathsPage() {
  const { selectedProjectId, selectedVersionId } = useStudio();
  const [activeTab, setActiveTab] = useState<'paths' | 'classes' | 'properties'>('paths');
  const [selectedPathId, setSelectedPathId] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<{ id: string; pathname: string } | null>(null);
  const [selectedOperation, setSelectedOperation] = useState<{
    id: string;
    operation: string;
  } | null>(null);
  const [selectedParameter, setSelectedParameter] = useState<{
    id: string;
    name: string;
    operationId: string;
  } | null>(null);
  const [canvasRefreshKey, setCanvasRefreshKey] = useState(0);

  const handlePathSelect = (pathId: string | null, pathname?: string) => {
    setSelectedPathId(pathId);
    setSelectedPath(pathId && pathname ? { id: pathId, pathname } : null);
    setSelectedOperation(null);
    setSelectedParameter(null);
  };

  const handleOperationSelect = (operation: { id: string; operation: string } | null) => {
    setSelectedOperation(operation);
    if (operation) {
      setSelectedParameter(null);
    }
  };

  const handleParameterSelect = (parameter: { id: string; name: string; operationId: string } | null) => {
    setSelectedParameter(parameter);
    if (parameter) {
      setSelectedOperation(null);
    }
  };

  const handleCanvasRefresh = () => {
    setCanvasRefreshKey(prev => prev + 1);
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-gray-50 dark:bg-gray-900">
      {/* Show message if no project/version selected */}
      {(!selectedProjectId || !selectedVersionId) ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="relative">
            {/* Background decorative elements */}
            <div className="absolute -top-20 -left-20 w-40 h-40 bg-linear-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-full blur-3xl opacity-60" />
            <div className="absolute -bottom-20 -right-20 w-40 h-40 bg-linear-to-br from-blue-100 to-cyan-100 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-full blur-3xl opacity-60" />

            <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-12 md:p-16 text-center shadow-xl shadow-gray-200/50 dark:shadow-gray-900/50">
              <div className="w-20 h-20 mx-auto mb-6 bg-linear-to-br from-amber-500 to-orange-600 rounded-2xl flex items-center justify-center shadow-lg shadow-amber-500/30">
                <svg className="h-10 w-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                </svg>
              </div>
              <h2 className="text-2xl md:text-3xl font-bold text-gray-900 dark:text-white mb-3">
                No Project Selected
              </h2>
              <p className="text-gray-600 dark:text-gray-400 max-w-md mx-auto">
                Please select a project and version from the header to view paths.
              </p>
            </div>
          </div>
        </div>
      ) : (
        /* Two-Panel Layout: Sidebar | Canvas | Properties */
        <div className="flex-1 flex h-full overflow-hidden">
          {/* Left Sidebar */}
          <PathsSidebar
            activeTab={activeTab}
            onTabChange={setActiveTab}
            selectedPathId={selectedPathId}
            onPathSelect={handlePathSelect}
          />

          {/* Center Canvas */}
          <PathsCanvasView
            selectedPathId={selectedPathId}
            onOperationSelect={handleOperationSelect}
            onParameterSelect={handleParameterSelect}
            refreshKey={canvasRefreshKey}
          />

          {/* Right Properties Panel - Operation */}
          {selectedOperation && selectedPath && (
            <OperationPropertiesPanel
              operationId={selectedOperation.id}
              operation={selectedOperation.operation}
              pathname={selectedPath.pathname}
              versionPathId={selectedPathId}
              onClose={() => setSelectedOperation(null)}
              onRefresh={handleCanvasRefresh}
            />
          )}

          {/* Right Properties Panel - Parameter */}
          {selectedParameter && selectedPath && (
            <ParameterPropertiesPanel
              parameterId={selectedParameter.id}
              operationId={selectedParameter.operationId}
              pathname={selectedPath.pathname}
              onClose={() => setSelectedParameter(null)}
              onRefresh={handleCanvasRefresh}
            />
          )}
        </div>
      )}
    </div>
  );
}
