'use client';

import { useState, useEffect, useCallback } from 'react';

const STORAGE_KEY = 'apiome_canvas_search_history';
const MAX_HISTORY_ITEMS = 20;

export interface SearchHistoryItem {
  query: string;
  isRegex: boolean;
  timestamp: number;
}

export function useSearchHistory() {
  // Initialize history from localStorage using initial state callback
  const [history, setHistory] = useState<SearchHistoryItem[]>(() => {
    if (typeof window === 'undefined') return [];
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          return parsed;
        }
      }
    } catch (error) {
      console.error('Failed to load search history:', error);
    }
    return [];
  });

  // Save history to localStorage whenever it changes
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
    } catch (error) {
      console.error('Failed to save search history:', error);
    }
  }, [history]);

  // Add a search query to history
  const addToHistory = useCallback((query: string, isRegex: boolean) => {
    if (!query.trim()) return;

    setHistory((prev) => {
      // Remove any existing entry with the same query and regex flag
      const filtered = prev.filter(
        (item) => !(item.query === query && item.isRegex === isRegex)
      );

      // Add new entry at the beginning
      const newEntry: SearchHistoryItem = {
        query,
        isRegex,
        timestamp: Date.now(),
      };

      // Keep only the most recent items
      return [newEntry, ...filtered].slice(0, MAX_HISTORY_ITEMS);
    });
  }, []);

  // Remove a specific item from history
  const removeFromHistory = useCallback((query: string, isRegex: boolean) => {
    setHistory((prev) =>
      prev.filter((item) => !(item.query === query && item.isRegex === isRegex))
    );
  }, []);

  // Clear all history
  const clearHistory = useCallback(() => {
    setHistory([]);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
      console.error('Failed to clear search history:', error);
    }
  }, []);

  // Get history count
  const historyCount = history.length;

  return {
    history,
    addToHistory,
    removeFromHistory,
    clearHistory,
    historyCount,
  };
}


