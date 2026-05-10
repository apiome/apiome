'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import YAML from 'yaml';
import type { Monaco } from '@monaco-editor/react';
import type { editor } from 'monaco-editor';
import { useStudio } from '../../StudioContext';
import { loadPathsCodeSpec } from '../lib/load-paths-code-spec';
import { markersForParsedText } from '../lib/paths-code-markers';
import { sortProjectsForSelector } from '@/app/utils/project-selector-sort';
import { AlertTriangle } from 'lucide-react';

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center bg-gray-50 dark:bg-gray-900">
      <p className="text-sm text-gray-500 dark:text-gray-400">Loading editor…</p>
    </div>
  ),
});

type CodeFormat = 'json' | 'yaml';

interface ProjectRow {
  id: string;
  name: string;
  slug: string;
}

interface VersionRow {
  id: string;
  version_id: string;
  description: string;
}

export interface PathsCodeViewProps {
  /** Bumps when the Paths canvas or sidebar refreshes operations / layout saves. */
  refreshKey: number;
}

export default function PathsCodeView({ refreshKey }: PathsCodeViewProps) {
  const { selectedProjectId, selectedVersionId } = useStudio();
  const [codeFormat, setCodeFormat] = useState<CodeFormat>('yaml');
  const [isDark, setIsDark] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pathsObject, setPathsObject] = useState<Record<string, unknown>>({});
  const [mergedSpecJson, setMergedSpecJson] = useState<string>('{}');
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [versions, setVersions] = useState<VersionRow[]>([]);

  const pathsEditorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const mergedEditorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const pathsParseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mergedParseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const sync = () => setIsDark(document.documentElement.classList.contains('dark'));
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/projects');
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data.success && data.projects) {
          setProjects(sortProjectsForSelector(data.projects));
        }
      } catch {
        if (!cancelled) setProjects([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedProjectId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/versions?projectId=${selectedProjectId}`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data.success && data.versions) {
          setVersions(data.versions);
        }
      } catch {
        if (!cancelled) setVersions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedVersionId || !selectedProjectId) {
      setPathsObject({});
      setMergedSpecJson('{}');
      return;
    }

    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const project = projects.find((p) => p.id === selectedProjectId);
        const version = versions.find((v) => v.id === selectedVersionId);
        const { pathsObject: po, mergedSpecJson: merged } = await loadPathsCodeSpec({
          versionId: selectedVersionId,
          projectName: project?.name || 'API',
          versionLabel: version?.version_id || '1.0.0',
          versionDescription: version?.description || '',
        });
        if (!cancelled) {
          setPathsObject(po);
          setMergedSpecJson(merged);
        }
      } catch (err) {
        console.error('[PathsCodeView] load failed:', err);
        if (!cancelled) {
          setPathsObject({});
          setMergedSpecJson('{}');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [selectedVersionId, selectedProjectId, refreshKey, projects, versions]);

  const pathsDisplay = useMemo(() => {
    try {
      return codeFormat === 'json'
        ? JSON.stringify(pathsObject, null, 2)
        : YAML.stringify(pathsObject);
    } catch {
      return '';
    }
  }, [pathsObject, codeFormat]);

  const mergedDisplay = useMemo(() => {
    try {
      const mergedObj = JSON.parse(mergedSpecJson) as Record<string, unknown>;
      return codeFormat === 'json'
        ? JSON.stringify(mergedObj, null, 2)
        : YAML.stringify(mergedObj);
    } catch {
      return mergedSpecJson;
    }
  }, [mergedSpecJson, codeFormat]);

  useEffect(() => {
    if (pathsParseTimerRef.current) clearTimeout(pathsParseTimerRef.current);
    pathsParseTimerRef.current = setTimeout(() => {
      const editorInst = pathsEditorRef.current;
      const model = editorInst?.getModel();
      if (!model || !monacoRef.current) return;
      monacoRef.current.editor.setModelMarkers(model, 'paths-code-parse', markersForParsedText(pathsDisplay, codeFormat));
    }, 320);
    return () => {
      if (pathsParseTimerRef.current) clearTimeout(pathsParseTimerRef.current);
    };
  }, [pathsDisplay, codeFormat]);

  useEffect(() => {
    if (mergedParseTimerRef.current) clearTimeout(mergedParseTimerRef.current);
    mergedParseTimerRef.current = setTimeout(() => {
      const editorInst = mergedEditorRef.current;
      const model = editorInst?.getModel();
      if (!model || !monacoRef.current) return;
      monacoRef.current.editor.setModelMarkers(model, 'paths-code-parse', markersForParsedText(mergedDisplay, codeFormat));
    }, 320);
    return () => {
      if (mergedParseTimerRef.current) clearTimeout(mergedParseTimerRef.current);
    };
  }, [mergedDisplay, codeFormat]);

  const selectedProject = projects.find((p) => p.id === selectedProjectId);
  const selectedVersion = versions.find((v) => v.id === selectedVersionId);

  const onPathsMount = useCallback((ed: editor.IStandaloneCodeEditor, monacoInstance: Monaco) => {
    pathsEditorRef.current = ed;
    monacoRef.current = monacoInstance;
  }, []);

  const onMergedMount = useCallback((ed: editor.IStandaloneCodeEditor, monacoInstance: Monaco) => {
    mergedEditorRef.current = ed;
    monacoRef.current = monacoInstance;
  }, []);

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-gray-50 dark:bg-gray-900">
      <div className="shrink-0 border-b border-gray-200 dark:border-gray-700 px-4 py-3 bg-white/90 dark:bg-gray-800/90">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Paths code</h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {selectedProject?.name ?? 'Project'} · {selectedVersion?.version_id ?? 'version'}
            </p>
          </div>
          <ToggleGroup.Root
            type="single"
            value={codeFormat}
            onValueChange={(v) => {
              if (v === 'json' || v === 'yaml') setCodeFormat(v);
            }}
            className="inline-flex bg-gray-100 dark:bg-gray-700/50 rounded-lg p-1"
          >
            <ToggleGroup.Item
              value="yaml"
              className="px-3 py-1.5 text-xs font-semibold rounded-md transition-all data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400"
            >
              YAML
            </ToggleGroup.Item>
            <ToggleGroup.Item
              value="json"
              className="px-3 py-1.5 text-xs font-semibold rounded-md transition-all data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm text-gray-600 dark:text-gray-400"
            >
              JSON
            </ToggleGroup.Item>
          </ToggleGroup.Root>
        </div>
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200/80 bg-amber-50/90 px-3 py-2 text-xs text-amber-950 dark:border-amber-800/60 dark:bg-amber-950/40 dark:text-amber-100">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" aria-hidden />
          <p>
            <span className="font-medium">Read-only (MVP).</span> Paths are generated from the canvas and database.
            Editing code here does not update the canvas. Switch to Canvas to design; merged preview updates when the
            version or paths refresh.
          </p>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex flex-col md:flex-row">
        <div className="flex-1 min-h-[240px] md:min-h-0 flex flex-col border-b md:border-b-0 md:border-r border-gray-200 dark:border-gray-700">
          <div className="shrink-0 px-3 py-2 text-xs font-medium text-gray-600 dark:text-gray-300 bg-gray-100/80 dark:bg-gray-800/80">
            OpenAPI paths (fragment)
          </div>
          <div className="flex-1 min-h-0">
            {loading ? (
              <div className="h-full flex items-center justify-center text-sm text-gray-500 dark:text-gray-400">
                Loading…
              </div>
            ) : (
              <Editor
                path="paths-fragment"
                height="100%"
                language={codeFormat === 'json' ? 'json' : 'yaml'}
                value={pathsDisplay}
                theme={isDark ? 'vs-dark' : 'light'}
                onMount={onPathsMount}
                options={{
                  readOnly: true,
                  minimap: { enabled: true },
                  fontSize: 13,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  automaticLayout: true,
                  padding: { top: 12, bottom: 12 },
                }}
              />
            )}
          </div>
        </div>
        <div className="flex-1 min-h-[240px] md:min-h-0 flex flex-col">
          <div className="shrink-0 px-3 py-2 text-xs font-medium text-gray-600 dark:text-gray-300 bg-gray-100/80 dark:bg-gray-800/80">
            Merged OpenAPI (paths + components/schemas)
          </div>
          <div className="flex-1 min-h-0">
            {loading ? (
              <div className="h-full flex items-center justify-center text-sm text-gray-500 dark:text-gray-400">
                Loading…
              </div>
            ) : (
              <Editor
                path="merged-preview"
                height="100%"
                language={codeFormat === 'json' ? 'json' : 'yaml'}
                value={mergedDisplay}
                theme={isDark ? 'vs-dark' : 'light'}
                onMount={onMergedMount}
                options={{
                  readOnly: true,
                  minimap: { enabled: true },
                  fontSize: 13,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  automaticLayout: true,
                  padding: { top: 12, bottom: 12 },
                }}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
