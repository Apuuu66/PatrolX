import { useState } from "react";
import { Layout, Menu, Typography, Card, Form, Input, Button, Tag, Space } from "antd";
import {
  BarChartOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const { Sider, Header, Content } = Layout;

const ROLE_LABELS: Record<string, string> = {
  admin: "管理员",
  viewer: "浏览者",
};

interface LoginFormValues {
  username: string;
  password: string;
}

function LoginPanel() {
  const { login } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (values: LoginFormValues) => {
    setSubmitting(true);
    setError(null);
    try {
      await login(values.username, values.password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "60vh" }}>
      <Card title="登录 PatrolX" style={{ width: 360 }}>
        <Typography.Paragraph type="secondary">系统由管理员创建账号，不支持在线注册。</Typography.Paragraph>
        {error && <Typography.Paragraph type="danger">{error}</Typography.Paragraph>}
        <Form layout="vertical" onFinish={(values) => void handleSubmit(values)}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  );
}

export function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, canWrite } = useAuth();
  const selected =
    location.pathname.startsWith("/tasks") || location.pathname === "/"
      ? "/tasks"
      : location.pathname.startsWith("/kpi-resources")
        ? "/kpi-resources"
      : location.pathname.startsWith("/inspectors")
        ? "/inspectors"
        : "/dicts";

  if (!user) {
    return <LoginPanel />;
  }

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
            { key: "/kpi-resources", icon: <DatabaseOutlined />, label: "基础指标" },
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
          <Space>
            <Typography.Text type="secondary">{user.username}</Typography.Text>
            <Tag color={canWrite ? "blue" : "default"}>{ROLE_LABELS[user.role] ?? user.role}</Tag>
            <Button size="small" icon={<LogoutOutlined />} onClick={() => void logout()}>
              登出
            </Button>
          </Space>
        </Header>
        <Content style={{ padding: 24, background: "#f5f5f5" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
