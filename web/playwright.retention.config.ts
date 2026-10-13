import { defineConfig } from "@playwright/test";

/**
 * 留存治理场景专用配置：独立数据根（e2e/.tmp-retention）、数据库与端口，
 * 只播种 51 个留存任务，使"仅留最近 50 个现场 / 被清理任务仍可查 / 重传恢复"
 * 断言可精确复现，且不受默认套件其他用例触发的全局清理影响。
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /retention\.spec\.ts/,
  timeout: 60_000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5184",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "bash e2e/start-backend.sh",
      url: "http://127.0.0.1:8011/healthz",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        PATROLX_E2E_SCENARIO: "retention",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5184 --strictPort",
      url: "http://127.0.0.1:5184",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        VITE_API_PROXY: "http://127.0.0.1:8011",
      },
    },
  ],
});
