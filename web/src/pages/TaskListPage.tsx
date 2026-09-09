import { useCallback, useEffect, useMemo, useState } from "react";
import {
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
  Upload,
} from "antd";
import {
  DeleteOutlined,
  EyeOutlined,
  FileTextOutlined,
  PlusOutlined,
  RedoOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useNavigate } from "react-router-dom";
import { api, type DictsResponse, type TaskStatus, type TaskSummary } from "../api/http";
import { SummaryCards } from "../components/SummaryCards";
import { TaskStatusTag } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";

const STATUS_OPTIONS = [
  { value: "pending", label: "排队中" },
  { value: "running", label: "执行中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
];

export function TaskListPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [items, setItems] = useState<TaskSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<TaskStatus | undefined>();
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [dicts, setDicts] = useState<DictsResponse | null>(null);
  const [form] = Form.useForm();
  const [file, setFile] = useState<File | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listTasks({ page, page_size: pageSize, status });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, status, message]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api.listDicts().then(setDicts).catch(() => undefined);
  }, []);

  const busy = useMemo(() => items.some((t) => t.status === "pending" || t.status === "running"), [items]);
  usePolling(load, 2000, busy);

  const stats = useMemo(() => {
    const acc = { total: 0, pass: 0, warn: 0, fail: 0, error: 0, skip: 0, systems: 0 };
    for (const t of items) {
      acc.total += t.stats.total;
      acc.pass += t.stats.pass;
      acc.warn += t.stats.warn;
      acc.fail += t.stats.fail;
      acc.error += t.stats.error;
      acc.skip += t.stats.skip;
      acc.systems += t.stats.systems ?? 1;
    }
    return acc;
  }, [items]);

  const submitUpload = async () => {
    if (!file) {
      message.warning("请选择数据压缩包");
      return;
    }
    setSubmitting(true);
    try {
      const values = form.getFieldsValue();
      const fd = new FormData();
      fd.append("package_file", file);
      if (values.name) fd.append("name", values.name);
      if (values.province) fd.append("province", values.province);
      if (values.operator) fd.append("operator", values.operator);
      if (values.version) fd.append("version", values.version);
      const created = await api.createTask(fd);
      message.success("任务已创建，开始执行");
      setOpen(false);
      setFile(null);
      form.resetFields();
      navigate(`/tasks/${created.task_id}`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const rerun = async (taskId: string) => {
    try {
      await api.rerunTask(taskId);
      message.success("已受理重跑");
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重跑失败");
    }
  };

  const remove = async (taskId: string) => {
    try {
      await api.deleteTask(taskId);
      message.success("任务已删除");
      await load();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除失败");
    }
  };

  const columns: ColumnsType<TaskSummary> = [
    {
      title: "任务",
      dataIndex: "name",
      render: (_, record) => (
        <div>
          <Typography.Link onClick={() => navigate(`/tasks/${record.task_id}`)}>{record.name}</Typography.Link>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: "block" }}>
            {record.task_id}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (v: string) => <TaskStatusTag status={v} />,
    },
    {
      title: "结果统计",
      width: 220,
      render: (_, record) => (
        <Space size={4} wrap>
          <Tag color="green">P {record.stats.pass}</Tag>
          <Tag color="gold">W {record.stats.warn}</Tag>
          <Tag color="red">F {record.stats.fail}</Tag>
          <Tag color="default">E {record.stats.error}</Tag>
          <Tag color="blue">S {record.stats.skip}</Tag>
        </Space>
      ),
    },
    {
      title: "模式",
      dataIndex: "mode",
      width: 90,
      render: (v: string) => <Tag>{v === "online" ? "在线" : "本地"}</Tag>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 160,
      render: (v: string) => dayjs(v).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "操作",
      width: 210,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => navigate(`/tasks/${record.task_id}`)}>
            详情
          </Button>
          <Button size="small" type="link" icon={<FileTextOutlined />} onClick={() => navigate(`/tasks/${record.task_id}/report`)}>
            报告
          </Button>
          <Popconfirm title="重跑该任务全部规则？" onConfirm={() => rerun(record.task_id)}>
            <Button size="small" type="link" icon={<RedoOutlined />}>
              重跑
            </Button>
          </Popconfirm>
          <Popconfirm title="删除任务（含现场数据）？" onConfirm={() => remove(record.task_id)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <SummaryCards stats={stats} />
      </Card>
      <Card
        title={
          <Space>
            <Typography.Text strong>任务列表</Typography.Text>
            <Typography.Text type="secondary">共 {total} 个任务</Typography.Text>
          </Space>
        }
        extra={
          <Space>
            <Select
              allowClear
              placeholder="状态筛选"
              style={{ width: 130 }}
              options={STATUS_OPTIONS}
              onChange={(v) => {
                setStatus(v);
                setPage(1);
              }}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
              上传数据包
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="task_id"
          loading={loading}
          dataSource={items}
          columns={columns}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      </Card>

      <Modal
        title="上传数据包（一个压缩包 = 一个任务）"
        open={open}
        confirmLoading={submitting}
        onOk={() => void submitUpload()}
        onCancel={() => {
          setOpen(false);
          setFile(null);
          form.resetFields();
        }}
        okText="提交巡检"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item label="数据压缩包" required>
            <Upload.Dragger
              maxCount={1}
              accept=".zip,.tar,.gz,.tgz,.tar.gz"
              beforeUpload={(f) => {
                setFile(f);
                return false;
              }}
              onRemove={() => setFile(null)}
            >
              <p>点击或拖拽压缩包到此处</p>
              <p style={{ color: "#999", fontSize: 12 }}>zip / tar.gz，默认上限 2GB</p>
            </Upload.Dragger>
          </Form.Item>
          <Form.Item label="任务名称" name="name">
            <Input placeholder="可选，默认取压缩包名" />
          </Form.Item>
          <Form.Item label="省份" name="province">
            <Select allowClear placeholder="选择省份" options={dictOptions(dicts?.province)} />
          </Form.Item>
          <Form.Item label="运营商" name="operator">
            <Select allowClear placeholder="选择运营商" options={dictOptions(dicts?.operator)} />
          </Form.Item>
          <Form.Item label="版本" name="version">
            <Select allowClear placeholder="选择版本" options={dictOptions(dicts?.version)} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

function dictOptions(items?: Array<{ code: string; name?: string }>) {
  return (items ?? []).map((d) => ({ value: d.code, label: d.name || d.code }));
}
