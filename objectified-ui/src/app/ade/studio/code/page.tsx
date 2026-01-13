'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import dynamic from 'next/dynamic';
import { Copy, Download, Check } from 'lucide-react';
import * as Select from '@radix-ui/react-select';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import * as Tooltip from '@radix-ui/react-tooltip';
import YAML from 'yaml';
import { useStudio } from '../StudioContext';
import { generateOpenApiSpec } from '../../../utils/openapi';
import { generateArazzoSpec } from '../../../utils/arazzo';
import { generateJsonSchema } from '../../../utils/jsonschema';
import { generateGraphQLSchema } from '../../../utils/graphql';
import { generateSQL, SQLDialect } from '../../../utils/sql-generator';
import { generateAsyncAPISpec } from '../../../utils/asyncapi-generator';
import {
  getProjectsForTenant,
  getVersionsForProject,
  getClassesWithPropertiesAndTags,
} from '../../../../../lib/db/helper';

// Dynamically import Monaco Editor with SSR disabled
const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center">
      <div className="text-gray-500 dark:text-gray-400">Loading editor...</div>
    </div>
  ),
});

interface Project {
  id: string;
  name: string;
  slug: string;
}

interface Version {
  id: string;
  version_id: string;
  description: string;
  published: boolean;
}

interface ClassWithProperties {
  id: string;
  name: string;
  description?: string;
  properties: any[];
  schema?: any;
  tags?: any[];
}

export default function CodePage() {
  const { data: session } = useSession();
  const currentTenantId = (session?.user as any)?.current_tenant_id;

  const { selectedProjectId, selectedVersionId } = useStudio();

  // Theme state
  const [isDark, setIsDark] = useState(false);

  // Projects and versions for display
  const [projects, setProjects] = useState<Project[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);

  // Code view state
  const [codeFormat, setCodeFormat] = useState<'json' | 'yaml'>('json');
  const [codeDisplayFormat, setCodeDisplayFormat] = useState<'openapi' | 'arazzo' | 'jsonschema' | 'graphql' | 'sql' | 'asyncapi'>('openapi');
  const [sqlDialect, setSqlDialect] = useState<SQLDialect>('postgresql');
  const [openApiSpec, setOpenApiSpec] = useState<string>('');
  const [arazzoSpec, setArazzoSpec] = useState<string>('');
  const [jsonSchemaSpec, setJsonSchemaSpec] = useState<string>('');
  const [graphqlSpec, setGraphqlSpec] = useState<string>('');
  const [sqlSpec, setSqlSpec] = useState<string>('');
  const [asyncApiSpec, setAsyncApiSpec] = useState<string>('');
  const [codeCopied, setCodeCopied] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // Check dark mode - prioritize localStorage, then fall back to system preference
  useEffect(() => {
    const initTheme = () => {
      const savedTheme = localStorage.getItem('theme');
      const html = document.documentElement;

      if (savedTheme === 'dark') {
        html.classList.add('dark');
        setIsDark(true);
      } else if (savedTheme === 'light') {
        html.classList.remove('dark');
        setIsDark(false);
      } else {
        // No saved preference - use system preference
        const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        if (systemPrefersDark) {
          html.classList.add('dark');
          setIsDark(true);
        } else {
          html.classList.remove('dark');
          setIsDark(false);
        }
      }
    };

    initTheme();

    // Listen for class changes
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class']
    });

    return () => {
      observer.disconnect();
    };
  }, []);

  // Load projects
  useEffect(() => {
    const loadProjects = async () => {
      if (!currentTenantId) return;
      try {
        const result = await getProjectsForTenant(currentTenantId);
        const data = JSON.parse(result);
        setProjects(data);
      } catch (error) {
        console.error('Failed to load projects:', error);
      }
    };
    loadProjects();
  }, [currentTenantId]);

  // Load versions when project changes
  useEffect(() => {
    const loadVersions = async () => {
      if (!selectedProjectId) return;
      try {
        const result = await getVersionsForProject(selectedProjectId);
        const data = JSON.parse(result);
        setVersions(data);
      } catch (error) {
        console.error('Failed to load versions:', error);
      }
    };
    loadVersions();
  }, [selectedProjectId]);

  // Generate specs when version is selected
  useEffect(() => {
    const generateSpecs = async () => {
      if (!selectedVersionId || !selectedProjectId) {
        setOpenApiSpec('');
        setArazzoSpec('');
        setJsonSchemaSpec('');
        setGraphqlSpec('');
        setSqlSpec('');
        setAsyncApiSpec('');
        return;
      }

      setIsLoading(true);
      try {
        // Load classes with properties
        const result = await getClassesWithPropertiesAndTags(selectedVersionId);
        const classesWithProperties: ClassWithProperties[] = JSON.parse(result);

        const currentProject = projects.find(p => p.id === selectedProjectId);
        const currentVersion = versions.find(v => v.id === selectedVersionId);

        // Generate all specs
        const openApiContent = await generateOpenApiSpec(classesWithProperties, {
          projectName: currentProject?.name || 'API',
          version: currentVersion?.version_id || '1.0.0',
          description: currentVersion?.description || ''
        });
        setOpenApiSpec(openApiContent);

        const arazzoContent = await generateArazzoSpec(classesWithProperties, {
          projectName: currentProject?.name || 'API',
          version: currentVersion?.version_id || '1.0.0',
          description: currentVersion?.description || ''
        });
        setArazzoSpec(arazzoContent);

        const jsonSchemaContent = generateJsonSchema(classesWithProperties, {
          projectName: currentProject?.name || 'Schema',
          description: currentVersion?.description || ''
        });
        setJsonSchemaSpec(jsonSchemaContent);

        const graphqlContent = generateGraphQLSchema(classesWithProperties, {
          projectName: currentProject?.name || 'API',
          version: currentVersion?.version_id || '1.0.0',
          description: currentVersion?.description || ''
        });
        setGraphqlSpec(graphqlContent);

        // Generate SQL DDL
        const sqlContent = generateSQL(classesWithProperties, sqlDialect, {
          includeDropStatements: false,
          includeComments: true,
          schemaName: '',
          namingConvention: 'snake_case'
        });
        setSqlSpec(sqlContent);

        // Generate AsyncAPI
        const asyncApiContent = generateAsyncAPISpec(classesWithProperties, {
          projectName: currentProject?.name || 'Event API',
          version: currentVersion?.version_id || '1.0.0',
          description: currentVersion?.description || '',
          protocol: 'kafka'
        });
        setAsyncApiSpec(asyncApiContent);
      } catch (error) {
        console.error('Failed to generate specs:', error);
      } finally {
        setIsLoading(false);
      }
    };

    generateSpecs();
  }, [selectedVersionId, selectedProjectId, projects, versions, sqlDialect]);

  const selectedProject = projects.find(p => p.id === selectedProjectId);
  const selectedVersion = versions.find(v => v.id === selectedVersionId);

  // Get current spec content
  const getSpecContent = useCallback(() => {
    const specContent = codeDisplayFormat === 'openapi'
      ? openApiSpec
      : codeDisplayFormat === 'arazzo'
      ? arazzoSpec
      : codeDisplayFormat === 'graphql'
      ? graphqlSpec
      : codeDisplayFormat === 'sql'
      ? sqlSpec
      : codeDisplayFormat === 'asyncapi'
      ? asyncApiSpec
      : jsonSchemaSpec;

    if (!specContent) return '';

    // GraphQL SDL and SQL DDL are always plain text, no JSON/YAML conversion
    if (codeDisplayFormat === 'graphql' || codeDisplayFormat === 'sql') {
      return specContent;
    }

    try {
      return codeFormat === 'json'
        ? specContent
        : YAML.stringify(JSON.parse(specContent));
    } catch {
      return specContent;
    }
  }, [codeDisplayFormat, openApiSpec, arazzoSpec, jsonSchemaSpec, graphqlSpec, sqlSpec, asyncApiSpec, codeFormat]);

  // Handle copy
  const handleCopy = useCallback(() => {
    const content = getSpecContent();
    navigator.clipboard.writeText(content);
    setCodeCopied(true);
    setTimeout(() => setCodeCopied(false), 2000);
  }, [getSpecContent]);

  // Handle download
  const handleDownload = useCallback(() => {
    const content = getSpecContent();

    // Handle GraphQL separately - always text/plain with .graphql extension
    if (codeDisplayFormat === 'graphql') {
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;

      const projectSlug = selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'api';
      const versionSlug = selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0';
      link.download = `${projectSlug}-${versionSlug}.graphql`;

      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      return;
    }

    // Handle SQL DDL separately - always text/plain with .sql extension
    if (codeDisplayFormat === 'sql') {
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;

      const projectSlug = selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'api';
      const versionSlug = selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0';
      link.download = `${projectSlug}-${versionSlug}-${sqlDialect}.sql`;

      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      return;
    }

    // Handle other formats (OpenAPI, AsyncAPI, Arazzo, JSON Schema)
    const mimeType = codeFormat === 'json' ? 'application/json' : 'text/yaml';
    const extension = codeFormat === 'json' ? 'json' : 'yaml';

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);

    const link = document.createElement('a');
    link.href = url;

    const projectSlug = selectedProject?.slug || selectedProject?.name?.toLowerCase().replace(/\s+/g, '-') || 'api';
    const versionSlug = selectedVersion?.version_id?.replace(/\./g, '-') || '1-0-0';
    const specType = codeDisplayFormat === 'openapi' ? 'openapi' : codeDisplayFormat === 'asyncapi' ? 'asyncapi' : codeDisplayFormat === 'arazzo' ? 'arazzo' : 'jsonschema';
    link.download = `${projectSlug}-${versionSlug}-${specType}.${extension}`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [getSpecContent, codeFormat, codeDisplayFormat, selectedProject, selectedVersion, sqlDialect]);

  if (!selectedProjectId || !selectedVersionId) {
    return (
      <div className="h-full flex items-center justify-center bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800">
        <div className="relative">
          <div className="absolute -top-20 -left-20 w-40 h-40 bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-full blur-3xl opacity-60" />
          <div className="absolute -bottom-20 -right-20 w-40 h-40 bg-gradient-to-br from-blue-100 to-cyan-100 dark:from-blue-900/20 dark:to-cyan-900/20 rounded-full blur-3xl opacity-60" />

          <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-12 md:p-16 text-center shadow-xl shadow-gray-200/50 dark:shadow-gray-900/50">
            <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-500/30">
              <svg className="h-10 w-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
            </div>
            <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">
              No Project Selected
            </h3>
            <p className="text-gray-500 dark:text-gray-400 max-w-sm mx-auto leading-relaxed">
              Select a project and version from the header to generate code specifications
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <Tooltip.Provider>
      <div className="h-full flex flex-col bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800">
        {/* Code View Header */}
        <div className="bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border-b border-gray-200/80 dark:border-gray-700/80 px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-5">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl shadow-lg shadow-indigo-500/25">
                  <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                </div>
                <div>
                  <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">
                    {codeDisplayFormat === 'openapi'
                      ? 'OpenAPI 3.1.0'
                      : codeDisplayFormat === 'arazzo'
                      ? 'Arazzo v1.0.1'
                      : codeDisplayFormat === 'graphql'
                      ? 'GraphQL SDL'
                      : codeDisplayFormat === 'sql'
                      ? `SQL DDL (${sqlDialect.charAt(0).toUpperCase() + sqlDialect.slice(1)})`
                      : codeDisplayFormat === 'asyncapi'
                      ? 'AsyncAPI 3.0.0'
                      : 'JSON Schema'}
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    {selectedProject?.name} • v{selectedVersion?.version_id}
                  </p>
                </div>
              </div>

              {/* Display Format Selector */}
              <div className="flex items-center gap-3 pl-5 border-l border-gray-200 dark:border-gray-700">
                <Select.Root value={codeDisplayFormat} onValueChange={(value) => setCodeDisplayFormat(value as 'openapi' | 'arazzo' | 'jsonschema' | 'graphql' | 'sql' | 'asyncapi')}>
                  <Select.Trigger className="inline-flex items-center justify-between gap-2 px-3 py-2 text-sm font-medium border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-all duration-200 cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 min-w-[200px]">
                    <Select.Value />
                    <Select.Icon>
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </Select.Icon>
                  </Select.Trigger>
                  <Select.Portal>
                    <Select.Content className="overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[9999]">
                      <Select.Viewport className="p-1">
                        <Select.Item value="openapi" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <Select.ItemText>OpenAPI Specification</Select.ItemText>
                          <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                            <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                          </Select.ItemIndicator>
                        </Select.Item>
                        <Select.Item value="asyncapi" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <Select.ItemText>AsyncAPI Specification</Select.ItemText>
                          <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                            <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                          </Select.ItemIndicator>
                        </Select.Item>
                        <Select.Item value="arazzo" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <Select.ItemText>Arazzo Specification</Select.ItemText>
                          <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                            <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                          </Select.ItemIndicator>
                        </Select.Item>
                        <Select.Item value="jsonschema" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <Select.ItemText>JSON Schema</Select.ItemText>
                          <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                            <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                          </Select.ItemIndicator>
                        </Select.Item>
                        <Select.Separator className="h-px my-1 mx-2 bg-gray-200 dark:bg-gray-700" />
                        <Select.Item value="graphql" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <Select.ItemText>GraphQL SDL</Select.ItemText>
                          <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                            <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                          </Select.ItemIndicator>
                        </Select.Item>
                        <Select.Item value="sql" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                          <Select.ItemText>SQL DDL</Select.ItemText>
                          <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                            <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                          </Select.ItemIndicator>
                        </Select.Item>
                      </Select.Viewport>
                    </Select.Content>
                  </Select.Portal>
                </Select.Root>

                {/* SQL Dialect Selector - only shown when SQL is selected */}
                {codeDisplayFormat === 'sql' && (
                  <Select.Root value={sqlDialect} onValueChange={(value) => setSqlDialect(value as SQLDialect)}>
                    <Select.Trigger className="inline-flex items-center justify-between gap-2 px-3 py-2 text-sm font-medium border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-all duration-200 cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 min-w-[140px]">
                      <Select.Value />
                      <Select.Icon>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </Select.Icon>
                    </Select.Trigger>
                    <Select.Portal>
                      <Select.Content className="overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-[9999]">
                        <Select.Viewport className="p-1">
                          <Select.Item value="postgresql" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                            <Select.ItemText>PostgreSQL</Select.ItemText>
                            <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                              <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                            </Select.ItemIndicator>
                          </Select.Item>
                          <Select.Item value="mysql" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                            <Select.ItemText>MySQL</Select.ItemText>
                            <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                              <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                            </Select.ItemIndicator>
                          </Select.Item>
                          <Select.Item value="sqlserver" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                            <Select.ItemText>SQL Server</Select.ItemText>
                            <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                              <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                            </Select.ItemIndicator>
                          </Select.Item>
                          <Select.Item value="oracle" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                            <Select.ItemText>Oracle</Select.ItemText>
                            <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                              <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                            </Select.ItemIndicator>
                          </Select.Item>
                          <Select.Item value="sqlite" className="relative flex items-center px-8 py-2 text-sm text-gray-700 dark:text-gray-300 rounded-md outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700">
                            <Select.ItemText>SQLite</Select.ItemText>
                            <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                              <Check className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                            </Select.ItemIndicator>
                          </Select.Item>
                        </Select.Viewport>
                      </Select.Content>
                    </Select.Portal>
                  </Select.Root>
                )}

                {/* Format Toggle (JSON/YAML) - hidden for GraphQL and SQL */}
                {codeDisplayFormat !== 'graphql' && codeDisplayFormat !== 'sql' && (
                  <ToggleGroup.Root
                    type="single"
                    value={codeFormat}
                    onValueChange={(value) => {
                      if (value) setCodeFormat(value as 'json' | 'yaml');
                    }}
                    className="inline-flex items-center bg-gray-100 dark:bg-gray-700/50 rounded-lg p-1"
                  >
                    <ToggleGroup.Item
                      value="json"
                      className="px-3 py-2 text-xs font-semibold rounded-md transition-all duration-200 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm data-[state=off]:text-gray-600 dark:data-[state=off]:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                    >
                      JSON
                    </ToggleGroup.Item>
                    <ToggleGroup.Item
                      value="yaml"
                      className="px-3 py-2 text-xs font-semibold rounded-md transition-all duration-200 data-[state=on]:bg-white dark:data-[state=on]:bg-gray-600 data-[state=on]:text-indigo-600 dark:data-[state=on]:text-indigo-400 data-[state=on]:shadow-sm data-[state=off]:text-gray-600 dark:data-[state=off]:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                    >
                      YAML
                    </ToggleGroup.Item>
                  </ToggleGroup.Root>
                )}
              </div>
            </div>

            <div className="flex gap-2">
              {/* Copy Button */}
              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <button
                    onClick={handleCopy}
                    disabled={codeCopied || isLoading}
                    className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
                      codeCopied
                        ? 'bg-green-500 text-white shadow-lg shadow-green-500/25'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                    }`}
                  >
                    {codeCopied ? <Check size={16} /> : <Copy size={16} />}
                    {codeCopied ? 'Copied!' : 'Copy'}
                  </button>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content
                    className="bg-gray-900 dark:bg-gray-700 text-white text-xs px-3 py-1.5 rounded-lg shadow-lg z-[10000]"
                    sideOffset={5}
                  >
                    {codeCopied ? 'Copied to clipboard!' : 'Copy to clipboard'}
                    <Tooltip.Arrow className="fill-gray-900 dark:fill-gray-700" />
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>

              {/* Download Button */}
              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <button
                    onClick={handleDownload}
                    disabled={isLoading}
                    className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white rounded-lg transition-all duration-200 shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40"
                  >
                    <Download size={16} />
                    Download
                  </button>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content
                    className="bg-gray-900 dark:bg-gray-700 text-white text-xs px-3 py-1.5 rounded-lg shadow-lg z-[10000]"
                    sideOffset={5}
                  >
                    Download as {codeFormat.toUpperCase()} file
                    <Tooltip.Arrow className="fill-gray-900 dark:fill-gray-700" />
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            </div>
          </div>
        </div>

        {/* Monaco Editor */}
        <div className="flex-1 overflow-hidden">
          {isLoading ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Generating specification...</p>
              </div>
            </div>
          ) : (
            <Editor
              height="100%"
              language={codeDisplayFormat === 'graphql' ? 'graphql' : codeDisplayFormat === 'sql' ? 'sql' : codeFormat}
              value={getSpecContent()}
              theme={isDark ? 'vs-dark' : 'light'}
              options={{
                readOnly: true,
                minimap: { enabled: true },
                fontSize: 13,
                fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                wordWrap: 'on',
                padding: { top: 16, bottom: 16 },
                automaticLayout: true,
              }}
            />
          )}
        </div>
      </div>
    </Tooltip.Provider>
  );
}

