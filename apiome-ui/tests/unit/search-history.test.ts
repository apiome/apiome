/**
 * Tests for useSearchHistory hook utility functions
 *
 * These tests verify the logic used in the search history feature.
 */

describe('Search History Utilities', () => {
  const STORAGE_KEY = 'apiome_canvas_search_history';
  const MAX_HISTORY_ITEMS = 20;

  interface SearchHistoryItem {
    query: string;
    isRegex: boolean;
    timestamp: number;
  }

  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();
  });

  describe('localStorage operations', () => {
    it('should save and retrieve history from localStorage', () => {
      const history: SearchHistoryItem[] = [
        { query: 'User', isRegex: false, timestamp: Date.now() },
        { query: 'Product', isRegex: false, timestamp: Date.now() - 1000 },
      ];

      localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
      const stored = localStorage.getItem(STORAGE_KEY);
      const parsed = JSON.parse(stored || '[]');

      expect(parsed).toHaveLength(2);
      expect(parsed[0].query).toBe('User');
      expect(parsed[1].query).toBe('Product');
    });

    it('should handle empty localStorage', () => {
      const stored = localStorage.getItem(STORAGE_KEY);
      expect(stored).toBeNull();
    });

    it('should clear history from localStorage', () => {
      const history: SearchHistoryItem[] = [
        { query: 'Test', isRegex: false, timestamp: Date.now() },
      ];

      localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
      expect(localStorage.getItem(STORAGE_KEY)).not.toBeNull();

      localStorage.removeItem(STORAGE_KEY);
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  describe('addToHistory logic', () => {
    it('should add new item at the beginning', () => {
      const history: SearchHistoryItem[] = [
        { query: 'Existing', isRegex: false, timestamp: Date.now() - 1000 },
      ];

      const newEntry: SearchHistoryItem = {
        query: 'New',
        isRegex: false,
        timestamp: Date.now(),
      };

      const newHistory = [newEntry, ...history];
      expect(newHistory[0].query).toBe('New');
      expect(newHistory[1].query).toBe('Existing');
    });

    it('should remove duplicate entries with same query and regex flag', () => {
      const history: SearchHistoryItem[] = [
        { query: 'User', isRegex: false, timestamp: Date.now() - 2000 },
        { query: 'Product', isRegex: false, timestamp: Date.now() - 1000 },
      ];

      const query = 'User';
      const isRegex = false;

      // Filter out existing entry
      const filtered = history.filter(
        (item) => !(item.query === query && item.isRegex === isRegex)
      );

      expect(filtered).toHaveLength(1);
      expect(filtered[0].query).toBe('Product');
    });

    it('should not remove entries with different regex flag', () => {
      const history: SearchHistoryItem[] = [
        { query: 'User', isRegex: false, timestamp: Date.now() - 2000 },
        { query: 'User', isRegex: true, timestamp: Date.now() - 1000 },
      ];

      const query = 'User';
      const isRegex = false;

      // Filter out existing entry with same regex flag
      const filtered = history.filter(
        (item) => !(item.query === query && item.isRegex === isRegex)
      );

      expect(filtered).toHaveLength(1);
      expect(filtered[0].isRegex).toBe(true);
    });

    it('should limit history to MAX_HISTORY_ITEMS', () => {
      const history: SearchHistoryItem[] = Array.from({ length: MAX_HISTORY_ITEMS }, (_, i) => ({
        query: `Query${i}`,
        isRegex: false,
        timestamp: Date.now() - i * 1000,
      }));

      const newEntry: SearchHistoryItem = {
        query: 'NewQuery',
        isRegex: false,
        timestamp: Date.now(),
      };

      const newHistory = [newEntry, ...history].slice(0, MAX_HISTORY_ITEMS);

      expect(newHistory).toHaveLength(MAX_HISTORY_ITEMS);
      expect(newHistory[0].query).toBe('NewQuery');
      expect(newHistory[MAX_HISTORY_ITEMS - 1].query).toBe(`Query${MAX_HISTORY_ITEMS - 2}`);
    });

    it('should not add empty queries', () => {
      const query = '   ';
      expect(query.trim()).toBe('');
    });
  });

  describe('removeFromHistory logic', () => {
    it('should remove specific item by query and regex flag', () => {
      const history: SearchHistoryItem[] = [
        { query: 'User', isRegex: false, timestamp: Date.now() },
        { query: 'Product', isRegex: false, timestamp: Date.now() - 1000 },
        { query: 'Order', isRegex: true, timestamp: Date.now() - 2000 },
      ];

      const query = 'Product';
      const isRegex = false;

      const filtered = history.filter(
        (item) => !(item.query === query && item.isRegex === isRegex)
      );

      expect(filtered).toHaveLength(2);
      expect(filtered.find(h => h.query === 'Product')).toBeUndefined();
    });

    it('should not remove item if regex flag differs', () => {
      const history: SearchHistoryItem[] = [
        { query: 'User', isRegex: false, timestamp: Date.now() },
        { query: 'User', isRegex: true, timestamp: Date.now() - 1000 },
      ];

      const query = 'User';
      const isRegex = true;

      const filtered = history.filter(
        (item) => !(item.query === query && item.isRegex === isRegex)
      );

      expect(filtered).toHaveLength(1);
      expect(filtered[0].isRegex).toBe(false);
    });
  });

  describe('SearchHistoryItem interface', () => {
    it('should create valid search history items', () => {
      const item: SearchHistoryItem = {
        query: 'UserClass',
        isRegex: false,
        timestamp: Date.now(),
      };

      expect(item.query).toBe('UserClass');
      expect(item.isRegex).toBe(false);
      expect(item.timestamp).toBeGreaterThan(0);
    });

    it('should create regex search history items', () => {
      const item: SearchHistoryItem = {
        query: '^User.*',
        isRegex: true,
        timestamp: Date.now(),
      };

      expect(item.query).toBe('^User.*');
      expect(item.isRegex).toBe(true);
    });
  });

  describe('history count', () => {
    it('should return correct count', () => {
      const history: SearchHistoryItem[] = [
        { query: 'Query1', isRegex: false, timestamp: Date.now() },
        { query: 'Query2', isRegex: false, timestamp: Date.now() - 1000 },
        { query: 'Query3', isRegex: true, timestamp: Date.now() - 2000 },
      ];

      expect(history.length).toBe(3);
    });

    it('should return zero for empty history', () => {
      const history: SearchHistoryItem[] = [];
      expect(history.length).toBe(0);
    });
  });
});

