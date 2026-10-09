import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Flex,
  Form,
  Dropdown,
  Modal,
  Pagination,
  Segmented,
  Select,
  Space,
  Table,
  Typography,
  Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  CaretDownOutlined,
  CaretRightOutlined,
  ClearOutlined,
  DeleteOutlined,
  FileTextOutlined,
  MoreOutlined,
  PlusOutlined,
  RedoOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  api,
  type TaskDeleteError,
  type DataPreparation,
  type DictsResponse,
  type OverviewSummary,
  type TaskStatus,
  type TaskSummary,
} from "../api/http";
import {
  categoryLabel,
  formatPreparationIssuePath,
  getPreparationDisplay,
} from "../utils/preparationDisplay";
import { TaskStatusTag } from "../components/StatusBadge";
import { StatusDistribution } from "../components/StatusDistribution";
import { MetadataList } from "../components/MetadataList";
import { usePolling } from "../hooks/usePolling";
import { formatTaskDuration, getTaskMetadataTags } from "../utils/taskCard";
import { getTaskFailureReason, sortTasksForList } from "../utils/taskListSort";
import { EmptyState, LoadErrorState, PageSkeleton } from "../components/PageState";
import { PageHeader } from "../components/PageHeader";

const STATUS_FILTER_OPTIONS = [
  { value: "", label: "全部" },
  { value: "pending", label: "排队中" },
  { value: "running", label: "执行中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
];

const PREPARATION_STATUS_COLORS: Record<string, string> = {
  pass: "#52c41a",
  warn: "#faad14",
  fail: "#ff4d4f",
  skip: "#1677ff",
  error: "#8c8c8c",
};

function TaskDeletePanel({
  taskId,
  error,
  collapsed,
  retrying,
  onToggle,
  onRetry,
}: {
  taskId: string;
  error: TaskDeleteError;
  collapsed: boolean;
  retrying: boolean;
  onToggle: (taskId: string) => void;
  onRetry: (taskId: string) => void;
}) {
  if (collapsed) {
    return (
      <Button type="text" size="small" danger onClick={() => onToggle(taskId)} style={{ paddingInline: 0 }}>
        <Flex align="center" gap={6}>
          删除失败
          <CaretRightOutlined />
        </Flex>
      </Button>
    );
  }
  return (
    <Alert
      type="error"
      showIcon
      message={
        <Flex align="center" gap={8} wrap="wrap">
          <Typography.Text strong>删除任务失败</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {error.reason}
          </Typography.Text>
        </Flex>
      }
      description={
        <Flex vertical gap={4}>
          <Typography.Text code style={{ fontSize: 12 }}>
            任务 {error.task_id || taskId}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            现场 {error.locations.join("、")}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }} code ellipsis>
            {error.failed_path}
            {error.path_length !== undefined && error.path_limit !== undefined
              ? ` · 长度 ${error.path_length}/${error.path_limit}`
              : ""}
          </Typography.Text>
        </Flex>
      }
      action={
        <Button size="small" icon={<ReloadOutlined />} loading={retrying} onClick={() => onRetry(taskId)}>
          重试删除
        </Button>
      }
    />
  );
}

function PreparationPanel({
  preparation,
  taskId,
  expanded,
  onToggle,
}: {
  preparation: DataPreparation;
  taskId: string;
  expanded: boolean;
  onToggle: (taskId: string) => void;
}) {
  const [showAllAbnormal, setShowAllAbnormal] = useState(false);
  const [activeCategories, setActiveCategories] = useState<string[]>([]);
  const display = useMemo(
    () => getPreparationDisplay(preparation, showAllAbnormal),
    [preparation, showAllAbnormal],
  );

  const toggleCategory = (category: string) =>
    setActiveCategories((current) =>
      current.includes(category)
        ? current.filter((value) => value !== category)
        : [...current, category],
    );

  return (
    <div className="preparation-panel">
      <Button type="text" size="small" onClick={() => onToggle(taskId)} style={{ paddingInline: 0 }}>
        <Flex align="center" gap={8}>
          <Typography.Text strong>数据准备</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {display.summary}
          </Typography.Text>
          <Typography.Text type="secondary">
            {expanded ? <CaretDownOutlined /> : <CaretRightOutlined />}
          </Typography.Text>
        </Flex>
      </Button>
      {expanded && (
        <div style={{ marginTop: 8 }}>
          <Flex vertical gap={4}>
            {display.visibleAbnormalItems.map((item) => {
              const active = activeCategories.includes(item.category);
              const firstIssue = item.issues?.[0];
              return (
                <div key={item.code}>
                  <Button
                    type="text"
                    block
                    onClick={() => toggleCategory(item.category)}
                    style={{
                      height: "auto",
                      minHeight: 34,
                      justifyContent: "flex-start",
                      paddingInline: 8,
                      textAlign: "left",
                    }}
                  >
                    <Flex align="center" gap={8} style={{ width: "100%" }}>
                      <span
                        aria-hidden
                        style={{
                          width: 8,
                          height: 8,
                          flex: "0 0 auto",
                          borderRadius: "50%",
                          background: PREPARATION_STATUS_COLORS[item.status],
                        }}
                      />
                      <Typography.Text strong style={{ fontSize: 13 }}>
                        {categoryLabel(item.category)}
                        {item.total_count > 0 ? ` ${item.extracted_count}/${item.total_count}` : ""}
                      </Typography.Text>
                      {firstIssue && (
                        <Typography.Text
                          type="secondary"
                          ellipsis
                          style={{ fontSize: 12, flex: 1, minWidth: 0 }}
                        >
                          {firstIssue.reason}
                        </Typography.Text>
                      )}
                      {active ? <CaretDownOutlined /> : <CaretRightOutlined />}
                    </Flex>
                  </Button>
                  {active && (
                    <div style={{ padding: "6px 16px 8px" }}>
                      {(item.issues ?? []).map((issue, index) => (
                        <div key={`${issue.type}-${index}`} style={{ marginBottom: 6 }}>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {issue.type} · {issue.reason}
                          </Typography.Text>
                          <Typography.Paragraph style={{ margin: 0, fontSize: 12 }} code ellipsis>
                            {formatPreparationIssuePath(issue)}
                          </Typography.Paragraph>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            {display.hiddenAbnormalCount > 0 && (
              <Button
                type="link"
                size="small"
                style={{ alignSelf: "flex-start" }}
                onClick={() => setShowAllAbnormal(true)}
              >
                展开全部 {display.abnormalItems.length} 类
              </Button>
            )}
            {display.abnormalItems.length === 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                各分类准备正常或暂无来源数据
              </Typography.Text>
            )}
            {display.normalSummary && (
              <Typography.Text type="secondary" style={{ fontSize: 12, paddingLeft: 8 }}>
                {display.normalSummary}
              </Typography.Text>
            )}
          </Flex>
        </div>
      )}
    </div>
  );
}

export function TaskListPage() {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [items, setItems] = useState<TaskSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [status, setStatus] = useState<TaskStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [dicts, setDicts] = useState<DictsResponse | null>(null);
  const [overview, setOverview] = useState<OverviewSummary | null>(null);
  const [form] = Form.useForm();
  const packageKind = Form.useWatch("package_kind", form);
  const isInspection = packageKind !== "log_supplement";
  const [file, setFile] = useState<File | null>(null);
  const [expandedRowKeys, setExpandedRowKeys] = useState<readonly string[]>([]);
  const [deleteErrors, setDeleteErrors] = useState<Record<string, TaskDeleteError>>({});
  const [deleteCollapsed, setDeleteCollapsed] = useState<Record<string, boolean>>({});
  const [deleting, setDeleting] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [data, overviewData] = await Promise.all([
        api.listTasks({ page, page_size: pageSize, status: status === "" ? undefined : status }),
        api.getOverview(),
      ]);
      setItems(data.items);
      setTotal(data.total);
      setOverview(overviewData);
    } catch (err) {
      const text = err instanceof Error ? err.message : "加载失败";
      setLoadError(text);
      message.error(text);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, status, message]);

  const retryLoad = useCallback(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api.listDicts().then(setDicts).catch(() => undefined);
  }, []);

  const sortedItems = useMemo(() => sortTasksForList(items), [items]);
  const busy = useMemo(() => items.some((t) => t.status === "pending" || t.status === "running"), [items]);
  usePolling(load, 2000, busy);

  const togglePreparation = (taskId: string) =>
    setExpandedRowKeys((current) =>
      current.includes(taskId) ? current.filter((value) => value !== taskId) : [...current, taskId],
    );

  const submitUpload = async () => {
    if (!file) {
      message.warning("请选择数据压缩包");
      return;
    }
    setSubmitting(true);
    try {
      const values = form.getFieldsValue();
      const packageKindValue = values.package_kind === "log_supplement" ? "log_supplement" : "inspection";
      const fd = new FormData();
      fd.append("package_file", file);
      fd.append("package_kind", packageKindValue);
      if (packageKindValue === "inspection") {
        if (values.province) fd.append("province", values.province);
        if (values.operator) fd.append("operator", values.operator);
        if (values.product) fd.append("product", values.product);
      }
      const created = await api.createTaskV3(fd);
      message.success("任务已创建，开始执行");
      setOpen(false);
      setFile(null);
      form.resetFields();
      navigate(`/tasks/${created.task_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "package_checksum_conflict") {
        message.error("同名任务已存在，但数据包 checksum 不同，请修改压缩包文件名或删除旧任务");
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

  const rebuildFull = useCallback(
    async (taskId: string) => {
      try {
        await api.rebuildTask(taskId, { mode: "full", confirmed: true, trigger_source: "ui" });
        message.success("已受理全量重建");
        await load();
      } catch (err) {
        message.error(err instanceof Error ? err.message : "全量重建失败");
      }
    },
    [load, message],
  );

  const confirmRebuildFull = (taskId: string) => {
    modal.confirm({
      title: "全量重建该任务？",
      content: "将删除并重建当前任务输出目录，重新解压并重算全部规则和 KPI 快照；该操作不可撤销。",
      okText: "全量重建",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => rebuildFull(taskId),
    });
  };

  const remove = useCallback(
    async (taskId: string) => {
      setDeleting((current) => ({ ...current, [taskId]: true }));
      try {
        await api.deleteTask(taskId);
        setDeleteErrors((current) => {
          if (!(taskId in current)) return current;
          const next = { ...current };
          delete next[taskId];
          return next;
        });
        setDeleteCollapsed((current) => {
          if (!(taskId in current)) return current;
          const next = { ...current };
          delete next[taskId];
          return next;
        });
        message.success("任务已删除");
        await load();
      } catch (err) {
        const detail = err instanceof ApiError && err.code === "task_delete_failed" ? err.detail : undefined;
        if (
          detail &&
          typeof detail === "object" &&
          "task_id" in detail &&
          "locations" in detail &&
          "failed_path" in detail &&
          "reason" in detail
        ) {
          const failure = detail as TaskDeleteError;
          setDeleteErrors((current) => ({ ...current, [taskId]: failure }));
          setDeleteCollapsed((current) => ({ ...current, [taskId]: false }));
          setExpandedRowKeys((current) => (current.includes(taskId) ? current : [...current, taskId]));
          return;
        }
        const fallback: TaskDeleteError = {
          task_id: taskId,
          locations: [`output/${taskId}`, `uploads/${taskId}`],
          failed_path: "-",
          reason: err instanceof Error ? err.message : "删除失败",
        };
        setDeleteErrors((current) => ({ ...current, [taskId]: fallback }));
        setDeleteCollapsed((current) => ({ ...current, [taskId]: false }));
        setExpandedRowKeys((current) => (current.includes(taskId) ? current : [...current, taskId]));
      } finally {
        setDeleting((current) => ({ ...current, [taskId]: false }));
      }
    },
    [load, message],
  );

  useEffect(() => {
    const expandedTaskIds = Object.keys(deleteErrors).filter((taskId) => !deleteCollapsed[taskId]);
    if (expandedTaskIds.length === 0) return;
    const timer = window.setTimeout(() => {
      setDeleteCollapsed((current) => {
        const next = { ...current };
        for (const taskId of expandedTaskIds) next[taskId] = true;
        return next;
      });
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [deleteErrors, deleteCollapsed]);

  const showUploadModal = () => {
    const last = sortedItems[0];
    if (last) {
      form.setFieldsValue({
        province: last.customer_province ?? undefined,
        operator: last.customer_operator ?? undefined,
        product: last.customer_product ?? undefined,
        version: last.customer_version ?? undefined,
      });
    }
    setOpen(true);
  };

  const columns: ColumnsType<TaskSummary> = [
    {
      title: "任务",
      key: "task",
      width: 320,
      render: (_, record) => {
        const failureReason = getTaskFailureReason(record);
        return (
          <div className="task-table-task">
            <Flex align="center" gap={8} wrap="wrap">
              <Typography.Link strong onClick={() => navigate(`/tasks/${record.task_id}`)}>
                {record.name}
              </Typography.Link>
              <TaskStatusTag status={record.status} />
            </Flex>
            <Typography.Text code type="secondary" className="task-table-id" ellipsis>
              {record.task_id}
            </Typography.Text>
            {failureReason && (
              <Typography.Text
                type="danger"
                className="task-table-reason"
                data-testid="task-failure-reason"
                ellipsis={{ tooltip: failureReason }}
              >
                {failureReason}
              </Typography.Text>
            )}
          </div>
        );
      },
    },
    {
      title: "状态摘要",
      key: "stats",
      width: 240,
      render: (_, record) => <StatusDistribution stats={record.stats} />,
    },
    {
      title: "元数据",
      key: "metadata",
      width: 260,
      render: (_, record) => <MetadataList items={getTaskMetadataTags(record, dicts)} />,
    },
    {
      title: "时间与耗时",
      key: "timeline",
      width: 220,
      render: (_, record) => {
        const duration = formatTaskDuration(record.created_at, record.completed_at);
        return (
          <Flex vertical gap={2} className="task-table-time">
            <Typography.Text type="secondary">
              创建 {dayjs(record.created_at).format("YYYY-MM-DD HH:mm")}
            </Typography.Text>
            {record.completed_at && (
              <Typography.Text type="secondary">
                完成 {dayjs(record.completed_at).format("YYYY-MM-DD HH:mm")}
              </Typography.Text>
            )}
            {duration && <Typography.Text type="secondary">耗时 {duration}</Typography.Text>}
          </Flex>
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 220,
      align: "right",
      render: (_, record) => {
        const isFailed = record.status === "failed";
        const canReport = record.status === "completed";
        const canRebuild = record.status === "completed" || record.status === "failed";
        return (
          <Space size={0} wrap className="task-table-actions">
            <Button type="link" size="small" onClick={() => navigate(`/tasks/${record.task_id}`)}>
              详情
            </Button>
            {/* 失败任务没有报告产物，用失败日志替代报告，保证行内平铺业务操作不超过 3 个（FR-012） */}
            {isFailed ? (
              <Button
                type="link"
                size="small"
                danger
                icon={<FileTextOutlined />}
                onClick={() => navigate(`/tasks/${record.task_id}/logs`)}
              >
                失败日志
              </Button>
            ) : (
              <Button
                type="link"
                size="small"
                disabled={!canReport}
                title={canReport ? undefined : "任务执行中不可查看报告"}
                onClick={() => navigate(`/tasks/${record.task_id}/report`)}
              >
                报告
              </Button>
            )}
            <Dropdown
              menu={{
                items: [
                  { key: "rerun", label: "重跑", icon: <RedoOutlined /> },
                  ...(canRebuild
                    ? [{ key: "rebuild", label: "全量重建", danger: true, icon: <ClearOutlined /> }]
                    : []),
                  { type: "divider" as const },
                  { key: "delete", label: "删除", danger: true, icon: <DeleteOutlined /> },
                ],
                onClick: ({ key }) => {
                  if (key === "rerun") void rerun(record.task_id);
                  if (key === "rebuild") confirmRebuildFull(record.task_id);
                  if (key === "delete") {
                    modal.confirm({
                      title: "删除任务（含现场数据）？",
                      content: "删除后无法恢复。",
                      okText: "删除",
                      okButtonProps: { danger: true },
                      cancelText: "取消",
                      onOk: () => remove(record.task_id),
                    });
                  }
                },
              }}
              trigger={["click"]}
            >
              <Button aria-label="更多操作" type="text" size="small" icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        );
      },
    },
  ];

  return (
    <Flex vertical gap={16}>
      <PageHeader
        title="巡检任务"
        description="按异常优先查看任务结果，失败原因直接显示在任务行内。"
        actions={
          <Button type="primary" icon={<PlusOutlined />} onClick={showUploadModal}>
            上传数据包
          </Button>
        }
      />

      <Card data-testid="task-overview" styles={{ body: { padding: "16px 20px" } }}>
        <div className="task-overview">
          <div className="task-overview-metrics">
            {[
              { key: "task_count", label: "巡检任务" },
              { key: "registered_rule_count", label: "注册规则" },
              { key: "rule_result_count", label: "规则结果" },
              { key: "finding_count", label: "发现问题数" },
            ].map((item) => (
              <div key={item.key} className="task-overview-metric">
                <div className="task-overview-value">
                  {(overview?.[item.key as keyof OverviewSummary] ?? 0).toLocaleString()}
                </div>
                <div className="task-overview-label">{item.label}</div>
              </div>
            ))}
          </div>
          <div className="task-overview-divider" />
          <div className="task-overview-status">
            <div className="task-overview-label">规则结果状态分布</div>
            {overview ? (
              <StatusDistribution
                stats={{
                  pass: overview.status_counts.pass,
                  warn: overview.status_counts.warn,
                  fail: overview.status_counts.fail,
                  error: overview.status_counts.error,
                  skip: overview.status_counts.skip,
                }}
                variant="full"
                emptyText="暂无规则结果"
              />
            ) : (
              <Typography.Text type="secondary">统计数据加载中</Typography.Text>
            )}
          </div>
        </div>
      </Card>

      <Card
        title={
          <Flex align="center" gap={8}>
            <Typography.Text strong>任务列表</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              共 {total} 个任务
            </Typography.Text>
          </Flex>
        }
        extra={
          <Segmented
            aria-label="任务状态快捷筛选"
            options={STATUS_FILTER_OPTIONS}
            value={status}
            onChange={(value) => {
              setStatus(value as TaskStatus | "");
              setPage(1);
            }}
          />
        }
      >
        <Flex vertical gap={12}>
          {loading && items.length === 0 && !loadError && <PageSkeleton rows={3} />}
          {loadError && items.length === 0 && (
            <LoadErrorState description={loadError} onRetry={retryLoad} retrying={loading} />
          )}
          {!loadError && (
            <Table<TaskSummary>
              className="task-table"
              rowKey="task_id"
              columns={columns}
              dataSource={sortedItems}
              loading={loading && items.length > 0}
              pagination={false}
              expandable={{
                expandedRowKeys: [...expandedRowKeys],
                onExpandedRowsChange: (keys) => setExpandedRowKeys(keys.map(String)),
                expandedRowRender: (record) => (
                  <Flex vertical gap={12} className="task-table-expanded">
                    {deleteErrors[record.task_id] && (
                      <TaskDeletePanel
                        taskId={record.task_id}
                        error={deleteErrors[record.task_id]}
                        collapsed={Boolean(deleteCollapsed[record.task_id])}
                        retrying={Boolean(deleting[record.task_id])}
                        onToggle={(id) =>
                          setDeleteCollapsed((current) => ({ ...current, [id]: !current[id] }))
                        }
                        onRetry={(id) => void remove(id)}
                      />
                    )}
                    {record.preparation ? (
                      <PreparationPanel
                        preparation={record.preparation}
                        taskId={record.task_id}
                        expanded
                        onToggle={togglePreparation}
                      />
                    ) : (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        暂无数据准备记录
                      </Typography.Text>
                    )}
                    {record.status === "failed" && (
                      <Button
                        type="link"
                        size="small"
                        icon={<FileTextOutlined />}
                        style={{ alignSelf: "flex-start", paddingInline: 0 }}
                        onClick={() => navigate(`/tasks/${record.task_id}/logs`)}
                      >
                        查看失败日志
                      </Button>
                    )}
                  </Flex>
                ),
              }}
              locale={{
                emptyText: (
                  <EmptyState
                    description="暂无巡检任务，先上传一个数据包开始巡检。"
                    action={
                      <Button icon={<PlusOutlined />} onClick={showUploadModal}>
                        上传数据包
                      </Button>
                    }
                  />
                ),
              }}
              scroll={{ x: 1200 }}
            />
          )}

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
        okText={isInspection ? "提交巡检" : "提交日志包"}
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
          <Form.Item label="包类型" name="package_kind" initialValue="inspection">
            <Select
              options={[
                { value: "inspection", label: "巡检包" },
                { value: "log_supplement", label: "日志补充包" },
              ]}
            />
          </Form.Item>
          {isInspection ? (
            <>
              <Form.Item label="省份" name="province" rules={[{ required: true, message: "请选择省份" }]}>
                <Select allowClear placeholder="选择省份" options={dictOptions(dicts?.province)} />
              </Form.Item>
              <Form.Item label="运营商" name="operator" rules={[{ required: true, message: "请选择运营商" }]}>
                <Select allowClear placeholder="选择运营商" options={dictOptions(dicts?.operator)} />
              </Form.Item>
              <Form.Item label="网元类型" name="product">
                <Select allowClear placeholder="选择网元类型" options={dictOptions(dicts?.product)} />
              </Form.Item>
            </>
          ) : (
            <Alert
              type="info"
              showIcon
              message="日志补充包不采集设备信息"
              description="不需要省份、运营商和网元类型；版本只从巡检包的 LST ME.txt 获取。"
            />
          )}
        </Form>
      </Modal>
    </Flex>
  );
}

function dictOptions(items?: Array<{ code: string; name?: string }>) {
  return (items ?? []).map((d) => ({ value: d.code, label: d.name || d.code }));
}
