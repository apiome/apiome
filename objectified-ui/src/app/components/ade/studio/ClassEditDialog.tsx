'use client';

import { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import Alert from '@mui/material/Alert';
import Checkbox from '@mui/material/Checkbox';
import FormControlLabel from '@mui/material/FormControlLabel';
import Radio from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import Autocomplete from '@mui/material/Autocomplete';
import { Copy, Download, RefreshCw, Check, Tag as TagIcon, ExternalLink } from 'lucide-react';
import YAML from 'yaml';
import jsf from 'json-schema-faker';
import { generateClassOpenApiSpec } from '../../../utils/openapi';
import { createClass, updateClass, assignTagToClass, removeTagFromClass, getTagsForClass } from '../../../../../lib/db/helper';
import Chip from '@mui/material/Chip';
import { ExtensionsEditor } from './ExtensionsEditor';

// Dynamically import Monaco Editor with SSR disabled
const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center">
      <div className="text-gray-500 dark:text-gray-400">Loading editor...</div>
    </div>
  ),
});

interface ClassEditDialogProps {
  open: boolean;
  onClose: () => void;
  editingClassData: any;
  nodes: any[];
  isReadOnly?: boolean;
  onSave?: () => void;
  projectId?: string;
  versionId?: string;
  projectTags?: any[];
  projectMetadata?: {
    summary?: string;
    termsOfService?: string;
    contact?: {
      name?: string;
      url?: string;
      email?: string;
    };
    license?: {
      name?: string;
      identifier?: string;
      url?: string;
    };
  };
}

const ClassEditDialog = ({ open, onClose, editingClassData, nodes, isReadOnly = false, onSave, projectId = '', versionId = '', projectTags = [], projectMetadata }: ClassEditDialogProps) => {
  const [tabValue, setTabValue] = useState(0);
  const [exampleRefreshKey, setExampleRefreshKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [openApiDoc, setOpenApiDoc] = useState<any>(null);
  const [loadingOpenApiDoc, setLoadingOpenApiDoc] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    allOf: [] as string[],
    anyOf: [] as string[],
    oneOf: [] as string[],
    discriminatorProperty: '',
    discriminatorUseAuto: true,
    additionalProperties: null as boolean | null,
    deprecated: false,
    deprecationMessage: '',
    selectedTags: [] as string[],
    extensions: {} as Record<string, any>,
    externalDocsUrl: '',
    externalDocsDescription: '',
    error: ''
  });

  // Reset view and form when dialog opens
  useEffect(() => {
    if (open) {
      setTabValue(0);
      setExampleRefreshKey(0);

      if (editingClassData) {
        // Edit mode - populate form with existing class data
        const schema = typeof editingClassData.schema === 'string'
          ? JSON.parse(editingClassData.schema)
          : editingClassData.schema || {};

        const allOf = schema.allOf?.map((item: any) => item.$ref?.split('/').pop()).filter(Boolean) || [];
        const anyOf = schema.anyOf?.map((item: any) => item.$ref?.split('/').pop()).filter(Boolean) || [];
        const oneOf = schema.oneOf?.map((item: any) => item.$ref?.split('/').pop()).filter(Boolean) || [];

        // Extract extensions (x- prefixed properties)
        const extensions: Record<string, any> = {};
        Object.keys(schema).forEach(key => {
          if (key.startsWith('x-')) {
            extensions[key] = schema[key];
          }
        });

        // Load tags for this class
        const loadTags = async () => {
          try {
            const result = await getTagsForClass(editingClassData.id);
            const classTags = JSON.parse(result);
            const tagIds = classTags.map((ct: any) => ct.tag_id);

            setFormData({
              name: editingClassData.name || '',
              description: editingClassData.description || '',
              allOf,
              anyOf,
              oneOf,
              discriminatorProperty: schema.discriminator?.propertyName || '',
              discriminatorUseAuto: !schema.discriminator?.mapping,
              additionalProperties: schema.additionalProperties !== undefined ? schema.additionalProperties : null,
              deprecated: schema.deprecated || false,
              deprecationMessage: schema.deprecationMessage || '',
              selectedTags: tagIds,
              extensions,
              externalDocsUrl: schema.externalDocs?.url || '',
              externalDocsDescription: schema.externalDocs?.description || '',
              error: ''
            });
          } catch (error) {
            console.error('Error loading tags:', error);
            setFormData({
              name: editingClassData.name || '',
              description: editingClassData.description || '',
              allOf,
              anyOf,
              oneOf,
              discriminatorProperty: schema.discriminator?.propertyName || '',
              discriminatorUseAuto: !schema.discriminator?.mapping,
              additionalProperties: schema.additionalProperties !== undefined ? schema.additionalProperties : null,
              deprecated: schema.deprecated || false,
              deprecationMessage: schema.deprecationMessage || '',
              selectedTags: [],
              extensions,
              externalDocsUrl: schema.externalDocs?.url || '',
              externalDocsDescription: schema.externalDocs?.description || '',
              error: ''
            });
          }
        };

        loadTags();
      } else {
        // Add mode - reset form to empty state
        setFormData({
          name: '',
          description: '',
          allOf: [],
          anyOf: [],
          oneOf: [],
          discriminatorProperty: '',
          discriminatorUseAuto: true,
          additionalProperties: null,
          deprecated: false,
          deprecationMessage: '',
          selectedTags: [],
          extensions: {},
          externalDocsUrl: '',
          externalDocsDescription: '',
          error: ''
        });
      }
    }
  }, [open, editingClassData]);

  // Helper function to build schema from form data
  const buildSchemaFromFormData = () => {
    const schema: any = { type: 'object', properties: {} };

    // Add composition types
    if (formData.allOf.length > 0) {
      schema.allOf = formData.allOf.map(name => ({ $ref: `#/components/schemas/${name}` }));
    }
    if (formData.anyOf.length > 0) {
      schema.anyOf = formData.anyOf.map(name => ({ $ref: `#/components/schemas/${name}` }));
    }
    if (formData.oneOf.length > 0) {
      schema.oneOf = formData.oneOf.map(name => ({ $ref: `#/components/schemas/${name}` }));
    }

    // Add discriminator if specified
    if (formData.discriminatorProperty && (formData.allOf.length > 0 || formData.anyOf.length > 0 || formData.oneOf.length > 0)) {
      schema.discriminator = { propertyName: formData.discriminatorProperty };
      if (!formData.discriminatorUseAuto) {
        schema.discriminator.mapping = {};
        const list = formData.allOf.length > 0 ? formData.allOf : formData.anyOf.length > 0 ? formData.anyOf : formData.oneOf;
        list.forEach((name: string) => {
          schema.discriminator.mapping[name] = `#/components/schemas/${name}`;
        });
      }
    }

    // Add additionalProperties if set
    if (formData.additionalProperties !== null) {
      schema.additionalProperties = formData.additionalProperties;
    }

    // Add deprecated if true
    if (formData.deprecated) {
      schema.deprecated = true;
      if (formData.deprecationMessage.trim()) {
        schema.deprecationMessage = formData.deprecationMessage.trim();
      }
    }

    // Add externalDocs if URL is provided
    if (formData.externalDocsUrl.trim()) {
      schema.externalDocs = {
        url: formData.externalDocsUrl.trim()
      };
      if (formData.externalDocsDescription.trim()) {
        schema.externalDocs.description = formData.externalDocsDescription.trim();
      }
    }

    // Add extensions (x- prefixed properties)
    Object.keys(formData.extensions).forEach(key => {
      if (key.startsWith('x-')) {
        schema[key] = formData.extensions[key];
      }
    });

    return schema;
  };

  // Generate OpenAPI doc asynchronously
  useEffect(() => {
    const generateOpenApiDocAsync = async () => {
      if (!open) return;

      setLoadingOpenApiDoc(true);
      try {
        const allClasses = nodes.map(node => node.data).filter(data => data && data.name);

        const previewClassData = editingClassData || {
          name: formData.name || 'NewClass',
          description: formData.description,
          schema: buildSchemaFromFormData()
        };

        const doc = await generateClassOpenApiSpec(previewClassData, allClasses, {
          title: `${previewClassData.name} Schema`,
          version: '1.0.0',
          description: 'OpenAPI 3.1.0 schema definition',
          metadata: projectMetadata
        });

        setOpenApiDoc(doc);
      } catch (error) {
        console.error('Failed to generate OpenAPI doc:', error);
        setOpenApiDoc(null);
      } finally {
        setLoadingOpenApiDoc(false);
      }
    };

    generateOpenApiDocAsync();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editingClassData, formData.name, formData.description, formData.allOf, formData.anyOf, formData.oneOf, formData.discriminatorProperty, formData.discriminatorUseAuto, formData.additionalProperties, nodes]);

  // Get all available class names for composition selectors (excluding current class)
  const availableClasses = nodes
    .map(node => node.data)
    .filter(data => data && data.name && (!editingClassData || data.name !== editingClassData.name))
    .map(data => data.name);

  // Save handler
  const handleSave = async () => {
    if (!formData.name.trim()) {
      setFormData(prev => ({ ...prev, error: 'Class name is required' }));
      return;
    }

    // For create mode, versionId is required
    if (!editingClassData && !versionId) {
      setFormData(prev => ({ ...prev, error: 'Version ID is required to create a class' }));
      return;
    }

    setSaving(true);
    setFormData(prev => ({ ...prev, error: '' }));

    try {
      // Build schema from form data
      const schema = buildSchemaFromFormData();

      let result: string;
      let classId: string;

      if (editingClassData) {
        // Update existing class
        result = await updateClass(
          editingClassData.id,
          formData.name,
          formData.description || null,
          schema
        );
        classId = editingClassData.id;
      } else {
        // Create new class
        result = await createClass(
          versionId!,
          formData.name,
          formData.description || null,
          schema
        );
        const response = JSON.parse(result);
        if (response.success && response.class) {
          classId = response.class.id;
        } else {
          setFormData(prev => ({ ...prev, error: response.error || 'Failed to create class' }));
          setSaving(false);
          return;
        }
      }

      const response = JSON.parse(result);
      if (!response.success) {
        setFormData(prev => ({ ...prev, error: response.error || 'Failed to save class' }));
        setSaving(false);
        return;
      }

      // Update tag assignments
      if (projectId && classId!) {
        try {
          // Get current tags
          const currentTagsResult = await getTagsForClass(classId);
          const currentTags = JSON.parse(currentTagsResult);
          const currentTagIds = currentTags.map((ct: any) => ct.tag_id);

          // Find tags to add and remove
          const tagsToAdd = formData.selectedTags.filter(id => !currentTagIds.includes(id));
          const tagsToRemove = currentTagIds.filter((id: string) => !formData.selectedTags.includes(id));

          // Add new tags
          for (const tagId of tagsToAdd) {
            await assignTagToClass(classId, tagId);
          }

          // Remove old tags
          for (const tagId of tagsToRemove) {
            await removeTagFromClass(classId, tagId);
          }
        } catch (error) {
          console.error('Error updating tags:', error);
          // Don't fail the whole save if tag update fails
        }
      }

      // Success - call onSave callback and close
      if (onSave) {
        onSave();
      }
      onClose();
    } catch (error) {
      console.error('Error saving class:', error);
      setFormData(prev => ({ ...prev, error: 'An error occurred while saving the class' }));
    } finally {
      setSaving(false);
    }
  };

  // Render composition selector
  const renderCompositionSelector = (
    label: string,
    helperText: string,
    value: string[],
    onChange: (items: string[]) => void,
    color: 'primary' | 'info' | 'secondary'
  ) => (
    <Box sx={{ mb: 2 }}>
      <Typography variant="body2" sx={{ mb: 1, fontWeight: 500 }}>
        {label}
      </Typography>
      <Autocomplete
        multiple
        options={availableClasses}
        value={value}
        onChange={(_, newValue) => onChange(newValue)}
        disabled={isReadOnly}
        slotProps={{
          chip: {
            color: color,
            size: "small"
          }
        }}
        renderInput={(params) => (
          <TextField
            {...params}
            placeholder="Select classes..."
            helperText={helperText}
            size="small"
          />
        )}
      />
    </Box>
  );

  // Get the preview class data for display
  const previewClassData = editingClassData || {
    name: formData.name || 'NewClass',
    description: formData.description,
    schema: { type: 'object', properties: {} }
  };

  // Get the class schema from the generated OpenAPI doc (with null check)
  const classSchema = openApiDoc?.components?.schemas?.[previewClassData.name];

  // Helper function to resolve $ref references in a schema
  const resolveRefs = (schema: any, schemas: any, visited: Set<string> = new Set(), path: string = ''): any => {
    if (!schema || typeof schema !== 'object') return schema;

    // Preprocess: Convert prefixItems to items array format for json-schema-faker compatibility
    // json-schema-faker doesn't support prefixItems (JSON Schema 2020-12), so we convert it
    if (schema.prefixItems && Array.isArray(schema.prefixItems)) {
      const processedSchema = { ...schema };

      // If items is true or an empty object, it means "allow any additional items"
      // For json-schema-faker, we'll use the prefixItems as a tuple
      if (schema.items === true || (schema.items && Object.keys(schema.items).length === 0)) {
        // Use prefixItems as items for tuple generation
        processedSchema.items = schema.prefixItems;
        delete processedSchema.prefixItems;

        // Set minItems and maxItems to match prefixItems length for consistent generation
        if (!processedSchema.minItems) {
          processedSchema.minItems = schema.prefixItems.length;
        }
        if (!processedSchema.maxItems) {
          processedSchema.maxItems = schema.prefixItems.length;
        }
      } else if (schema.items) {
        // If there's both prefixItems and items, merge them
        // This is tricky - for now, just use prefixItems as the tuple
        processedSchema.items = schema.prefixItems;
        delete processedSchema.prefixItems;
        processedSchema.minItems = schema.prefixItems.length;
        processedSchema.maxItems = schema.prefixItems.length;
      } else {
        // No items specified, use prefixItems as items
        processedSchema.items = schema.prefixItems;
        delete processedSchema.prefixItems;
        processedSchema.minItems = schema.prefixItems.length;
        processedSchema.maxItems = schema.prefixItems.length;
      }

      schema = processedSchema;
    }

    // Handle $ref
    if (schema.$ref && typeof schema.$ref === 'string') {
      const refPath = schema.$ref.split('/');
      const refName = refPath[refPath.length - 1];

      // Prevent circular references
      if (visited.has(refName)) {
        return { type: 'object', description: `Circular reference to ${refName}` };
      }

      const referencedSchema = schemas[refName];
      if (referencedSchema) {
        const newVisited = new Set(visited);
        newVisited.add(refName);
        return resolveRefs(referencedSchema, schemas, newVisited, `${path}/${refName}`);
      }
      return schema; // Can't resolve, return as-is
    }

    // Handle allOf by merging schemas
    if (Array.isArray(schema.allOf)) {
      const merged: any = {};
      const requiredSet = new Set<string>();

      schema.allOf.forEach((subSchema: any, index: number) => {
        const resolved = resolveRefs(subSchema, schemas, visited, `${path}/allOf[${index}]`);

        // Extract required before merging to handle it separately
        const { required: resolvedRequired, properties: resolvedProperties, ...resolvedRest } = resolved;

        // Merge non-properties/required fields
        Object.assign(merged, resolvedRest);

        // Merge properties
        if (resolvedProperties) {
          merged.properties = { ...merged.properties, ...resolvedProperties };
        }

        // Merge required arrays (use Set to avoid duplicates)
        if (resolvedRequired) {
          resolvedRequired.forEach((field: string) => requiredSet.add(field));
        }
      });

      // Convert Set back to array if there are required fields
      if (requiredSet.size > 0) {
        merged.required = Array.from(requiredSet);
      }

      // Keep other properties from the original schema
      const { allOf, required: restRequired, properties: restProperties, ...rest } = schema;

      // Merge properties from original schema (these are additional properties)
      if (restProperties) {
        merged.properties = { ...merged.properties, ...restProperties };
      }

      // Merge required from original schema
      if (restRequired) {
        restRequired.forEach((field: string) => requiredSet.add(field));
        merged.required = Array.from(requiredSet);
      }

      return { ...merged, ...rest };
    }

    // Handle anyOf and oneOf
    if (Array.isArray(schema.anyOf)) {
      return {
        ...schema,
        anyOf: schema.anyOf.map((s: any, index: number) =>
          resolveRefs(s, schemas, visited, `${path}/anyOf[${index}]`)
        )
      };
    }

    if (Array.isArray(schema.oneOf)) {
      return {
        ...schema,
        oneOf: schema.oneOf.map((s: any, index: number) =>
          resolveRefs(s, schemas, visited, `${path}/oneOf[${index}]`)
        )
      };
    }

    // Recursively resolve nested objects and arrays
    const resolved: any = Array.isArray(schema) ? [] : {};
    for (const key in schema) {
      if (schema.hasOwnProperty(key)) {
        // Don't recursively resolve primitive values or strings that aren't schemas
        const value = schema[key];
        if (value && typeof value === 'object') {
          resolved[key] = resolveRefs(value, schemas, visited, `${path}/${key}`);
        } else {
          resolved[key] = value;
        }
      }
    }
    return resolved;
  };

  // Generate schema content based on current tab
  let schemaContent: string = '';

  if (loadingOpenApiDoc || !openApiDoc) {
    schemaContent = '// Loading schema...';
  } else if (tabValue === 1) {
    // JSON view
    schemaContent = JSON.stringify(openApiDoc, null, 2);
  } else if (tabValue === 2) {
    // YAML view
    schemaContent = YAML.stringify(openApiDoc, { lineWidth: 0, aliasDuplicateObjects: false });
  } else if (tabValue === 3) {
    // Example view - regenerate when exampleRefreshKey changes
    try {
      // Resolve all $ref references for json-schema-faker
      const resolvedSchema = resolveRefs(classSchema, openApiDoc.components.schemas);

      // Debug: Log the resolved schema to verify allOf merging
      console.log('Original schema:', classSchema);
      console.log('Resolved schema for example generation:', resolvedSchema);
      console.log('Resolved schema properties:', resolvedSchema.properties);

      // Use exampleRefreshKey in random seed to force regeneration
      jsf.option({
        random: () => {
          // Mix in exampleRefreshKey to ensure different results on each refresh
          const seed = Math.random() * (exampleRefreshKey + 1);
          return seed - Math.floor(seed);
        }
      });

      const fakeData = jsf.generate(resolvedSchema);
      schemaContent = JSON.stringify(fakeData, null, 2);
    } catch (error) {
      console.error('Error generating fake data:', error);
      schemaContent = JSON.stringify({
        error: 'Could not generate example data',
        message: error instanceof Error ? error.message : String(error)
      }, null, 2);
    }
  }

  const handleCopy = () => {
    if (!openApiDoc) return;

    let content: string;
    if (tabValue === 3) {
      // Example view
      try {
        const resolvedSchema = resolveRefs(classSchema, openApiDoc.components.schemas);
        const fakeData = jsf.generate(resolvedSchema);
        content = JSON.stringify(fakeData, null, 2);
      } catch (error) {
        console.error('Error generating fake data:', error);
        content = JSON.stringify({ error: 'Could not generate example data' }, null, 2);
      }
    } else if (tabValue === 2) {
      // YAML view
      content = YAML.stringify(openApiDoc, { lineWidth: 0, aliasDuplicateObjects: false });
    } else {
      // JSON view
      content = JSON.stringify(openApiDoc, null, 2);
    }

    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExport = () => {
    if (!openApiDoc) return;

    let content: string;
    let filenameSuffix: string;
    let mimeType: string;
    let extension: string;

    if (tabValue === 3) {
      // Example view
      try {
        const resolvedSchema = resolveRefs(classSchema, openApiDoc.components.schemas);
        const fakeData = jsf.generate(resolvedSchema);
        content = JSON.stringify(fakeData, null, 2);
      } catch (error) {
        console.error('Error generating fake data:', error);
        content = JSON.stringify({ error: 'Could not generate example data' }, null, 2);
      }
      filenameSuffix = 'example';
      mimeType = 'application/json';
      extension = 'json';
    } else if (tabValue === 2) {
      // YAML view
      content = YAML.stringify(openApiDoc, { lineWidth: 0, aliasDuplicateObjects: false });
      filenameSuffix = 'schema';
      mimeType = 'text/yaml';
      extension = 'yaml';
    } else {
      // JSON view
      content = JSON.stringify(openApiDoc, null, 2);
      filenameSuffix = 'schema';
      mimeType = 'application/json';
      extension = 'json';
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${previewClassData.name.toLowerCase()}-${filenameSuffix}.${extension}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      slotProps={{
        paper: {
          sx: {
            height: '90vh',
            maxHeight: '900px',
          }
        }
      }}
    >
      <DialogTitle sx={{ borderBottom: 1, borderColor: 'divider', pb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Typography variant="h6" component="span">
              {!editingClassData ? 'Add Class' : isReadOnly ? `View Class: ${formData.name || editingClassData.name}` : `Edit Class: ${formData.name || editingClassData.name}`}
            </Typography>
            {isReadOnly && (
              <Typography
                variant="caption"
                sx={{
                  color: '#000',
                  bgcolor: '#fbbf24',
                  px: 1.5,
                  py: 0.5,
                  borderRadius: 1,
                  fontWeight: 600,
                  fontSize: '0.75rem'
                }}
              >
                Read Only
              </Typography>
            )}
          </Box>
        </Box>
      </DialogTitle>

      {/* Tabs */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={tabValue} onChange={(_, newValue) => setTabValue(newValue)}>
          <Tab label="Edit" />
          <Tab label="JSON" />
          <Tab label="YAML" />
          <Tab label="Example" />
        </Tabs>
      </Box>

      <DialogContent sx={{ p: tabValue === 0 ? 3 : 0, overflow: tabValue === 0 ? 'auto' : 'hidden' }}>
        {/* Tab 0: Edit Form */}
        {tabValue === 0 && (
          <Box>
            {formData.error && <Alert severity="error" sx={{ mb: 2 }}>{formData.error}</Alert>}

            <TextField
              autoFocus
              margin="dense"
              label="Class Name"
              fullWidth
              required
              value={formData.name}
              onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value.replace(/[^A-Za-z0-9_]/g, '') }))}
              helperText="Only letters, numbers, and underscores are allowed; recommend PascalCase class names."
              sx={{ mb: 2 }}
              disabled={isReadOnly}
            />

            <TextField
              margin="dense"
              label="Description"
              fullWidth
              multiline
              rows={2}
              value={formData.description}
              onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
              sx={{ mb: 2 }}
              disabled={isReadOnly}
            />

            {/* Tags */}
            {projectId && projectTags && projectTags.length > 0 && (
              <Box sx={{ mb: 3 }}>
                <Typography variant="body2" sx={{ mb: 1, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <TagIcon size={16} />
                  Tags
                </Typography>
                <Autocomplete
                  multiple
                  options={projectTags.map((tag: any) => tag.id)}
                  value={formData.selectedTags}
                  onChange={(_, newValue) => setFormData(prev => ({ ...prev, selectedTags: newValue }))}
                  disabled={isReadOnly}
                  getOptionLabel={(tagId) => {
                    const tag = projectTags.find((t: any) => t.id === tagId);
                    return tag ? tag.name : tagId;
                  }}
                  renderTags={(value, getTagProps) =>
                    value.map((tagId, index) => {
                      const tag = projectTags.find((t: any) => t.id === tagId);
                      return (
                        <Chip
                          label={tag?.name || tagId}
                          color={tag?.color as any || 'default'}
                          size="small"
                          {...getTagProps({ index })}
                        />
                      );
                    })
                  }
                  renderOption={(props, tagId) => {
                    const tag = projectTags.find((t: any) => t.id === tagId);
                    return (
                      <li {...props}>
                        <Chip
                          label={tag?.name || tagId}
                          color={tag?.color as any || 'default'}
                          size="small"
                          sx={{ mr: 1 }}
                        />
                        {tag?.description || ''}
                      </li>
                    );
                  }}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      placeholder="Select tags..."
                      helperText="Organize and categorize this class"
                      size="small"
                    />
                  )}
                />
              </Box>
            )}

            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
              Composition/Inheritance (Optional)
            </Typography>

            {renderCompositionSelector(
              "allOf (Inheritance)",
              "Must match all listed schemas",
              formData.allOf,
              (items) => setFormData(prev => ({ ...prev, allOf: items })),
              "primary"
            )}

            {renderCompositionSelector(
              "anyOf (Alternatives)",
              "Must match at least one listed schema",
              formData.anyOf,
              (items) => setFormData(prev => ({ ...prev, anyOf: items })),
              "info"
            )}

            {renderCompositionSelector(
              "oneOf (Exclusive)",
              "Must match exactly one listed schema",
              formData.oneOf,
              (items) => setFormData(prev => ({ ...prev, oneOf: items })),
              "secondary"
            )}

            {/* Discriminator */}
            {(formData.allOf.length > 0 || formData.anyOf.length > 0 || formData.oneOf.length > 0) && (
              <Box sx={{ mt: 3, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                  Discriminator (Optional)
                </Typography>
                <TextField
                  margin="dense"
                  label="Discriminator Property Name"
                  fullWidth
                  placeholder="e.g., type, petType, kind"
                  value={formData.discriminatorProperty}
                  onChange={(e) => setFormData(prev => ({ ...prev, discriminatorProperty: e.target.value }))}
                  helperText="Property name that indicates which schema variant to use for polymorphic objects. This is used for (de)serialization operations."
                  sx={{ mb: 2 }}
                  disabled={isReadOnly}
                />
                {formData.discriminatorProperty && (
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={formData.discriminatorUseAuto}
                        onChange={(e) => setFormData(prev => ({ ...prev, discriminatorUseAuto: e.target.checked }))}
                        disabled={isReadOnly}
                      />
                    }
                    label="Use automatic mapping"
                  />
                )}
              </Box>
            )}

            {/* Additional Properties */}
            <Box sx={{ mt: 3, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                Additional Properties
              </Typography>
              <RadioGroup
                value={formData.additionalProperties === null ? 'default' : formData.additionalProperties ? 'allow' : 'disallow'}
                onChange={(e) => {
                  const value = e.target.value;
                  setFormData(prev => ({ ...prev, additionalProperties: value === 'default' ? null : value === 'allow' }));
                }}
              >
                <FormControlLabel
                  value="default"
                  control={<Radio />}
                  label="Not specified (default behavior - property omitted)"
                  disabled={isReadOnly}
                />
                <FormControlLabel
                  value="allow"
                  control={<Radio />}
                  label="Allow additional properties (set true)"
                  disabled={isReadOnly}
                />
                <FormControlLabel
                  value="disallow"
                  control={<Radio />}
                  label="Disallow additional properties (set false)"
                  disabled={isReadOnly}
                />
              </RadioGroup>
            </Box>

            {/* Deprecated */}
            <Box sx={{ mt: 3, p: 2, bgcolor: 'warning.lighter', borderRadius: 1, border: 1, borderColor: 'warning.light' }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={formData.deprecated}
                    onChange={(e) => setFormData(prev => ({ ...prev, deprecated: e.target.checked }))}
                    disabled={isReadOnly}
                  />
                }
                label={
                  <Box>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                      Mark as Deprecated
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      Indicates this class should no longer be used
                    </Typography>
                  </Box>
                }
              />
              {formData.deprecated && (
                <TextField
                  margin="dense"
                  label="Deprecation Message (Optional)"
                  fullWidth
                  multiline
                  rows={2}
                  placeholder="e.g., Use NewClass instead. This will be removed in version 2.0."
                  value={formData.deprecationMessage}
                  onChange={(e) => setFormData(prev => ({ ...prev, deprecationMessage: e.target.value }))}
                  helperText="Provide context about why it's deprecated and what to use instead"
                  sx={{ mt: 1 }}
                  disabled={isReadOnly}
                />
              )}
            </Box>

            {/* External Documentation */}
            <Box sx={{ mt: 3, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                External Documentation
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
                Link to additional documentation outside the OpenAPI specification
              </Typography>

              <TextField
                margin="dense"
                label="Documentation URL"
                fullWidth
                type="url"
                value={formData.externalDocsUrl}
                onChange={(e) => setFormData(prev => ({ ...prev, externalDocsUrl: e.target.value }))}
                placeholder="https://docs.example.com/classes/user"
                helperText="URL to external documentation"
                sx={{ mb: 2 }}
                disabled={isReadOnly}
                slotProps={{
                  input: {
                    endAdornment: formData.externalDocsUrl.trim() && (
                      <Button
                        size="small"
                        startIcon={<ExternalLink size={16} />}
                        onClick={() => {
                          const url = formData.externalDocsUrl.trim();
                          if (url) {
                            window.open(url, '_blank', 'noopener,noreferrer');
                          }
                        }}
                        disabled={isReadOnly}
                        sx={{ ml: 1 }}
                      >
                        Check Link
                      </Button>
                    ),
                  }
                }}
              />

              <TextField
                margin="dense"
                label="Description (Optional)"
                fullWidth
                multiline
                rows={2}
                value={formData.externalDocsDescription}
                onChange={(e) => setFormData(prev => ({ ...prev, externalDocsDescription: e.target.value }))}
                placeholder="e.g., Detailed user guide with examples"
                helperText="Optional description of the external documentation"
                disabled={isReadOnly}
              />
            </Box>

            {/* Extensions */}
            <Box sx={{ mt: 3, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
              <ExtensionsEditor
                value={formData.extensions}
                onChange={(extensions) => setFormData(prev => ({ ...prev, extensions }))}
                disabled={isReadOnly}
                size="small"
              />
            </Box>
          </Box>
        )}

        {/* Tab 1: JSON View */}
        {tabValue === 1 && (
          <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ display: 'flex', gap: 1, p: 2, borderBottom: 1, borderColor: 'divider' }}>
              <Button
                size="small"
                startIcon={copied ? <Check size={16} /> : <Copy size={16} />}
                onClick={handleCopy}
                variant="outlined"
                disabled={copied || loadingOpenApiDoc || !openApiDoc}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button
                size="small"
                startIcon={<Download size={16} />}
                onClick={handleExport}
                variant="contained"
                disabled={loadingOpenApiDoc || !openApiDoc}
              >
                Export
              </Button>
            </Box>
            <Box sx={{ flex: 1 }}>
              <Editor
                height="100%"
                language="json"
                value={schemaContent}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  fontSize: 13,
                  wordWrap: 'on',
                  lineNumbers: 'on',
                  renderWhitespace: 'none',
                  folding: true
                }}
              />
            </Box>
          </Box>
        )}

        {/* Tab 2: YAML View */}
        {tabValue === 2 && (
          <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ display: 'flex', gap: 1, p: 2, borderBottom: 1, borderColor: 'divider' }}>
              <Button
                size="small"
                startIcon={copied ? <Check size={16} /> : <Copy size={16} />}
                onClick={handleCopy}
                variant="outlined"
                disabled={copied || loadingOpenApiDoc || !openApiDoc}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button
                size="small"
                startIcon={<Download size={16} />}
                onClick={handleExport}
                variant="contained"
                disabled={loadingOpenApiDoc || !openApiDoc}
              >
                Export
              </Button>
            </Box>
            <Box sx={{ flex: 1 }}>
              <Editor
                height="100%"
                language="yaml"
                value={schemaContent}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  fontSize: 13,
                  wordWrap: 'on',
                  lineNumbers: 'on',
                  renderWhitespace: 'none',
                  folding: true
                }}
              />
            </Box>
          </Box>
        )}

        {/* Tab 3: Example View */}
        {tabValue === 3 && (
          <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ display: 'flex', gap: 1, p: 2, borderBottom: 1, borderColor: 'divider' }}>
              <Button
                size="small"
                startIcon={<RefreshCw size={16} />}
                onClick={() => setExampleRefreshKey(prev => prev + 1)}
                variant="outlined"
                title="Generate new example"
                disabled={loadingOpenApiDoc || !openApiDoc}
              >
                Refresh
              </Button>
              <Button
                size="small"
                startIcon={copied ? <Check size={16} /> : <Copy size={16} />}
                onClick={handleCopy}
                variant="outlined"
                disabled={copied || loadingOpenApiDoc || !openApiDoc}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button
                size="small"
                startIcon={<Download size={16} />}
                onClick={handleExport}
                variant="contained"
                disabled={loadingOpenApiDoc || !openApiDoc}
              >
                Export
              </Button>
            </Box>
            <Box sx={{ flex: 1 }}>
              <Editor
                key={`example-${exampleRefreshKey}`}
                height="100%"
                language="json"
                value={schemaContent}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  fontSize: 13,
                  wordWrap: 'on',
                  lineNumbers: 'on',
                  renderWhitespace: 'none',
                  folding: true
                }}
              />
            </Box>
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>
          Cancel
        </Button>
        {!isReadOnly && tabValue === 0 && (
          <Button onClick={handleSave} variant="contained" disabled={saving}>
            {saving ? 'Saving...' : 'Save'}
          </Button>
        )}
        {tabValue !== 0 && (
          <Button onClick={onClose} variant="contained">
            Close
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};

export default ClassEditDialog;

