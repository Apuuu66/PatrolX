import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined, RedoOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { api, type User } from "../api/http";
import { useAuth } from "../auth/AuthContext";

const ROLE_OPTIONS = [
  { value: "admin", label: "管理员" },
  { value: "viewer", label: "浏览者" },
];

const ROLE_LABELS: Record<string, string> = {
  admin: "管理员",
  viewer: "浏览者",
};

interface CreateUserValues {
  username: string;
  password: string;
  role: "admin" | "viewer";
}

interface PasswordValues {
  new_password: string;
}

interface RoleValues {
  role: "admin" | "viewer";
}

export function UsersPage() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const [items, setItems] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null);
  const [roleTarget, setRoleTarget] = useState<User | null>(null);
  const [createForm] = Form.useForm<CreateUserValues>();
  const [passwordForm] = Form.useForm<PasswordValues>();
  const [roleForm] = Form.useForm<RoleValues>();

  const load = useCallback(
    async (nextPage = page, nextPageSize = pageSize) => {
      setLoading(true);
      try {
        const data = await api.listUsers({ page: nextPage, page_size: nextPageSize });
        setItems(data.items);
        setTotal(data.total);
      } catch (err) {
        message.error(err instanceof Error ? err.message : "用户加载失败");
      } finally {
        setLoading(false);
      }
    },
    [message, page, pageSize],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async (values: CreateUserValues) => {
    try {
      await api.createUser(values);
      message.success("用户已创建");
      setCreateOpen(false);
      createForm.resetFields();
      await load(1, pageSize);
      setPage(1);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "创建用户失败");
    }
  };

  const handleResetPassword = async (values: PasswordValues) => {
    if (!passwordTarget) return;
    try {
      await api.resetUserPassword(passwordTarget.username, values);
      message.success("密码已重置，旧会话已失效");
      setPasswordTarget(null);
      passwordForm.resetFields();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重置密码失败");
    }
  };

  const handleUpdateRole = async (values: RoleValues) => {
    if (!roleTarget) return;
    try {
      await api.updateUserRole(roleTarget.username, values);
      message.success("角色已更新，旧会话已失效");
      setRoleTarget(null);
      roleForm.resetFields();
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "更新角色失败");
    }
  };

  const handleDelete = async (record: User) => {
    try {
      await api.deleteUser(record.username);
      message.success("用户已删除");
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除用户失败");
    }
  };

  const columns: ColumnsType<User> = [
    { title: "用户名", dataIndex: "username", width: 180 },
    {
      title: "角色",
      dataIndex: "role",
      width: 110,
      render: (value: string) => <Tag color={value === "admin" ? "blue" : "default"}>{ROLE_LABELS[value] ?? value}</Tag>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 170,
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "操作",
      width: 240,
      render: (_, record) => {
        const isSelf = record.username === user?.username;
        return (
          <Space size={4}>
            <Button
              size="small"
              type="link"
              icon={<RedoOutlined />}
              onClick={() => {
                setPasswordTarget(record);
                passwordForm.resetFields();
              }}
            >
              重置密码
            </Button>
            <Button
              size="small"
              type="link"
              disabled={isSelf}
              onClick={() => {
                setRoleTarget(record);
                roleForm.setFieldsValue({ role: record.role === "admin" ? "admin" : "viewer" });
              }}
            >
              角色
            </Button>
            <Popconfirm title={`删除用户 ${record.username}？`} onConfirm={() => void handleDelete(record)}>
              <Button size="small" type="link" danger disabled={isSelf}>
                删除
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  if (user?.role !== "admin") {
    return <Alert type="warning" showIcon message="仅管理员可以使用用户管理" />;
  }

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card
        title={<Typography.Text strong>用户台账</Typography.Text>}
        extra={
          <Space>
            <Typography.Text type="secondary">共 {total} 个用户</Typography.Text>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建用户
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="username"
          size="small"
          loading={loading}
          dataSource={items}
          columns={columns}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
              void load(nextPage, nextPageSize);
            },
          }}
        />
      </Card>

      <Modal
        title="创建用户"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        okText="创建"
      >
        <Typography.Paragraph type="secondary">系统不支持在线注册，账号由管理员创建。</Typography.Paragraph>
        <Form form={createForm} layout="vertical" initialValues={{ role: "viewer" }} onFinish={handleCreate}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            rules={[
              { required: true, message: "请输入初始密码" },
              { min: 8, message: "密码至少 8 位" },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: "请选择角色" }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码：${passwordTarget?.username ?? ""}`}
        open={Boolean(passwordTarget)}
        onCancel={() => setPasswordTarget(null)}
        onOk={() => passwordForm.submit()}
        okText="重置"
      >
        <Form form={passwordForm} layout="vertical" onFinish={handleResetPassword}>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: "请输入新密码" },
              { min: 8, message: "密码至少 8 位" },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
        <Typography.Text type="secondary">重置后该用户的所有登录会话会立即失效。</Typography.Text>
      </Modal>

      <Modal
        title={`修改角色：${roleTarget?.username ?? ""}`}
        open={Boolean(roleTarget)}
        onCancel={() => setRoleTarget(null)}
        onOk={() => roleForm.submit()}
        okText="保存"
      >
        <Form form={roleForm} layout="vertical" onFinish={handleUpdateRole}>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: "请选择角色" }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
        </Form>
        <Typography.Text type="secondary">不能修改自己的角色；系统至少保留一个管理员。</Typography.Text>
      </Modal>
    </Space>
  );
}
