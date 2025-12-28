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

import StudioSideNav, { ClassItem, PropertyItem, StudioSideNavCallbacks } from '@/app/components/ade/studio/StudioSideNav';
import PropertyDialog from '@/app/components/ade/studio/PropertyDialog';
import ClassEditDialog from '@/app/components/ade/studio/ClassEditDialog';
import ClassImportDialog from '@/app/components/ade/studio/ClassImportDialog';
import PropertyTemplateBrowserDialog from '@/app/components/ade/studio/PropertyTemplateBrowserDialog';
import TagManager from '@/app/components/ade/studio/TagManager';
import { getPropertiesForProject, createProperty, updateProperty, deleteProperty, getClassesForVersion, deleteClass, getTagsForProject } from '../../../../lib/db/helper';
import { Dialog, DialogTitle, DialogContent, DialogActions, DialogContentText, Button } from '@mui/material';

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
  const { selectedProjectId, selectedVersionId, triggerCanvasRefresh, sidebarRefreshKey, isReadOnly, zoomToClassFn, createGroupFn, clickToFocusEnabled, groups, deleteGroup } = useStudio();

  // Check if we're on the code view - hide sidebar for code view
  const isCodeView = pathname?.includes('/code');

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
        const result = await getPropertiesForProject(selectedProjectId);
        const data = JSON.parse(result);
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

    let result;
    if (propertyDialog.mode === 'add') {
      result = await createProperty(selectedProjectId, propertyData.name, propertyData.description, propertyData.data);
    } else if (propertyDialog.selectedProperty) {
      result = await updateProperty(propertyDialog.selectedProperty.id, propertyData.name, propertyData.description, propertyData.data);
    }

    const response = JSON.parse(result!);
    if (!response.success) throw new Error(response.error || 'Failed to save property');

    setPropertyDialog({ open: false, mode: 'add', selectedProperty: null });
    setRefreshKey(prev => prev + 1);
  };

  // Delete handler
  const handleDeleteConfirm = async () => {
    if (!deleteDialog.target) return;

    try {
      const result = deleteDialog.target.type === 'class'
        ? await deleteClass(deleteDialog.target.id)
        : await deleteProperty(deleteDialog.target.id);

      const response = JSON.parse(result);
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
    onClassAdd: handleClassAdd, onClassEdit: handleClassEdit, onClassDelete: handleClassDelete, onClassImport: handleClassImport,
    onClassSelect: (classItem) => {
      console.log('Class selected:', classItem);
      // Only zoom if click-to-focus mode is enabled
      if (clickToFocusEnabled && zoomToClassFn) {
        zoomToClassFn(classItem.id);
      }
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

      const group = groups.find(g => g.id === groupId);
      const confirmed = await confirmDialog({
        title: 'Delete Group',
        message: `Are you sure you want to delete the group "${group?.name || 'this group'}"? The classes inside will not be deleted.`,
        variant: 'warning',
        confirmLabel: 'Delete Group',
        cancelLabel: 'Cancel',
      });

      if (!confirmed) return;

      deleteGroup(groupId);
      triggerCanvasRefresh();
    },
  };

  // Transform groups for sidebar display
  const sidebarGroups = React.useMemo(() => {
    return groups.map(group => {
      const colorConfig = GROUP_COLORS.find(c => c.name === group.color) || GROUP_COLORS[0];
      return {
        id: group.id,
        name: group.name,
        color: colorConfig.hex,
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
      {/* Static Header with Project/Version selectors */}
      <StudioHeader
        onProjectTagsLoaded={(tags) => setProjectTags(tags)}
      />

      {/* Sidebar and main content area - with padding for fixed header */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden", marginTop: "48px" }}>
        {/* Only show sidebar for canvas/editor view, not for code view */}
        {!isCodeView && currentTenantId && selectedProjectId && selectedVersionId && (
          <StudioSideNav classes={classes} properties={properties} groups={sidebarGroups} callbacks={callbacks} refreshKey={refreshKey}
                         selectedProjectId={selectedProjectId} selectedVersionId={selectedVersionId} isReadOnly={isReadOnly} />
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

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialog.open} onClose={() => setDeleteDialog({ open: false, target: null })}>
        <DialogTitle>Confirm Delete</DialogTitle>
        <DialogContent>
          <DialogContentText>Are you sure you want to delete this {deleteDialog.target?.type}? This action cannot be undone.</DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialog({ open: false, target: null })}>Cancel</Button>
          <Button onClick={handleDeleteConfirm} color="error" variant="contained">Delete</Button>
        </DialogActions>
      </Dialog>

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
