'use client';

import { useState, useEffect, useMemo } from 'react';
import { Upload, X, FileCode, AlertTriangle, CheckCircle2, Package, Search, Check, ChevronRight, ArrowUpAZ, ArrowDownAZ, Link2, FileText, Github, ChevronDown } from 'lucide-react';
import * as Checkbox from '@radix-ui/react-checkbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../../ui/Dialog';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../../ui/Collapsible';
import { collectExternalTypeKeysFromDocument } from '../../../../../lib/importers/openapi';
import { Button } from '../../ui/Button';
import { analyzeSpecification, AnalysisResult, extractFileMetadata, FileMetadataPreview } from '../../../utils/openapi-analyzer';
import { importClassesToVersion, ImportClassesResult } from '../../../../../lib/db/class-import-actions';
import { getVersionById, createVersion, bumpPrereleaseVersion } from '../../../../../lib/db/helper';
import UrlImportPanel from '../dashboard/UrlImportPanel';
import ClipboardImportPanel from '../dashboard/ClipboardImportPanel';
import GitImportPanel from '../dashboard/GitImportPanel';
import { ConflictReport, type ImportConflict } from '../dashboard/ConflictReport';
import { isDuplicateSchema } from '../../../utils/schema-definition-equal';
import { detectPropertyConflicts } from '../../../utils/property-conflict-detection';
import { detectReferenceConflicts } from '../../../utils/reference-conflict-detection';
import { detectTypeMismatches } from '../../../utils/type-mismatch-detection';
import { detectSemanticConflicts } from '../../../utils/semantic-conflict-detection';
import {
  getTransitiveDependencies,
  isReferencedBySelectedSchemas,
  getSchemaType,
  getSchemaTags,
  type SchemaDisplayType,
} from '../../../utils/schema-tree-utils';
import { getSmartClassName } from '../../../../../lib/schema-context-naming';

interface ClassImportDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  versionId: string;
  projectId: string;
  existingClassNames: string[];
  /** Map of lowercase class name -> schema for duplicate definition detection (#582). When provided, duplicate_schema is only reported when same name has a different definition. */
  existingClassSchemas?: Record<string, any>;
  userId: string;
}

interface SchemaInfo {
  name: string;
  properties: number;
  selected: boolean;
  exists: boolean; // Whether a class with this name already exists
  schemaType: SchemaDisplayType;
  tags: string[];
}

/** Top-level property names from a schema (for per-property merge #593). */
function getSchemaPropertyNames(schema: any): string[] {
  const names = new Set<string>();
  if (schema?.properties && typeof schema.properties === 'object') {
    Object.keys(schema.properties).forEach((k) => names.add(k));
  }
  if (schema?.allOf && Array.isArray(schema.allOf)) {
    schema.allOf.forEach((item: any) => {
      if (item?.properties && typeof item.properties === 'object') {
        Object.keys(item.properties).forEach((k) => names.add(k));
      }
    });
  }
  return Array.from(names).sort();
}

// Helper function to count properties including those from allOf/oneOf/anyOf
function countSchemaProperties(schema: any): number {
  let count = 0;

  if (schema.properties) {
    count += Object.keys(schema.properties).length;
  }

  if (schema.allOf && Array.isArray(schema.allOf)) {
    schema.allOf.forEach((item: any) => {
      if (item.properties) {
        count += Object.keys(item.properties).length;
      }
    });
  }

  if (schema.oneOf && Array.isArray(schema.oneOf)) {
    let maxOneOf = 0;
    schema.oneOf.forEach((item: any) => {
      if (item.properties) {
        maxOneOf = Math.max(maxOneOf, Object.keys(item.properties).length);
      }
    });
    count += maxOneOf;
  }

  if (schema.anyOf && Array.isArray(schema.anyOf)) {
    let maxAnyOf = 0;
    schema.anyOf.forEach((item: any) => {
      if (item.properties) {
        maxAnyOf = Math.max(maxAnyOf, Object.keys(item.properties).length);
      }
    });
    count += maxAnyOf;
  }

  return count;
}

/** Internal type options for type mapping (#757). */
const INTERNAL_TYPE_OPTIONS: { value: string; label: string; schema: any }[] = [
  { value: '__keep__', label: 'Keep as-is', schema: null as any },
  { value: 'string', label: 'string', schema: { type: 'string' } },
  { value: 'string:date-time', label: 'string (date-time)', schema: { type: 'string', format: 'date-time' } },
  { value: 'string:date', label: 'string (date)', schema: { type: 'string', format: 'date' } },
  { value: 'string:uuid', label: 'string (uuid)', schema: { type: 'string', format: 'uuid' } },
  { value: 'integer', label: 'integer', schema: { type: 'integer' } },
  { value: 'integer:int32', label: 'integer (int32)', schema: { type: 'integer', format: 'int32' } },
  { value: 'integer:int64', label: 'integer (int64)', schema: { type: 'integer', format: 'int64' } },
  { value: 'number', label: 'number', schema: { type: 'number' } },
  { value: 'number:float', label: 'number (float)', schema: { type: 'number', format: 'float' } },
  { value: 'number:double', label: 'number (double)', schema: { type: 'number', format: 'double' } },
  { value: 'boolean', label: 'boolean', schema: { type: 'boolean' } },
];

const ClassImportDialog: React.FC<ClassImportDialogProps> = ({
  open,
  onClose,
  onSuccess,
  versionId,
  projectId,
  existingClassNames,
  existingClassSchemas,
  userId,
}) => {
  const [currentStep, setCurrentStep] = useState<'source' | 'file-upload' | 'select' | 'importing' | 'done'>('source');
  const [selectedSource, setSelectedSource] = useState<'file' | 'url' | 'clipboard' | 'git' | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileMetadata, setFileMetadata] = useState<FileMetadataPreview | null>(null);
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [schemas, setSchemas] = useState<SchemaInfo[]>([]);
  const [searchFilter, setSearchFilter] = useState('');
  const [filterType, setFilterType] = useState<SchemaDisplayType | ''>('');
  const [filterTag, setFilterTag] = useState<string>('');
  const [selectedSchemaName, setSelectedSchemaName] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc' | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportClassesResult | null>(null);
  const [urlContent, setUrlContent] = useState<string | null>(null);
  const [urlFilename, setUrlFilename] = useState<string | null>(null);
  const [clipboardContent, setClipboardContent] = useState<string | null>(null);
  const [clipboardFilename, setClipboardFilename] = useState<string | null>(null);
  const [gitContent, setGitContent] = useState<string | null>(null);
  const [gitFilename, setGitFilename] = useState<string | null>(null);
  const [gitMetadata, setGitMetadata] = useState<FileMetadataPreview | null>(null);
  const [applyNamingConvention, setApplyNamingConvention] = useState(true);
  const [classNamingConvention, setClassNamingConvention] = useState<'PascalCase' | 'camelCase' | 'snake_case' | 'kebab-case' | 'none'>('PascalCase');
  const [propertyNamingConvention, setPropertyNamingConvention] = useState<'PascalCase' | 'camelCase' | 'snake_case' | 'kebab-case' | 'none'>('camelCase');
  /** Per-schema class name overrides for import (#753). When absent, smart name from schema context is used. */
  const [classNameOverrides, setClassNameOverrides] = useState<Record<string, string>>({});
  /** Prefix/suffix applied to every class name after naming convention (#755). */
  const [classPrefix, setClassPrefix] = useState('');
  const [classSuffix, setClassSuffix] = useState('');
  /** Type mapping: external type key → internal JSON Schema (#757). */
  const [typeMapping, setTypeMapping] = useState<Record<string, any>>({});
  /** How to resolve duplicate class names: keep (skip), replace (#587), merge (#588), rename (#589), or createVersion (#590). */
  const [conflictResolution, setConflictResolution] = useState<'keep' | 'replace' | 'merge' | 'rename' | 'createVersion'>('keep');
  /** When conflictResolution is 'rename', suffix applied to conflicting class names (e.g. "Imported" → Pet → PetImported). */
  const [renameSuffix, setRenameSuffix] = useState('Imported');
  /** When conflictResolution is 'createVersion', prerelease suffix for new version (e.g. "b" → 1.0.0b). */
  const [prereleaseSuffix, setPrereleaseSuffix] = useState('b');
  /** When conflictResolution is 'merge', strategy: additive (add new, keep existing) or override (imported wins, constraints merged). */
  const [mergeStrategy, setMergeStrategy] = useState<'additive' | 'override'>('additive');
  /** Per-property merge strategy (#593): schema key → property name → strategy. Only set when user overrides default. */
  const [propertyMergeStrategies, setPropertyMergeStrategies] = useState<Record<string, Record<string, 'additive' | 'override'>>>({});
  /** When true, existing classes can be selected and will be replaced or merged. */
  const overwriteExisting = conflictResolution === 'replace' || conflictResolution === 'merge';
  /** When true, existing (conflicting) classes can be selected—either to overwrite, import under a new name, or import into a new version. */
  const canSelectExisting = overwriteExisting || conflictResolution === 'rename' || conflictResolution === 'createVersion';
  /** When import used "Create new version", the created version_id string (e.g. 1.0.0b) for success message. */
  const [createdVersionLabel, setCreatedVersionLabel] = useState<string | null>(null);

  const handleSourceClick = (source: 'file' | 'url' | 'clipboard' | 'git') => {
    setSelectedSource(source);
    setCurrentStep('file-upload');
  };

  const handleBack = () => {
    if (currentStep === 'done') {
      setCurrentStep('select');
    } else if (currentStep === 'importing') {
      setCurrentStep('select');
    } else if (currentStep === 'select') {
      setCurrentStep('file-upload');
      setAnalysisResult(null);
      setSchemas([]);
    } else if (currentStep === 'file-upload') {
      setCurrentStep('source');
      setSelectedSource(null);
      setSelectedFile(null);
      setFileMetadata(null);
      setUrlContent(null);
      setUrlFilename(null);
      setClipboardContent(null);
      setClipboardFilename(null);
    }
  };

  const handleClose = () => {
    if (importResult?.success && onSuccess) {
      onSuccess();
    }
    // Reset all state
    setCurrentStep('source');
    setSelectedSource(null);
    setSelectedFile(null);
    setFileMetadata(null);
    setAnalysisResult(null);
    setSchemas([]);
    setSearchFilter('');
    setFilterType('');
    setFilterTag('');
    setSelectedSchemaName(null);
    setImportResult(null);
    setUrlContent(null);
    setUrlFilename(null);
    setClipboardContent(null);
    setClipboardFilename(null);
    setGitContent(null);
    setGitFilename(null);
    setGitMetadata(null);
    setApplyNamingConvention(true);
    setClassNamingConvention('PascalCase');
    setPropertyNamingConvention('camelCase');
    setClassNameOverrides({});
    setClassPrefix('');
    setClassSuffix('');
    setConflictResolution('keep');
    setRenameSuffix('Imported');
    setPrereleaseSuffix('b');
    setCreatedVersionLabel(null);
    setMergeStrategy('additive');
    setPropertyMergeStrategies({});
    onClose();
  };

  const handleAnalyze = async () => {
    if (!selectedFile && !urlContent && !clipboardContent && !gitContent) return;

    setIsAnalyzing(true);
    try {
      const content = urlContent || clipboardContent || gitContent || await selectedFile!.text();
      const filename = urlFilename || clipboardFilename || gitFilename || selectedFile?.name || 'openapi-spec.yaml';
      const result = await analyzeSpecification(content, filename);
      setAnalysisResult(result);

      // Initialize schemas list with conflict detection (#580, #582: duplicate = same name + different definition)
      const schemaObj = result.document?.components?.schemas || result.document?.definitions || {};
      const schemaList: SchemaInfo[] = Object.keys(schemaObj).map(name => {
        const raw = schemaObj[name];
        const exists = isDuplicateSchema(name, raw, existingClassNames, existingClassSchemas);
        return {
          name,
          properties: countSchemaProperties(raw),
          selected: !exists, // Auto-select only non-conflicting classes
          exists,
          schemaType: getSchemaType(raw),
          tags: getSchemaTags(raw),
        };
      });
      setSchemas(schemaList);
      setCurrentStep('select');
    } catch (error) {
      console.error('Analysis error:', error);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleUrlSpecificationFetched = async (content: string, filename: string) => {
    setUrlContent(content);
    setUrlFilename(filename);

    // Auto-analyze when URL content is fetched
    setIsAnalyzing(true);
    try {
      const result = await analyzeSpecification(content, filename);
      setAnalysisResult(result);

      // Initialize schemas list with conflict detection (#580, #582: duplicate = same name + different definition)
      const schemaObj = result.document?.components?.schemas || result.document?.definitions || {};
      const schemaList: SchemaInfo[] = Object.keys(schemaObj).map(name => {
        const raw = schemaObj[name];
        const exists = isDuplicateSchema(name, raw, existingClassNames, existingClassSchemas);
        return {
          name,
          properties: countSchemaProperties(raw),
          selected: !exists,
          exists,
          schemaType: getSchemaType(raw),
          tags: getSchemaTags(raw),
        };
      });
      setSchemas(schemaList);
      setCurrentStep('select');
    } catch (error) {
      console.error('URL content analysis error:', error);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleClipboardSpecificationReady = (content: string, filename: string) => {
    setClipboardContent(content);
    setClipboardFilename(filename);
  };

  const handleGitSpecificationFetched = (content: string, filename: string, metadata?: FileMetadataPreview) => {
    setGitContent(content);
    setGitFilename(filename);
    setGitMetadata(metadata || null);
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFileSelect(files[0]);
    }
  };

  const handleFileSelect = async (file: File) => {
    const validExtensions = ['.yaml', '.yml', '.json', '.graphql', '.gql'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();

    if (validExtensions.includes(fileExtension)) {
      setSelectedFile(file);
      setFileMetadata(null);

      setIsLoadingMetadata(true);
      try {
        const content = await file.text();
        const metadata = extractFileMetadata(content);
        setFileMetadata(metadata);
      } catch (error) {
        console.error('Error extracting metadata:', error);
      } finally {
        setIsLoadingMetadata(false);
      }
    } else {
      console.error('Invalid file type');
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelect(e.target.files[0]);
    }
  };

  const handleToggleSchema = (name: string) => {
    const schemaObj = (analysisResult?.document?.components?.schemas ?? analysisResult?.document?.definitions ?? {}) as Record<string, unknown>;
    const current = schemas.find((s) => s.name === name);
    if (!current) return;
    if (current.exists && !canSelectExisting) return;

    if (current.selected) {
      // Deselecting: only allow if no other selected schema references this one (#579)
      if (isReferencedBySelectedSchemas(name, schemas, schemaObj)) return;
      setSchemas((prev) => prev.map((s) => (s.name === name ? { ...s, selected: false } : s)));
    } else {
      // Selecting: also select all transitive dependencies (#579). When overwriteExisting, allow selecting existing too.
      const deps = getTransitiveDependencies(name, schemaObj);
      const toSelect = new Set([name, ...deps]);
      setSchemas((prev) =>
        prev.map((s) => (toSelect.has(s.name) && (canSelectExisting || !s.exists) ? { ...s, selected: true } : s))
      );
    }
  };

  const handleSelectAllNew = () => {
    setSchemas(prev => prev.map(s => (canSelectExisting || !s.exists ? { ...s, selected: true } : s)));
  };

  const handleSelectNone = () => {
    setSchemas(prev => prev.map(s => ({ ...s, selected: false })));
  };

  const handleImport = async () => {
    if (!analysisResult || !versionId || !projectId || !userId) return;

    const selected = canSelectExisting
      ? schemas.filter(s => s.selected)
      : schemas.filter(s => s.selected && !s.exists);
    const selectedSchemas = selected.map(s => s.name);
    if (selectedSchemas.length === 0) return;

    const schemaObj = analysisResult.document?.components?.schemas ?? analysisResult.document?.definitions ?? {};
    const schemaExists = new Set(schemas.filter(s => s.exists).map(s => s.name));
    const classNameMap: Record<string, string> = {};
    for (const schemaKey of selectedSchemas) {
      const raw = schemaObj[schemaKey];
      const baseName = classNameOverrides[schemaKey]?.trim() || getSmartClassName(schemaKey, raw);
      if (!baseName) continue;
      // #589: When conflict resolution is "rename" and this schema conflicts, import under a new name (base + suffix).
      const isConflicting = schemaExists.has(schemaKey);
      const name =
        conflictResolution === 'rename' && isConflicting
          ? baseName + (renameSuffix.trim() || 'Imported')
          : baseName;
      classNameMap[schemaKey] = name;
    }

    setIsImporting(true);
    setCurrentStep('importing');

    let targetVersionId = versionId;

    try {
      // #590: When "Import as new version" is selected, create a sub-version (e.g. 1.0.0b) and import there
      if (conflictResolution === 'createVersion') {
        const getRes = JSON.parse(await getVersionById(versionId));
        if (!getRes.success || !getRes.version_id) {
          setImportResult({ success: false, error: getRes.error || 'Could not load current version' });
          setCurrentStep('done');
          return;
        }
        const newVersionIdStr = bumpPrereleaseVersion(getRes.version_id, prereleaseSuffix.trim() || 'b');
        const createRes = JSON.parse(
          await createVersion(
            projectId,
            userId,
            newVersionIdStr,
            'Imported as new version',
            'Import as new version to avoid conflicts'
          )
        );
        if (!createRes.success || !createRes.version?.id) {
          setImportResult({ success: false, error: createRes.error || 'Could not create new version' });
          setCurrentStep('done');
          return;
        }
        targetVersionId = createRes.version.id;
        setCreatedVersionLabel(newVersionIdStr);
      } else {
        setCreatedVersionLabel(null);
      }

      const document = analysisResult.document;
      const result = await importClassesToVersion({
        versionId: targetVersionId,
        projectId,
        document,
        selectedSchemas,
        applyNamingConvention,
        classNamingConvention,
        propertyNamingConvention,
        classNameMap: Object.keys(classNameMap).length > 0 ? classNameMap : undefined,
        classPrefix: classPrefix.trim() || undefined,
        classSuffix: classSuffix.trim() || undefined,
        typeMapping: Object.keys(typeMapping).length > 0 ? typeMapping : undefined,
        requiredOverrides: undefined,
        overwriteExisting: conflictResolution === 'createVersion' ? false : (overwriteExisting || undefined),
        mergeStrategy: conflictResolution === 'merge' ? mergeStrategy : undefined,
        propertyMergeStrategies:
          conflictResolution === 'merge' && Object.keys(propertyMergeStrategies).length > 0 ? propertyMergeStrategies : undefined,
      });
      setImportResult(result);
      setCurrentStep('done');
    } catch (error) {
      console.error('Import error:', error);
      setImportResult({ success: false, error: String(error) });
      setCurrentStep('done');
    } finally {
      setIsImporting(false);
    }
  };

  const selectedSchema = selectedSchemaName && analysisResult
    ? (analysisResult.document?.components?.schemas?.[selectedSchemaName] ||
       analysisResult.document?.definitions?.[selectedSchemaName])
    : null;

  const allTags = Array.from(new Set(schemas.flatMap((s) => s.tags))).sort();

  const filteredSchemas = schemas
    .filter((schema) => {
      const matchesName = schema.name.toLowerCase().includes(searchFilter.toLowerCase());
      const matchesType = !filterType || schema.schemaType === filterType;
      const matchesTag = !filterTag || schema.tags.includes(filterTag);
      return matchesName && matchesType && matchesTag;
    })
    .sort((a, b) => {
      if (sortOrder === 'asc') return a.name.localeCompare(b.name);
      if (sortOrder === 'desc') return b.name.localeCompare(a.name);
      return 0;
    });

  const selectedCount = canSelectExisting
    ? schemas.filter(s => s.selected).length
    : schemas.filter(s => s.selected && !s.exists).length;
  const newCount = schemas.filter(s => !s.exists).length;
  const conflictCount = schemas.filter(s => s.exists).length;

  /** Conflict report data for #596: overview of all detected conflicts; #582: duplicate; #583: property; #584: reference; #585: type mismatch; #586: semantic */
  const conflictReportItems: ImportConflict[] = useMemo(() => {
    const duplicateConflicts: ImportConflict[] = schemas
      .filter((s) => s.exists)
      .map((s) => ({
        kind: 'duplicate_schema' as const,
        schemaName: s.name,
        message: `A class named "${s.name}" already exists with a different definition. Importing will overwrite or you can rename.`,
        impactIfResolved: overwriteExisting
          ? 'With "Replace existing" enabled, the selected class will replace the existing one with the imported schema.'
          : conflictResolution === 'rename'
            ? 'With "Import with new name (rename)" you can import this class under a new name (e.g. ' + s.name + (renameSuffix.trim() || 'Imported') + '); the existing class is unchanged.'
            : conflictResolution === 'createVersion'
              ? 'With "Import as new version" a new sub-version (e.g. 1.0.0' + (prereleaseSuffix.trim() || 'b') + ') will be created and the import will go there; the current version is unchanged.'
              : 'Use "Import with new name (rename)" to import under a new name, or "Import as new version" to create a sub-version. Or enable "Replace existing" to overwrite with the imported schema.',
      }));
    const schemaNames = schemas.map((s) => s.name);
    const selectedSchemaNamesForConflicts = canSelectExisting
      ? schemas.filter((s) => s.selected).map((s) => s.name)
      : schemas.filter((s) => s.selected && !s.exists).map((s) => s.name);
    const propertyConflicts = analysisResult?.document
      ? detectPropertyConflicts({ document: analysisResult.document, schemaNames })
      : [];
    const referenceConflicts = analysisResult?.document
      ? detectReferenceConflicts({
          document: analysisResult.document,
          schemaNames,
          selectedSchemaNames: selectedSchemaNamesForConflicts,
        })
      : [];
    const typeMismatchConflicts = analysisResult?.document
      ? detectTypeMismatches({ document: analysisResult.document, schemaNames })
      : [];
    const semanticConflicts = analysisResult?.document
      ? detectSemanticConflicts({ document: analysisResult.document, schemaNames })
      : [];
    return [
      ...duplicateConflicts,
      ...propertyConflicts,
      ...referenceConflicts,
      ...typeMismatchConflicts,
      ...semanticConflicts,
    ];
  }, [schemas, analysisResult?.document, overwriteExisting, conflictResolution, renameSuffix, prereleaseSuffix]);

  const selectedSchemaNames = useMemo(
    () =>
      canSelectExisting
        ? schemas.filter((s) => s.selected).map((s) => s.name)
        : schemas.filter((s) => s.selected && !s.exists).map((s) => s.name),
    [schemas, canSelectExisting]
  );
  const externalTypeKeys = useMemo(
    () => (analysisResult?.document ? collectExternalTypeKeysFromDocument(analysisResult.document, selectedSchemaNames) : []),
    [analysisResult?.document, selectedSchemaNames]
  );

  const handleTypeMappingChange = (externalKey: string, internalValue: string) => {
    const next = { ...typeMapping };
    if (internalValue === '__keep__') {
      delete next[externalKey];
    } else {
      const option = INTERNAL_TYPE_OPTIONS.find((o) => o.value === internalValue);
      if (option?.schema) next[externalKey] = option.schema;
    }
    setTypeMapping(next);
  };

  const getPropertyType = (prop: any): string => {
    if (prop.$ref) {
      const refName = prop.$ref.split('/').pop();
      return `$ref → ${refName}`;
    }
    if (prop.type === 'array') {
      if (prop.items?.$ref) {
        const refName = prop.items.$ref.split('/').pop();
        return `array<$ref → ${refName}>`;
      }
      return `array<${prop.items?.type || 'any'}>`;
    }
    if (prop.enum) {
      const enumValues = prop.enum.slice(0, 4).join(', ');
      const remaining = prop.enum.length - 4;
      if (remaining > 0) {
        return `enum (${enumValues}, ... ${remaining} more)`;
      }
      return `enum (${enumValues})`;
    }
    return prop.type || 'any';
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col" showCloseButton={false}>
        <DialogHeader className="border-b border-gray-200 dark:border-gray-700 pb-4">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-2xl font-bold text-gray-900 dark:text-white">
              Import Classes
            </DialogTitle>
            <button
              onClick={handleClose}
              className="rounded-lg p-2 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              <X className="h-5 w-5 text-gray-500 dark:text-gray-400" />
            </button>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Import classes from an OpenAPI specification into your current version
          </p>
        </DialogHeader>

        {/* Step Indicator */}
        <div className="border-b border-gray-200 dark:border-gray-700 py-4 px-6">
          <div className="flex items-center justify-center gap-2 text-sm">
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-8 h-8 rounded-full font-semibold ${
                currentStep === 'source' || currentStep === 'file-upload'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-green-600 text-white'
              }`}>
                {['select', 'importing', 'done'].includes(currentStep) ? '✓' : '1'}
              </div>
              <span className="ml-2 font-medium text-gray-900 dark:text-white">Source</span>
            </div>
            <div className={`w-16 h-0.5 ${['select', 'importing', 'done'].includes(currentStep) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'}`}></div>
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-8 h-8 rounded-full font-semibold ${
                currentStep === 'select'
                  ? 'bg-indigo-600 text-white'
                  : ['importing', 'done'].includes(currentStep)
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
              }`}>
                {['importing', 'done'].includes(currentStep) ? '✓' : '2'}
              </div>
              <span className={`ml-2 ${['select', 'importing', 'done'].includes(currentStep) ? 'font-medium text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'}`}>
                Select Classes
              </span>
            </div>
            <div className={`w-16 h-0.5 ${['importing', 'done'].includes(currentStep) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'}`}></div>
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-8 h-8 rounded-full font-semibold ${
                currentStep === 'importing'
                  ? 'bg-indigo-600 text-white'
                  : currentStep === 'done'
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
              }`}>
                {currentStep === 'done' ? '✓' : '3'}
              </div>
              <span className={`ml-2 ${['importing', 'done'].includes(currentStep) ? 'font-medium text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'}`}>
                Import
              </span>
            </div>
          </div>
        </div>

        {/* Scrollable Content Area */}
        <div className="overflow-y-auto py-6 px-6 flex-1">
          {currentStep === 'source' && (
            <div className="mb-8">
              <div className="bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-950/30 dark:to-purple-950/30 rounded-xl border-2 border-indigo-200 dark:border-indigo-800 p-6">
                <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-6 text-center">
                  Choose Import Source
                </h2>
                <div className="grid grid-cols-4 gap-4 max-w-4xl mx-auto">
                  {/* File Upload */}
                  <button
                    onClick={() => handleSourceClick('file')}
                    className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                      selectedSource === 'file'
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                        : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                    }`}
                  >
                    <div className="flex flex-col items-center text-center">
                      <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                        selectedSource === 'file'
                          ? 'bg-indigo-500 text-white'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                      }`}>
                        <Upload className="h-6 w-6" />
                      </div>
                      <div className={`font-semibold mb-1 ${
                        selectedSource === 'file' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                      }`}>
                        File Upload
                      </div>
                      <div className="text-xs text-gray-600 dark:text-gray-400">
                        Upload OpenAPI/Swagger specification
                      </div>
                    </div>
                  </button>

                  {/* URL Import */}
                  <button
                    onClick={() => handleSourceClick('url')}
                    className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                      selectedSource === 'url'
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                        : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                    }`}
                  >
                    <div className="flex flex-col items-center text-center">
                      <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                        selectedSource === 'url'
                          ? 'bg-indigo-500 text-white'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                      }`}>
                        <Link2 className="h-6 w-6" />
                      </div>
                      <div className={`font-semibold mb-1 ${
                        selectedSource === 'url' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                      }`}>
                        URL Import
                      </div>
                      <div className="text-xs text-gray-600 dark:text-gray-400">
                        Fetch from URL with authentication
                      </div>
                    </div>
                  </button>

                  {/* Clipboard */}
                  <button
                    onClick={() => handleSourceClick('clipboard')}
                    className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                      selectedSource === 'clipboard'
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                        : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                    }`}
                  >
                    <div className="flex flex-col items-center text-center">
                      <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                        selectedSource === 'clipboard'
                          ? 'bg-indigo-500 text-white'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                      }`}>
                        <FileText className="h-6 w-6" />
                      </div>
                      <div className={`font-semibold mb-1 ${
                        selectedSource === 'clipboard' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                      }`}>
                        Clipboard Paste
                      </div>
                      <div className="text-xs text-gray-600 dark:text-gray-400">
                        Paste JSON or YAML content
                      </div>
                    </div>
                  </button>

                  {/* Git Repository */}
                  <button
                    onClick={() => handleSourceClick('git')}
                    className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                      selectedSource === 'git'
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                        : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                    }`}
                  >
                    <div className="flex flex-col items-center text-center">
                      <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                        selectedSource === 'git'
                          ? 'bg-indigo-500 text-white'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                      }`}>
                        <Github className="h-6 w-6" />
                      </div>
                      <div className={`font-semibold mb-1 ${
                        selectedSource === 'git' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                      }`}>
                        Git Repository
                      </div>
                      <div className="text-xs text-gray-600 dark:text-gray-400">
                        Import from GitHub/GitLab
                      </div>
                    </div>
                  </button>
                </div>
              </div>
            </div>
          )}

          {currentStep === 'file-upload' && selectedSource === 'url' && (
            <UrlImportPanel
              onSpecificationFetched={handleUrlSpecificationFetched}
            />
          )}

          {currentStep === 'file-upload' && selectedSource === 'clipboard' && (
            <ClipboardImportPanel
              onSpecificationReady={handleClipboardSpecificationReady}
            />
          )}

          {currentStep === 'file-upload' && selectedSource === 'git' && (
            <GitImportPanel
              userId={userId}
              onSpecificationFetched={handleGitSpecificationFetched}
            />
          )}

          {currentStep === 'file-upload' && selectedSource === 'file' && (
            <>
              {/* Drop Zone */}
              <div className="mb-6">
                <div
                  onDragEnter={handleDragEnter}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  className={`border-2 border-dashed rounded-xl p-12 text-center transition-all ${
                    isDragging
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                      : 'border-gray-300 dark:border-gray-600 hover:border-indigo-400 dark:hover:border-indigo-600'
                  }`}
                >
                  <div className="flex flex-col items-center gap-4">
                    <div className={`w-16 h-16 rounded-2xl flex items-center justify-center ${
                      isDragging
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-400'
                    }`}>
                      <Upload className="h-8 w-8" />
                    </div>

                    {selectedFile ? (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                          <FileCode className="h-5 w-5" />
                          <span className="font-medium">{selectedFile.name}</span>
                        </div>
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                          {(selectedFile.size / 1024).toFixed(2)} KB
                        </p>
                        <button
                          onClick={() => {
                            setSelectedFile(null);
                            setFileMetadata(null);
                          }}
                          className="text-sm text-red-600 dark:text-red-400 hover:underline"
                        >
                          Remove file
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="space-y-2">
                          <p className="text-lg font-medium text-gray-900 dark:text-white">
                            Drop files here
                          </p>
                          <p className="text-sm text-gray-600 dark:text-gray-400">or</p>
                        </div>
                        <label className="cursor-pointer">
                          <input
                            type="file"
                            className="hidden"
                            accept=".yaml,.yml,.json,.graphql,.gql"
                            onChange={handleFileInputChange}
                          />
                          <span className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg transition-colors shadow-sm">
                            <Upload className="h-5 w-5" />
                            Browse Files
                          </span>
                        </label>
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          Supports: .yaml, .yml, .json, .graphql, .gql
                        </p>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* File Metadata Preview */}
              {selectedFile && (
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                    <FileCode className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
                    File Preview
                  </h3>

                  {isLoadingMetadata ? (
                    <div className="flex items-center justify-center py-8">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 dark:border-indigo-400"></div>
                      <span className="ml-3 text-gray-600 dark:text-gray-400">Analyzing file...</span>
                    </div>
                  ) : fileMetadata ? (
                    <div className="space-y-4">
                      {!fileMetadata.formatSupported && fileMetadata.format !== 'unknown' && (
                        <div className="p-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                          <div className="flex items-start gap-3">
                            <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                            <div>
                              <div className="font-medium text-amber-900 dark:text-amber-200">
                                Format Not Supported
                              </div>
                              <div className="text-sm text-amber-700 dark:text-amber-300 mt-1">
                                The detected format <span className="font-semibold">{fileMetadata.formatDisplayName}</span> is not supported.
                                Only OpenAPI 3.x and Swagger 2.x specifications are supported.
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {!fileMetadata.syntaxValid && (
                        <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                          <div className="flex items-start gap-3">
                            <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
                            <div>
                              <div className="font-medium text-red-900 dark:text-red-200">File Parse Error</div>
                              <div className="text-sm text-red-700 dark:text-red-300 mt-1">
                                {fileMetadata.parseError || 'Unable to parse file content'}
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      <div className="grid grid-cols-3 gap-4">
                        <div className={`rounded-lg p-4 border ${fileMetadata.formatSupported ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800'}`}>
                          <div className="flex items-center gap-2 mb-2">
                            {fileMetadata.formatSupported ? (
                              <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
                            ) : (
                              <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                            )}
                            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                              Format
                            </span>
                          </div>
                          <div className="text-sm font-semibold text-gray-900 dark:text-white">
                            {fileMetadata.formatDisplayName}
                          </div>
                        </div>

                        <div className="rounded-lg p-4 border bg-gray-50 dark:bg-gray-900/30 border-gray-200 dark:border-gray-700">
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Version</span>
                          <div className="text-sm font-semibold text-gray-900 dark:text-white mt-2">
                            {fileMetadata.specVersion || fileMetadata.version || 'N/A'}
                          </div>
                        </div>

                        <div className={`rounded-lg p-4 border ${fileMetadata.syntaxValid ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'}`}>
                          <div className="flex items-center gap-2 mb-2">
                            {fileMetadata.syntaxValid ? (
                              <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
                            ) : (
                              <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
                            )}
                            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Syntax</span>
                          </div>
                          <div className="text-sm font-semibold text-gray-900 dark:text-white">
                            {fileMetadata.syntaxValid ? `Valid ${fileMetadata.syntax.toUpperCase()}` : 'Invalid'}
                          </div>
                        </div>
                      </div>

                      {fileMetadata.title && (
                        <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Title</span>
                          <div className="text-base font-semibold text-gray-900 dark:text-white mt-1">{fileMetadata.title}</div>
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              )}
            </>
          )}

          {currentStep === 'select' && analysisResult && (
            <div className="space-y-6">
              {/* Summary */}
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div className="flex items-center gap-4">
                    <button
                      onClick={handleSelectAllNew}
                      className="px-3 py-1.5 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg transition-colors"
                    >
                      Select All New
                    </button>
                    <button
                      onClick={handleSelectNone}
                      className="px-3 py-1.5 text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      Select None
                    </button>
                    <div className="flex items-center gap-3 text-sm">
                      <span className="text-gray-500 dark:text-gray-400">
                        <span className="font-medium text-indigo-600 dark:text-indigo-400">{selectedCount}</span> selected
                      </span>
                      <span className="text-gray-300 dark:text-gray-600">|</span>
                      <span className="text-green-600 dark:text-green-400">
                        {newCount} new
                      </span>
                      {conflictCount > 0 && (
                        <>
                          <span className="text-gray-300 dark:text-gray-600">|</span>
                          <span className="text-amber-600 dark:text-amber-400">
                            {conflictCount} existing
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="relative flex-1 min-w-[160px]">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                      <input
                        type="text"
                        placeholder="Search by name..."
                        value={searchFilter}
                        onChange={(e) => setSearchFilter(e.target.value)}
                        className="w-full pl-9 pr-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                      />
                    </div>
                    <select
                      value={filterType}
                      onChange={(e) => setFilterType((e.target.value || '') as SchemaDisplayType | '')}
                      className="py-2 pl-3 pr-8 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                      title="Filter by type"
                    >
                      <option value="">All types</option>
                      <option value="object">object</option>
                      <option value="array">array</option>
                      <option value="allOf">allOf</option>
                      <option value="oneOf">oneOf</option>
                      <option value="anyOf">anyOf</option>
                      <option value="enum">enum</option>
                      <option value="string">string</option>
                      <option value="number">number</option>
                      <option value="integer">integer</option>
                      <option value="boolean">boolean</option>
                      <option value="null">null</option>
                      <option value="unknown">unknown</option>
                    </select>
                    <select
                      value={filterTag}
                      onChange={(e) => setFilterTag(e.target.value)}
                      className="py-2 pl-3 pr-8 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                      title="Filter by tag"
                    >
                      <option value="">All tags</option>
                      {allTags.map((tag) => (
                        <option key={tag} value={tag}>
                          {tag}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              {/* Conflict Report (#596): overview of all detected conflicts (incl. #585 type mismatch) */}
              {conflictReportItems.length > 0 && (
                <ConflictReport conflicts={conflictReportItems} defaultOpen={true} className="mb-6" />
              )}

              {/* Pre-Import Analysis */}
              {analysisResult.metrics && (
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Pre-Import Analysis</h3>

                  <div className="grid grid-cols-3 gap-4 mb-4">
                    {/* Schema Count */}
                    <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-lg p-4 border border-indigo-200 dark:border-indigo-800">
                      <div className="text-2xl font-bold text-indigo-600 dark:text-indigo-400">
                        {analysisResult.metrics.schemaCount}
                      </div>
                      <div className="text-xs text-indigo-700 dark:text-indigo-300 mt-1">
                        Schemas Found
                      </div>
                    </div>

                    {/* Property Count */}
                    <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4 border border-blue-200 dark:border-blue-800">
                      <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                        {analysisResult.metrics.propertyCount}
                      </div>
                      <div className="text-xs text-blue-700 dark:text-blue-300 mt-1">
                        Total Properties
                      </div>
                    </div>

                    {/* Reference Count */}
                    <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-4 border border-purple-200 dark:border-purple-800">
                      <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">
                        {analysisResult.metrics.referenceCount}
                      </div>
                      <div className="text-xs text-purple-700 dark:text-purple-300 mt-1">
                        References ($ref)
                      </div>
                    </div>
                  </div>

                  {/* Circular References Warning */}
                  {analysisResult.metrics.circularReferences && analysisResult.metrics.circularReferences.length > 0 && (
                    <div className="mb-4 p-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                      <div className="flex items-start gap-3">
                        <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                          <h4 className="text-sm font-semibold text-amber-800 dark:text-amber-200 mb-2">
                            Circular Dependencies Detected
                          </h4>
                          <p className="text-xs text-amber-700 dark:text-amber-300 mb-3">
                            The following schemas have circular references. This may cause issues during import or usage:
                          </p>
                          <div className="flex flex-wrap gap-2">
                            {analysisResult.metrics.circularReferences.map((schemaName, idx) => (
                              <span
                                key={idx}
                                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-100 dark:bg-amber-900/40 border border-amber-300 dark:border-amber-700 text-xs font-medium text-amber-800 dark:text-amber-200"
                              >
                                <Package className="h-3.5 w-3.5" />
                                {schemaName}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* External References Warning */}
                  {analysisResult.metrics.externalReferences && analysisResult.metrics.externalReferences.length > 0 && (
                    <div className="mb-4 p-4 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
                      <div className="flex items-start gap-3">
                        <AlertTriangle className="h-5 w-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                          <h4 className="text-sm font-semibold text-blue-800 dark:text-blue-200 mb-2">
                            External References Found
                          </h4>
                          <p className="text-xs text-blue-700 dark:text-blue-300 mb-3">
                            {analysisResult.metrics.externalReferences.length} external URL reference(s) detected. These will need to be resolved:
                          </p>
                          <div className="space-y-1 max-h-24 overflow-y-auto">
                            {analysisResult.metrics.externalReferences.map((url, idx) => (
                              <div key={idx} className="text-xs font-mono text-blue-700 dark:text-blue-300 bg-blue-100 dark:bg-blue-900/30 px-2 py-1 rounded break-all">
                                {url}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Composition Schemas Info */}
                  {analysisResult.metrics.compositionSchemas &&
                   (analysisResult.metrics.compositionSchemas.allOf > 0 ||
                    analysisResult.metrics.compositionSchemas.oneOf > 0 ||
                    analysisResult.metrics.compositionSchemas.anyOf > 0) && (
                    <div className="p-4 rounded-lg bg-gray-50 dark:bg-gray-900/30 border border-gray-200 dark:border-gray-700">
                      <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-3">
                        Composition Schemas
                      </h4>
                      <div className="grid grid-cols-3 gap-3 text-xs">
                        {analysisResult.metrics.compositionSchemas.allOf > 0 && (
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-600 dark:text-gray-400">allOf:</span>
                            <span className="font-semibold text-gray-900 dark:text-white">
                              {analysisResult.metrics.compositionSchemas.allOf}
                            </span>
                          </div>
                        )}
                        {analysisResult.metrics.compositionSchemas.oneOf > 0 && (
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-600 dark:text-gray-400">oneOf:</span>
                            <span className="font-semibold text-gray-900 dark:text-white">
                              {analysisResult.metrics.compositionSchemas.oneOf}
                            </span>
                          </div>
                        )}
                        {analysisResult.metrics.compositionSchemas.anyOf > 0 && (
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-gray-600 dark:text-gray-400">anyOf:</span>
                            <span className="font-semibold text-gray-900 dark:text-white">
                              {analysisResult.metrics.compositionSchemas.anyOf}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Class Selection */}
              <div className="grid grid-cols-2 gap-6">
                {/* Left: Class List */}
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
                  <div className="border-b border-gray-200 dark:border-gray-700 p-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Classes to Import</h3>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setSortOrder(sortOrder === 'asc' ? null : 'asc')}
                          className={`p-1.5 rounded transition-colors ${
                            sortOrder === 'asc'
                              ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                              : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                          }`}
                          title="Sort A → Z"
                        >
                          <ArrowUpAZ className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setSortOrder(sortOrder === 'desc' ? null : 'desc')}
                          className={`p-1.5 rounded transition-colors ${
                            sortOrder === 'desc'
                              ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                              : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                          }`}
                          title="Sort Z → A"
                        >
                          <ArrowDownAZ className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                  <div className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
                    {filteredSchemas.map((schema) => {
                      const schemaObjForDeps = (analysisResult?.document?.components?.schemas ??
                        analysisResult?.document?.definitions ??
                        {}) as Record<string, unknown>;
                      const requiredBySelection =
                        schema.selected && isReferencedBySelectedSchemas(schema.name, schemas, schemaObjForDeps);
                      return (
                      <div
                        key={schema.name}
                        className={`flex items-center gap-3 p-3 rounded-lg transition-colors ${
                          schema.exists && !canSelectExisting
                            ? 'opacity-60 cursor-not-allowed'
                            : requiredBySelection
                            ? 'cursor-not-allowed'
                            : 'cursor-pointer'
                        } ${
                          selectedSchemaName === schema.name
                            ? 'bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800'
                            : schema.exists
                            ? 'bg-amber-50/50 dark:bg-amber-900/10'
                            : 'hover:bg-gray-50 dark:hover:bg-gray-700/50'
                        }`}
                        onClick={() => setSelectedSchemaName(schema.name)}
                        title={requiredBySelection ? 'Required by other selected classes' : undefined}
                      >
                        <Checkbox.Root
                          checked={schema.selected}
                          disabled={(schema.exists && !canSelectExisting) || requiredBySelection}
                          onCheckedChange={() => handleToggleSchema(schema.name)}
                          onClick={(e) => e.stopPropagation()}
                          className="w-5 h-5 rounded border-2 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600 data-[disabled]:opacity-50 data-[disabled]:cursor-not-allowed flex items-center justify-center"
                          title={requiredBySelection ? 'Required by other selected classes' : undefined}
                        >
                          <Checkbox.Indicator>
                            <Check className="w-4 h-4 text-white" />
                          </Checkbox.Indicator>
                        </Checkbox.Root>
                        <Package className={`h-5 w-5 flex-shrink-0 ${schema.exists ? 'text-amber-500' : 'text-indigo-600 dark:text-indigo-400'}`} />
                        <div className="flex-1 min-w-0">
                          <div className={`font-medium ${schema.exists && !canSelectExisting ? 'line-through text-gray-500 dark:text-gray-400' : 'text-gray-900 dark:text-white'} truncate`}>
                            {schema.name}
                            {schema.exists && (
                              <span className="ml-2 text-xs font-normal text-amber-600 dark:text-amber-400 no-underline">
                                {conflictResolution === 'replace' && '(exists – will replace)'}
                                {conflictResolution === 'merge' && `(exists – will merge ${mergeStrategy})`}
                                {conflictResolution === 'rename' && `(will import as ${schema.name}${renameSuffix.trim() || 'Imported'})`}
                                {conflictResolution === 'keep' && '(exists)'}
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-gray-500 dark:text-gray-400">
                            {schema.properties} properties
                          </div>
                        </div>
                        {selectedSchemaName === schema.name && (
                          <ChevronRight className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
                        )}
                      </div>
                      );
                    })}
                  </div>
                </div>

                {/* Right: Schema Preview */}
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
                  <div className="border-b border-gray-200 dark:border-gray-700 p-4">
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Class Preview</h3>
                  </div>
                  <div className="p-4 max-h-[400px] overflow-y-auto">
                    {selectedSchema && selectedSchemaName ? (
                      <div className="space-y-4">
                        <div>
                          <h4 className="text-xl font-bold text-gray-900 dark:text-white mb-2">
                            {selectedSchemaName}
                          </h4>
                          {/* Name mapping: smart name from schema context with optional override (#753) */}
                          <div className="mb-3">
                            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                              Import as class name
                            </label>
                            <input
                              type="text"
                              value={classNameOverrides[selectedSchemaName] ?? getSmartClassName(selectedSchemaName, selectedSchema)}
                              onChange={(e) => {
                                const v = e.target.value.trim();
                                const smart = getSmartClassName(selectedSchemaName, selectedSchema);
                                if (v === '' || v === smart) {
                                  setClassNameOverrides((prev) => {
                                    const next = { ...prev };
                                    delete next[selectedSchemaName];
                                    return next;
                                  });
                                } else {
                                  setClassNameOverrides((prev) => ({ ...prev, [selectedSchemaName]: e.target.value }));
                                }
                              }}
                              placeholder={getSmartClassName(selectedSchemaName, selectedSchema)}
                              className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                            />
                            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                              From schema title / x-class-name when available
                            </p>
                          </div>
                          {schemas.find(s => s.name === selectedSchemaName)?.exists && (
                            <div className="mb-3 p-2 rounded bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                              <p className="text-sm text-amber-700 dark:text-amber-300">
                                {conflictResolution === 'replace' && 'Will replace the existing class with the imported schema.'}
                                {conflictResolution === 'merge' && `Will merge with existing (${mergeStrategy}: ${mergeStrategy === 'additive' ? 'add new properties, keep existing' : 'imported wins, constraints merged'}).`}
                                {conflictResolution === 'keep' && '⚠️ A class with this name already exists in this version and cannot be imported.'}
                              </p>
                            </div>
                          )}
                          {selectedSchema.description && (
                            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                              {selectedSchema.description}
                            </p>
                          )}
                        </div>

                        {selectedSchema.properties && (
                          <div>
                            <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Properties:</h5>
                            <div className="space-y-2 pl-4 border-l-2 border-gray-200 dark:border-gray-700">
                              {Object.entries(selectedSchema.properties).map(([propName, propValue]: [string, any]) => (
                                <div key={propName} className="text-sm">
                                  <span className="font-mono text-indigo-600 dark:text-indigo-400">{propName}</span>
                                  <span className="text-gray-500 dark:text-gray-400">: </span>
                                  <span className="text-gray-700 dark:text-gray-300">{getPropertyType(propValue)}</span>
                                  {selectedSchema.required?.includes(propName) && (
                                    <span className="ml-2 text-xs text-red-600 dark:text-red-400 font-medium">(required)</span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-center py-12 text-gray-400 dark:text-gray-500">
                        Select a class to preview
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Import Options: Conflict resolution (#587, #588), Naming Convention (#581) */}
              <div className="mt-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">Import Options</h4>
                <div className="mb-3">
                  <span className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">When a class with the same name exists</span>
                  <div className="flex flex-wrap gap-4 pl-0">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="conflictResolution"
                        checked={conflictResolution === 'keep'}
                        onChange={() => setConflictResolution('keep')}
                        className="w-4 h-4 border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
                      />
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Keep existing (skip)</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="conflictResolution"
                        checked={conflictResolution === 'replace'}
                        onChange={() => setConflictResolution('replace')}
                        className="w-4 h-4 border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
                      />
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Replace with imported</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="conflictResolution"
                        checked={conflictResolution === 'merge'}
                        onChange={() => setConflictResolution('merge')}
                        className="w-4 h-4 border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
                      />
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Merge</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="conflictResolution"
                        checked={conflictResolution === 'rename'}
                        onChange={() => setConflictResolution('rename')}
                        className="w-4 h-4 border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
                      />
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Import with new name (rename)</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="conflictResolution"
                        checked={conflictResolution === 'createVersion'}
                        onChange={() => setConflictResolution('createVersion')}
                        className="w-4 h-4 border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
                      />
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Import as new version (e.g. 1.0.0b)</span>
                    </label>
                  </div>
                  {conflictResolution === 'createVersion' && (
                    <div className="mt-2 pl-6">
                      <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Sub-version suffix (#590)</label>
                      <input
                        type="text"
                        value={prereleaseSuffix}
                        onChange={(e) => setPrereleaseSuffix(e.target.value)}
                        placeholder="e.g. b or import"
                        className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 w-full max-w-[200px]"
                      />
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        A new version will be created (e.g. 1.0.0 → 1.0.0{prereleaseSuffix.trim() || 'b'}) and the import will go there, avoiding conflicts with the current version.
                      </p>
                    </div>
                  )}
                  {conflictResolution === 'rename' && (
                    <div className="mt-2 pl-6">
                      <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Suffix for conflicting classes (#589)</label>
                      <input
                        type="text"
                        value={renameSuffix}
                        onChange={(e) => setRenameSuffix(e.target.value)}
                        placeholder="e.g. Imported or V2"
                        className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 w-full max-w-[200px]"
                      />
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        Conflicting classes will be imported with this suffix (e.g. Pet → Pet{renameSuffix.trim() || 'Imported'}).
                      </p>
                    </div>
                  )}
                  {conflictResolution === 'merge' && (
                    <div className="mt-2 pl-6 space-y-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Merge strategy (#588)</label>
                        <select
                          value={mergeStrategy}
                          onChange={(e) => setMergeStrategy(e.target.value as 'additive' | 'override')}
                          className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                        >
                          <option value="additive">Additive: add new properties, keep existing</option>
                          <option value="override">Override: imported wins, constraints merged</option>
                        </select>
                      </div>
                      <Collapsible>
                        <CollapsibleTrigger className="flex items-center gap-2 text-xs font-medium text-gray-600 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-400">
                          <ChevronDown className="h-4 w-4 transition-transform data-[state=open]:rotate-180" />
                          Customize per property (#593)
                        </CollapsibleTrigger>
                        <CollapsibleContent className="mt-2 pl-4 border-l-2 border-gray-200 dark:border-gray-600">
                          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                            Override the default merge strategy for individual properties on conflicting classes.
                          </p>
                          {schemas.filter((s) => s.exists && s.selected).length === 0 ? (
                            <p className="text-xs text-gray-500 dark:text-gray-400 italic">Select conflicting classes above to customize.</p>
                          ) : (
                            <div className="space-y-3">
                              {schemas
                                .filter((s) => s.exists && s.selected)
                                .map((schema) => {
                                  const schemaKey = schema.name;
                                  const raw = analysisResult?.document?.components?.schemas?.[schemaKey] ?? analysisResult?.document?.definitions?.[schemaKey];
                                  const propNames = raw ? getSchemaPropertyNames(raw) : [];
                                  if (propNames.length === 0) return null;
                                  return (
                                    <div key={schemaKey} className="space-y-1.5">
                                      <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{schemaKey}</span>
                                      <div className="space-y-1 pl-2">
                                        {propNames.map((propName) => {
                                          const value = propertyMergeStrategies[schemaKey]?.[propName] ?? '';
                                          return (
                                            <div key={propName} className="flex items-center gap-2">
                                              <span className="text-xs font-mono text-gray-600 dark:text-gray-400 w-32 truncate" title={propName}>
                                                {propName}
                                              </span>
                                              <select
                                                value={value}
                                                onChange={(e) => {
                                                  const v = e.target.value as '' | 'additive' | 'override';
                                                  setPropertyMergeStrategies((prev) => {
                                                    const next = { ...prev };
                                                    if (!next[schemaKey]) next[schemaKey] = { ...(prev[schemaKey] || {}) };
                                                    if (v === '') {
                                                      delete next[schemaKey][propName];
                                                      if (Object.keys(next[schemaKey]).length === 0) delete next[schemaKey];
                                                    } else {
                                                      next[schemaKey] = { ...next[schemaKey], [propName]: v };
                                                    }
                                                    return next;
                                                  });
                                                }}
                                                className="flex-1 min-w-0 text-xs px-2 py-1 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                                              >
                                                <option value="">Use default ({mergeStrategy})</option>
                                                <option value="additive">Additive</option>
                                                <option value="override">Override</option>
                                              </select>
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  );
                                })}
                            </div>
                          )}
                        </CollapsibleContent>
                      </Collapsible>
                    </div>
                  )}
                </div>
                <label className="flex items-center gap-2 cursor-pointer mb-3">
                  <input
                    type="checkbox"
                    checked={applyNamingConvention}
                    onChange={(e) => setApplyNamingConvention(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
                  />
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    Apply naming convention
                  </span>
                </label>
                {applyNamingConvention && (
                  <div className="flex flex-wrap gap-4 pl-6">
                    <div>
                      <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Classes</label>
                      <select
                        value={classNamingConvention}
                        onChange={(e) => setClassNamingConvention(e.target.value as typeof classNamingConvention)}
                        className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                      >
                        <option value="PascalCase">PascalCase</option>
                        <option value="camelCase">camelCase</option>
                        <option value="snake_case">snake_case</option>
                        <option value="kebab-case">kebab-case</option>
                        <option value="none">None (keep original)</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Properties</label>
                      <select
                        value={propertyNamingConvention}
                        onChange={(e) => setPropertyNamingConvention(e.target.value as typeof propertyNamingConvention)}
                        className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                      >
                        <option value="PascalCase">PascalCase</option>
                        <option value="camelCase">camelCase</option>
                        <option value="snake_case">snake_case</option>
                        <option value="kebab-case">kebab-case</option>
                        <option value="none">None (keep original)</option>
                      </select>
                    </div>
                  </div>
                )}
                <div className="flex flex-wrap gap-4 pl-6 pt-2 border-t border-gray-100 dark:border-gray-700 mt-3 pt-3">
                  <div className="flex-1 min-w-[140px]">
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Class name prefix (#755)</label>
                    <input
                      type="text"
                      value={classPrefix}
                      onChange={(e) => setClassPrefix(e.target.value)}
                      placeholder="e.g. Api"
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
                    />
                  </div>
                  <div className="flex-1 min-w-[140px]">
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Class name suffix (#755)</label>
                    <input
                      type="text"
                      value={classSuffix}
                      onChange={(e) => setClassSuffix(e.target.value)}
                      placeholder="e.g. Dto"
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
                    />
                  </div>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 pl-6 mt-1">
                  Prefix and suffix are applied to every imported class name (e.g. Api + User + Dto → ApiUserDto).
                </p>
                {externalTypeKeys.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700">
                    <Collapsible defaultOpen={false} className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
                      <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
                        <span>Type mapping (#757)</span>
                        <ChevronDown className="h-4 w-4 shrink-0 data-[state=open]:rotate-180 transition-transform" />
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <div className="px-4 pb-4 pt-1 border-t border-gray-100 dark:border-gray-700">
                          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                            Map external types to internal types for imported properties.
                          </p>
                          <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                              <thead>
                                <tr className="border-b border-gray-200 dark:border-gray-600">
                                  <th className="text-left py-2 font-medium text-gray-700 dark:text-gray-300">External type</th>
                                  <th className="text-left py-2 font-medium text-gray-700 dark:text-gray-300">Map to</th>
                                </tr>
                              </thead>
                              <tbody>
                                {externalTypeKeys.map((externalKey) => {
                                  const currentMapped = typeMapping[externalKey];
                                  const currentValue = currentMapped
                                    ? INTERNAL_TYPE_OPTIONS.find((o) => o.schema && JSON.stringify(o.schema) === JSON.stringify(currentMapped))?.value ?? '__keep__'
                                    : '__keep__';
                                  return (
                                    <tr key={externalKey} className="border-b border-gray-100 dark:border-gray-700/50">
                                      <td className="py-2 text-gray-900 dark:text-white font-mono text-xs">{externalKey}</td>
                                      <td className="py-2">
                                        <select
                                          value={currentValue}
                                          onChange={(e) => handleTypeMappingChange(externalKey, e.target.value)}
                                          className="w-full max-w-[220px] px-2 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                                        >
                                          <option value="__keep__">Keep as-is</option>
                                          {INTERNAL_TYPE_OPTIONS.filter((o) => o.value !== '__keep__').map((o) => (
                                            <option key={o.value} value={o.value}>{o.label}</option>
                                          ))}
                                        </select>
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  </div>
                )}
              </div>
            </div>
          )}

          {currentStep === 'importing' && (
            <div className="flex flex-col items-center justify-center py-16">
              <div className="relative mb-6">
                <div className="w-16 h-16 border-4 border-indigo-200 dark:border-indigo-800 rounded-full"></div>
                <div className="w-16 h-16 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin absolute top-0 left-0"></div>
              </div>
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Importing Classes...</h3>
              <p className="text-gray-500 dark:text-gray-400">Please wait while we import the selected classes</p>
            </div>
          )}

          {currentStep === 'done' && importResult && (
            <div className="flex flex-col items-center justify-center py-12">
              {importResult.success ? (
                <>
                  <div className="w-16 h-16 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mb-6">
                    <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
                  </div>
                  <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Import Complete!</h3>
                  <p className="text-gray-500 dark:text-gray-400 mb-4">
                    Successfully imported {importResult.importedCount} class{importResult.importedCount !== 1 ? 'es' : ''}
                    {createdVersionLabel ? ` into new version ${createdVersionLabel}` : ''}.
                  </p>
                  {importResult.skippedCount != null && importResult.skippedCount > 0 ? (
                    <p className="text-amber-600 dark:text-amber-400 text-sm">
                      {importResult.skippedCount} class{importResult.skippedCount !== 1 ? 'es were' : ' was'} skipped (already exist)
                    </p>
                  ) : null}
                  {importResult.warnings && importResult.warnings.length > 0 ? (
                    <div className="mt-4 w-full max-w-md rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 text-left">
                      <p className="text-sm font-medium text-amber-800 dark:text-amber-200 mb-2">
                        Warnings ({importResult.warnings.length})
                      </p>
                      <ul className="text-sm text-amber-700 dark:text-amber-300 list-disc list-inside space-y-1">
                        {importResult.warnings.slice(0, 10).map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                        {importResult.warnings.length > 10 ? (
                          <li>+ {importResult.warnings.length - 10} more</li>
                        ) : null}
                      </ul>
                    </div>
                  ) : null}
                </>
              ) : (
                <>
                  <div className="w-16 h-16 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center justify-center mb-6">
                    <AlertTriangle className="h-8 w-8 text-red-600 dark:text-red-400" />
                  </div>
                  <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Import Failed</h3>
                  <p className="text-red-600 dark:text-red-400">{importResult.error || 'An error occurred during import'}</p>
                </>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex items-center justify-between bg-gray-50 dark:bg-gray-800/50">
          {currentStep === 'importing' || currentStep === 'done' ? (
            <>
              <div />
              <Button variant="outline" onClick={handleClose}>
                Close
              </Button>
            </>
          ) : currentStep !== 'source' ? (
            <>
              <Button variant="outline" onClick={handleBack}>
                ← Back
              </Button>
              <div className="flex gap-2">
                <Button variant="outline" onClick={handleClose}>
                  Cancel
                </Button>
                {currentStep === 'file-upload' && selectedSource === 'file' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!selectedFile || isAnalyzing || (fileMetadata !== null && !fileMetadata.formatSupported)}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Continue →'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'clipboard' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!clipboardContent || isAnalyzing}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Continue →'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'git' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!gitContent || isAnalyzing || (gitMetadata !== null && !gitMetadata.formatSupported)}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Continue →'}
                  </Button>
                )}
                {currentStep === 'select' && (
                  <Button
                    onClick={handleImport}
                    disabled={selectedCount === 0}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    Import {selectedCount} Class{selectedCount !== 1 ? 'es' : ''} →
                  </Button>
                )}
              </div>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <div />
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ClassImportDialog;

