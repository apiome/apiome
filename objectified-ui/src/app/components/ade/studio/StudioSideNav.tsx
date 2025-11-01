// SideNav.tsx
'use client';

import React, { useState } from 'react';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import Typography from '@mui/material/Typography';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';

const StudioSideNav: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<'classes' | 'properties'>('classes');

  const handleTabChange = (event: React.SyntheticEvent, newValue: 'classes' | 'properties') => {
    setCurrentTab(newValue);
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
        <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
          {currentTab === 'classes' && (
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', mt: 4 }}>
                Classes view - coming soon
              </Typography>
            </Box>
          )}
          {currentTab === 'properties' && (
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', mt: 4 }}>
                Properties view - coming soon
              </Typography>
            </Box>
          )}
        </Box>
      </Box>
    </Drawer>
  );
};

export default StudioSideNav;