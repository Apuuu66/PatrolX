import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import type { ReactNode } from "react";

/** AntD 主题只在业务页面加载，避免原生应用壳首屏同步执行整套组件运行时。 */
export default function PageProviders({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1677ff",
          borderRadius: 8,
          colorBgLayout: "#f5f5f5",
          colorBorderSecondary: "#f0f0f0",
          fontSize: 14,
          fontSizeSM: 12,
          fontSizeLG: 16,
          lineHeight: 1.5715,
          colorText: "rgba(0, 0, 0, 0.88)",
          colorTextSecondary: "rgba(0, 0, 0, 0.65)",
          colorTextDescription: "rgba(0, 0, 0, 0.65)",
          colorTextTertiary: "rgba(0, 0, 0, 0.45)",
        },
      }}
    >
      <AntApp>{children}</AntApp>
    </ConfigProvider>
  );
}
