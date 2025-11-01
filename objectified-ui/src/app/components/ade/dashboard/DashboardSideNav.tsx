// SideNav.tsx
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import React from 'react';
import { User, Building2, Folders, FileDigit } from 'lucide-react';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  disabled?: boolean;
}

interface NavSection {
  header: string;
  items: NavItem[];
}

const DashboardSideNav: React.FC = () => {
  const pathname = usePathname();

  const navSections: NavSection[] = [
    {
      header: 'Account',
      items: [{ label: 'Profile', href: '/ade/dashboard/profile', icon: User }],
    },
    {
      header: 'Administration',
      items: [
        { label: 'Tenants', href: '/ade/dashboard/tenants', icon: Building2 },
      ],
    },
    {
      header: 'Specifications',
      items: [
        { label: 'Projects', href: '/ade/dashboard/projects', icon: Folders },
        { label: 'Versions', href: '/ade/dashboard/versions', icon: FileDigit },
      ],
    },
  ];

  const isActive = (href: string) => pathname === href;

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
      <Box sx={{ overflow: 'auto', p: 2 }}>
        {navSections.map((section, index) => (
          <Box key={section.header} sx={{ mb: index < navSections.length - 1 ? 3 : 0 }}>
            <Typography
              variant="overline"
              sx={{
                px: 2,
                py: 1,
                display: 'block',
                fontWeight: 600,
                color: 'text.secondary',
                letterSpacing: 1.1,
              }}
            >
              {section.header}
            </Typography>
            <List disablePadding>
              {section.items.map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href);

                return (
                  <ListItem key={item.href} disablePadding>
                    <ListItemButton
                      component={Link}
                      href={item.href}
                      disabled={item.disabled}
                      selected={active}
                      sx={{
                        borderRadius: 1,
                        mb: 0.5,
                        '&.Mui-selected': {
                          bgcolor: 'primary.main',
                          color: 'primary.contrastText',
                          '&:hover': {
                            bgcolor: 'primary.dark',
                          },
                          '& .MuiListItemIcon-root': {
                            color: 'primary.contrastText',
                          },
                        },
                      }}
                    >
                      <ListItemIcon sx={{ minWidth: 40 }}>
                        <Icon size={20} />
                      </ListItemIcon>
                      <ListItemText
                        primary={item.label}
                        slotProps={{
                          primary: {
                            fontSize: '0.875rem',
                            fontWeight: active ? 600 : 400,
                          },
                        }}
                      />
                    </ListItemButton>
                  </ListItem>
                );
              })}
            </List>
            {index < navSections.length - 1 && <Divider sx={{ my: 2 }} />}
          </Box>
        ))}
      </Box>
    </Drawer>
  );
};

export default DashboardSideNav;