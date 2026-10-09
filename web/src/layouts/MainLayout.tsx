import { useEffect, useState } from "react";
import { Layout, Menu, Typography, Modal, Form, Input, Button, Tag, Space } from "antd";
import {
  ApartmentOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  FundOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const { Sider, Header, Content } = Layout;

const ROLE_LABELS: Record<string, string> = {
  admin: "管理员",
  viewer: "浏览者",
};

/**
 * 路由 → 顶栏标题映射（FR-020、R14）。
 * 顺序敏感：先匹配更具体的子路由，再匹配一级页面。
 */
const PAGE_TITLE_RULES: readonly { pattern: RegExp; title: string }[] = [
  { pattern: /^\/tasks\/[^/]+\/rules\/[^/]+$/, title: "规则详情" },
  { pattern: /^\/tasks\/[^/]+\/report$/, title: "巡检报告" },
  { pattern: /^\/tasks\/[^/]+\/logs$/, title: "执行日志" },
  { pattern: /^\/tasks\/[^/]+$/, title: "任务详情" },
  { pattern: /^\/tasks?$/, title: "巡检任务" },
  { pattern: /^\/inventory\/devices\/[^/]+$/, title: "设备详情" },
  { pattern: /^\/inventory$/, title: "设备台账" },
  { pattern: /^\/measurement-units$/, title: "基础指标" },
  { pattern: /^\/inspectors$/, title: "规则管理" },
  { pattern: /^\/dicts$/, title: "数据字典" },
  { pattern: /^\/users$/, title: "用户管理" },
];

/** 顶栏标题：未知路径回退到默认落地页标题，避免出现空标题或产品名重复。 */
export function resolvePageTitle(pathname: string): string {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  if (normalized === "/") return "巡检任务";
  return PAGE_TITLE_RULES.find((rule) => rule.pattern.test(normalized))?.title ?? "巡检任务";
}

interface LoginFormValues {
  username: string;
  password: string;
}

function LoginModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { login } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) setError(null);
  }, [open]);

  const handleSubmit = async (values: LoginFormValues) => {
    setSubmitting(true);
    setError(null);
    try {
      await login(values.username, values.password);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="登录 PatrolX"
      open={open}
      onCancel={onClose}
      footer={null}
      width={360}
    >
      <div>
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
      </div>
    </Modal>
  );
}

export function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const [loginOpen, setLoginOpen] = useState(false);
  const selected =
    location.pathname === "/" || location.pathname.startsWith("/tasks")
      ? "/tasks"
      : location.pathname.startsWith("/inventory")
        ? "/inventory"
      : location.pathname.startsWith("/measurement-units")
        ? "/measurement-units"
      : location.pathname.startsWith("/inspectors")
        ? "/inspectors"
      : location.pathname.startsWith("/users")
        ? "/users"
        : "/dicts";

  const menuItems = [
    { key: "/tasks", icon: <FileSearchOutlined />, label: "巡检任务" },
    { key: "/inventory", icon: <ApartmentOutlined />, label: "设备台账" },
    { key: "/measurement-units", icon: <FundOutlined />, label: "基础指标" },
    { key: "/inspectors", icon: <BarChartOutlined />, label: "规则管理" },
    { key: "/dicts", icon: <DatabaseOutlined />, label: "数据字典" },
    ...(user?.role === "admin" ? [{ key: "/users", icon: <UserOutlined />, label: "用户管理" }] : []),
  ];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="light" width={200} className="app-sider">
        <div className="app-sider-brand">
          <SafetyCertificateOutlined />
          PatrolX
        </div>
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[selected]}
          items={menuItems}
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
          }}
        >
          <div className="app-shell-inner app-shell-header">
            <Typography.Title level={4} className="app-header-title" data-testid="app-page-title">
              {resolvePageTitle(location.pathname)}
            </Typography.Title>
            <Space>
              {user ? (
                <>
                  <Typography.Text type="secondary">{user.username}</Typography.Text>
                  <Tag color={user.role === "admin" ? "blue" : "default"}>
                    {ROLE_LABELS[user.role] ?? user.role}
                  </Tag>
                  <Button size="small" icon={<LogoutOutlined />} onClick={() => void logout()}>
                    登出
                  </Button>
                </>
              ) : (
                <>
                  <Typography.Text type="secondary">访客模式</Typography.Text>
                  {/* 访客模式登录降为默认按钮权重，不与页面主操作竞争（FR-020、R14） */}
                  <Button size="small" onClick={() => setLoginOpen(true)}>
                    登录
                  </Button>
                </>
              )}
            </Space>
          </div>
        </Header>
        <Content style={{ padding: 24, background: "#f5f5f5" }}>
          <div className="app-shell-inner">
            <Outlet />
          </div>
        </Content>
      </Layout>
      <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
    </Layout>
  );
}
