import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // antd 重页面用例在慢速 CI 上单例耗时可达数秒，默认 5s 超时会误报失败。
    testTimeout: 15000,
    include: ["src/**/*.test.tsx"],
    setupFiles: ["src/test/setup.ts"],
  },
});
