'use client';

import React, { useState, useEffect } from 'react';
import { X, Plus, Trash2, FileJson, Layers } from 'lucide-react';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { useStudio } from '../../StudioContext';
import {
  getClassesWithPropertiesAndTags,
} from '../../../../../../lib/db/helper';
import ReuseSearchCombobox from './ReuseSearchCombobox';
import { buildArraySchemaFromCurrent } from './schema-builder-utils';

interface SchemaBuilderProps {
  value?: any; // Current schema value (can be $ref, type: object, etc.)
  onChange: (schema: any) => void;
  label?: string;
  description?: string;
  allowInline?: boolean; // Allow creating inline object schemas
}

interface ClassItem {
  id: string;
  name: string;
  description?: string;
}

interface PropertyItem {
  id: string;
  name: string;
  type?: string;
  data?: any;
}

export default function SchemaBuilder({
  value,
  onChange,
  label = 'Schema',
  description,
  allowInline = true,
}: SchemaBuilderProps) {
  const isDark = useDarkMode();
  const { selectedVersionId } = useStudio();
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [properties, setProperties] = useState<PropertyItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [schemaType, setSchemaType] = useState<'ref' | 'object' | 'array' | 'primitive'>('ref');
  const [selectedClassId, setSelectedClassId] = useState<string>('');
  const [selectedPropertyId, setSelectedPropertyId] = useState<string>('');
  const [arrayItemSchema, setArrayItemSchema] = useState<any>(null);
  const [primitiveType, setPrimitiveType] = useState<string>('string');

  // Load classes and properties
  useEffect(() => {
    if (!selectedVersionId) {
      setClasses([]);
      setProperties([]);
      return;
    }

    const loadData = async () => {
      setIsLoading(true);
      try {
        const classesResponse = await getClassesWithPropertiesAndTags(selectedVersionId);
        const classesData: any[] = JSON.parse(classesResponse as string);

        const uniqueClasses = classesData.reduce((acc: ClassItem[], cls: any) => {
          if (!acc.find((c) => c.id === cls.id)) {
            acc.push({ id: cls.id, name: cls.name, description: cls.description });
          }
          return acc;
        }, []);

        setClasses(uniqueClasses);

        const uniqueProperties = new Map<string, PropertyItem>();
        if (Array.isArray(classesData)) {
          classesData.forEach((cls: any) => {
            if (cls.properties && Array.isArray(cls.properties)) {
              cls.properties.forEach((prop: any) => {
                if (!uniqueProperties.has(prop.id)) {
                  uniqueProperties.set(prop.id, {
                    id: prop.id,
                    name: prop.name,
                    type: prop.data?.type,
                    data: prop.data,
                  });
                }
              });
            }
          });
        }

        setProperties(Array.from(uniqueProperties.values()));
      } catch (error) {
        console.error('Error loading classes and properties:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
  }, [selectedVersionId]);

  // Initialize from value - wait for classes to load
  useEffect(() => {
    if (value) {
      if (value.$ref) {
        setSchemaType('ref');
        // Extract class ID from $ref (format: #/components/schemas/ClassName)
        const className = value.$ref.split('/').pop();
        
        if (classes.length > 0) {
          const classItem = classes.find(c => c.name === className);
          if (classItem) {
            setSelectedClassId(classItem.id);
          } else {
            // Class not found - might not be loaded yet, but we'll keep the $ref
            setSelectedClassId(''); // Clear selection if class not found
          }
        }
      } else if (value.type === 'array') {
        setSchemaType('array');
        setArrayItemSchema(value.items || null);
      } else if (value.type === 'object') {
        setSchemaType('object');
      } else {
        setSchemaType('primitive');
        setPrimitiveType(value.type || 'string');
      }
    } else {
      // No value - reset to defaults
      setSchemaType('ref');
      setSelectedClassId('');
      setSelectedPropertyId('');
      setArrayItemSchema(null);
      setPrimitiveType('string');
    }
  }, [value, classes]);

  const handleSchemaTypeChange = (type: 'ref' | 'object' | 'array' | 'primitive') => {
    setSchemaType(type);
    
    // Reset related state
    setSelectedClassId('');
    setSelectedPropertyId('');
    setArrayItemSchema(null);
    setPrimitiveType('string');

    // Emit default schema based on type
    if (type === 'primitive') {
      onChange({ type: 'string' });
    } else if (type === 'array') {
      onChange(buildArraySchemaFromCurrent(value));
    } else if (type === 'object') {
      onChange({ type: 'object', properties: {} });
    } else {
      onChange(null);
    }
  };

  const handleClassSelect = (classId: string) => {
    setSelectedClassId(classId);
    const classItem = classes.find(c => c.id === classId);
    if (classItem) {
      onChange({ $ref: `#/components/schemas/${classItem.name}` });
    }
  };

  const handlePropertySelect = (propertyId: string) => {
    setSelectedPropertyId(propertyId);
    const propertyItem = properties.find(p => p.id === propertyId);
    if (propertyItem && propertyItem.data) {
      // Use the property's schema directly
      onChange(propertyItem.data);
    }
  };

  const handleArrayItemSchemaChange = (itemSchema: any) => {
    setArrayItemSchema(itemSchema);
    onChange({ type: 'array', items: itemSchema });
  };

  const handlePrimitiveTypeChange = (type: string) => {
    setPrimitiveType(type);
    onChange({ type });
  };

  const handleClear = () => {
    setSchemaType('ref');
    setSelectedClassId('');
    setSelectedPropertyId('');
    setArrayItemSchema(null);
    setPrimitiveType('string');
    onChange(null);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 mb-0.5">
            {label}
          </label>
          {description && (
            <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5">
              {description}
            </p>
          )}
        </div>
        {value && (
          <button
            onClick={handleClear}
            className="p-1 text-gray-400 hover:text-red-500 transition-colors"
            title="Clear schema"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Schema Type Selector */}
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => handleSchemaTypeChange('ref')}
          className={`px-3 py-2 rounded-lg text-xs font-medium transition-all ${
            schemaType === 'ref'
              ? 'bg-indigo-500 text-white shadow-md'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
          }`}
        >
          <div className="flex items-center gap-1.5 justify-center">
            <Layers size={12} />
            <span>Class Reference</span>
          </div>
        </button>
        <button
          type="button"
          onClick={() => handleSchemaTypeChange('array')}
          className={`px-3 py-2 rounded-lg text-xs font-medium transition-all ${
            schemaType === 'array'
              ? 'bg-indigo-500 text-white shadow-md'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
          }`}
        >
          <div className="flex items-center gap-1.5 justify-center">
            <FileJson size={12} />
            <span>Array</span>
          </div>
        </button>
        {allowInline && (
          <>
            <button
              type="button"
              onClick={() => handleSchemaTypeChange('object')}
              className={`px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                schemaType === 'object'
                  ? 'bg-indigo-500 text-white shadow-md'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}
            >
              <div className="flex items-center gap-1.5 justify-center">
                <FileJson size={12} />
                <span>Object</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => handleSchemaTypeChange('primitive')}
              className={`px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                schemaType === 'primitive'
                  ? 'bg-indigo-500 text-white shadow-md'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}
            >
              <div className="flex items-center gap-1.5 justify-center">
                <FileJson size={12} />
                <span>Primitive</span>
              </div>
            </button>
          </>
        )}
      </div>

      {/* Schema Configuration */}
      {schemaType === 'ref' && (
        <div className="space-y-2">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Reuse class ($ref)
            </label>
            {isLoading ? (
              <div className="text-xs text-gray-500 dark:text-gray-400 py-2">Loading classes...</div>
            ) : classes.length === 0 ? (
              <div className="text-xs text-gray-500 dark:text-gray-400 py-2 border border-dashed rounded-lg px-3">
                No classes available. Create classes in the main Studio editor.
              </div>
            ) : (
              <ReuseSearchCombobox
                aria-label="Select class for schema reference"
                items={classes.map((cls) => ({ id: cls.id, label: cls.name }))}
                value={selectedClassId}
                onValueChange={(id) => handleClassSelect(id)}
                placeholder="Search classes…"
                searchPlaceholder="Filter by name…"
                emptyText="No classes match."
                triggerClassName="h-9 text-sm"
              />
            )}
            {value?.$ref && !selectedClassId && classes.length > 0 && (
              <div className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                ⚠️ Class "{value.$ref.split('/').pop()}" not found in available classes
              </div>
            )}
          </div>
        </div>
      )}

      {schemaType === 'array' && (
        <div className="space-y-2">
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            Array Item Schema
          </label>
          <SchemaBuilder
            value={arrayItemSchema}
            onChange={handleArrayItemSchemaChange}
            label=""
            allowInline={true}
          />
        </div>
      )}

      {schemaType === 'object' && allowInline && (
        <div className="p-3 border border-dashed rounded-lg">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Inline object schemas will be defined as type: object with properties.
            For complex schemas, use a Class Reference instead.
          </p>
        </div>
      )}

      {schemaType === 'primitive' && allowInline && (
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            Primitive Type
          </label>
          <select
            value={primitiveType}
            onChange={(e) => handlePrimitiveTypeChange(e.target.value)}
            className={`w-full px-3 py-2 rounded-lg text-sm border ${
              isDark
                ? 'bg-gray-900 border-gray-600 text-gray-100'
                : 'bg-white border-gray-300 text-gray-900'
            } focus:outline-none focus:ring-2 focus:ring-indigo-500`}
          >
            <option value="string">String</option>
            <option value="integer">Integer</option>
            <option value="number">Number</option>
            <option value="boolean">Boolean</option>
          </select>
        </div>
      )}

      {/* Current Schema Preview */}
      {value && (
        <div className="mt-3 p-2 bg-gray-50 dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700">
          <div className="text-[10px] font-mono text-gray-600 dark:text-gray-400">
            {JSON.stringify(value, null, 2)}
          </div>
        </div>
      )}
    </div>
  );
}
