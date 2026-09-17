import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/episode-e2e",
  testMatch: "**/*.e2e.ts",
  testIgnore: "**/production-layout.e2e.ts",
  workers: 1,
  fullyParallel: false,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  outputDir: "../.cache/episode-playwright-artifacts",
  use: { trace: "retain-on-failure" },
});
