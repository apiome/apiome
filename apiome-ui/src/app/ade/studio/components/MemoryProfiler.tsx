'use client';

import * as React from 'react';
import { useState, useEffect, useCallback, useRef } from 'react';
import { Activity, Cpu, HardDrive, TrendingUp, TrendingDown, Minus, RefreshCw, Trash2, X, ChevronDown, ChevronUp } from 'lucide-react';
import * as Tooltip from '@radix-ui/react-tooltip';

// Extend Performance interface to include memory (Chrome-specific)
interface PerformanceMemory {
  usedJSHeapSize: number;
  totalJSHeapSize: number;
  jsHeapSizeLimit: number;
}

interface ExtendedPerformance extends Performance {
  memory?: PerformanceMemory;
}

interface MemorySnapshot {
  timestamp: number;
  usedHeap: number;
  totalHeap: number;
  heapLimit: number;
  nodeCount: number;
  edgeCount: number;
  groupCount: number;
  renderCount: number;
}

interface MemoryProfilerProps {
  nodeCount: number;
  edgeCount: number;
  groupCount: number;
  onClose?: () => void;
  isMinimized?: boolean;
  onMinimizeToggle?: () => void;
}

// Format bytes to human-readable size
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

// Calculate percentage
function calcPercentage(used: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((used / total) * 100);
}

// Get trend icon based on memory change
function getTrendIcon(current: number, previous: number) {
  if (previous === 0) return <Minus className="w-3 h-3 text-gray-400" />;
  const change = ((current - previous) / previous) * 100;
  if (change > 5) return <TrendingUp className="w-3 h-3 text-red-500" />;
  if (change < -5) return <TrendingDown className="w-3 h-3 text-green-500" />;
  return <Minus className="w-3 h-3 text-gray-400" />;
}

// Get memory status color based on usage percentage
function getMemoryStatusColor(percentage: number): string {
  if (percentage < 50) return 'text-green-500';
  if (percentage < 75) return 'text-yellow-500';
  if (percentage < 90) return 'text-orange-500';
  return 'text-red-500';
}

function getMemoryBarColor(percentage: number): string {
  if (percentage < 50) return 'bg-green-500';
  if (percentage < 75) return 'bg-yellow-500';
  if (percentage < 90) return 'bg-orange-500';
  return 'bg-red-500';
}

export default function MemoryProfiler({
  nodeCount,
  edgeCount,
  groupCount,
  onClose,
  isMinimized = false,
  onMinimizeToggle,
}: MemoryProfilerProps) {
  // Check if memory API is available on initial render
  const [isSupported] = useState(() => {
    if (typeof window === 'undefined') return false;
    const perf = performance as ExtendedPerformance;
    return !!perf.memory;
  });
  const [currentMemory, setCurrentMemory] = useState<MemorySnapshot | null>(null);
  const [snapshots, setSnapshots] = useState<MemorySnapshot[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [gcHint, setGcHint] = useState<string | null>(null);
  const [updateCount, setUpdateCount] = useState(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  // Collect memory snapshot
  const collectSnapshot = useCallback((): MemorySnapshot | null => {
    const perf = performance as ExtendedPerformance;
    if (!perf.memory) return null;

    return {
      timestamp: Date.now(),
      usedHeap: perf.memory.usedJSHeapSize,
      totalHeap: perf.memory.totalJSHeapSize,
      heapLimit: perf.memory.jsHeapSizeLimit,
      nodeCount,
      edgeCount,
      groupCount,
      renderCount: 0, // Deprecated - kept for interface compatibility
    };
  }, [nodeCount, edgeCount, groupCount]);

  // Update current memory periodically
  useEffect(() => {
    const updateMemory = () => {
      const snapshot = collectSnapshot();
      if (snapshot) {
        setCurrentMemory(snapshot);
        setUpdateCount(prev => prev + 1);
      }
    };

    updateMemory();
    const interval = setInterval(updateMemory, 1000);
    return () => clearInterval(interval);
  }, [collectSnapshot]);

  // Recording mode
  useEffect(() => {
    if (isRecording) {
      intervalRef.current = setInterval(() => {
        const snapshot = collectSnapshot();
        if (snapshot) {
          setSnapshots(prev => [...prev.slice(-59), snapshot]); // Keep last 60 snapshots (1 minute at 1s intervals)
        }
      }, 1000);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [isRecording, collectSnapshot]);

  // Take manual snapshot
  const takeSnapshot = useCallback(() => {
    const snapshot = collectSnapshot();
    if (snapshot) {
      setSnapshots(prev => [...prev, snapshot]);
    }
  }, [collectSnapshot]);

  // Clear snapshots
  const clearSnapshots = useCallback(() => {
    setSnapshots([]);
  }, []);

  // Suggest garbage collection (hint only - cannot force GC in browser)
  const suggestGC = useCallback(() => {
    // Try to hint GC by nullifying references and creating memory pressure
    // This is just a hint - browsers may or may not honor it
    setGcHint('GC hint sent. The browser may collect garbage on its next cycle.');

    // Clear the hint after 3 seconds
    setTimeout(() => setGcHint(null), 3000);

    // Some techniques that may encourage GC (browser-dependent):
    // 1. Create and release a large array to trigger memory pressure
    try {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const _ = new Array(1000000).fill(0);
    } catch {
      // Ignore errors
    }
  }, []);

  // Calculate memory change from previous snapshot
  const previousSnapshot = snapshots.length > 1 ? snapshots[snapshots.length - 2] : null;
  const memoryChange = currentMemory && previousSnapshot
    ? currentMemory.usedHeap - previousSnapshot.usedHeap
    : 0;

  // Get memory usage percentage
  const usagePercentage = currentMemory
    ? calcPercentage(currentMemory.usedHeap, currentMemory.heapLimit)
    : 0;

  // Minimized view
  if (isMinimized) {
    return (
      <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-lg shadow-lg border border-gray-200/80 dark:border-gray-700/80 p-2">
        <button
          onClick={onMinimizeToggle}
          className="flex items-center gap-2 text-xs font-medium text-gray-700 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-400"
        >
          <Activity className="w-4 h-4" />
          <span className={getMemoryStatusColor(usagePercentage)}>
            {currentMemory ? formatBytes(currentMemory.usedHeap) : 'N/A'}
          </span>
          <ChevronUp className="w-3 h-3" />
        </button>
      </div>
    );
  }

  return (
    <Tooltip.Provider>
      <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 w-72">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-indigo-500" />
            <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">Memory Profiler</span>
          </div>
          <div className="flex items-center gap-1">
            {onMinimizeToggle && (
              <button
                onClick={onMinimizeToggle}
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
                title="Minimize"
              >
                <ChevronDown className="w-4 h-4" />
              </button>
            )}
            {onClose && (
              <button
                onClick={onClose}
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
                title="Close"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {!isSupported ? (
          <div className="p-4 text-center">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Memory API not available in this browser.
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
              Use Chrome with --enable-precise-memory-info flag
            </p>
          </div>
        ) : (
          <div className="p-3 space-y-3">
            {/* Memory Usage Bar */}
            <div>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-gray-600 dark:text-gray-400">Heap Usage</span>
                <span className={`font-medium ${getMemoryStatusColor(usagePercentage)}`}>
                  {usagePercentage}%
                </span>
              </div>
              <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full ${getMemoryBarColor(usagePercentage)} transition-all duration-300`}
                  style={{ width: `${usagePercentage}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[10px] mt-1 text-gray-500 dark:text-gray-400">
                <span>{currentMemory ? formatBytes(currentMemory.usedHeap) : '-'}</span>
                <span>{currentMemory ? formatBytes(currentMemory.heapLimit) : '-'}</span>
              </div>
            </div>

            {/* Memory Stats Grid */}
            <div className="grid grid-cols-2 gap-2">
              {/* Used Heap */}
              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-2">
                    <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 mb-0.5">
                      <HardDrive className="w-3 h-3" />
                      Used Heap
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                        {currentMemory ? formatBytes(currentMemory.usedHeap) : '-'}
                      </span>
                      {previousSnapshot && getTrendIcon(currentMemory?.usedHeap || 0, previousSnapshot.usedHeap)}
                    </div>
                  </div>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg" sideOffset={4}>
                    Currently allocated JavaScript heap memory
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>

              {/* Total Heap */}
              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-2">
                    <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 mb-0.5">
                      <Cpu className="w-3 h-3" />
                      Total Heap
                    </div>
                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                      {currentMemory ? formatBytes(currentMemory.totalHeap) : '-'}
                    </span>
                  </div>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg" sideOffset={4}>
                    Total heap size including free space
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            </div>

            {/* Canvas Metrics */}
            <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-lg p-2">
              <div className="text-[10px] text-indigo-600 dark:text-indigo-400 font-medium mb-1.5">
                Canvas Metrics
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <div className="text-lg font-bold text-gray-800 dark:text-gray-200">{nodeCount}</div>
                  <div className="text-[10px] text-gray-500 dark:text-gray-400">Nodes</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-gray-800 dark:text-gray-200">{edgeCount}</div>
                  <div className="text-[10px] text-gray-500 dark:text-gray-400">Edges</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-gray-800 dark:text-gray-200">{groupCount}</div>
                  <div className="text-[10px] text-gray-500 dark:text-gray-400">Groups</div>
                </div>
              </div>
            </div>

            {/* Render Count */}
            {/* Update Count */}
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-600 dark:text-gray-400">Memory Updates</span>
              <span className="font-mono text-gray-800 dark:text-gray-200">{updateCount}</span>
            </div>

            {/* Memory Change Indicator */}
            {memoryChange !== 0 && (
              <div className={`text-xs text-center py-1 rounded ${
                memoryChange > 0 
                  ? 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400' 
                  : 'bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400'
              }`}>
                {memoryChange > 0 ? '+' : ''}{formatBytes(memoryChange)} since last snapshot
              </div>
            )}

            {/* GC Hint Message */}
            {gcHint && (
              <div className="text-xs text-center py-1 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400">
                {gcHint}
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={() => setIsRecording(!isRecording)}
                className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                  isRecording
                    ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-900/50'
                    : 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-900/50'
                }`}
              >
                <Activity className={`w-3 h-3 ${isRecording ? 'animate-pulse' : ''}`} />
                {isRecording ? 'Stop' : 'Record'}
              </button>

              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <button
                    onClick={takeSnapshot}
                    className="p-1.5 rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                  >
                    <RefreshCw className="w-4 h-4" />
                  </button>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg" sideOffset={4}>
                    Take Snapshot
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>

              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <button
                    onClick={suggestGC}
                    className="p-1.5 rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg" sideOffset={4}>
                    Suggest GC
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            </div>

            {/* Snapshots List */}
            {snapshots.length > 0 && (
              <div className="border-t border-gray-200 dark:border-gray-700 pt-2">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-medium text-gray-600 dark:text-gray-400">
                    Snapshots ({snapshots.length})
                  </span>
                  <button
                    onClick={clearSnapshots}
                    className="text-[10px] text-red-500 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300"
                  >
                    Clear
                  </button>
                </div>
                <div className="max-h-24 overflow-y-auto space-y-1">
                  {snapshots.slice(-5).reverse().map((snapshot) => (
                    <div
                      key={snapshot.timestamp}
                      className="flex items-center justify-between text-[10px] py-0.5 px-1.5 bg-gray-50 dark:bg-gray-700/50 rounded"
                    >
                      <span className="text-gray-500 dark:text-gray-400">
                        {new Date(snapshot.timestamp).toLocaleTimeString()}
                      </span>
                      <span className="font-medium text-gray-700 dark:text-gray-300">
                        {formatBytes(snapshot.usedHeap)}
                      </span>
                      <span className="text-gray-400 dark:text-gray-500">
                        {snapshot.nodeCount}n / {snapshot.edgeCount}e
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Performance Tips */}
            {usagePercentage > 75 && (
              <div className="text-[10px] text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 rounded p-2">
                <strong>Tip:</strong> High memory usage detected. Consider:
                <ul className="list-disc list-inside mt-1 space-y-0.5">
                  <li>Enabling Level of Detail (LOD) mode</li>
                  <li>Reducing visible nodes with groups</li>
                  <li>Closing unused browser tabs</li>
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </Tooltip.Provider>
  );
}

