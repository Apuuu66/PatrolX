import { Layout, Menu, Typography } from "antd";
import {
  BarChartOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

const { Sider, Header, Content } = Layout;

export function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const selected =
    location.pathname.startsWith("/tasks") || location.pathname === "/"
      ? "/tasks"
      : location.pathname.startsWith("/kpi-resources")
        ? "/kpi-resources"
      : location.pathname.startsWith("/inspectors")
        ? "/inspectors"
        : "/dicts";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="dark" width={200}>
        <div
          style={{
            height: 56,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            color: "#fff",
            fontWeight: 600,
            fontSize: 16,
          }}
        >
          <SafetyCertificateOutlined />
          PatrolX
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          items={[
            { key: "/tasks", icon: <FileSearchOutlined />, label: "巡检任务" },
            { key: "/kpi-resources", icon: <DatabaseOutlined />, label: "KPI 指标库" },
            { key: "/inspectors", icon: <BarChartOutlined />, label: "规则管理" },
            { key: "/dicts", icon: <DatabaseOutlined />, label: "数据字典" },
          ]}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: "#fff",
            padding: "0 24px",
            borderBottom: "1px solid #f0f0f0",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Typography.Title level={4} style={{ margin: 0 }}>
            系统维护巡检平台
          </Typography.Title>
          <Typography.Text type="secondary">本地 / 在线双模式</Typography.Text>
        </Header>
        <Content style={{ padding: 24, background: "#f5f5f5" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
