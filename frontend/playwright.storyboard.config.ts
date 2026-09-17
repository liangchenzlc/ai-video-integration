import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/episode-e2e",
  testMatch: "production-layout.e2e.ts",
  workers: 1,
  reporter: "list",
  outputDir: "../.cache/storyboard-layout-artifacts",
  use: {
    channel: "chrome",
    baseURL: "http://127.0.0.1:5181",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${process.execPath}" node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5181 --strictPort`,
    url: "http://127.0.0.1:5181/tests/episode-e2e/production-preview.html",
    reuseExistingServer: !process.env.CI,
  },
});
