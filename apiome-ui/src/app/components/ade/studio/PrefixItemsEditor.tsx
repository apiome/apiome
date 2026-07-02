'use client';

import React, { useState, useEffect } from 'react';
import { Plus, Trash2, GripVertical } from 'lucide-react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

type JSONSchema = { type?: string | string[]; [k: string]: any };

interface PrefixItemsEditorProps {
  value?: JSONSchema[];
  onChange: (items: JSONSchema[]) => void;
}

interface SortableItemProps {
  id: string;
  index: number;
  schema: JSONSchema;
  onUpdate: (index: number, schema: JSONSchema) => void;
  onRemove: (index: number) => void;
}

const SortableItem: React.FC<SortableItemProps> = ({ id, index, schema, onUpdate, onRemove }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 };

  const [description, setDescription] = useState<string>(schema?.description || '');
  const [examplesText, setExamplesText] = useState<string>(
    schema?.examples ? schema.examples.map((e: any) => typeof e === 'string' ? e : JSON.stringify(e)).join(', ') : ''
  );

  useEffect(() => {
    setDescription(schema?.description || '');
    setExamplesText(
      schema?.examples ? schema.examples.map((e: any) => typeof e === 'string' ? e : JSON.stringify(e)).join(', ') : ''
    );
  }, [schema]);

  const handleTypeChange = (newType: string) => {
    onUpdate(index, { ...schema, type: newType || undefined });
  };

  const handleDescriptionChange = (newDescription: string) => {
    setDescription(newDescription);
    const updated = { ...schema };
    if (newDescription.trim()) updated.description = newDescription;
    else delete updated.description;
    onUpdate(index, updated);
  };

  const handleExamplesChange = (value: string) => {
    setExamplesText(value);
    const updated = { ...schema };
    const type = getType();
    const parts = value.split(',').map(s => s.trim()).filter(Boolean);
    if (value.trim()) {
      updated.examples = parts.map(part => {
        if (type === 'number' || type === 'integer') {
          const num = Number(part);
          return isNaN(num) ? part : num;
        }
        if (type === 'boolean') {
          if (part.toLowerCase() === 'true') return true;
          if (part.toLowerCase() === 'false') return false;
          return part;
        }
        if (type === 'object' || type === 'array') {
          try { return JSON.parse(part); } catch { return part; }
        }
        return part;
      });
    } else {
      delete updated.examples;
    }
    onUpdate(index, updated);
  };

  const getType = () => {
    if (!schema?.type) return '';
    return Array.isArray(schema.type) ? schema.type[0] : schema.type;
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="mb-2 p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
    >
      <div className="flex items-center gap-2 mb-3">
        <button
          type="button"
          {...attributes}
          {...listeners}
          className="cursor-grab active:cursor-grabbing flex items-center text-slate-500 dark:text-slate-400 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <GripVertical className="w-5 h-5" />
        </button>
        <span className="text-sm font-semibold min-w-[80px]">Position {index}</span>
        <select
          value={getType()}
          onChange={(e) => handleTypeChange(e.target.value)}
          className="min-w-[140px] px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
        >
          <option value="">Any</option>
          <option value="string">string</option>
          <option value="number">number</option>
          <option value="integer">integer</option>
          <option value="boolean">boolean</option>
          <option value="object">object</option>
          <option value="array">array</option>
          <option value="null">null</option>
        </select>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="p-2 rounded text-red-600 hover:bg-red-500/10"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
      <input
        type="text"
        className="w-full mb-3 px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
        placeholder="Description for this position (e.g., X coordinate, Name column)"
        value={description}
        onChange={(e) => handleDescriptionChange(e.target.value)}
      />
      <div>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
          Examples (comma-separated)
        </label>
        <input
          type="text"
          className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
          placeholder={getType() === 'number' ? 'e.g., 10.5, 20.3' : getType() === 'boolean' ? 'e.g., true, false' : 'e.g., value1, value2'}
          value={examplesText}
          onChange={(e) => handleExamplesChange(e.target.value)}
        />
        <p className="text-xs text-slate-500 mt-1">Example values for this {getType() || 'position'}</p>
      </div>
    </div>
  );
};

export const PrefixItemsEditor: React.FC<PrefixItemsEditorProps> = ({ value = [], onChange }) => {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const handleDragEnd = (event: any) => {
    const { active, over } = event;
    if (active.id !== over?.id) {
      const oldIndex = value.findIndex((_, i) => `prefix-${i}` === active.id);
      const newIndex = value.findIndex((_, i) => `prefix-${i}` === over?.id);
      if (oldIndex !== -1 && newIndex !== -1) onChange(arrayMove(value, oldIndex, newIndex));
    }
  };

  const handleUpdate = (index: number, schema: JSONSchema) => {
    const updated = [...value];
    updated[index] = schema;
    onChange(updated);
  };

  const handleRemove = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  const handleAdd = () => {
    onChange([...value, { type: 'string' }]);
  };

  return (
    <div>
      <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
        Define schemas for specific array positions. Items beyond these positions will use the regular <code className="px-1 py-0.5 rounded bg-slate-200 dark:bg-slate-700">items</code> schema.
      </p>

      {value.length === 0 && (
        <div className="p-6 mb-4 text-center text-slate-500 dark:text-slate-400 border border-dashed border-slate-300 dark:border-slate-600 rounded-lg">
          No prefix items defined. Click &quot;Add Position&quot; to define schemas for specific array positions.
        </div>
      )}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={value.map((_, i) => `prefix-${i}`)} strategy={verticalListSortingStrategy}>
          {value.map((schema, index) => (
            <SortableItem
              key={`prefix-${index}`}
              id={`prefix-${index}`}
              index={index}
              schema={schema}
              onUpdate={handleUpdate}
              onRemove={handleRemove}
            />
          ))}
        </SortableContext>
      </DndContext>

      <button
        type="button"
        onClick={handleAdd}
        className="mt-2 w-full py-2 px-4 rounded-lg border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-center gap-2"
      >
        <Plus className="w-4 h-4" />
        Add Position
      </button>

      {value.length > 0 && (
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-4">
          <strong>Example:</strong> For a tuple like <code className="px-1 rounded bg-slate-200 dark:bg-slate-700">[string, number, boolean]</code>,
          define 3 positions with types string, number, and boolean respectively.
        </p>
      )}
    </div>
  );
};
