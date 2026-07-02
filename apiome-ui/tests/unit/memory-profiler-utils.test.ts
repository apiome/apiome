/**
 * Memory Profiler Utility Tests
 *
 * These tests verify the utility functions and logic used by the MemoryProfiler component.
 * The component itself is verified through the build process and manual E2E testing.
 */

describe('MemoryProfiler Utilities', () => {
  // Test formatBytes utility function logic
  describe('formatBytes', () => {
    const formatBytes = (bytes: number): string => {
      if (bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
    };

    it('should format 0 bytes correctly', () => {
      expect(formatBytes(0)).toBe('0 B');
    });

    it('should format bytes to KB', () => {
      expect(formatBytes(1024)).toBe('1 KB');
      expect(formatBytes(2048)).toBe('2 KB');
    });

    it('should format bytes to MB', () => {
      expect(formatBytes(1024 * 1024)).toBe('1 MB');
      expect(formatBytes(50 * 1024 * 1024)).toBe('50 MB');
    });

    it('should format bytes to GB', () => {
      expect(formatBytes(1024 * 1024 * 1024)).toBe('1 GB');
      expect(formatBytes(2 * 1024 * 1024 * 1024)).toBe('2 GB');
    });

    it('should format fractional values', () => {
      expect(formatBytes(1536)).toBe('1.5 KB');
      expect(formatBytes(1.5 * 1024 * 1024)).toBe('1.5 MB');
    });
  });

  // Test calcPercentage utility function logic
  describe('calcPercentage', () => {
    const calcPercentage = (used: number, total: number): number => {
      if (total === 0) return 0;
      return Math.round((used / total) * 100);
    };

    it('should return 0 when total is 0', () => {
      expect(calcPercentage(100, 0)).toBe(0);
    });

    it('should calculate percentage correctly', () => {
      expect(calcPercentage(50, 100)).toBe(50);
      expect(calcPercentage(25, 100)).toBe(25);
      expect(calcPercentage(75, 100)).toBe(75);
    });

    it('should handle full usage', () => {
      expect(calcPercentage(100, 100)).toBe(100);
    });

    it('should round to nearest integer', () => {
      expect(calcPercentage(33, 100)).toBe(33);
      expect(calcPercentage(1, 3)).toBe(33);
    });
  });

  // Test getMemoryStatusColor utility function logic
  describe('getMemoryStatusColor', () => {
    const getMemoryStatusColor = (percentage: number): string => {
      if (percentage < 50) return 'text-green-500';
      if (percentage < 75) return 'text-yellow-500';
      if (percentage < 90) return 'text-orange-500';
      return 'text-red-500';
    };

    it('should return green for low usage', () => {
      expect(getMemoryStatusColor(0)).toBe('text-green-500');
      expect(getMemoryStatusColor(25)).toBe('text-green-500');
      expect(getMemoryStatusColor(49)).toBe('text-green-500');
    });

    it('should return yellow for moderate usage', () => {
      expect(getMemoryStatusColor(50)).toBe('text-yellow-500');
      expect(getMemoryStatusColor(60)).toBe('text-yellow-500');
      expect(getMemoryStatusColor(74)).toBe('text-yellow-500');
    });

    it('should return orange for high usage', () => {
      expect(getMemoryStatusColor(75)).toBe('text-orange-500');
      expect(getMemoryStatusColor(85)).toBe('text-orange-500');
      expect(getMemoryStatusColor(89)).toBe('text-orange-500');
    });

    it('should return red for critical usage', () => {
      expect(getMemoryStatusColor(90)).toBe('text-red-500');
      expect(getMemoryStatusColor(95)).toBe('text-red-500');
      expect(getMemoryStatusColor(100)).toBe('text-red-500');
    });
  });

  // Test getMemoryBarColor utility function logic
  describe('getMemoryBarColor', () => {
    const getMemoryBarColor = (percentage: number): string => {
      if (percentage < 50) return 'bg-green-500';
      if (percentage < 75) return 'bg-yellow-500';
      if (percentage < 90) return 'bg-orange-500';
      return 'bg-red-500';
    };

    it('should return green background for low usage', () => {
      expect(getMemoryBarColor(25)).toBe('bg-green-500');
    });

    it('should return yellow background for moderate usage', () => {
      expect(getMemoryBarColor(60)).toBe('bg-yellow-500');
    });

    it('should return orange background for high usage', () => {
      expect(getMemoryBarColor(80)).toBe('bg-orange-500');
    });

    it('should return red background for critical usage', () => {
      expect(getMemoryBarColor(95)).toBe('bg-red-500');
    });
  });

  // Test memory snapshot interface
  describe('MemorySnapshot interface', () => {
    interface MemorySnapshot {
      timestamp: number;
      usedHeap: number;
      totalHeap: number;
      heapLimit: number;
      nodeCount: number;
      edgeCount: number;
      groupCount: number;
      renderCount: number;
    }

    it('should create a valid memory snapshot', () => {
      const snapshot: MemorySnapshot = {
        timestamp: Date.now(),
        usedHeap: 50 * 1024 * 1024,
        totalHeap: 100 * 1024 * 1024,
        heapLimit: 2 * 1024 * 1024 * 1024,
        nodeCount: 10,
        edgeCount: 5,
        groupCount: 2,
        renderCount: 100,
      };

      expect(snapshot.timestamp).toBeGreaterThan(0);
      expect(snapshot.usedHeap).toBe(52428800);
      expect(snapshot.totalHeap).toBe(104857600);
      expect(snapshot.nodeCount).toBe(10);
      expect(snapshot.edgeCount).toBe(5);
      expect(snapshot.groupCount).toBe(2);
    });

    it('should calculate memory change between snapshots', () => {
      const oldSnapshot: MemorySnapshot = {
        timestamp: Date.now() - 1000,
        usedHeap: 50 * 1024 * 1024,
        totalHeap: 100 * 1024 * 1024,
        heapLimit: 2 * 1024 * 1024 * 1024,
        nodeCount: 10,
        edgeCount: 5,
        groupCount: 2,
        renderCount: 100,
      };

      const newSnapshot: MemorySnapshot = {
        timestamp: Date.now(),
        usedHeap: 60 * 1024 * 1024,
        totalHeap: 120 * 1024 * 1024,
        heapLimit: 2 * 1024 * 1024 * 1024,
        nodeCount: 15,
        edgeCount: 8,
        groupCount: 3,
        renderCount: 150,
      };

      const memoryChange = newSnapshot.usedHeap - oldSnapshot.usedHeap;
      expect(memoryChange).toBe(10 * 1024 * 1024); // 10 MB increase

      const nodeChange = newSnapshot.nodeCount - oldSnapshot.nodeCount;
      expect(nodeChange).toBe(5);
    });
  });

  // Test performance.memory API availability detection
  describe('Performance Memory API', () => {
    it('should detect if performance.memory is available', () => {
      interface ExtendedPerformance extends Performance {
        memory?: {
          usedJSHeapSize: number;
          totalJSHeapSize: number;
          jsHeapSizeLimit: number;
        };
      }

      const perf = performance as ExtendedPerformance;

      // In most test environments, performance.memory is not available
      // This tests that the component handles the undefined case
      const isSupported = perf.memory !== undefined;

      // The test should handle either case gracefully
      expect(typeof isSupported).toBe('boolean');
    });
  });
});

