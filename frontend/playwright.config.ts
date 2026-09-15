import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/e2e",
  workers: 1,
  fullyParallel: false,
  timeout: 45000,
  expect: { timeout: 12000 },
  reporter: [
    ["list"],
    ["json", { outputFile: "../.cache/t01-desktop-tests.json" }],
  ],
  use: { trace: "retain-on-failure" },
});
