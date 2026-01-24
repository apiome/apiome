'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import {
  Database,
  Plus,
  Edit,
  Trash2,
  Search,
  FileCode,
  Tag,
  AlertCircle,
  CheckCircle,
  Upload,
  Shield,
  RefreshCw,
} from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Alert } from '@/app/components/ui/Alert';
import { useDialog } from '@/app/components/providers/DialogProvider';
import PrimitiveEditorDialog from './PrimitiveEditorDialog';
import PrimitiveImportDialog from './PrimitiveImportDialog';

interface Primitive {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  category: string;
  schema: Record<string, unknown>;
  tags: string[];
  created_by: string | null;
  is_system: boolean;
  is_public: boolean;
  usage_count: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export default function PrimitivesManagementClient() {
  const { data: session } = useSession();
  const { confirm } = useDialog();

  const [primitives, setPrimitives] = useState<Primitive[]>([]);
  const [filteredPrimitives, setFilteredPrimitives] = useState<Primitive[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [showSystemPrimitives, setShowSystemPrimitives] = useState(true);

  // Dialogs
  const [showEditorDialog, setShowEditorDialog] = useState(false);
  const [showImportDialog, setShowImportDialog] = useState(false);
  const [editingPrimitive, setEditingPrimitive] = useState<Primitive | null>(null);

  const currentTenantId = (session?.user as { current_tenant_id?: string })?.current_tenant_id;

  const loadPrimitives = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/primitives');

      // Check if response is ok before parsing
      if (!response.ok) {
        const text = await response.text();
        console.error('API error:', response.status, text);
        showMessage('error', `Failed to load primitives: ${text || response.statusText}`);
        return;
      }

      const data = await response.json();

      if (data.success) {
        setPrimitives(data.primitives || []);
      } else {
        showMessage('error', data.error || 'Failed to load primitives');
      }
    } catch (error) {
      console.error('Error loading primitives:', error);
      const errorMessage = error instanceof Error ? error.message : 'Failed to load primitives';
      showMessage('error', errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  const filterPrimitives = useCallback(() => {
    let filtered = [...primitives];

    // Filter by system/tenant
    if (!showSystemPrimitives) {
      filtered = filtered.filter(p => !p.is_system);
    }

    // Filter by category
    if (selectedCategory !== 'all') {
      filtered = filtered.filter(p => p.category === selectedCategory);
    }

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(p =>
        p.name.toLowerCase().includes(query) ||
        p.description?.toLowerCase().includes(query) ||
        p.tags.some(tag => tag.toLowerCase().includes(query))
      );
    }

    setFilteredPrimitives(filtered);
  }, [primitives, searchQuery, selectedCategory, showSystemPrimitives]);

  useEffect(() => {
    if (currentTenantId) {
      loadPrimitives();
    }
  }, [currentTenantId, loadPrimitives]);

  useEffect(() => {
    filterPrimitives();
  }, [filterPrimitives]);

  const showMessage = (type: 'success' | 'error', text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 5000);
  };

  const handleCreatePrimitive = () => {
    setEditingPrimitive(null);
    setShowEditorDialog(true);
  };

  const handleEditPrimitive = (primitive: Primitive) => {
    if (primitive.is_system) {
      showMessage('error', 'System primitives cannot be edited');
      return;
    }
    setEditingPrimitive(primitive);
    setShowEditorDialog(true);
  };

  const handleDeletePrimitive = async (primitive: Primitive) => {
    if (primitive.is_system) {
      showMessage('error', 'System primitives cannot be deleted');
      return;
    }

    const confirmed = await confirm({
      title: 'Delete Primitive',
      message: `Are you sure you want to delete the primitive "${primitive.name}"?${primitive.usage_count > 0 ? ` This primitive is currently used in ${primitive.usage_count} place${primitive.usage_count !== 1 ? 's' : ''}.` : ''}`,
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
      variant: 'danger',
    });

    if (!confirmed) return;

    try {
      const response = await fetch(`/api/primitives/${primitive.id}`, {
        method: 'DELETE',
      });

      const data = await response.json();

      if (data.success) {
        showMessage('success', 'Primitive deleted successfully');
        await loadPrimitives();
      } else {
        showMessage('error', data.error || 'Failed to delete primitive');
      }
    } catch (error) {
      console.error('Error deleting primitive:', error);
      showMessage('error', 'Failed to delete primitive');
    }
  };

  const handleSavePrimitive = async () => {
    await loadPrimitives();
    setShowEditorDialog(false);
  };

  const handleImportComplete = async () => {
    await loadPrimitives();
    setShowImportDialog(false);
  };

  const categories = Array.from(new Set(primitives.map(p => p.category))).sort();
  const stats = {
    total: primitives.length,
    system: primitives.filter(p => p.is_system).length,
    tenant: primitives.filter(p => !p.is_system).length,
    categories: categories.length,
  };

  if (!currentTenantId) {
    return (
      <div className="flex items-center justify-center h-full">
        <Alert variant="warning">
          <AlertCircle className="h-4 w-4" />
          <span>Please select a tenant to manage primitives</span>
        </Alert>
      </div>
    );
  }

  return (
    <>
      {/* Header */}
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <Database className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
                Primitives
              </h2>
              <p className="text-gray-600 dark:text-gray-400 text-sm mt-1">
                Manage your tenant&apos;s reusable JSON Schema primitive definitions
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Button
                onClick={() => setShowImportDialog(true)}
                variant="secondary"
              >
                <Upload className="w-4 h-4 mr-2" />
                Import from Schema
              </Button>
              <Button onClick={handleCreatePrimitive}>
                <Plus className="w-4 h-4 mr-2" />
                Create Primitive
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto p-6">
        <div className="space-y-6">
          {/* Message Banner */}
          {message && (
            <Alert variant={message.type === 'success' ? 'default' : 'error'}>
              {message.type === 'success' ? (
                <CheckCircle className="h-4 w-4" />
              ) : (
                <AlertCircle className="h-4 w-4" />
              )}
              <span>{message.text}</span>
            </Alert>
          )}

          {/* Statistics */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400">Total Primitives</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white mt-1">{stats.total}</p>
                </div>
                <Database className="w-8 h-8 text-indigo-600 dark:text-indigo-400 opacity-50" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400">System</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white mt-1">{stats.system}</p>
                </div>
                <Shield className="w-8 h-8 text-blue-600 dark:text-blue-400 opacity-50" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400">Tenant</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white mt-1">{stats.tenant}</p>
                </div>
                <FileCode className="w-8 h-8 text-green-600 dark:text-green-400 opacity-50" />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400">Categories</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white mt-1">{stats.categories}</p>
                </div>
                <Tag className="w-8 h-8 text-purple-600 dark:text-purple-400 opacity-50" />
              </div>
            </div>
          </div>

          {/* Filters */}
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex flex-col md:flex-row gap-4">
              <div className="flex-1">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <Input
                    type="text"
                    placeholder="Search primitives..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-10"
                  />
                </div>
              </div>

              <div className="flex items-center gap-4">
                <select
                  value={selectedCategory}
                  onChange={(e) => setSelectedCategory(e.target.value)}
                  className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                >
                  <option value="all">All Categories</option>
                  {categories.map(cat => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>

                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={showSystemPrimitives}
                    onChange={(e) => setShowSystemPrimitives(e.target.checked)}
                    className="w-4 h-4 text-indigo-600 rounded"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">Show System</span>
                </label>

                <Button
                  variant="secondary"
                  size="sm"
                  onClick={loadPrimitives}
                  disabled={loading}
                >
                  <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                </Button>
              </div>
            </div>
          </div>

          {/* Primitives Table */}
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <RefreshCw className="w-6 h-6 animate-spin text-indigo-600" />
              </div>
            ) : filteredPrimitives.length === 0 ? (
              <div className="text-center py-12">
                <Database className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                <p className="text-gray-600 dark:text-gray-400">No primitives found</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Name
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Category
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Description
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Tags
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Usage
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Type
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {filteredPrimitives.map((primitive) => (
                      <tr
                        key={primitive.id}
                        className="hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors"
                      >
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center">
                            <FileCode className="w-4 h-4 text-indigo-600 dark:text-indigo-400 mr-2" />
                            <span className="text-sm font-medium text-gray-900 dark:text-white">
                              {primitive.name}
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300">
                            {primitive.category}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          <div className="text-sm text-gray-600 dark:text-gray-400 max-w-xs truncate">
                            {primitive.description || '—'}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex flex-wrap gap-1">
                            {primitive.tags.slice(0, 3).map((tag, idx) => (
                              <span
                                key={idx}
                                className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300"
                              >
                                {tag}
                              </span>
                            ))}
                            {primitive.tags.length > 3 && (
                              <span className="text-xs text-gray-500">+{primitive.tags.length - 3}</span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600 dark:text-gray-400">
                          {primitive.usage_count}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {primitive.is_system ? (
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                              <Shield className="w-3 h-3 mr-1" />
                              System
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
                              Tenant
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              onClick={() => handleEditPrimitive(primitive)}
                              disabled={primitive.is_system}
                              className="text-indigo-600 hover:text-indigo-900 dark:text-indigo-400 dark:hover:text-indigo-300 disabled:opacity-50 disabled:cursor-not-allowed"
                              title={primitive.is_system ? 'System primitives cannot be edited' : 'Edit primitive'}
                            >
                              <Edit className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDeletePrimitive(primitive)}
                              disabled={primitive.is_system}
                              className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300 disabled:opacity-50 disabled:cursor-not-allowed"
                              title={primitive.is_system ? 'System primitives cannot be deleted' : 'Delete primitive'}
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Dialogs */}
      {showEditorDialog && (
        <PrimitiveEditorDialog
          primitive={editingPrimitive}
          onClose={() => setShowEditorDialog(false)}
          onSave={handleSavePrimitive}
          onMessage={showMessage}
        />
      )}

      {showImportDialog && (
        <PrimitiveImportDialog
          onClose={() => setShowImportDialog(false)}
          onComplete={handleImportComplete}
          onMessage={showMessage}
        />
      )}
    </>
  );
}
