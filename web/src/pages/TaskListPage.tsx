import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Select,
  Space,
  Typography,
  Upload,
} from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  RedoOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  api,
  type DictsResponse,
  type OverviewSummary,
  type TaskStatus,
  type TaskSummary,
} from "../api/http";
import { TaskStatusTag } from "../components/StatusBadge";
import { RESULT_STATUS_META } from "../components/statusLabels";
import { usePolling } from "../hooks/usePolling";

const STATUS_OPTIONS = [
  { value: "pending", label: "排队中" },
  { value: "running", label: "执行中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
];

const OVERVIEW_ITEMS = [
  { key: "task_count", label: "巡检任务" },
  { key: "registered_rule_count", label: "注册规则" },
  { key: "rule_result_count", label: "规则结果" },
  { key: "finding_count", label: "发现问题" },
] as const;

export function TaskListPage() {
  const { message, modal } = App.useApp();
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
  const [overview, setOverview] = useState<OverviewSummary | null>(null);
  const [form] = Form.useForm();
  const [file, setFile] = useState<File | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [data, overviewData] = await Promise.all([
        api.listTasks({ page, page_size: pageSize, status }),
        api.getOverview(),
      ]);
      setItems(data.items);
      setTotal(data.total);
      setOverview(overviewData);
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

  const submitUpload = async (force = false) => {
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
      if (values.product) fd.append("product", values.product);
      if (values.version) fd.append("version", values.version);
      if (force) fd.append("force", "true");
      const created = await api.createTask(fd);
      message.success("任务已创建，开始执行");
      setOpen(false);
      setFile(null);
      form.resetFields();
      navigate(`/tasks/${created.task_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "duplicate_package") {
        modal.confirm({
          title: "任务已存在，是否覆盖？",
          content: "覆盖后将删除旧任务的现场数据，并重新执行巡检。",
          okText: "覆盖重跑",
          okButtonProps: { danger: true },
          cancelText: "取消",
          onOk: () => submitUpload(true),
        });
      } else {
        message.error(err instanceof Error ? err.message : "创建失败");
      }
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

  return (
    <Flex vertical gap={16}>
      <Card styles={{ body: { padding: "18px 20px" } }}>
        <Flex gap={28} align="center" justify="space-between" wrap="wrap">
          <Flex gap={36} wrap="wrap">
            {OVERVIEW_ITEMS.map((item) => (
              <div key={item.key}>
                <Typography.Title level={4} style={{ margin: 0, fontWeight: 700 }}>
                  {(overview?.[item.key] ?? 0).toLocaleString()}
                </Typography.Title>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {item.label}
                </Typography.Text>
              </div>
            ))}
          </Flex>
          <Flex gap={16} wrap="wrap">
            {RESULT_STATUS_META.map((item) => (
              <div key={item.key} style={{ minWidth: 72, textAlign: "center" }}>
                <Typography.Text strong style={{ display: "block", fontSize: 20, color: item.color }}>
                  {(overview?.status_counts?.[item.key] ?? 0).toLocaleString()}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {item.label}
                </Typography.Text>
              </div>
            ))}
          </Flex>
        </Flex>
      </Card>

      <Card
        title={
          <Flex align="center" gap={8}>
            <Typography.Text strong>任务列表</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              共 {total} 个任务
            </Typography.Text>
          </Flex>
        }
        extra={
          <Space wrap>
            <Select
              allowClear
              placeholder="状态筛选"
              style={{ width: 130 }}
              options={STATUS_OPTIONS}
              value={status}
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
        <Flex vertical gap={12}>
          {items.map((record) => (
            <Card
              key={record.task_id}
              hoverable
              styles={{
                body: {
                  padding: 16,
                  display: "grid",
                  gridTemplateColumns: "minmax(220px, 1.2fr) minmax(300px, 1fr) auto",
                  gap: 18,
                  alignItems: "center",
                },
              }}
            >
              <div>
                <Typography.Link strong onClick={() => navigate(`/tasks/${record.task_id}`)}>
                  {record.name}
                </Typography.Link>
                <Flex gap={8} align="center" wrap="wrap" style={{ marginTop: 6 }}>
                  <Typography.Text code style={{ fontSize: 12 }}>
                    {record.task_id}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {record.mode === "online" ? "在线" : "本地"}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {dayjs(record.created_at).format("YYYY-MM-DD HH:mm")}
                  </Typography.Text>
                </Flex>
                {(record.customer_province || record.customer_operator || record.customer_product || record.customer_version) && (
                  <Flex gap={4} wrap="wrap" style={{ marginTop: 4 }}>
                    {codeToName(dicts, "province", record.customer_province) && <Typography.Text code style={{ fontSize: 12, color: "#1677ff" }}>{codeToName(dicts, "province", record.customer_province)}</Typography.Text>}
                    {codeToName(dicts, "operator", record.customer_operator) && <Typography.Text code style={{ fontSize: 12, color: "#1677ff" }}>{codeToName(dicts, "operator", record.customer_operator)}</Typography.Text>}
                    {codeToName(dicts, "product", record.customer_product) && <Typography.Text code style={{ fontSize: 12, color: "#1677ff" }}>{codeToName(dicts, "product", record.customer_product)}</Typography.Text>}
                    {codeToName(dicts, "version", record.customer_version) && <Typography.Text code style={{ fontSize: 12, color: "#1677ff" }}>{codeToName(dicts, "version", record.customer_version)}</Typography.Text>}
                  </Flex>
                )}
              </div>

              <Flex gap={8} wrap="wrap">
                {RESULT_STATUS_META.map((item) => {
                  const value = record.stats[item.key];
                  return (
                    <div
                      key={item.key}
                      style={{
                        flex: "1 1 52px",
                        minWidth: 56,
                        padding: "7px 6px",
                        borderRadius: 10,
                        textAlign: "center",
                        background: `${item.color}14`,
                      }}
                    >
                      <Typography.Text strong style={{ display: "block", color: item.color, fontSize: 18 }}>
                        {value}
                      </Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        {item.label}
                      </Typography.Text>
                    </div>
                  );
                })}
              </Flex>

              <Flex vertical align="flex-end" gap={8}>
                <TaskStatusTag status={record.status} />
                <Space size={0} wrap>
                  <Button type="text" size="small" onClick={() => navigate(`/tasks/${record.task_id}`)}>
                    详情
                  </Button>
                  <Button type="text" size="small" onClick={() => navigate(`/tasks/${record.task_id}/report`)}>
                    报告
                  </Button>
                  <Popconfirm title="重跑该任务全部规则？" onConfirm={() => rerun(record.task_id)}>
                    <Button type="text" size="small" icon={<RedoOutlined />}>
                      重跑
                    </Button>
                  </Popconfirm>
                  <Popconfirm title="删除任务（含现场数据）？" onConfirm={() => remove(record.task_id)}>
                    <Button type="text" size="small" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              </Flex>
            </Card>
          ))}

          {!loading && items.length === 0 && <Empty description="暂无巡检任务" />}

          <Flex justify="flex-end">
            <Pagination
              current={page}
              pageSize={pageSize}
              total={total}
              showSizeChanger
              showTotal={(value) => `共 ${value} 个任务`}
              onChange={(p, ps) => {
                setPage(p);
                setPageSize(ps);
              }}
            />
          </Flex>
        </Flex>
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
          <Form.Item label="产品形态" name="product">
            <Select allowClear placeholder="选择产品形态" options={dictOptions(dicts?.product)} />
          </Form.Item>
          <Form.Item label="版本" name="version">
            <Select allowClear placeholder="选择版本" options={dictOptions(dicts?.version)} />
          </Form.Item>
        </Form>
      </Modal>
    </Flex>
  );
}

function dictOptions(items?: Array<{ code: string; name?: string }>) {
  return (items ?? []).map((d) => ({ value: d.code, label: d.name || d.code }));
}

function codeToName(
  dicts: DictsResponse | null,
  group: "province" | "operator" | "product" | "version",
  code: string | null | undefined,
): string | null {
  if (!code) return null;
  const item = dicts?.[group]?.find((d) => d.code === code);
  return item?.name || code;
}
