import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:5183",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "bash e2e/start-backend.sh",
      url: "http://127.0.0.1:8010/healthz",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5183 --strictPort",
      url: "http://127.0.0.1:5183",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        VITE_API_PROXY: "http://127.0.0.1:8010",
      },
    },
  ],
});
