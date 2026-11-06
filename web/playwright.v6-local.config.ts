import { defineConfig } from "@playwright/test";

const e2eRoot = process.env.PATROLX_E2E_TEST_ROOT ?? "/tmp/patrolx-kpi-v6-e2e";
process.env.PATROLX_E2E_TEST_ROOT = e2eRoot;

export default defineConfig({
  testDir: "./e2e",
  testIgnore: /retention\.spec\.ts/,
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5183",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "bash e2e/start-backend.sh",
      url: "http://127.0.0.1:8012/healthz",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        PATROLX_E2E_PORT: "8012",
        PATROLX_E2E_DIR: e2eRoot,
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5183 --strictPort",
      url: "http://127.0.0.1:5183",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        VITE_API_PROXY: "http://127.0.0.1:8012",
      },
    },
  ],
});
