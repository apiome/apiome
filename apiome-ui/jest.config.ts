import type { Config } from 'jest';

const config: Config = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom', // Changed from 'node' to support React components
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts', '**/*.test.tsx'], // Added tsx
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json', 'node'],
  collectCoverageFrom: [
    'lib/**/*.{ts,tsx}',
    'src/**/*.{ts,tsx}',
    '!lib/**/*.d.ts',
    '!lib/**/*.test.{ts,tsx}',
    '!src/**/*.test.{ts,tsx}',
  ],
  coverageDirectory: 'coverage',
  // `text-summary` gives a compact console table; `json-summary` writes
  // coverage/coverage-summary.json which CI parses into the job summary (RC1-3.1, #3616).
  coverageReporters: ['text', 'text-summary', 'json-summary', 'lcov', 'html'],
  transform: {
    '^.+\\.[tj]sx?$': ['ts-jest', {
      tsconfig: {
        jsx: 'react-jsx',
        allowJs: true,
        esModuleInterop: true,
        allowSyntheticDefaultImports: true,
      }
    }]
  },
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
    '^@lib/(.*)$': '<rootDir>/lib/$1',
    '^react-markdown$': '<rootDir>/tests/__mocks__/react-markdown.tsx',
    '^remark-gfm$': '<rootDir>/tests/__mocks__/remark-gfm.ts',
    '^rehype-raw$': '<rootDir>/tests/__mocks__/rehype-raw.ts',
    '^.*auth/server-session$': '<rootDir>/tests/__mocks__/server-session.ts',
  },
  transformIgnorePatterns: [
    'node_modules/(?!(react-markdown|remark-gfm|unified|bail|is-plain-obj|trough|vfile|unist-.*|unified|remark-.*|mdast-.*|micromark.*|decode-named-character-reference|character-entities|property-information|hast-util-whitespace|space-separated-tokens|comma-separated-tokens|pretty-bytes|@seriousme/openapi-schema-validator|uuid)/)',
  ],
  setupFilesAfterEnv: ['<rootDir>/tests/setup.ts'],
  testTimeout: 30000,

  // Verbose output configuration - provides detailed pass/fail info per test
  verbose: true,
  bail: false,
  notify: false,
  notifyMode: 'failure-change',

  // Built-in reporter with verbose output
  reporters: [
    [
      'default',
      {
        verbose: true,
      }
    ]
  ],

  // Test name pattern for verbose logging
  testNamePattern: '.*',
};

export default config;

