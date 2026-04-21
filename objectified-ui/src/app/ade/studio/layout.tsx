'use client';

import "../../globals.css";
import * as React from 'react';
import { useState } from 'react';
import { useSession } from 'next-auth/react';
import { usePathname } from 'next/navigation';
import { StudioProvider, useStudio } from './StudioContext';
import { useDialog } from '../../components/providers/DialogProvider';
import StudioHeader from './components/StudioHeader';
import { GROUP_COLORS } from '@/app/components/ade/studio/GroupNode';
import { resolveGroupFrameHex } from '@/app/utils/group-frame-colors';

import StudioSideNav, { ClassItem, PropertyItem, StudioSideNavCallbacks } from '@/app/components/ade/studio/StudioSideNav';
import PropertyDialog from '@/app/components/ade/studio/PropertyDialog';
import ClassEditDialog from '@/app/components/ade/studio/ClassEditDialog';
import ClassImportDialog from '@/app/components/ade/studio/ClassImportDialog';
import PropertyTemplateBrowserDialog from '@/app/components/ade/studio/PropertyTemplateBrowserDialog';
import ClassTemplateBrowserDialog from '@/app/components/ade/studio/ClassTemplateBrowserDialog';
import TagManager from '@/app/components/ade/studio/TagManager';
import { getClassesForVersion, getTagsForProject } from '../../../../lib/db/helper';
import { deleteClassWithSession } from '../../../../lib/api/rest-client';
import * as Dialog from '@radix-ui/react-dialog';
import { ADE_SUBHEADER_RESERVE_PX } from '../constants/subheader-layout';
import { GitCommandPalette } from './components/GitCommandPalette';
import StudioFooterBar from './components/StudioFooterBar';

// Helper function to check permissions
const checkPermissions = async (condition: boolean, message: string, alertDialog: any) => {
  if (!condition) {
    await alertDialog({ message, variant: 'warning' });
    return false;
  }
  return true;
};

function StudioLayoutContent({ children }: Readonly<{ children: React.ReactNode }>) {
  const { data: session } = useSession();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const pathname = usePathname();
  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const currentUserId = (session?.user as any)?.user_id;
  const {
    selectedProjectId,
    selectedVersionId,
    triggerCanvasRefresh,
    triggerSidebarRefresh,
    sidebarRefreshKey,
    isReadOnly,
    zoomToClassFn,
    toggleClassVisibilityFn,
    hiddenClassIds,
    createGroupFn,
    clickToFocusEnabled,
    groups,
    deleteGroupFn,
    updateGroup,
    canvasPresentationMode,
    suppressGroupSidebarDestructive,
  } = useStudio();

  // Check if we're on the code or paths view - hide sidebar for these views
  const isCodeView = pathname?.includes('/code') || pathname?.includes('/paths');

  // View transition loading state
  const [isViewLoading, setIsViewLoading] = useState(false);
  const previousPathRef = React.useRef(pathname);

  // Detect view transitions and show loading, then clear after render
  React.useEffect(() => {
    if (pathname !== previousPathRef.current) {
      setIsViewLoading(true);
      previousPathRef.current = pathname;

      // Use double requestAnimationFrame to ensure children have rendered
      // First RAF waits for React to commit, second RAF waits for paint
      const frameId = requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setIsViewLoading(false);
        });
      });
      return () => cancelAnimationFrame(frameId);
    }
  }, [pathname]);

  // State
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [properties, setProperties] = useState<PropertyItem[]>([]);
  const [projectTags, setProjectTags] = useState<any[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isLoadingProperties, setIsLoadingProperties] = useState(false);

  // Dialog state
  const [classDialog, setClassDialog] = useState({ open: false, selectedClass: null as ClassItem | null });
  const [classImportDialog, setClassImportDialog] = useState({ open: false });
  const [propertyDialog, setPropertyDialog] = useState({ open: false, mode: 'add' as 'add' | 'edit', selectedProperty: null as PropertyItem | null });
  const [propertyTemplateDialog, setPropertyTemplateDialog] = useState({ open: false });
  const [classTemplateDialog, setClassTemplateDialog] = useState({ open: false });
  const [deleteDialog, setDeleteDialog] = useState({ open: false, target: null as { type: 'class' | 'property'; id: string } | null });
  const [tagManagerOpen, setTagManagerOpen] = useState(false);


  // Load project tags
  React.useEffect(() => {
    const loadProjectTags = async () => {
      if (!selectedProjectId) {
        setProjectTags([]);
        return;
      }
      try {
        const result = await getTagsForProject(selectedProjectId);
        const tags = JSON.parse(result);
        setProjectTags(tags);
      } catch (error) {
        console.error('Failed to load project tags:', error);
        setProjectTags([]);
      }
    };
    loadProjectTags();
  }, [selectedProjectId]);

  // Load data effects
  React.useEffect(() => {
    const loadProperties = async () => {
      if (!selectedProjectId) {
        setProperties([]);
        return;
      }
      setIsLoadingProperties(true);
      try {
        const response = await fetch(`/api/properties/${selectedProjectId}`);
        const result = await response.json();
        if (!result.success) {
          throw new Error(result.error || 'Failed to load properties');
        }
        const data = result.properties || [];
        const transformedProperties: PropertyItem[] = data.map((prop: any) => ({
          id: prop.id, name: prop.name, description: prop.description, ...prop.data
        }));
        setProperties(transformedProperties);
      } catch (error) {
        console.error('Error loading properties:', error);
        setProperties([]);
      } finally {
        setIsLoadingProperties(false);
      }
    };
    loadProperties();
  }, [selectedProjectId, refreshKey]);

  React.useEffect(() => {
    const loadClasses = async () => {
      if (!selectedVersionId) {
        setClasses([]);
        return;
      }
      try {
        const result = await getClassesForVersion(selectedVersionId);
        const data = JSON.parse(result);
        const transformedClasses: ClassItem[] = data.map((cls: any) => ({
          id: cls.id, name: cls.name, description: cls.description, schema: cls.schema
        }));
        setClasses(transformedClasses);
      } catch (error) {
        console.error('Error loading classes:', error);
        setClasses([]);
      }
    };
    loadClasses();
  }, [selectedVersionId, refreshKey, sidebarRefreshKey]);

  // Map of lowercase class name -> schema for duplicate definition detection (#582)
  const existingClassSchemasByLowerName = React.useMemo(() => {
    const map: Record<string, any> = {};
    for (const c of classes) {
      if (!c.name || c.schema == null) continue;
      const schema = typeof c.schema === 'string' ? (() => { try { return JSON.parse(c.schema); } catch { return null; } })() : c.schema;
      if (schema && typeof schema === 'object') map[c.name.toLowerCase()] = schema;
    }
    return map;
  }, [classes]);

  // Expose handleClassEdit via ref for canvas to trigger
  const handleClassEditRef = React.useRef<((classItem: ClassItem) => Promise<void>) | null>(null);
  React.useEffect(() => {
    (window as any).__studioHandleClassEdit = handleClassEditRef.current;
  }, []);

  // Permission check helpers
  const checkVersionSelected = () => checkPermissions(!!selectedVersionId, 'Please select a version from the canvas first', alertDialog);
  const checkProjectSelected = () => checkPermissions(!!selectedProjectId, 'Please select a project from the canvas first', alertDialog);
  const checkNotReadOnly = (action: string) => checkPermissions(!isReadOnly, `Cannot ${action} in a published version. Please select an unpublished version to make changes.`, alertDialog);

  // Class handlers
  const handleClassAdd = async () => {
    if (!(await checkVersionSelected()) || !(await checkNotReadOnly('add classes'))) return;
    setClassDialog({ open: true, selectedClass: null });
  };

  const handleClassEdit = async (classItem: ClassItem) => {
    if (!(await checkVersionSelected()) || !(await checkNotReadOnly('edit classes'))) return;
    setClassDialog({ open: true, selectedClass: classItem });
  };

  // Keep ref updated
  React.useEffect(() => {
    handleClassEditRef.current = handleClassEdit;
    (window as any).__studioHandleClassEdit = handleClassEdit;
  }, [handleClassEdit]);

  const handleClassDelete = async (classId: string) => {
    if (!(await checkVersionSelected()) || !(await checkNotReadOnly('delete classes'))) return;
    setDeleteDialog({ open: true, target: { type: 'class', id: classId } });
  };

  const handleClassImport = async () => {
    if (!(await checkVersionSelected()) || !(await checkNotReadOnly('import classes'))) return;
    setClassImportDialog({ open: true });
  };

  const handleClassTemplates = async () => {
    if (!(await checkVersionSelected()) || !(await checkNotReadOnly('add classes'))) return;
    setClassTemplateDialog({ open: true });
  };

  // Property handlers
  const handlePropertyAdd = async () => {
    if (!(await checkProjectSelected()) || !(await checkNotReadOnly('add properties'))) return;
    setPropertyDialog({ open: true, mode: 'add', selectedProperty: null });
  };

  const handlePropertyTemplates = async () => {
    if (!(await checkProjectSelected()) || !(await checkNotReadOnly('add properties'))) return;
    setPropertyTemplateDialog({ open: true });
  };

  const handlePropertyEdit = async (propertyItem: PropertyItem) => {
    if (!(await checkProjectSelected()) || !(await checkNotReadOnly('edit properties'))) return;
    setPropertyDialog({ open: true, mode: 'edit', selectedProperty: propertyItem });
  };

  const handlePropertyDelete = async (propertyId: string) => {
    if (!(await checkProjectSelected()) || !(await checkNotReadOnly('delete properties'))) return;
    setDeleteDialog({ open: true, target: { type: 'property', id: propertyId } });
  };

  const handlePropertySubmit = async (propertyData: { name: string; description: string | null; data: any }) => {
    if (!selectedProjectId) throw new Error('No project selected');

    try {
      let response;
      if (propertyDialog.mode === 'add') {
        response = await fetch(`/api/properties/${selectedProjectId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: propertyData.name,
            description: propertyData.description,
            data: propertyData.data,
          }),
        });
      } else if (propertyDialog.selectedProperty) {
        response = await fetch(`/api/properties/${selectedProjectId}/${propertyDialog.selectedProperty.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: propertyData.name,
            description: propertyData.description,
            data: propertyData.data,
          }),
        });
      } else {
        throw new Error('No property selected for update');
      }

      const result = await response.json();
      if (!result.success) {
        throw new Error(result.error || 'Failed to save property');
      }

      setPropertyDialog({ open: false, mode: 'add', selectedProperty: null });
      setRefreshKey(prev => prev + 1);
    } catch (error) {
      console.error('Error saving property:', error);
      throw error;
    }
  };

  // Delete handler
  const handleDeleteConfirm = async () => {
    if (!deleteDialog.target) return;

    try {
      let response;
      if (deleteDialog.target.type === 'class') {
        response = await deleteClassWithSession(deleteDialog.target.id);
      } else {
        // Delete property via REST API
        const apiResponse = await fetch(`/api/properties/${selectedProjectId}/${deleteDialog.target.id}`, {
          method: 'DELETE',
        });
        response = await apiResponse.json();
      }

      if (!response.success) {
        await alertDialog({ message: response.error || `Failed to delete ${deleteDialog.target.type}`, variant: 'error' });
        return;
      }

      setDeleteDialog({ open: false, target: null });
      setRefreshKey(prev => prev + 1);
      if (deleteDialog.target.type === 'class') {
        triggerCanvasRefresh();
      }
    } catch (error) {
      console.error('Error deleting:', error);
      await alertDialog({ message: 'An error occurred while deleting', variant: 'error' });
    }
  };

  const callbacks: StudioSideNavCallbacks = {
    onClassAdd: handleClassAdd, onClassEdit: handleClassEdit, onClassDelete: handleClassDelete, onClassImport: handleClassImport, onClassTemplates: handleClassTemplates,
    onClassSelect: (classItem) => {
      console.log('Class selected:', classItem);
      // Only zoom if click-to-focus mode is enabled
      if (clickToFocusEnabled && zoomToClassFn) {
        zoomToClassFn(classItem.id);
      }
    },
    onClassVisibilityToggle: (classId, visible) => {
      toggleClassVisibilityFn?.(classId, visible);
      triggerCanvasRefresh();
    },
    onPropertyAdd: handlePropertyAdd, onPropertyEdit: handlePropertyEdit, onPropertyDelete: handlePropertyDelete, onPropertyTemplates: handlePropertyTemplates,
    onPropertySelect: (propertyItem) => console.log('Property selected:', propertyItem),
    onGroupAdd: () => {
      if (createGroupFn) {
        createGroupFn();
      }
    },
    onGroupSelect: (groupId) => {
      // Zoom to the group node on the canvas
      if (zoomToClassFn) {
        zoomToClassFn(groupId);
      }
    },
    onGroupDelete: async (groupId) => {
      if (isReadOnly) {
        await alertDialog({ message: 'Cannot delete groups in a published version.', variant: 'warning' });
        return;
      }

      if (deleteGroupFn) {
        await deleteGroupFn(groupId);
        return;
      }

      await alertDialog({
        message: 'Canvas editor is still loading. Please try again in a moment.',
        variant: 'warning',
      });
    },
    onGroupDeleteAllClasses: async (groupId) => {
      if (isReadOnly) return;
      const group = groups.find(g => g.id === groupId);
      const classIds = group?.nodeIds ?? [];
      if (classIds.length === 0) return;

      const resolvedName = group?.name?.trim();
      if (!resolvedName) return;

      const confirmed = await confirmDialog({
        title: 'Delete All Classes in Group',
        message: `Are you sure you want to delete all ${classIds.length} class${classIds.length === 1 ? '' : 'es'} in "${resolvedName}"? This action cannot be undone.`,
        variant: 'danger',
        confirmLabel: 'Delete All',
        cancelLabel: 'Cancel',
      });
      if (!confirmed) return;

      const errors: string[] = [];
      for (const classId of classIds) {
        const response = await deleteClassWithSession(classId);
        if (!response.success) {
          errors.push(response.error || classId);
        }
      }
      if (errors.length > 0) {
        await alertDialog({
          message: `Failed to delete ${errors.length} class${errors.length === 1 ? '' : 'es'}: ${errors.slice(0, 3).join(', ')}${errors.length > 3 ? '...' : ''}`,
          variant: 'error',
        });
      }

      updateGroup(groupId, { nodeIds: [] });
      setRefreshKey(prev => prev + 1);
      triggerSidebarRefresh();
      triggerCanvasRefresh();
    },
  };

  // Transform groups for sidebar display
  const sidebarGroups = React.useMemo(() => {
    return groups.map(group => {
      const { hex: colorHex } = resolveGroupFrameHex(group.color, GROUP_COLORS);
      return {
        id: group.id,
        name: group.name,
        color: colorHex,
        nodeIds: group.nodeIds,
      };
    });
  }, [groups, sidebarRefreshKey]);

  // Convert classes to nodes format expected by ClassEditDialog
  const classNodes = React.useMemo(() => {
    return classes.map(cls => ({
      id: cls.id,
      type: 'classNode',
      position: { x: 0, y: 0 },
      data: {
        id: cls.id,
        name: cls.name,
        description: cls.description,
        schema: cls.schema
      }
    }));
  }, [classes]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 48px)" }}>
      {/* Static Header with Project/Version selectors — hidden during canvas presentation (#517) */}
      {!canvasPresentationMode && (
        <StudioHeader
          onProjectTagsLoaded={(tags) => setProjectTags(tags)}
        />
      )}

      {/* Sidebar and main content area - with padding for fixed header.
          The footer renders as a sibling in this flex column, so flex:1 here
          naturally yields its height without explicit subtraction. */}
      <div
        style={{
          display: "flex",
          flex: 1,
          overflow: "hidden",
          minHeight: 0,
          marginTop: canvasPresentationMode ? 0 : `${ADE_SUBHEADER_RESERVE_PX}px`,
        }}
      >
        {/* Only show sidebar for canvas/editor view, not for code view */}
        {!canvasPresentationMode &&
          !isCodeView &&
          currentTenantId &&
          selectedProjectId &&
          selectedVersionId && (
          <StudioSideNav classes={classes} properties={properties} groups={sidebarGroups} callbacks={callbacks} refreshKey={refreshKey}
                         hiddenClassIds={hiddenClassIds}
                         selectedProjectId={selectedProjectId} selectedVersionId={selectedVersionId} isReadOnly={isReadOnly}
                         suppressGroupDestructiveActions={suppressGroupSidebarDestructive} />
        )}

        <main style={{ flex: 1, overflow: "hidden", position: "relative", zIndex: 100, display: "flex", flexDirection: "column" }}>
          {/* View transition loading indicator */}
          {isViewLoading && (
            <div className="absolute inset-0 z-50 flex items-center justify-center bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm">
              <div className="text-center">
                <div className="w-10 h-10 border-3 border-indigo-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
                <p className="text-sm font-medium text-gray-600 dark:text-gray-300">Please wait, loading...</p>
              </div>
            </div>
          )}
          {children}
        </main>
      </div>

      {/* Class Dialog */}
      <ClassEditDialog
        open={classDialog.open}
        onClose={() => {
          setClassDialog({ open: false, selectedClass: null });
        }}
        editingClassData={classDialog.selectedClass}
        nodes={classNodes}
        isReadOnly={isReadOnly}
        onSave={() => {
          setRefreshKey(prev => prev + 1);
          triggerCanvasRefresh();
        }}
        projectId={selectedProjectId || ''}
        versionId={selectedVersionId || ''}
        projectTags={projectTags}
      />

      {/* Class Import Dialog */}
      <ClassImportDialog
        open={classImportDialog.open}
        onClose={() => setClassImportDialog({ open: false })}
        onSuccess={() => {
          setRefreshKey(prev => prev + 1);
          triggerCanvasRefresh();
        }}
        versionId={selectedVersionId || ''}
        projectId={selectedProjectId || ''}
        existingClassNames={classes.map(c => c.name)}
        existingClassSchemas={existingClassSchemasByLowerName}
        userId={currentUserId || ''}
      />

      {/* Property Dialog */}
      <PropertyDialog
        open={propertyDialog.open}
        onClose={() => setPropertyDialog({ open: false, mode: 'add', selectedProperty: null })}
        mode={propertyDialog.mode}
        property={propertyDialog.selectedProperty}
        onSubmit={handlePropertySubmit}
        availableClasses={classes.map(c => c.name)}
      />

      {/* Property Template Browser Dialog */}
      <PropertyTemplateBrowserDialog
        open={propertyTemplateDialog.open}
        onClose={() => setPropertyTemplateDialog({ open: false })}
        onSuccess={() => {
          setRefreshKey(prev => prev + 1);
        }}
        projectId={selectedProjectId || ''}
        tenantId={currentTenantId}
      />

      {/* Class Template Browser Dialog */}
      <ClassTemplateBrowserDialog
        open={classTemplateDialog.open}
        onClose={() => setClassTemplateDialog({ open: false })}
        onSuccess={() => {
          setRefreshKey(prev => prev + 1);
          triggerCanvasRefresh?.();
        }}
        versionId={selectedVersionId || ''}
        projectId={selectedProjectId || ''}
        tenantId={currentTenantId}
      />

      {/* Delete Confirmation Dialog */}
      <Dialog.Root open={deleteDialog.open} onOpenChange={(open) => !open && setDeleteDialog({ open: false, target: null })}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[10001]" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[10002] w-full max-w-sm bg-white dark:bg-gray-900 rounded-xl shadow-xl p-6"
          >
            <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-gray-100">Confirm Delete</Dialog.Title>
            <p className="mt-2 text-gray-700 dark:text-gray-300">
              Are you sure you want to delete this {deleteDialog.target?.type}? This action cannot be undone.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteDialog({ open: false, target: null })}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteConfirm}
                className="px-4 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {/* Tag Manager Dialog */}
      <TagManager
        open={tagManagerOpen}
        onClose={() => setTagManagerOpen(false)}
        projectId={selectedProjectId || ''}
        tags={projectTags}
        onTagsChanged={() => {
          // Reload tags
          if (selectedProjectId) {
            getTagsForProject(selectedProjectId).then(result => {
              setProjectTags(JSON.parse(result));
            }).catch(console.error);
          }
        }}
      />

      <GitCommandPalette />

      {/* Programmatic state of the canvas — pinned to the bottom of the studio layout.
          Hidden in presentation mode for chrome consistency with StudioHeader. */}
      {!canvasPresentationMode && <StudioFooterBar />}
    </div>
  );
}

export default function StudioLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <StudioProvider>
      <StudioLayoutContent>{children}</StudioLayoutContent>
    </StudioProvider>
  );
}
