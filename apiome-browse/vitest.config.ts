import { defineConfig } from 'vitest/config';

// Unit tests for the browse app's pure helpers (no DB, no DOM). Page/Client components are React
// Server/Client components exercised via build + manual verification; the testable logic (sort-mode
// resolution and ORDER BY composition) lives in framework-free modules under lib/.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['lib/**/*.test.ts'],
  },
});
