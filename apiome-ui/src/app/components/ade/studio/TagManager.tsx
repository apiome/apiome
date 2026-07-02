'use client';

import { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Label } from '../../ui/Label';
import { Textarea } from '../../ui/Textarea';
import { Alert } from '../../ui/Alert';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../ui/Select';
import { Edit, Trash2, Plus, Tag as TagIcon } from 'lucide-react';
import { createTag, updateTag, deleteTag } from '../../../../../lib/db/helper';
import { useDialog } from '../../providers/DialogProvider';
import { cn } from '../../../../../lib/utils';

interface Tag {
  id: string;
  project_id: string;
  name: string;
  color: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

interface TagManagerProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  tags: Tag[];
  onTagsChanged: () => void;
}

const TAG_COLORS = [
  { value: 'default', label: 'Default' },
  { value: 'primary', label: 'Primary' },
  { value: 'secondary', label: 'Secondary' },
  { value: 'error', label: 'Red' },
  { value: 'warning', label: 'Orange' },
  { value: 'info', label: 'Blue' },
  { value: 'success', label: 'Green' },
] as const;

const colorBadgeClasses: Record<string, string> = {
  default: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200',
  primary: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-200',
  secondary: 'bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200',
  error: 'bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200',
  warning: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
  info: 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200',
  success: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200',
};

function getColorClass(color: string): string {
  return colorBadgeClasses[color] ?? colorBadgeClasses.default;
}

const TagManager = ({ open, onClose, projectId, tags, onTagsChanged }: TagManagerProps) => {
  const { confirm: confirmDialog } = useDialog();

  const [editingTag, setEditingTag] = useState<Tag | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    color: 'default',
    description: '',
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  // Reset form when dialog closes
  useEffect(() => {
    if (!open) {
      setEditingTag(null);
      setIsCreating(false);
      setFormData({ name: '', color: 'default', description: '' });
      setError('');
    }
  }, [open]);

  const handleStartCreate = () => {
    setFormData({ name: '', color: 'default', description: '' });
    setEditingTag(null);
    setIsCreating(true);
    setError('');
  };

  const handleStartEdit = (tag: Tag) => {
    setFormData({
      name: tag.name,
      color: tag.color,
      description: tag.description || '',
    });
    setEditingTag(tag);
    setIsCreating(false);
    setError('');
  };

  const handleCancelEdit = () => {
    setEditingTag(null);
    setIsCreating(false);
    setFormData({ name: '', color: 'default', description: '' });
    setError('');
  };

  const handleSave = async () => {
    if (!formData.name.trim()) {
      setError('Tag name is required');
      return;
    }

    setSaving(true);
    setError('');

    try {
      let result;
      if (isCreating) {
        result = await createTag(
          projectId,
          formData.name,
          formData.color,
          formData.description || null
        );
      } else if (editingTag) {
        result = await updateTag(
          editingTag.id,
          formData.name,
          formData.color,
          formData.description || null
        );
      }

      if (!result) {
        setError('No response from server');
        setSaving(false);
        return;
      }

      const response = JSON.parse(result);
      if (!response.success) {
        setError(response.error || 'Failed to save tag');
        setSaving(false);
        return;
      }

      onTagsChanged();
      handleCancelEdit();
    } catch (err) {
      console.error('Error saving tag:', err);
      setError('An error occurred while saving the tag');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (tag: Tag) => {
    const confirmed = await confirmDialog({
      title: 'Delete Tag',
      message: `Are you sure you want to delete the tag "${tag.name}"? This will remove it from all classes.`,
      confirmLabel: 'Delete',
      variant: 'danger',
    });

    if (!confirmed) return;

    try {
      const result = await deleteTag(tag.id);

      if (!result) {
        setError('No response from server');
        return;
      }

      const response = JSON.parse(result);

      if (!response.success) {
        setError(response.error || 'Failed to delete tag');
        return;
      }

      onTagsChanged();
    } catch (err) {
      console.error('Error deleting tag:', err);
      setError('An error occurred while deleting the tag');
    }
  };

  const isEditing = isCreating || editingTag !== null;

  return (
    <Dialog
      open={open}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-md w-full" showCloseButton={true} aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <TagIcon size={20} />
            Manage Tags
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {error && (
            <Alert variant="error" onClose={() => setError('')}>
              {error}
            </Alert>
          )}

          {/* Edit/Create Form */}
          {isEditing && (
            <div className="mb-4 p-4 rounded-lg border border-gray-200 dark:border-gray-700 space-y-4">
              <div className="space-y-2">
                <Label htmlFor="tag-name">Tag Name</Label>
                <Input
                  id="tag-name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full"
                  autoFocus
                  placeholder="Tag name"
                />
              </div>

              <div className="space-y-2">
                <Label>Color</Label>
                <Select
                  value={formData.color}
                  onValueChange={(value) => setFormData({ ...formData, color: value })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Color" />
                  </SelectTrigger>
                  <SelectContent>
                    {TAG_COLORS.map((colorOption) => (
                      <SelectItem key={colorOption.value} value={colorOption.value}>
                        <span
                          className={cn(
                            'inline-flex px-2 py-0.5 rounded text-xs font-medium',
                            getColorClass(colorOption.value)
                          )}
                        >
                          {colorOption.label}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="tag-description">Description (optional)</Label>
                <Textarea
                  id="tag-description"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full min-h-[60px]"
                  placeholder="Optional description"
                  rows={2}
                />
              </div>

              <div className="flex gap-2 justify-end">
                <Button variant="outline" onClick={handleCancelEdit} disabled={saving}>
                  Cancel
                </Button>
                <Button onClick={handleSave} disabled={saving}>
                  {saving ? 'Saving...' : isCreating ? 'Create' : 'Update'}
                </Button>
              </div>
            </div>
          )}

          {/* Create Button */}
          {!isEditing && (
            <Button
              variant="outline"
              onClick={handleStartCreate}
              className="w-full mb-2"
            >
              <Plus size={16} className="mr-2" />
              Create New Tag
            </Button>
          )}

          {/* Tags List */}
          <div className="space-y-2">
            {tags.length === 0 ? (
              <p className="text-center py-8 text-sm text-gray-500 dark:text-gray-400">
                No tags yet. Create your first tag to organize classes.
              </p>
            ) : (
              <ul className="space-y-2">
                {tags.map((tag) => (
                  <li
                    key={tag.id}
                    className={cn(
                      'flex items-center justify-between gap-2 p-3 rounded-lg border',
                      'border-gray-200 dark:border-gray-700',
                      editingTag?.id === tag.id
                        ? 'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-200 dark:border-indigo-800'
                        : 'bg-white dark:bg-gray-800'
                    )}
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <span
                        className={cn(
                          'shrink-0 inline-flex px-2 py-0.5 rounded text-xs font-medium',
                          getColorClass(tag.color)
                        )}
                      >
                        {tag.name}
                      </span>
                      <span className="text-sm text-gray-500 dark:text-gray-400 truncate">
                        {tag.description || 'No description'}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => handleStartEdit(tag)}
                        title="Edit tag"
                      >
                        <Edit size={16} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20"
                        onClick={() => handleDelete(tag)}
                        title="Delete tag"
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default TagManager;
