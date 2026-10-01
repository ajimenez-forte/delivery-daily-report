import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    globalSetup: ["tests/e2e/setup.ts"],
    testTimeout: 30000,
    hookTimeout: 240000,
    fileParallelism: false,
  },
});
