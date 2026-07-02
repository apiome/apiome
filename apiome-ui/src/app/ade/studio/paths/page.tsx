'use client';

import React, { useState } from 'react';
import { useStudio } from '../StudioContext';
import PathsSidebar from './components/PathsSidebar';
import PathsCanvasView from './components/PathsCanvasView';
import PathsCodeView from './components/PathsCodeView';
import OperationPropertiesPanel from './components/OperationPropertiesPanel';
import ParameterPropertiesPanel from './components/ParameterPropertiesPanel';
import ResponsePropertiesPanel from './components/ResponsePropertiesPanel';

export default function PathsPage() {
  const { selectedProjectId, selectedVersionId, pathsViewMode, bumpPathsQualityRevision } = useStudio();
  const [activeTab, setActiveTab] = useState<'paths' | 'operations' | 'classes' | 'properties' | 'security' | 'servers'>('paths');
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
  const [selectedResponse, setSelectedResponse] = useState<{
    id: string;
    statusCode: string;
    description: string;
  } | null>(null);
  const [canvasRefreshKey, setCanvasRefreshKey] = useState(0);
  const [helpDismissed, setHelpDismissed] = useState(false);
  const [responsePanelRefreshKey, setResponsePanelRefreshKey] = useState(0);
  /** Zoom Paths canvas to this node id after load (e.g. sidebar operation click). */
  const [pathsCanvasPendingFocusNodeId, setPathsCanvasPendingFocusNodeId] = useState<string | null>(null);

  // Check if help was dismissed
  React.useEffect(() => {
    if (typeof window !== 'undefined') {
      setHelpDismissed(sessionStorage.getItem('paths-help-dismissed') === 'true');
    }
  }, []);

  React.useEffect(() => {
    bumpPathsQualityRevision();
  }, [canvasRefreshKey, selectedProjectId, selectedVersionId, bumpPathsQualityRevision]);

  const handlePathSelect = (pathId: string | null, pathname?: string) => {
    setSelectedPathId(pathId);
    setSelectedPath(pathId && pathname ? { id: pathId, pathname } : null);
    setSelectedOperation(null);
    setSelectedParameter(null);
    setSelectedResponse(null);
    setPathsCanvasPendingFocusNodeId(null);
  };

  const handleOperationFocusFromSidebar = React.useCallback(
    (pathId: string, pathname: string, operation: { id: string; operation: string }) => {
      setSelectedPathId(pathId);
      setSelectedPath({ id: pathId, pathname });
      setSelectedParameter(null);
      setSelectedResponse(null);
      setSelectedOperation(operation);
      setPathsCanvasPendingFocusNodeId(operation.id);
    },
    []
  );

  const handleOperationSelect = (operation: { id: string; operation: string } | null) => {
    setSelectedOperation(operation);
    if (operation) {
      setSelectedParameter(null);
      setSelectedResponse(null);
    }
  };

  const handleParameterSelect = (parameter: { id: string; name: string; operationId: string } | null) => {
    setSelectedParameter(parameter);
    if (parameter) {
      setSelectedOperation(null);
      setSelectedResponse(null);
    }
  };

  const handleResponseSelect = (response: { id: string; statusCode: string; description: string } | null) => {
    // Force panel refresh by updating the refresh key when selecting a response
    // This ensures the panel reloads data even if clicking the same response node
    if (response) {
      setResponsePanelRefreshKey(prev => prev + 1);
    }
    setSelectedResponse(response);
    if (response) {
      setSelectedOperation(null);
      setSelectedParameter(null);
    }
  };

  const handleCanvasRefresh = () => {
    setCanvasRefreshKey(prev => prev + 1);
    // Also refresh response panel if it's open
    setResponsePanelRefreshKey(prev => prev + 1);
  };

  const handlePathnameUpdated = (nextPathname: string) => {
    setSelectedPath((prev) => (prev ? { ...prev, pathname: nextPathname } : null));
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
        /* Three-Panel Layout: Sidebar | Canvas | Properties */
        <div className="flex-1 flex h-full overflow-hidden relative">
          {pathsViewMode === 'code' ? (
            <PathsCodeView refreshKey={canvasRefreshKey} />
          ) : (
            <>
          {/* Left Sidebar */}
          <PathsSidebar
            activeTab={activeTab}
            onTabChange={(tab) => setActiveTab(tab)}
            selectedPathId={selectedPathId}
            onPathSelect={handlePathSelect}
            onOperationFocus={handleOperationFocusFromSidebar}
            onSecurityRefresh={handleCanvasRefresh}
          />

          {/* Center Canvas */}
          <div className="flex-1 relative">
            {!selectedPathId && (
              <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
                <div className="bg-white/90 dark:bg-gray-800/90 backdrop-blur-sm border border-gray-200 dark:border-gray-700 rounded-xl p-6 shadow-xl max-w-md mx-4 pointer-events-auto">
                  <div className="text-center">
                    <div className="w-16 h-16 mx-auto mb-4 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center">
                      <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                      </svg>
                    </div>
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                      Select a Path
                    </h3>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                      Choose a path from the sidebar to start creating endpoints.
                    </p>
                    <div className="text-xs text-gray-500 dark:text-gray-500 space-y-1">
                      <p>💡 <strong>Tip:</strong> Drag operations from the sidebar to the canvas</p>
                      <p>💡 <strong>Tip:</strong> Drag classes/properties onto operations to define request/response schemas</p>
                    </div>
                  </div>
                </div>
              </div>
            )}
            <PathsCanvasView
              selectedPathId={selectedPathId}
              pathname={selectedPath?.pathname ?? null}
              onOperationSelect={handleOperationSelect}
              onParameterSelect={handleParameterSelect}
              onResponseSelect={handleResponseSelect}
              refreshKey={canvasRefreshKey}
              onRefresh={handleCanvasRefresh}
              onPathnameUpdated={handlePathnameUpdated}
              pendingFocusNodeId={pathsCanvasPendingFocusNodeId}
              onPendingFocusComplete={() => setPathsCanvasPendingFocusNodeId(null)}
            />
          </div>

          {/* Right Properties Panel - Operation */}
          {selectedOperation && selectedPath && (
            <OperationPropertiesPanel
              operationId={selectedOperation.id}
              operation={selectedOperation.operation}
              pathname={selectedPath.pathname}
              versionPathId={selectedPathId}
              onClose={() => setSelectedOperation(null)}
              onRefresh={handleCanvasRefresh}
              refreshKey={canvasRefreshKey}
            />
          )}

          {/* Right Properties Panel - Parameter */}
          {selectedParameter && selectedPath && (
            <ParameterPropertiesPanel
              parameterId={selectedParameter.id}
              operationId={selectedParameter.operationId || undefined}
              versionPathId={selectedPath.id}
              pathname={selectedPath.pathname}
              onClose={() => setSelectedParameter(null)}
              onRefresh={handleCanvasRefresh}
            />
          )}

          {/* Right Properties Panel - Response */}
          {selectedResponse && selectedPathId && (
            <ResponsePropertiesPanel
              key={`response-panel-${selectedResponse.id}-${responsePanelRefreshKey}`}
              responseId={selectedResponse.id}
              statusCode={selectedResponse.statusCode}
              initialDescription={selectedResponse.description}
              versionPathId={selectedPathId}
              refreshKey={responsePanelRefreshKey}
              onClose={() => setSelectedResponse(null)}
              onRefresh={handleCanvasRefresh}
            />
          )}

          {/* Help Banner - Show when path is selected but no operation/parameter/response is selected */}
          {selectedPathId && !selectedOperation && !selectedParameter && !selectedResponse && !helpDismissed && (
            <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 z-20 pointer-events-none">
              <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-md border border-gray-200 dark:border-gray-700 rounded-xl px-4 py-3 shadow-xl max-w-2xl mx-4 pointer-events-auto">
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center">
                    <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-1">
                      Drag & Drop Design
                    </h4>
                    <div className="text-xs text-gray-600 dark:text-gray-400 space-y-1">
                      <p>• <strong>Operations:</strong> Drag from sidebar → Drop on canvas</p>
                      <p>• <strong>Schemas:</strong> Drag classes/properties from sidebar → Drop on operation nodes</p>
                      <p>• <strong>Parameters/Responses:</strong> Click operation nodes to configure</p>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      // Store dismissal in sessionStorage
                      if (typeof window !== 'undefined') {
                        sessionStorage.setItem('paths-help-dismissed', 'true');
                        setHelpDismissed(true);
                      }
                    }}
                    className="flex-shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
                    aria-label="Dismiss"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
