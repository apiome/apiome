// SideNav.tsx
'use client';

import React, { useState } from 'react';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import Typography from '@mui/material/Typography';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import TextField from '@mui/material/TextField';
import InputAdornment from '@mui/material/InputAdornment';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import Fab from '@mui/material/Fab';
import { Search, Add, Edit, Delete } from '@mui/icons-material';

export interface ClassItem {
  id: string;
  name: string;
  description?: string;
  schema?: any; // JSON Schema object stored in database
}

export interface PropertyItem {
  id: string;
  name: string;
  type?: string;
  $ref?: string; // Reference to another class schema
  title?: string;
  description?: string;
  format?: string;
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: boolean;
  exclusiveMaximum?: boolean;
  multipleOf?: number;
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;
  enum?: string[];
  default?: any;
  required?: boolean;
}

export interface StudioSideNavCallbacks {
  // Classes callbacks
  onClassAdd?: () => void;
  onClassEdit?: (classItem: ClassItem) => void;
  onClassDelete?: (classId: string) => void;
  onClassSelect?: (classItem: ClassItem) => void;

  // Properties callbacks
  onPropertyAdd?: () => void;
  onPropertyEdit?: (propertyItem: PropertyItem) => void;
  onPropertyDelete?: (propertyId: string) => void;
  onPropertySelect?: (propertyItem: PropertyItem) => void;
}

interface StudioSideNavProps {
  classes?: ClassItem[];
  properties?: PropertyItem[];
  callbacks?: StudioSideNavCallbacks;
  refreshKey?: number; // Used to trigger refresh from parent
  selectedProjectId?: string | null; // Currently selected project from canvas
  selectedVersionId?: string | null; // Currently selected version from canvas
  isReadOnly?: boolean; // Whether the current version is published (read-only)
}

const StudioSideNav: React.FC<StudioSideNavProps> = ({
  classes = [],
  properties = [],
  callbacks = {},
  refreshKey = 0,
  selectedProjectId = null,
  selectedVersionId = null,
  isReadOnly = false,
}) => {
  const [currentTab, setCurrentTab] = useState<'classes' | 'properties'>('classes');
  const [classesSearchQuery, setClassesSearchQuery] = useState('');
  const [propertiesSearchQuery, setPropertiesSearchQuery] = useState('');
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null);
  const [selectedPropertyId, setSelectedPropertyId] = useState<string | null>(null);

  const handleTabChange = (event: React.SyntheticEvent, newValue: 'classes' | 'properties') => {
    setCurrentTab(newValue);
  };

  // Filter classes based on search query
  const filteredClasses = classes.filter(cls =>
    cls.name.toLowerCase().includes(classesSearchQuery.toLowerCase()) ||
    (cls.description?.toLowerCase().includes(classesSearchQuery.toLowerCase()) ?? false)
  );

  // Filter properties based on search query
  const filteredProperties = properties.filter(prop =>
    prop.name.toLowerCase().includes(propertiesSearchQuery.toLowerCase()) ||
    (prop.type?.toLowerCase().includes(propertiesSearchQuery.toLowerCase()) ?? false) ||
    (prop.description?.toLowerCase().includes(propertiesSearchQuery.toLowerCase()) ?? false)
  );

  const handleClassSelect = (classItem: ClassItem) => {
    setSelectedClassId(classItem.id);
    callbacks.onClassSelect?.(classItem);
  };

  const handlePropertySelect = (propertyItem: PropertyItem) => {
    setSelectedPropertyId(propertyItem.id);
    callbacks.onPropertySelect?.(propertyItem);
  };

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: 256,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: 256,
          boxSizing: 'border-box',
          top: 48, // Offset for top header
          height: 'calc(100vh - 48px)',
          borderRight: 1,
          borderColor: 'divider',
        },
      }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Version/Project Status Indicator */}
        {((currentTab === 'classes' && !selectedVersionId) || (currentTab === 'properties' && !selectedProjectId)) && (
          <Box
            sx={{
              p: 1.5,
              bgcolor: 'warning.light',
              color: 'warning.contrastText',
              textAlign: 'center',
              fontSize: '0.75rem',
              fontWeight: 500,
              borderBottom: 1,
              borderColor: 'divider'
            }}
          >
            {currentTab === 'classes'
              ? '⚠️ Select a version from the canvas to manage classes'
              : '⚠️ Select a project from the canvas to manage properties'}
          </Box>
        )}

        {/* Tabs Navigation */}
        <Tabs
          value={currentTab}
          onChange={handleTabChange}
          variant="fullWidth"
          sx={{
            borderBottom: 1,
            borderColor: 'divider',
            minHeight: 48,
          }}
        >
          <Tab
            label="Classes"
            value="classes"
            sx={{
              minHeight: 48,
              textTransform: 'none',
              fontWeight: currentTab === 'classes' ? 600 : 400,
            }}
          />
          <Tab
            label="Properties"
            value="properties"
            sx={{
              minHeight: 48,
              textTransform: 'none',
              fontWeight: currentTab === 'properties' ? 600 : 400,
            }}
          />
        </Tabs>

        {/* Tab Content */}
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {currentTab === 'classes' ? (
            // Classes View
            <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Search Bar */}
              <Box sx={{ p: 2, pb: 1 }}>
                <TextField
                  fullWidth
                  size="small"
                  placeholder="Search classes..."
                  value={classesSearchQuery}
                  onChange={(e) => setClassesSearchQuery(e.target.value)}
                  slotProps={{
                    input: {
                      startAdornment: (
                        <InputAdornment position="start">
                          <Search fontSize="small" />
                        </InputAdornment>
                      ),
                    },
                  }}
                />
              </Box>

              {/* Classes List */}
              <Box sx={{ flex: 1, overflow: 'auto' }}>
                {filteredClasses.length === 0 ? (
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ textAlign: 'center', mt: 4, px: 2 }}
                  >
                    {classes.length === 0
                      ? 'No classes yet. Click + to add one.'
                      : 'No classes match your search.'}
                  </Typography>
                ) : (
                  <List dense>
                    {filteredClasses.map((classItem) => (
                      <ListItem
                        key={classItem.id}
                        disablePadding
                        secondaryAction={
                          <Box>
                            <IconButton
                              edge="end"
                              size="small"
                              disabled={!selectedVersionId || isReadOnly}
                              onClick={(e) => {
                                e.stopPropagation();
                                callbacks.onClassEdit?.(classItem);
                              }}
                              title={!selectedVersionId ? 'Select a version first' : isReadOnly ? 'Cannot edit published version' : 'Edit class'}
                            >
                              <Edit fontSize="small" />
                            </IconButton>
                            <IconButton
                              edge="end"
                              size="small"
                              disabled={!selectedVersionId || isReadOnly}
                              onClick={(e) => {
                                e.stopPropagation();
                                callbacks.onClassDelete?.(classItem.id);
                              }}
                              title={!selectedVersionId ? 'Select a version first' : isReadOnly ? 'Cannot edit published version' : 'Delete class'}
                            >
                              <Delete fontSize="small" />
                            </IconButton>
                          </Box>
                        }
                      >
                        <ListItemButton
                          selected={selectedClassId === classItem.id}
                          onClick={() => handleClassSelect(classItem)}
                        >
                          <ListItemText
                            primary={classItem.name}
                            secondary={classItem.description}
                            slotProps={{
                              primary: { noWrap: true },
                              secondary: { noWrap: true },
                            }}
                          />
                        </ListItemButton>
                      </ListItem>
                    ))}
                  </List>
                )}
              </Box>

              {/* Add Button */}
              <Box sx={{ position: 'absolute', bottom: 16, right: 16 }}>
                <Fab
                  color="primary"
                  size="small"
                  onClick={() => callbacks.onClassAdd?.()}
                  disabled={!selectedVersionId || isReadOnly}
                  aria-label="Add class"
                  title={!selectedVersionId ? 'Select a version first' : isReadOnly ? 'Cannot edit published version' : 'Add class'}
                >
                  <Add />
                </Fab>
              </Box>
            </Box>
          ) : (
            // Properties View
            <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Search Bar */}
              <Box sx={{ p: 2, pb: 1 }}>
                <TextField
                  fullWidth
                  size="small"
                  placeholder="Search properties..."
                  value={propertiesSearchQuery}
                  onChange={(e) => setPropertiesSearchQuery(e.target.value)}
                  slotProps={{
                    input: {
                      startAdornment: (
                        <InputAdornment position="start">
                          <Search fontSize="small" />
                        </InputAdornment>
                      ),
                    },
                  }}
                />
              </Box>

              {/* Properties List */}
              <Box sx={{ flex: 1, overflow: 'auto' }}>
                {filteredProperties.length === 0 ? (
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{ textAlign: 'center', mt: 4, px: 2 }}
                  >
                    {properties.length === 0
                      ? 'No properties yet. Click + to add one.'
                      : 'No properties match your search.'}
                  </Typography>
                ) : (
                  <Box>
                    {filteredProperties.map((propertyItem) => (
                      <Box
                        key={propertyItem.id}
                        draggable={!isReadOnly}
                        onDragStart={(e) => {
                          // Prevent drag in read-only mode
                          if (isReadOnly) {
                            e.preventDefault();
                            return;
                          }
                          // Set the property data as the drag payload
                          e.dataTransfer.effectAllowed = 'copy';
                          e.dataTransfer.setData('application/json', JSON.stringify({
                            type: 'property',
                            property: propertyItem
                          }));
                        }}
                        onClick={() => handlePropertySelect(propertyItem)}
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 1,
                          px: 2,
                          py: 1.5,
                          mb: 0.5,
                          cursor: isReadOnly ? 'default' : 'grab',
                          backgroundColor: selectedPropertyId === propertyItem.id
                            ? 'action.selected'
                            : 'transparent',
                          borderRadius: 1,
                          transition: 'all 0.2s',
                          '&:hover': {
                            backgroundColor: selectedPropertyId === propertyItem.id
                              ? 'action.selected'
                              : 'action.hover',
                          },
                          '&:active': {
                            cursor: 'grabbing',
                          },
                          border: '1px solid',
                          borderColor: 'divider',
                        }}
                      >
                        {/* Property content */}
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography
                            variant="body2"
                            sx={{
                              fontWeight: 500,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {propertyItem.name}
                          </Typography>
                          <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              display: 'block',
                            }}
                          >
                            {propertyItem.type || propertyItem.description}
                          </Typography>
                        </Box>

                        {/* Action buttons */}
                        <Box sx={{ display: 'flex', gap: 0.5 }}>
                          <IconButton
                            size="small"
                            disabled={!selectedProjectId || isReadOnly}
                            onClick={(e) => {
                              e.stopPropagation();
                              callbacks.onPropertyEdit?.(propertyItem);
                            }}
                            title={!selectedProjectId ? 'Select a project first' : isReadOnly ? 'Cannot edit published version' : 'Edit property'}
                            sx={{
                              opacity: 0.7,
                              '&:hover': { opacity: 1 }
                            }}
                          >
                            <Edit fontSize="small" />
                          </IconButton>
                          <IconButton
                            size="small"
                            disabled={!selectedProjectId || isReadOnly}
                            onClick={(e) => {
                              e.stopPropagation();
                              callbacks.onPropertyDelete?.(propertyItem.id);
                            }}
                            title={!selectedProjectId ? 'Select a project first' : isReadOnly ? 'Cannot edit published version' : 'Delete property'}
                            sx={{
                              opacity: 0.7,
                              '&:hover': { opacity: 1 }
                            }}
                          >
                            <Delete fontSize="small" />
                          </IconButton>
                        </Box>
                      </Box>
                    ))}
                  </Box>
                )}
              </Box>

              {/* Add Button */}
              <Box sx={{ position: 'absolute', bottom: 16, right: 16 }}>
                <Fab
                  color="primary"
                  size="small"
                  onClick={() => callbacks.onPropertyAdd?.()}
                  disabled={!selectedProjectId || isReadOnly}
                  aria-label="Add property"
                  title={!selectedProjectId ? 'Select a project first' : isReadOnly ? 'Cannot edit published version' : 'Add property'}
                >
                  <Add />
                </Fab>
              </Box>
            </Box>
          )}
        </Box>
      </Box>
    </Drawer>
  );
};

export default StudioSideNav;