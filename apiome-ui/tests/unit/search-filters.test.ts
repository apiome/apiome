/**
 * Tests for Search Filter functionality
 *
 * These tests verify the logic used in the search filter feature.
 */

describe('Search Filters', () => {
  // Type definitions
  type SearchFilterType = 'all' | 'class' | 'allOf' | 'oneOf' | 'anyOf';

  interface NodeData {
    name: string;
    description?: string;
    properties?: Array<{ name?: string; description?: string }>;
    schema?: {
      allOf?: unknown[];
      oneOf?: unknown[];
      anyOf?: unknown[];
    };
  }

  interface CanvasGroup {
    id: string;
    name: string;
    nodeIds: string[];
  }

  // Helper functions (same logic as in page.tsx)
  const matchesTypeFilter = (nodeData: NodeData, filterType: SearchFilterType): boolean => {
    if (filterType === 'all') return true;
    const schema = nodeData?.schema;
    const isAllOf = !!schema?.allOf;
    const isOneOf = !!schema?.oneOf;
    const isAnyOf = !!schema?.anyOf;

    switch (filterType) {
      case 'class': return !isAllOf && !isOneOf && !isAnyOf;
      case 'allOf': return isAllOf;
      case 'oneOf': return isOneOf;
      case 'anyOf': return isAnyOf;
      default: return true;
    }
  };

  const matchesGroupFilter = (
    nodeId: string,
    filterGroup: string,
    groups: CanvasGroup[]
  ): boolean => {
    if (filterGroup === 'all') return true;
    const group = groups.find(g => g.nodeIds.includes(nodeId));
    if (filterGroup === 'ungrouped') {
      return !group;
    }
    return group?.id === filterGroup;
  };

  const matchesPropertiesFilter = (
    props: Array<unknown> | undefined,
    filterHasProperties: 'all' | 'with' | 'without'
  ): boolean => {
    if (filterHasProperties === 'all') return true;
    const hasProps = !!(props && Array.isArray(props) && props.length > 0);
    return filterHasProperties === 'with' ? hasProps : !hasProps;
  };

  const hasPropertyNamed = (
    props: Array<{ name?: string }> | undefined,
    propName: string
  ): boolean => {
    if (!props || !Array.isArray(props) || !propName) return true;
    const lowerPropName = propName.toLowerCase();
    return props.some(p => (p.name ?? '').toLowerCase().includes(lowerPropName));
  };

  describe('Type Filter', () => {
    it('should match all types when filter is "all"', () => {
      const nodeData: NodeData = { name: 'Test' };
      expect(matchesTypeFilter(nodeData, 'all')).toBe(true);
    });

    it('should match regular class when filter is "class"', () => {
      const nodeData: NodeData = { name: 'User' };
      expect(matchesTypeFilter(nodeData, 'class')).toBe(true);
    });

    it('should not match allOf class when filter is "class"', () => {
      const nodeData: NodeData = { name: 'AdminUser', schema: { allOf: [{}] } };
      expect(matchesTypeFilter(nodeData, 'class')).toBe(false);
    });

    it('should match allOf class when filter is "allOf"', () => {
      const nodeData: NodeData = { name: 'AdminUser', schema: { allOf: [{}] } };
      expect(matchesTypeFilter(nodeData, 'allOf')).toBe(true);
    });

    it('should match oneOf class when filter is "oneOf"', () => {
      const nodeData: NodeData = { name: 'Response', schema: { oneOf: [{}] } };
      expect(matchesTypeFilter(nodeData, 'oneOf')).toBe(true);
    });

    it('should match anyOf class when filter is "anyOf"', () => {
      const nodeData: NodeData = { name: 'FlexibleInput', schema: { anyOf: [{}] } };
      expect(matchesTypeFilter(nodeData, 'anyOf')).toBe(true);
    });

    it('should not match regular class when filter is "allOf"', () => {
      const nodeData: NodeData = { name: 'User' };
      expect(matchesTypeFilter(nodeData, 'allOf')).toBe(false);
    });
  });

  describe('Group Filter', () => {
    const groups: CanvasGroup[] = [
      { id: 'group-1', name: 'Auth Models', nodeIds: ['node-1', 'node-2'] },
      { id: 'group-2', name: 'Payment Models', nodeIds: ['node-3'] },
    ];

    it('should match all when filter is "all"', () => {
      expect(matchesGroupFilter('node-1', 'all', groups)).toBe(true);
      expect(matchesGroupFilter('node-99', 'all', groups)).toBe(true);
    });

    it('should match ungrouped nodes when filter is "ungrouped"', () => {
      expect(matchesGroupFilter('node-99', 'ungrouped', groups)).toBe(true);
    });

    it('should not match grouped nodes when filter is "ungrouped"', () => {
      expect(matchesGroupFilter('node-1', 'ungrouped', groups)).toBe(false);
    });

    it('should match nodes in specific group', () => {
      expect(matchesGroupFilter('node-1', 'group-1', groups)).toBe(true);
      expect(matchesGroupFilter('node-2', 'group-1', groups)).toBe(true);
    });

    it('should not match nodes not in the filtered group', () => {
      expect(matchesGroupFilter('node-3', 'group-1', groups)).toBe(false);
      expect(matchesGroupFilter('node-1', 'group-2', groups)).toBe(false);
    });
  });

  describe('Properties Filter', () => {
    it('should match all when filter is "all"', () => {
      expect(matchesPropertiesFilter(undefined, 'all')).toBe(true);
      expect(matchesPropertiesFilter([], 'all')).toBe(true);
      expect(matchesPropertiesFilter([{ name: 'id' }], 'all')).toBe(true);
    });

    it('should match nodes with properties when filter is "with"', () => {
      expect(matchesPropertiesFilter([{ name: 'id' }], 'with')).toBe(true);
      expect(matchesPropertiesFilter([{ name: 'id' }, { name: 'name' }], 'with')).toBe(true);
    });

    it('should not match nodes without properties when filter is "with"', () => {
      expect(matchesPropertiesFilter(undefined, 'with')).toBe(false);
      expect(matchesPropertiesFilter([], 'with')).toBe(false);
    });

    it('should match nodes without properties when filter is "without"', () => {
      expect(matchesPropertiesFilter(undefined, 'without')).toBe(true);
      expect(matchesPropertiesFilter([], 'without')).toBe(true);
    });

    it('should not match nodes with properties when filter is "without"', () => {
      expect(matchesPropertiesFilter([{ name: 'id' }], 'without')).toBe(false);
    });
  });

  describe('Property Name Filter', () => {
    const propsWithId = [{ name: 'id' }, { name: 'name' }, { name: 'email' }];
    const propsWithCreatedAt = [{ name: 'createdAt' }, { name: 'updatedAt' }];

    it('should match when no property name filter is specified', () => {
      expect(hasPropertyNamed(propsWithId, '')).toBe(true);
      expect(hasPropertyNamed([], '')).toBe(true);
      expect(hasPropertyNamed(undefined, '')).toBe(true);
    });

    it('should match when property exists', () => {
      expect(hasPropertyNamed(propsWithId, 'id')).toBe(true);
      expect(hasPropertyNamed(propsWithId, 'name')).toBe(true);
      expect(hasPropertyNamed(propsWithId, 'email')).toBe(true);
    });

    it('should match case-insensitively', () => {
      expect(hasPropertyNamed(propsWithId, 'ID')).toBe(true);
      expect(hasPropertyNamed(propsWithId, 'Name')).toBe(true);
      expect(hasPropertyNamed(propsWithId, 'EMAIL')).toBe(true);
    });

    it('should match partial names', () => {
      expect(hasPropertyNamed(propsWithCreatedAt, 'created')).toBe(true);
      expect(hasPropertyNamed(propsWithCreatedAt, 'At')).toBe(true);
    });

    it('should not match when property does not exist', () => {
      expect(hasPropertyNamed(propsWithId, 'password')).toBe(false);
      expect(hasPropertyNamed(propsWithId, 'role')).toBe(false);
    });
  });

  describe('Combined Filters', () => {
    const nodes = [
      {
        id: 'user-1',
        data: {
          name: 'User',
          properties: [{ name: 'id' }, { name: 'email' }]
        }
      },
      {
        id: 'admin-1',
        data: {
          name: 'AdminUser',
          schema: { allOf: [{}] },
          properties: [{ name: 'role' }]
        }
      },
      {
        id: 'empty-1',
        data: {
          name: 'EmptyClass',
          properties: []
        }
      },
    ];

    const groups: CanvasGroup[] = [
      { id: 'auth', name: 'Auth', nodeIds: ['user-1', 'admin-1'] },
    ];

    it('should filter by multiple criteria', () => {
      // Filter: regular classes with properties in auth group
      const matches = nodes.filter(node => {
        const data = node.data;
        if (!matchesTypeFilter(data, 'class')) return false;
        if (!matchesGroupFilter(node.id, 'auth', groups)) return false;
        if (!matchesPropertiesFilter(data.properties, 'with')) return false;
        return true;
      });

      expect(matches.length).toBe(1);
      expect(matches[0].data.name).toBe('User');
    });

    it('should filter ungrouped classes without properties', () => {
      const matches = nodes.filter(node => {
        const data = node.data;
        if (!matchesGroupFilter(node.id, 'ungrouped', groups)) return false;
        if (!matchesPropertiesFilter(data.properties, 'without')) return false;
        return true;
      });

      expect(matches.length).toBe(1);
      expect(matches[0].data.name).toBe('EmptyClass');
    });
  });

  describe('Active Filters Detection', () => {
    const hasActiveFilters = (
      type: SearchFilterType,
      group: string,
      hasProps: 'all' | 'with' | 'without',
      propName: string
    ): boolean => {
      return type !== 'all' ||
             group !== 'all' ||
             hasProps !== 'all' ||
             propName.trim() !== '';
    };

    it('should detect no active filters', () => {
      expect(hasActiveFilters('all', 'all', 'all', '')).toBe(false);
      expect(hasActiveFilters('all', 'all', 'all', '   ')).toBe(false);
    });

    it('should detect active type filter', () => {
      expect(hasActiveFilters('class', 'all', 'all', '')).toBe(true);
      expect(hasActiveFilters('allOf', 'all', 'all', '')).toBe(true);
    });

    it('should detect active group filter', () => {
      expect(hasActiveFilters('all', 'group-1', 'all', '')).toBe(true);
      expect(hasActiveFilters('all', 'ungrouped', 'all', '')).toBe(true);
    });

    it('should detect active properties filter', () => {
      expect(hasActiveFilters('all', 'all', 'with', '')).toBe(true);
      expect(hasActiveFilters('all', 'all', 'without', '')).toBe(true);
    });

    it('should detect active property name filter', () => {
      expect(hasActiveFilters('all', 'all', 'all', 'id')).toBe(true);
      expect(hasActiveFilters('all', 'all', 'all', 'email')).toBe(true);
    });
  });
});

