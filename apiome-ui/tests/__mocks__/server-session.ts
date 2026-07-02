import { jest } from '@jest/globals';

// Default: unauthenticated (tests that need a session should override via
// jest.mock or mockResolvedValueOnce on this export directly).
export const getAuthSession = jest.fn(async () => null);
