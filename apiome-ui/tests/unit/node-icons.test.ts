/**
 * Tests for Node Icon functionality
 *
 * These tests verify the logic used for class node icons.
 */

describe('Node Icon Feature', () => {
  // Mock icon options (simplified from actual implementation)
  const NODE_ICON_OPTIONS = [
    { name: 'User', category: 'People' },
    { name: 'Users', category: 'People' },
    { name: 'Building', category: 'People' },
    { name: 'ShoppingCart', category: 'Commerce' },
    { name: 'CreditCard', category: 'Commerce' },
    { name: 'Database', category: 'Storage' },
    { name: 'Server', category: 'Storage' },
    { name: 'FileText', category: 'Files' },
    { name: 'Mail', category: 'Communication' },
    { name: 'Calendar', category: 'Time' },
    { name: 'Key', category: 'Security' },
    { name: 'Lock', category: 'Security' },
    { name: 'Settings', category: 'Tools' },
    { name: 'Globe', category: 'Location' },
    { name: 'Tag', category: 'Organization' },
    { name: 'Star', category: 'Status' },
    { name: 'Activity', category: 'Analytics' },
    { name: 'Layout', category: 'Layout' },
    { name: 'Link', category: 'Connections' },
    { name: 'Image', category: 'Media' },
  ];

  describe('Icon Search', () => {
    const searchIcons = (query: string) => {
      if (!query.trim()) return NODE_ICON_OPTIONS;
      const lowerQuery = query.toLowerCase();
      return NODE_ICON_OPTIONS.filter(opt =>
        opt.name.toLowerCase().includes(lowerQuery) ||
        opt.category.toLowerCase().includes(lowerQuery)
      );
    };

    it('should return all icons when search is empty', () => {
      expect(searchIcons('')).toHaveLength(NODE_ICON_OPTIONS.length);
      expect(searchIcons('   ')).toHaveLength(NODE_ICON_OPTIONS.length);
    });

    it('should filter by icon name', () => {
      const results = searchIcons('user');
      expect(results.length).toBeGreaterThan(0);
      expect(results.some(r => r.name === 'User')).toBe(true);
      expect(results.some(r => r.name === 'Users')).toBe(true);
    });

    it('should filter by category', () => {
      const results = searchIcons('security');
      expect(results.length).toBe(2);
      expect(results.some(r => r.name === 'Key')).toBe(true);
      expect(results.some(r => r.name === 'Lock')).toBe(true);
    });

    it('should be case insensitive', () => {
      expect(searchIcons('USER')).toEqual(searchIcons('user'));
      expect(searchIcons('Security')).toEqual(searchIcons('security'));
    });

    it('should return empty array when no matches', () => {
      const results = searchIcons('xyznonexistent');
      expect(results).toHaveLength(0);
    });

    it('should match partial names', () => {
      const results = searchIcons('shop');
      expect(results.some(r => r.name === 'ShoppingCart')).toBe(true);
    });
  });

  describe('Icon Selection', () => {
    interface ClassNodeTheme {
      backgroundColor?: string;
      borderColor?: string;
      headerGradient?: string;
      textColor?: string;
      headerTextColor?: string;
      icon?: string;
    }

    const handleIconSelect = (
      currentTheme: ClassNodeTheme | undefined,
      iconName: string | null
    ): ClassNodeTheme => {
      return {
        ...(currentTheme || {}),
        icon: iconName || undefined
      };
    };

    it('should add icon to empty theme', () => {
      const result = handleIconSelect(undefined, 'User');
      expect(result.icon).toBe('User');
    });

    it('should add icon to existing theme', () => {
      const existingTheme: ClassNodeTheme = {
        backgroundColor: '#ffffff',
        borderColor: '#000000',
      };
      const result = handleIconSelect(existingTheme, 'Database');
      expect(result.icon).toBe('Database');
      expect(result.backgroundColor).toBe('#ffffff');
      expect(result.borderColor).toBe('#000000');
    });

    it('should replace existing icon', () => {
      const existingTheme: ClassNodeTheme = { icon: 'User' };
      const result = handleIconSelect(existingTheme, 'Database');
      expect(result.icon).toBe('Database');
    });

    it('should remove icon when null is passed', () => {
      const existingTheme: ClassNodeTheme = { icon: 'User' };
      const result = handleIconSelect(existingTheme, null);
      expect(result.icon).toBeUndefined();
    });

    it('should preserve other theme properties when removing icon', () => {
      const existingTheme: ClassNodeTheme = {
        backgroundColor: '#ffffff',
        icon: 'User',
      };
      const result = handleIconSelect(existingTheme, null);
      expect(result.icon).toBeUndefined();
      expect(result.backgroundColor).toBe('#ffffff');
    });
  });

  describe('Icon Display', () => {
    const getIconComponent = (iconName: string | undefined): string | null => {
      if (!iconName) return null;
      const iconOption = NODE_ICON_OPTIONS.find(opt => opt.name === iconName);
      return iconOption ? iconOption.name : null;
    };

    const getDisplayContent = (iconName: string | undefined, className: string): string => {
      const icon = getIconComponent(iconName);
      if (icon) {
        return `[Icon: ${icon}]`;
      }
      // Fallback to class name initials
      return className.substring(0, 2).toUpperCase();
    };

    it('should return null for no icon', () => {
      expect(getIconComponent(undefined)).toBeNull();
      expect(getIconComponent('')).toBeNull();
    });

    it('should return icon name for valid icon', () => {
      expect(getIconComponent('User')).toBe('User');
      expect(getIconComponent('Database')).toBe('Database');
    });

    it('should return null for invalid icon name', () => {
      expect(getIconComponent('NonExistentIcon')).toBeNull();
    });

    it('should display icon when set', () => {
      const display = getDisplayContent('User', 'Customer');
      expect(display).toBe('[Icon: User]');
    });

    it('should display initials when no icon', () => {
      const display = getDisplayContent(undefined, 'Customer');
      expect(display).toBe('CU');
    });

    it('should display initials for invalid icon', () => {
      const display = getDisplayContent('InvalidIcon', 'Customer');
      expect(display).toBe('CU');
    });
  });

  describe('Icon Categories', () => {
    const getCategories = () => {
      const categories = new Set(NODE_ICON_OPTIONS.map(opt => opt.category));
      return Array.from(categories).sort();
    };

    it('should have multiple categories', () => {
      const categories = getCategories();
      expect(categories.length).toBeGreaterThan(5);
    });

    it('should include common categories', () => {
      const categories = getCategories();
      expect(categories).toContain('People');
      expect(categories).toContain('Commerce');
      expect(categories).toContain('Storage');
      expect(categories).toContain('Security');
    });
  });
});

