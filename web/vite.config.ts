import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_PROXY || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/healthz": { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("/node_modules/")) return undefined;
          if (id.includes("/echarts/")) return "echarts";
          if (id.includes("/zrender/")) return "zrender";
          if (id.includes("/antd/es/table/")) return "antd-table";
          if (id.includes("/antd/")) return "antd";
          if (id.includes("/@ant-design/") || id.includes("/@rc-component/") || /\/rc-[a-z-]+\//.test(id)) {
            return "antd-deps";
          }
          return "vendor";
        },
      },
    },
  },
});
