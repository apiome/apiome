/**
 * Test Setup
 *
 * This file runs before all tests and sets up the testing environment
 */

// Import React Testing Library setup
import '@testing-library/jest-dom';
import { webcrypto } from 'node:crypto';
import { TextEncoder, TextDecoder } from 'util';

// Polyfill TextEncoder/TextDecoder for jsdom environment
// Required for pg library and other Node.js modules
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder as any;

// jsdom's default `globalThis.crypto` may lack `subtle` (or live on `window` only); align with browsers (#526)
const g = globalThis as typeof globalThis & { crypto?: Crypto };
if (!g.crypto?.subtle) {
  Object.defineProperty(g, 'crypto', {
    value: webcrypto as unknown as Crypto,
    configurable: true,
    enumerable: true,
    writable: true,
  });
}

// Extend Jest matchers
expect.extend({
  toBeValidSchema(received: any) {
    const pass = received && typeof received === 'object' && received.type;
    return {
      pass,
      message: () => pass
        ? `Expected schema not to be valid`
        : `Expected schema to be valid (must have a 'type' property)`,
    };
  },
});

// Set longer timeout for integration tests
jest.setTimeout(30000);

// Suppress console logs during tests (optional)
if (process.env.SUPPRESS_LOGS === 'true') {
  global.console = {
    ...console,
    log: jest.fn(),
    debug: jest.fn(),
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
  };
}

// Ensure test environment variables are set
process.env.NODE_ENV = 'test';
process.env.TEST_POSTGRES_DB = process.env.TEST_POSTGRES_DB || 'apiome_test';

console.log('Test environment initialized');
console.log(`Test database: ${process.env.TEST_POSTGRES_DB}`);

